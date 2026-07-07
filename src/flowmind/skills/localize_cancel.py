"""localize_cancel 技能：取消一个正在 queued/running 的 VL 任务。

薄包装 VL `DELETE /api/v1/tasks/{task_id}`；不在此重排或重提。
"""
from __future__ import annotations

import requests
from pydantic import BaseModel, Field

from flowmind.config import load_config
from flowmind.contracts import ReasoningChain, SkillOutput
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


# ── 入口 ──

@skill(id="localize_cancel", name="取消视频本地化任务", version=_VERSION)
def localize_cancel(inp: CancelInput) -> SkillOutput[CancelReport]:
    """调 DELETE /api/v1/tasks/{task_id} 取消任务，返回结构化结果。

    4xx（任务不存在 / 已结束）→ INTERNAL+video（资源问题）。
    5xx / 连接错 → INTERNAL+transient 或 environment，由 invoke() 分类。
    """
    cfg = load_config().localizer
    url = f"{cfg.api_base.rstrip('/')}{cfg.api_prefix}/tasks/{inp.task_id}"
    resp = requests.delete(url, timeout=cfg.http_timeout)
    resp.raise_for_status()
    body = resp.json()
    message = str(body.get("message", ""))

    report = CancelReport(
        task_id=inp.task_id,
        cancelled=True,
        message=message,
    )
    chain = ReasoningChain(
        conclusion=f"已请求取消任务 {inp.task_id}",
        triggered_rules=[],
        evidence=[],
        causal_analysis=f"VL 响应：{message}",
        risk_note="任务已被请求取消；VL 端可能仍需几秒清理。",
    )
    return SkillOutput(
        data=report,
        reasoning=[chain],
        confidence=1.0,
        sample_size=1,
    )