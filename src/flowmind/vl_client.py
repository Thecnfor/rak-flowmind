"""v0.3.7: 视频本地化后端客户端。

封装 video-localizer HTTP 调用，消除 5 个 localize_* 技能里重复的
requests.get/post/delete + 错误分类 + 超时管理。

特性：
- 单例 requests.Session（连接池复用）
- 统一错误分类（environment / video / transient / unknown）
- 统一超时 / 404 / 5xx 处理
- 健康检查 fast-fail
"""
from __future__ import annotations

import json

import requests

from flowmind.config import LocalizerConfig, get_config
from flowmind.contracts import SkillError
from flowmind.errors import ErrorCode


class VLAPIError(Exception):
    """视频本地化后端调用异常，携带结构化错误分类。"""

    def __init__(self, code: str, message: str, category: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.category = category
        self.details = details or {}


class VLClient:
    """video-localizer 后端的 thin 客户端。

    用法（每个 localize_* 技能实例化一次）：
        cfg = get_config().localizer
        client = VLClient(cfg)
        resp = client.post("/batch", payload)
    """

    def __init__(self, cfg: LocalizerConfig | None = None):
        self.cfg = cfg or get_config().localizer
        self._session = requests.Session()

    @property
    def base_url(self) -> str:
        return f"{self.cfg.api_base.rstrip('/')}{self.cfg.api_prefix}"

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def health_check(self) -> None:
        """fast-fail：VL 不通立刻抛 environment 错。"""
        try:
            r = self._session.get(self._url("/health"), timeout=self.cfg.health_timeout)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise VLAPIError(
                code=ErrorCode.INTERNAL,
                message=f"video-localizer 健康检查失败: {exc}",
                category="environment",
                details={"url": self.base_url},
            ) from exc

    def post(self, path: str, payload: dict) -> dict:
        """POST 请求。失败抛 VLAPIError（带 category）。"""
        try:
            r = self._session.post(
                self._url(path), json=payload, timeout=self.cfg.http_timeout
            )
        except requests.RequestException as exc:
            raise VLAPIError(
                code=ErrorCode.INTERNAL,
                message=f"POST {path} 失败: {exc}",
                category="environment",
            ) from exc
        return self._parse(r, path)

    def get(self, path: str) -> dict:
        """GET 请求。404 → NOT_FOUND；其他 4xx/5xx → INTERNAL。"""
        try:
            r = self._session.get(self._url(path), timeout=self.cfg.http_timeout)
        except requests.RequestException as exc:
            raise VLAPIError(
                code=ErrorCode.INTERNAL,
                message=f"GET {path} 失败: {exc}",
                category="environment",
            ) from exc
        if r.status_code == 404:
            raise VLAPIError(
                code=ErrorCode.NOT_FOUND,
                message=f"资源不存在: {path}",
                category="video",
            )
        return self._parse(r, path)

    def delete(self, path: str) -> dict:
        try:
            r = self._session.delete(self._url(path), timeout=self.cfg.http_timeout)
        except requests.RequestException as exc:
            raise VLAPIError(
                code=ErrorCode.INTERNAL,
                message=f"DELETE {path} 失败: {exc}",
                category="environment",
            ) from exc
        return self._parse(r, path)

    @staticmethod
    def _parse(r: requests.Response, path: str) -> dict:
        """解析响应：4xx → 错误；5xx → 临时；2xx → JSON。"""
        if 400 <= r.status_code < 500:
            try:
                detail = r.json()
            except Exception:
                detail = r.text[:200]
            raise VLAPIError(
                code=ErrorCode.VALIDATION if r.status_code in (400, 422) else ErrorCode.INTERNAL,
                message=f"{r.status_code} {path}: {detail}",
                category="video" if r.status_code in (400, 404, 422) else "unknown",
                details={"status_code": r.status_code, "body": detail},
            )
        if r.status_code >= 500:
            raise VLAPIError(
                code=ErrorCode.INTERNAL,
                message=f"5xx {path}: {r.text[:200]}",
                category="transient",
                details={"status_code": r.status_code},
            )
        try:
            return r.json()
        except json.JSONDecodeError:
            return {"_raw": r.text}


def vlapi_to_skill_error(exc: VLAPIError) -> SkillError:
    """VLAPIError → SkillError 转换（让 invoke() 统一兜底）。

    注意：SkillError 没有 `category` 字段（契约层不变量）。类别信息塞进
    details["category"]，调用方可在 `error.details["category"]` 读到。
    """
    details = dict(exc.details or {})
    details.setdefault("category", exc.category)
    return SkillError(
        code=exc.code,
        message=exc.message,
        retriable=exc.category == "transient",
        details=details,
    )
