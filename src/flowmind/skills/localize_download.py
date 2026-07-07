"""localize_download 技能：列出已完成任务的产物文件 + VL 的 download URL。

不把二进制塞进 SkillResult（破坏 JSON 信封）；让 Agent 按 URL 自行拉取。
小文件路径同时返回本地路径，Agent 可用 Read 等工具直接读。
"""
from __future__ import annotations

import requests
from pydantic import BaseModel, Field

from flowmind.config import load_config
from flowmind.contracts import ReasoningChain, SkillOutput
from flowmind.skill import skill

_VERSION = "0.1.0"


# ── 入参 ──

class DownloadInput(BaseModel):
    """download 技能入参。"""
    task_id: str = Field(..., min_length=1, description="已 completed 任务的 task_id")


# ── 出参 ──

class DownloadFile(BaseModel):
    """单个产物文件信息。"""
    filename: str
    local_path: str        # VL 端路径
    url: str               # VL 的 download URL（Agent 可自行 GET）


class DownloadReport(BaseModel):
    """download 技能业务载荷。"""
    task_id: str
    status: str
    files: list[DownloadFile]
    degraded: bool = False     # completed 但无产物时为 True（VL 假完成）
    warning: str | None = None


# ── 入口 ──

@skill(id="localize_download", name="获取任务产物清单与下载链接", version=_VERSION)
def localize_download(inp: DownloadInput) -> SkillOutput[DownloadReport]:
    """调 GET /api/v1/tasks/{task_id} 拉任务详情，列出 outputs 里的文件 + VL 的 download URL。

    任务未完成 → INTERNAL+video（资源状态不对）。
    任务 completed 但 outputs 空 → degraded=True（VL 假完成信号，让 Agent 警惕）。
    """
    cfg = load_config().localizer
    url = f"{cfg.api_base.rstrip('/')}{cfg.api_prefix}/tasks/{inp.task_id}"
    resp = requests.get(url, timeout=cfg.http_timeout)

    if resp.status_code == 404:
        # 任务不存在 → video 类（资源问题）
        raise requests.HTTPError(f"404 Task {inp.task_id} not found")
    resp.raise_for_status()
    body = resp.json()

    status = body.get("status", "unknown")
    if status != "completed":
        # 用 HTTPError(400) 模拟「资源状态不对」——让 invoke() 归到 video 类
        raise requests.HTTPError(
            f"400 Task {inp.task_id} not completed (status={status})"
        )

    outputs = body.get("outputs") or {}
    base = cfg.api_base.rstrip("/") + cfg.api_prefix
    files = [
        DownloadFile(
            filename=name,
            local_path=str(path),
            url=f"{base}/tasks/{inp.task_id}/download?file={name}",
        )
        for name, path in outputs.items()
    ]

    degraded = len(files) == 0
    warning = (
        f"任务 {inp.task_id} 状态为 completed 但无产物输出，可能是 VL 假完成（ASR 无内容等）"
        if degraded else None
    )

    report = DownloadReport(
        task_id=inp.task_id,
        status=status,
        files=files,
        degraded=degraded,
        warning=warning,
    )
    chain = ReasoningChain(
        conclusion=(
            f"任务 {inp.task_id} 产物清单：{len(files)} 个文件"
            + ("（degraded：completed 但无产物）" if degraded else "")
        ),
        triggered_rules=[],
        evidence=[],
        causal_analysis=f"VL 返回 status={status} + outputs 共 {len(outputs)} 项",
        risk_note=warning or "按 URL 拉取文件即可；大文件建议用流式下载。",
    )
    return SkillOutput(
        data=report,
        reasoning=[chain],
        confidence=1.0 if not degraded else 0.5,
        sample_size=len(files),
        degraded=degraded,
        degradation_reason=warning,
    )