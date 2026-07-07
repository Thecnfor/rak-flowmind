"""localize_retry 技能：用同样的入参重新提交一个失败/取消的任务。

内部走两步：GET /tasks/{id} 拿原参数 → POST /tasks（单条）重提。
对 Agent 来说一次调用就行，不用自己拿 source_video 再调 batch。
"""
from __future__ import annotations

import requests
from pydantic import BaseModel, Field

from flowmind.config import LocalizerConfig, load_config
from flowmind.contracts import ReasoningChain, SkillOutput
from flowmind.skill import skill

_VERSION = "0.1.0"


# ── 入参 ──

class RetryInput(BaseModel):
    """retry 技能入参。"""
    task_id: str = Field(..., min_length=1, description="要重提的原 task_id")


# ── 出参 ──

class RetryReport(BaseModel):
    """retry 技能业务载荷。"""
    original_task_id: str
    new_task_id: str
    original_status: str | None
    source_video: str
    target_lang: str
    enable_tts: bool
    remove_subtitles: bool


# ── 入口 ──

@skill(id="localize_retry", name="重提失败任务", version=_VERSION)
def localize_retry(inp: RetryInput) -> SkillOutput[RetryReport]:
    """拿原 task 的入参（source_video/target_lang/enable_tts/remove_subtitles），
    调 POST /tasks 单条重新提交，返回新 task_id。

    失败处理：
    - 原 task 不存在（404）→ video 类（资源缺失）
    - 原 task 没 source_video（VL 假完成场景）→ video 类（input 缺失）
    - POST /tasks 失败 → 沿用标准分类（transient / environment / video）
    """
    cfg: LocalizerConfig = load_config().localizer
    base = cfg.api_base.rstrip("/") + cfg.api_prefix

    # 1) GET 原 task 拿参数
    get_url = f"{base}/tasks/{inp.task_id}"
    resp = requests.get(get_url, timeout=cfg.http_timeout)
    if resp.status_code == 404:
        # 用 HTTPError(404) 让 invoke() 归 video 类
        raise requests.HTTPError(f"404 Task {inp.task_id} not found")
    resp.raise_for_status()
    original = resp.json()
    original_status = original.get("status")

    source_video = original.get("source_video")
    target_lang = original.get("target_language") or "en"
    enable_tts = bool(original.get("enable_tts", False))
    remove_subtitles = bool(original.get("remove_subtitles", True))

    if not source_video:
        # VL 假完成 / 数据损坏：拿不到 source_video → input 缺失
        raise requests.HTTPError(
            f"400 Task {inp.task_id} has no source_video, cannot retry"
        )

    # 2) POST /tasks 单条重提
    post_url = f"{base}/tasks"
    payload = {
        "video_path": source_video,
        "target_lang": target_lang,
        "source_lang": original.get("source_lang") or "zh",
        "enable_tts": enable_tts,
        "remove_subtitles": remove_subtitles,
    }
    if original.get("chat_id"):
        payload["chat_id"] = original["chat_id"]
    resp2 = requests.post(post_url, json=payload, timeout=cfg.http_timeout)
    resp2.raise_for_status()
    new_body = resp2.json()
    new_task_id = new_body.get("task_id") or new_body.get("job_id") or ""

    report = RetryReport(
        original_task_id=inp.task_id,
        new_task_id=new_task_id,
        original_status=original_status,
        source_video=source_video,
        target_lang=target_lang,
        enable_tts=enable_tts,
        remove_subtitles=remove_subtitles,
    )
    chain = ReasoningChain(
        conclusion=f"已重提任务 {inp.task_id} → 新 task {new_task_id}（status={original_status} → queued）",
        triggered_rules=[],
        evidence=[],
        causal_analysis=f"沿用原参数：source_video={source_video} / target_lang={target_lang} / "
                        f"enable_tts={enable_tts} / remove_subtitles={remove_subtitles}",
        risk_note="新任务独立调度；原 task 的失败原因若仍存在会再次失败，看 error 字段定位。",
    )
    return SkillOutput(
        data=report,
        reasoning=[chain],
        confidence=1.0,
        sample_size=1,
    )