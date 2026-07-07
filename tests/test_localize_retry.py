"""P1 retry 补完：localize_retry skill — Agent 重提失败任务时不用走两步。

设计：
- 输入：task_id（原失败/取消的任务）
- 流程：GET /tasks/{id} 拿原参数（source_video / target_lang / enable_tts / remove_subtitles 等）
        → POST /tasks 单条重新提交
        → 返回新 task_id
- 不重排队（VL 没原生 retry endpoint；语义上 = 新建一个任务用同样的入参）
- 失败处理：
  · 原 task 不存在 → video 类
  · 原 task 没 source_video（VL 假完成） → video 类（input 缺失）
  · 新提交失败 → 沿用标准分类
"""
from __future__ import annotations

import requests

import flowmind.skills  # noqa: F401  触发所有技能注册
from flowmind.config import FlowmindConfig, LocalizerConfig
from flowmind.skill import invoke, registry


def _set_base(monkeypatch):
    cfg = FlowmindConfig(localizer=LocalizerConfig())
    # retry skill 也走 load_config，统一 patch
    import flowmind.skills.localize_retry as lr
    monkeypatch.setattr(lr.load_config.__module__ + ".load_config", lambda: cfg, raising=False)


# ── 注册检查 ──

def test_retry_is_registered():
    """localize_retry 必须出现在注册表里才能被 MCP 发现。"""
    reg = registry()
    assert "localize_retry" in reg


# ── 工具 ──

def _install_get_task(monkeypatch, *, response, status_code=200, raise_for_status_exc=None):
    """装 GET /tasks/{id} 的 mock。"""
    import flowmind.skills.localize_retry as lr
    def fake_get(url, timeout=None, **_kw):
        _status = status_code
        class _R:
            @property
            def status_code(self): return _status
            _json = response or {}
            def raise_for_status(self):
                if raise_for_status_exc is not None:
                    raise raise_for_status_exc
                if _status >= 400:
                    raise requests.HTTPError(f"{_status}")
            def json(self): return self._json
        return _R()
    monkeypatch.setattr(lr.requests, "get", fake_get)


def _install_post_task(monkeypatch, *, response=None, status_code=200, side_effect=None, raise_for_status_exc=None):
    """装 POST /tasks 的 mock（单条任务，非 /batch）。"""
    import flowmind.skills.localize_retry as lr
    calls = []
    def fake_post(url, json=None, timeout=None, **_kw):
        calls.append({"url": url, "json": json, "timeout": timeout})
        if side_effect is not None:
            raise side_effect
        _status = status_code
        class _R:
            @property
            def status_code(self): return _status
            _json = response or {"task_id": "new_id", "job_id": "new_id", "status": "queued"}
            def raise_for_status(self):
                if raise_for_status_exc is not None:
                    raise raise_for_status_exc
                if _status >= 400:
                    raise requests.HTTPError(f"{_status}")
            def json(self): return self._json
        return _R()
    monkeypatch.setattr(lr.requests, "post", fake_post)
    return calls


# ── Happy path ──

def test_retry_uses_original_params(monkeypatch):
    """retry 读原 task 的 source_video/target_lang/enable_tts/remove_subtitles，重提给 POST /tasks。"""
    _set_base(monkeypatch)
    _install_get_task(monkeypatch, response={
        "task_id": "old1",
        "status": "failed",
        "source_video": "/old/path.mp4",
        "target_language": "en",
        "enable_tts": True,
        "remove_subtitles": True,
    })
    post_calls = _install_post_task(monkeypatch, response={
        "task_id": "new1",
        "job_id": "new1",
        "status": "queued",
    })
    r = invoke("localize_retry", {"task_id": "old1"})
    assert r.ok is True
    assert r.data.original_task_id == "old1"
    assert r.data.new_task_id == "new1"
    # POST URL 是单条 /tasks（不是 /batch）
    assert post_calls[0]["url"].endswith("/api/v1/tasks")
    # POST payload 沿用原参数
    p = post_calls[0]["json"]
    assert p["video_path"] == "/old/path.mp4"
    assert p["target_lang"] == "en"
    assert p["enable_tts"] is True
    assert p["remove_subtitles"] is True


# ── 原 task 不存在 ──

def test_retry_unknown_task_returns_degraded_video(monkeypatch):
    """原 task 404 → degraded + video（资源不存在）。"""
    _set_base(monkeypatch)
    _install_get_task(
        monkeypatch,
        response={"detail": "Task not found"},
        status_code=404,
    )
    r = invoke("localize_retry", {"task_id": "ghost"})
    assert r.metrics.degraded is True
    assert r.data.failure_category == "video"


# ── 原 task 没 source_video（VL 假完成等）──

def test_retry_without_source_video_returns_degraded_video(monkeypatch):
    """原 task 状态是 completed 但 source_video 缺失 → degraded + video（input 缺失）。"""
    _set_base(monkeypatch)
    _install_get_task(monkeypatch, response={
        "task_id": "fake_done",
        "status": "completed",
        "source_video": None,
        "target_language": "en",
    })
    r = invoke("localize_retry", {"task_id": "fake_done"})
    assert r.metrics.degraded is True
    assert r.data.failure_category == "video"
    # 错误信息要明确说"无法重提"
    assert "source" in (r.data.message or "").lower() or "video" in (r.data.message or "").lower()


# ── 提交新任务失败：沿用标准分类 ──

def test_retry_submit_failure_returns_degraded_transient(monkeypatch):
    """POST /tasks 5xx → degraded + transient。"""
    _set_base(monkeypatch)
    _install_get_task(monkeypatch, response={
        "task_id": "old1",
        "source_video": "/old/path.mp4",
        "target_language": "en",
        "enable_tts": False,
        "remove_subtitles": True,
    })
    _install_post_task(
        monkeypatch,
        status_code=503,
        response={"detail": "service unavailable"},
    )
    r = invoke("localize_retry", {"task_id": "old1"})
    assert r.metrics.degraded is True
    assert r.data.failure_category == "transient"
    assert r.data.retriable is True


def test_retry_connection_error_returns_degraded_environment(monkeypatch):
    """POST /tasks 连接失败 → degraded + environment。"""
    _set_base(monkeypatch)
    _install_get_task(monkeypatch, response={
        "task_id": "old1",
        "source_video": "/old/path.mp4",
        "target_language": "en",
        "enable_tts": False,
        "remove_subtitles": True,
    })
    _install_post_task(monkeypatch, side_effect=requests.exceptions.ConnectionError("refused"))
    r = invoke("localize_retry", {"task_id": "old1"})
    assert r.metrics.degraded is True
    assert r.data.failure_category == "environment"


# ── 推理链 ──

def test_retry_reasoning_mentions_original_and_new(monkeypatch):
    """推理链结论提到「重提了 X → 新 task Y」。"""
    _set_base(monkeypatch)
    _install_get_task(monkeypatch, response={
        "task_id": "old1",
        "source_video": "/old/path.mp4",
        "target_language": "en",
        "enable_tts": True,
        "remove_subtitles": False,
    })
    _install_post_task(monkeypatch, response={"task_id": "new1", "status": "queued"})
    r = invoke("localize_retry", {"task_id": "old1"})
    assert r.ok is True
    chain = r.reasoning[0]
    assert "old1" in chain.conclusion
    assert "new1" in chain.conclusion