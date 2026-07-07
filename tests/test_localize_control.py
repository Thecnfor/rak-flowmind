"""P1: localize_cancel / localize_download 技能 — 让 Agent 完全通过 MCP 操作 VL。

设计：
- localize_cancel: 单 task_id 调 DELETE /tasks/{id}，返 cancelled 状态
- localize_download: 列出产物文件路径 + 提供 VL 的 download URL（Agent 自行拉）
  不直接把二进制塞 SkillResult（破坏 JSON 信封）
- 失败时走标准 INTERNAL + category
"""
from __future__ import annotations

import requests

import flowmind.skills  # noqa: F401
from flowmind.config import FlowmindConfig, LocalizerConfig
from flowmind.skill import invoke, registry


# ── 共享 fixture ──

def _set_base(monkeypatch):
    cfg = FlowmindConfig(localizer=LocalizerConfig())
    monkeypatch.setattr("flowmind.skills.localize_batch.load_config", lambda: cfg)
    monkeypatch.setattr("flowmind.skills.localize_status.load_config", lambda: cfg)


# ── 注册检查 ──

def test_cancel_and_download_are_registered():
    """localize_cancel / localize_download 必须出现在注册表里才能被 MCP 发现。"""
    reg = registry()
    assert "localize_cancel" in reg
    assert "localize_download" in reg


# ── localize_cancel ──

def _install_delete(monkeypatch, *, status_code=200, json_data=None, side_effect=None):
    import flowmind.skills.localize_cancel as lc
    calls = []
    _status = status_code  # closure capture
    def fake_delete(url, timeout=None, **_kw):
        calls.append({"url": url, "timeout": timeout})
        if side_effect is not None:
            raise side_effect
        class _R:
            _json = json_data or {"message": "cancelled"}
            @property
            def status_code(self):
                return _status
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError(f"{self.status_code}")
            def json(self):
                return self._json
        return _R()
    monkeypatch.setattr(lc.requests, "delete", fake_delete)
    return calls


def test_cancel_sends_delete_to_correct_url(monkeypatch):
    """cancel skill 调 DELETE /api/v1/tasks/{task_id}。"""
    _set_base(monkeypatch)
    calls = _install_delete(monkeypatch)
    r = invoke("localize_cancel", {"task_id": "abc123"})
    assert r.ok is True
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/api/v1/tasks/abc123")


def test_cancel_returns_cancellation_status(monkeypatch):
    """返回结构化结果：ok=true，data.cancelled=True，data.task_id。"""
    _set_base(monkeypatch)
    _install_delete(monkeypatch, json_data={"message": "Task abc123 cancelled"})
    r = invoke("localize_cancel", {"task_id": "abc123"})
    assert r.ok is True
    assert r.data.task_id == "abc123"
    assert r.data.cancelled is True
    assert "cancelled" in r.data.message.lower() or "cancel" in r.data.message.lower()


def test_cancel_404_returns_internal_video_error(monkeypatch):
    """task 不存在 → INTERNAL+video（VL raise_for_status 抛 HTTPError，invoke 兜底分类）。"""
    _set_base(monkeypatch)
    _install_delete(
        monkeypatch,
        status_code=404,
        json_data={"detail": "Task not found"},
    )
    r = invoke("localize_cancel", {"task_id": "ghost"})
    assert r.ok is False
    assert r.error.code == "INTERNAL"
    # 404 在 4xx 范围内 → video 类（资源不存在）
    assert r.error.category == "video"


def test_cancel_already_finished_returns_environment_error(monkeypatch):
    """VL 报 'already finished'（400）→ video 类。"""
    _set_base(monkeypatch)
    _install_delete(
        monkeypatch,
        status_code=400,
        json_data={"detail": "Cannot cancel task (not found or already finished)"},
    )
    r = invoke("localize_cancel", {"task_id": "done123"})
    assert r.ok is False
    assert r.error.category == "video"


# ── localize_download ──

def _install_get_with_tasks(monkeypatch, *, task_response):
    """装 GET /tasks/{id}（用于拿产物清单）。"""
    import flowmind.skills.localize_download as ld
    def fake_get(url, timeout=None, **_kw):
        # 根据 URL 是否带 /download 区分
        if "/download" in url:
            # 不应调这个 URL（我们只列产物清单）
            raise AssertionError(f"should not call /download in v0.1: {url}")
        class _R:
            status_code = 200
            _json = task_response
            def raise_for_status(self): pass
            def json(self): return self._json
        return _R()
    monkeypatch.setattr(ld.requests, "get", fake_get)


def test_download_lists_output_files_with_urls(monkeypatch):
    """completed task 的产物路径 + 可访问的 download URL 列出来。"""
    _set_base(monkeypatch)
    _install_get_with_tasks(monkeypatch, task_response={
        "task_id": "abc123",
        "status": "completed",
        "output_dir": "/tmp/vl_output/abc123",
        "outputs": {
            "output_sub.mp4": "/tmp/vl_output/abc123/output_sub.mp4",
            "dubbed_video.mp4": "/tmp/vl_output/abc123/dubbed_video.mp4",
            "trans.srt": "/tmp/vl_output/abc123/trans.srt",
        },
    })
    r = invoke("localize_download", {"task_id": "abc123"})
    assert r.ok is True
    files = {f.filename: f for f in r.data.files}
    assert "output_sub.mp4" in files
    assert "trans.srt" in files
    # URL 指向 VL 的 download 端点
    assert "/api/v1/tasks/abc123/download" in files["output_sub.mp4"].url
    assert "file=output_sub.mp4" in files["output_sub.mp4"].url


def test_download_not_completed_returns_video_error(monkeypatch):
    """未完成 task 不能下载 → video 类（参数问题，task 状态不对）。"""
    _set_base(monkeypatch)
    _install_get_with_tasks(monkeypatch, task_response={
        "task_id": "running1",
        "status": "running",
        "output_dir": None,
        "outputs": {},
    })
    r = invoke("localize_download", {"task_id": "running1"})
    assert r.ok is False
    assert r.error.code == "INTERNAL"
    assert r.error.category == "video"
    # message 应该提示 task 未完成
    assert "not completed" in r.error.message.lower() or "running" in r.error.message.lower()


def test_download_no_outputs_returns_empty_list(monkeypatch):
    """completed task 但 outputs 为空（VL 假完成场景）→ ok=true，files=[] + degraded。"""
    _set_base(monkeypatch)
    _install_get_with_tasks(monkeypatch, task_response={
        "task_id": "fake_done",
        "status": "completed",
        "output_dir": "/tmp/vl_output/fake_done",
        "outputs": {},
    })
    r = invoke("localize_download", {"task_id": "fake_done"})
    assert r.ok is True
    assert r.data.files == []
    assert r.data.degraded is True, "completed 但无产物 → 视为降级"
    assert "fake_done" in r.data.warning or "空" in r.data.warning


def test_download_404_returns_environment_error(monkeypatch):
    """task 不存在 → environment。"""
    _set_base(monkeypatch)
    import flowmind.skills.localize_download as ld
    def fake_get(url, timeout=None, **_kw):
        raise requests.HTTPError("404")
    monkeypatch.setattr(ld.requests, "get", fake_get)
    r = invoke("localize_download", {"task_id": "ghost"})
    assert r.ok is False
    assert r.error.category in ("video", "environment")