"""错误分类与错误码枚举。

注意：本模块独立于 contracts.py / skill.py，是 v0.3 视频本地化引入的。
- `ErrorCode`：HTTP 错误码的统一引用（替代散落的字符串字面量）
- `FailureCategory`：失败原因语义分类，用于让 Agent 决定「重试 vs 修环境 vs 放弃」
- `_classify_exception(exc)`：把任意异常归到 4 类之一
- `is_retriable(category)`：基于分类返回是否值得重试

放在新文件而非 contracts.py / skill.py 是为了严守「不修改契约层 / 框架层」的项目不变量。
"""
from __future__ import annotations

import re
from enum import Enum

import requests


class ErrorCode(str, Enum):
    """视频本地化后端错误码（HTTP 层语义）。"""
    NOT_FOUND = "NOT_FOUND"
    VALIDATION = "VALIDATION"
    INTERNAL = "INTERNAL"


class FailureCategory(str, Enum):
    """失败原因语义分类——Agent 依据此决定后续动作。

    字符串值用小写以匹配 PR 测试断言（直接用 `"environment"` / `"video"` 等字面量）。
    """
    ENVIRONMENT = "environment"   # 网络/服务不通——别重试，先查环境
    VIDEO = "video"               # 资源/输入问题——修视频本身或换源
    TRANSIENT = "transient"       # 服务端临时故障——可以重试
    UNKNOWN = "unknown"           # 兜底——具体看错误消息


# 关键字 → 类别的快速短路表（按优先级排列）
_ENV_KEYWORDS = ("Failed to resolve", "locate the files on the Hub")
_VIDEO_KEYWORDS = ("Video file not found",)
_VIDEO_EXT_RE = re.compile(r"File extension '[^']+' not in allowed list")
_TRANSIENT_STATUSES = frozenset({500, 502, 503, 504})


def _classify_exception(exc: BaseException) -> str:
    """把任意异常归到 'environment' / 'video' / 'transient' / 'unknown' 之一。

    规则按顺序短路匹配，先匹配先返回。测试覆盖见 `tests/test_errors.py`。
    """
    msg = str(exc) if exc else ""

    # ── environment ──
    if isinstance(exc, requests.exceptions.ConnectionError):
        return FailureCategory.ENVIRONMENT.value
    if isinstance(exc, requests.exceptions.Timeout):
        return FailureCategory.ENVIRONMENT.value
    if "timeout" in msg.lower():
        return FailureCategory.ENVIRONMENT.value
    for kw in _ENV_KEYWORDS:
        if kw in msg:
            return FailureCategory.ENVIRONMENT.value

    # ── video ──
    for kw in _VIDEO_KEYWORDS:
        if kw in msg:
            return FailureCategory.VIDEO.value
    if _VIDEO_EXT_RE.search(msg):
        return FailureCategory.VIDEO.value

    # ── transient / video（HTTP 4xx/5xx）──
    status: int | None = None
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)
        if status is None:
            # fake / 自构造的 HTTPError 没挂 response；尝试从消息开头解析状态码
            # 真实 requests 库的 HTTPError 消息格式是 "<status> <reason>"
            import re as _re
            m = _re.match(r"^\s*(\d{3})\b", msg)
            if m:
                status = int(m.group(1))
        if status in _TRANSIENT_STATUSES:
            return FailureCategory.TRANSIENT.value
        if status is not None and 400 <= status < 500:
            return FailureCategory.VIDEO.value

    # ── 兜底 ──
    return FailureCategory.UNKNOWN.value


def is_retriable(category: str) -> bool:
    """只有 transient 类错误值得重试。environment 修环境；video 改输入；unknown 看消息。"""
    return category == FailureCategory.TRANSIENT.value