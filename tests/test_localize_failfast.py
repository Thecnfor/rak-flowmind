"""localize_batch fail-fast 测试：VL 不通时不要 submit，立刻返回 INTERNAL+environment。"""
from __future__ import annotations

import requests

import flowmind.skills  # noqa: F401  触发技能注册
from flowmind.skill import invoke


# ── 工具：拦截 health check + submit ──

def _install_get_health(monkeypatch, *, side_effect=None, status_code=200, json_data=None):
    """拦截 requests.get（用于 health 探活）。"""
    import flowmind.skills.localize_batch as lb
    def fake_get(url, timeout=None, **_kw):
        if side_effect is not None:
            raise side_effect
        class _R:
            pass
        r = _R()
        r.status_code = status_code
        r._json = json_data or {"status": "ok"}
        def raise_for_status():
            if r.status_code >= 400:
                from requests.exceptions import HTTPError
                raise HTTPError(f"{r.status_code} HTTPError")
        def json():
            return r._json
        r.raise_for_status = raise_for_status
        r.json = json
        return r
    monkeypatch.setattr(lb.requests, "get", fake_get)


def _install_post(monkeypatch, *, status_code=200, json_data=None, side_effect=None):
    import flowmind.skills.localize_batch as lb
    calls = []
    def fake_post(url, json=None, timeout=None, **_kw):
        calls.append({"url": url, "json": json, "timeout": timeout})
        if side_effect is not None:
            raise side_effect
        class _R:
            pass
        r = _R()
        r.status_code = status_code
        r._json = json_data or {"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"}
        def raise_for_status():
            pass
        def json():
            return r._json
        r.raise_for_status = raise_for_status
        r.json = json
        return r
    monkeypatch.setattr(lb.requests, "post", fake_post)
    return calls


# ── 测试 ──

def test_health_check_failure_short_circuits_submit(monkeypatch):
    """VL /health 抛 ConnectionError → 立即 degraded+environment，不调 POST。"""
    _install_get_health(monkeypatch, side_effect=requests.exceptions.ConnectionError("refused"))
    post_calls = _install_post(monkeypatch)
    r = invoke("localize_batch", {"video_paths": ["/fake/v.mp4"]})
    assert r.metrics.degraded is True
    assert r.data.failure_category == "environment"
    assert r.data.retriable is False
    assert post_calls == [], "VL 不通时不该发 submit 请求"


def test_health_check_5xx_short_circuits_submit(monkeypatch):
    """VL /health 返 5xx → 立即 degraded+transient。"""
    _install_get_health(monkeypatch, status_code=503)
    post_calls = _install_post(monkeypatch)
    r = invoke("localize_batch", {"video_paths": ["/fake/v.mp4"]})
    assert r.metrics.degraded is True
    assert r.data.failure_category == "transient"
    assert post_calls == []


def test_health_check_ok_then_submit_proceeds(monkeypatch):
    """健康检查通过 → 继续提交。"""
    _install_get_health(monkeypatch, status_code=200, json_data={"status": "ok"})
    post_calls = _install_post(monkeypatch)
    r = invoke("localize_batch", {"video_paths": ["/fake/v.mp4"]})
    assert r.ok is True
    assert len(post_calls) == 1


def test_health_check_uses_short_timeout(monkeypatch):
    """健康检查超时必须短（≤3s），不能拖累 submit 路径。"""
    seen = {}
    def fake_get(url, timeout=None, **_kw):
        seen["timeout"] = timeout
        raise requests.exceptions.Timeout("slow")
    import flowmind.skills.localize_batch as lb
    monkeypatch.setattr(lb.requests, "get", fake_get)
    _install_post(monkeypatch)
    invoke("localize_batch", {"video_paths": ["/fake/v.mp4"]})
    assert seen.get("timeout") is not None
    assert seen["timeout"] <= 3.0, f"health timeout 应该 ≤3s，实际 {seen['timeout']}"