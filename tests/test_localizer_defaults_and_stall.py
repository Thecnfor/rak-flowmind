"""B3 修复测试：(1) tts_default 真接通 cfg；(2) stalled 判定只对 running 不对 retrying。"""
from __future__ import annotations

import requests

import flowmind.skills  # noqa: F401
from flowmind.skill import invoke


# ── 工具 ──

def _args(paths, **kw):
    out = {"video_paths": paths}
    out.update({k: v for k, v in kw.items() if v is not None or k == "enable_tts"})
    return out


def _path(i, ext=".mp4"):
    return f"/fake/v{i}{ext}"


def _install_post(monkeypatch, *, json_data=None):
    """装 POST mock。"""
    import flowmind.skills.localize_batch as lb
    def fake_post(url, json=None, timeout=None, **_kw):
        class _R:
            pass
        r = _R()
        r.status_code = 200
        r._json = json_data or {"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"}
        def raise_for_status():
            pass
        def json_fn():
            return r._json
        r.raise_for_status = raise_for_status
        r.json = json_fn
        return r
    monkeypatch.setattr(lb.requests, "post", fake_post)
    return fake_post


def _install_get_health(monkeypatch, *, status_code=200, json_data=None):
    import flowmind.skills.localize_batch as lb
    def fake_get(url, timeout=None, **_kw):
        class _R:
            pass
        r = _R()
        r.status_code = status_code
        r._json = json_data or {"status": "ok"}
        def raise_for_status():
            pass
        def json_fn():
            return r._json
        r.raise_for_status = raise_for_status
        r.json = json_fn
        return r
    monkeypatch.setattr(lb.requests, "get", fake_get)


def _install_get_status(monkeypatch, per_task_response):
    """per_task_response: dict[task_id, json_body] 或 Exception"""
    import flowmind.skills.localize_status as ls
    calls = []
    def fake_get(url, timeout=None, **_kw):
        calls.append({"url": url, "timeout": timeout})
        task_id = url.rsplit("/", 1)[-1]
        if isinstance(per_task_response, Exception):
            raise per_task_response
        body = per_task_response.get(task_id)
        class _R:
            pass
        r = _R()
        r.status_code = 200 if body else 404
        r._json = body or {}
        def raise_for_status():
            if r.status_code == 404:
                raise requests.HTTPError("404")
        def json_fn():
            return r._json
        r.raise_for_status = raise_for_status
        r.json = json_fn
        return r
    monkeypatch.setattr(ls.requests, "get", fake_get)
    return calls


def _task(task_id, status="running", started=None, finished=None, error=None, source="/fake/v.mp4", target="en"):
    if started is None:
        from datetime import datetime, timezone, timedelta
        started = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    return {
        "task_id": task_id,
        "job_id": task_id,
        "status": status,
        "source_video": source,
        "target_language": target,
        "output_dir": None,
        "outputs": {},
        "error": error,
        "created_at": started,
        "started_at": started,
        "finished_at": finished,
    }


# ── tts_default 真接通 ──

def test_tts_default_from_config_when_user_omits(monkeypatch, tmp_path):
    """用户不传 enable_tts 时，skill 应读 cfg.tts_default（默认 True）。"""
    from flowmind.config import FlowmindConfig, LocalizerConfig
    cfg = FlowmindConfig(localizer=LocalizerConfig(tts_default=False))
    # monkeypatch load_config 直接返回指定配置（DEFAULT_CONFIG_PATH 在 def 时已绑定，不能改）
    monkeypatch.setattr("flowmind.skills.localize_batch.load_config", lambda: cfg)

    captured = {}
    def fake_post(url, json=None, timeout=None, **_kw):
        captured["payload"] = json
        class _R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"}
        return _R()
    import flowmind.skills.localize_batch as lb
    monkeypatch.setattr(lb.requests, "post", fake_post)
    # health 通过
    _install_get_health(monkeypatch)

    r = invoke("localize_batch", {"video_paths": [_path(1)]})
    assert r.ok is True
    assert captured["payload"]["enable_tts"] is False, \
        "用户未传 enable_tts 时应读 cfg.tts_default=false"


def test_tts_explicit_overrides_config(monkeypatch, tmp_path):
    """用户显式传 enable_tts=True 时，覆盖 cfg.tts_default=False。"""
    from flowmind.config import FlowmindConfig, LocalizerConfig
    cfg = FlowmindConfig(localizer=LocalizerConfig(tts_default=False))
    monkeypatch.setattr("flowmind.skills.localize_batch.load_config", lambda: cfg)

    captured = {}
    def fake_post(url, json=None, timeout=None, **_kw):
        captured["payload"] = json
        class _R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"}
        return _R()
    import flowmind.skills.localize_batch as lb
    monkeypatch.setattr(lb.requests, "post", fake_post)
    _install_get_health(monkeypatch)

    r = invoke("localize_batch", {"video_paths": [_path(1)], "enable_tts": True})
    assert r.ok is True
    assert captured["payload"]["enable_tts"] is True


# ── stalled 判定：retrying 不算 stalled ──

def test_retrying_task_is_not_stalled_even_if_long(monkeypatch):
    """retrying + 启动很久以前 → 不算 stalled（VL 在自动重试，不是真卡住）。"""
    from datetime import datetime, timezone, timedelta
    long_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _install_get_status(monkeypatch, {"j1": _task("j1", status="retrying", started=long_ago)})
    r = invoke("localize_status", {"task_ids": ["j1"]})
    assert r.ok is True
    assert r.data.tasks[0].is_stalled is False
    # 不应触发 STAL-01
    chain = r.reasoning[0]
    assert not any(rule.rule_id == "STAL-01" for rule in chain.triggered_rules)


def test_running_task_still_marked_stalled_over_threshold(monkeypatch):
    """running + 启动很久以前 → 仍标 stalled（不变行为）。"""
    from datetime import datetime, timezone, timedelta
    long_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _install_get_status(monkeypatch, {"j2": _task("j2", status="running", started=long_ago)})
    r = invoke("localize_status", {"task_ids": ["j2"]})
    assert r.ok is True
    assert r.data.tasks[0].is_stalled is True
    chain = r.reasoning[0]
    assert any(rule.rule_id == "STAL-01" for rule in chain.triggered_rules)