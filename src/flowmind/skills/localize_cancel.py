"""localize_cancel 技能：取消一个正在 queued/running 的 VL 任务。

薄包装 VL `DELETE /api/v1/tasks/{task_id}`；不在此重排或重提。
v0.3：错误在技能体内分类后以 degraded SkillOutput 返回，failure_category 字段告诉
Agent 是 video / transient / environment 中的哪一类。
"""
from __future__ import annotations

import requests
from pydantic import BaseModel, Field

from flowmind.config import load_config
from flowmind.contracts import ReasoningChain, SkillOutput
from flowmind.errors import _classify_exception, is_retriable
from flowmind.skill import skill

_VERSION = "0.1.0"


# ── 入参 ──

class CancelInput(BaseModel):
    """cancel 技能入参。"""
    task_id: str = Field(..., min_length=1, description="要取消的 task_id")


# ── 出参 ──

class CancelReport(BaseModel):
    """cancel 技能业务载荷。"""
    task_id: str
    cancelled: bool
    message: str
    failure_category: str | None = None  # "environment" / "video" / "transient" / "unknown"
    retriable: bool = False
    warning: str | None = None


# ── 入口 ──

@skill(id="localize_cancel", name="取消视频本地化任务", version=_VERSION)
def localize_cancel(inp: CancelInput) -> SkillOutput[CancelReport]:
    """调 DELETE /api/v1/tasks/{task_id} 取消任务，返回结构化结果。

    错误分类：
    - 4xx（任务不存在 / 已结束）→ video
    - 5xx → transient（可重试）
    - ConnectionError / Timeout → environment（先查网络）
    """
    cfg = load_config().localizer
    url = f"{cfg.api_base.rstrip('/')}{cfg.api_prefix}/tasks/{inp.task_id}"

    try:
        resp = requests.delete(url, timeout=cfg.http_timeout)
    except requests.exceptions.RequestException as exc:
        cat = _classify_exception(exc)
        return _failure_output(inp.task_id, exc, cat)

    # 显式按 status_code 分类（不依赖 raise_for_status 抛错时不挂 response 的场景）
    if resp.status_code >= 500:
        return _failure_output(inp.task_id, Exception(f"{resp.status_code} HTTPError"), "transient")
    if resp.status_code >= 400:
        return _failure_output(inp.task_id, Exception(f"{resp.status_code} HTTPError"), "video")
    resp.raise_for_status()

    body = resp.json()
    message = str(body.get("message", ""))

    report = CancelReport(task_id=inp.task_id, cancelled=True, message=message)
    chain = ReasoningChain(
        conclusion=f"已请求取消任务 {inp.task_id}",
        triggered_rules=[],
        evidence=[],
        causal_analysis=f"VL 响应：{message}",
        risk_note="任务已被请求取消；VL 端可能仍需几秒清理。",
    )
    return SkillOutput(
        data=report, reasoning=[chain], confidence=1.0, sample_size=1,
    )


def _failure_output(task_id: str, exc: Exception, category: str) -> SkillOutput[CancelReport]:
    """统一的失败返回：degraded SkillOutput，category 在 report 字段里。"""
    report = CancelReport(
        task_id=task_id,
        cancelled=False,
        message=str(exc),
        failure_category=category,
        retriable=is_retriable(category),
        warning=f"取消失败（{category}）：{exc}",
    )
    chain = ReasoningChain(
        conclusion=f"取消任务 {task_id} 失败（{category}）",
        triggered_rules=[],
        evidence=[],
        causal_analysis=f"{type(exc).__name__}: {exc}",
        risk_note=(
            f"{'可重试' if is_retriable(category) else '需查环境或任务状态'}；"
            f"transient/environment 通常无需 Agent 介入。"
        ),
    )
    return SkillOutput(
        data=report, reasoning=[chain], confidence=0.0, sample_size=1,
        degraded=True, degradation_reason=category,
    )