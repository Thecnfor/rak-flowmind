"""localize_status 技能测试：单/多任务状态查询、stalled 判定、四段式链。"""
from __future__ import annotations

import requests

import flowmind.skills  # noqa: F401  触发技能注册
from flowmind.skill import invoke


# ── 工具 ──

def _args(task_ids, *, stall_threshold_seconds=None):
    out = {"task_ids": list(task_ids)}
    if stall_threshold_seconds is not None:
        out["stall_threshold_seconds"] = stall_threshold_seconds
    return out


def _task(task_id, status="running", error=None, output_dir=None,
          created="2026-07-03T02:00:00", started="2026-07-03T02:00:05",
          finished=None, source_video="/fake/v.mp4", target_lang="en"):
    body = {
        "task_id": task_id,
        "job_id": task_id,
        "status": status,
        "source_video": source_video,
        "target_language": target_lang,
        "output_dir": output_dir,
        "outputs": {} if output_dir is None else {"output_sub.mp4": output_dir + "/output_sub.mp4"},
        "error": error,
        "progress": None,
        "created_at": created,
        "started_at": started,
        "finished_at": finished,
    }
    return body


class _FakeResp:
    def __init__(self, *, status_code=200, json_data=None, raise_for_status_exc=None):
        self.status_code = status_code
        self._json = json_data or {}
        self._raise_exc = raise_for_status_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._json


def _install_get(monkeypatch, *, per_task_response):
    """per_task_response: dict[task_id, json_body] 或 Exception（统一抛）"""
    calls: list[dict] = []

    def fake_get(url, timeout=None, **_kw):
        calls.append({"url": url, "timeout": timeout})
        # 解析 task_id from URL
        task_id = url.rsplit("/", 1)[-1]
        if isinstance(per_task_response, Exception):
            raise per_task_response
        body = per_task_response.get(task_id)
        if body is None:
            return _FakeResp(status_code=404, raise_for_status_exc=requests.HTTPError("404"))
        return _FakeResp(status_code=200, json_data=body)

    monkeypatch.setattr("flowmind.skills.localize_status.requests.get", fake_get)
    return calls


# ── 入参校验 ──

def test_empty_task_ids_is_validation_error(monkeypatch):
    calls = _install_get(monkeypatch, per_task_response={})
    result = invoke("localize_status", _args([]))
    assert result.ok is False
    assert result.error.code == "VALIDATION"
    assert calls == []


# ── 单任务：completed ──

def test_single_completed_task(monkeypatch):
    from datetime import datetime, timedelta, timezone
    finished = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    calls = _install_get(monkeypatch, per_task_response={
        "j1": _task("j1", status="completed", output_dir="/out/j1",
                    finished=finished),
    })
    result = invoke("localize_status", _args(["j1"]))
    assert result.ok is True
    assert result.data.tasks[0].task_id == "j1"
    assert result.data.tasks[0].status == "completed"
    assert result.data.tasks[0].is_terminal is True
    assert result.data.tasks[0].is_stalled is False
    assert result.data.completed == 1
    assert result.data.failed == 0
    assert result.data.all_terminal is True
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/api/v1/tasks/j1")


# ── 单任务：running + stalled 判定 ──

def test_running_task_marked_stalled_over_threshold(monkeypatch):
    """running + started 很久以前 → is_stalled=True。"""
    from datetime import datetime, timedelta, timezone
    long_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _install_get(monkeypatch, per_task_response={
        "j2": _task("j2", status="running", started=long_ago, created=long_ago),
    })
    result = invoke("localize_status", _args(["j2"]))
    assert result.ok is True
    t = result.data.tasks[0]
    assert t.status == "running"
    assert t.is_terminal is False
    assert t.is_stalled is True
    # 推理链命中 STAL-01
    chain = result.reasoning[0]
    assert any(r.rule_id == "STAL-01" for r in chain.triggered_rules)


def test_recently_started_running_not_stalled(monkeypatch):
    """running 但刚启动 → is_stalled=False（默认 threshold=600s）。"""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    recent_started = (now - timedelta(seconds=30)).isoformat()
    _install_get(monkeypatch, per_task_response={
        "j3": _task("j3", status="running", started=recent_started,
                    created=recent_started),
    })
    result = invoke("localize_status", _args(["j3"]))
    assert result.ok is True
    t = result.data.tasks[0]
    assert t.is_stalled is False


# ── 单任务：failed ──

def test_failed_task_marks_failure_and_terminal(monkeypatch):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    finished = (now - timedelta(seconds=30)).isoformat()
    _install_get(monkeypatch, per_task_response={
        "j4": _task("j4", status="failed", error="No module named 'whisperx'",
                    finished=finished),
    })
    result = invoke("localize_status", _args(["j4"]))
    assert result.ok is True
    t = result.data.tasks[0]
    assert t.status == "failed"
    assert t.is_terminal is True
    assert t.error == "No module named 'whisperx'"
    assert result.data.failed == 1
    chain = result.reasoning[0]
    assert any(r.rule_id == "STAL-02" for r in chain.triggered_rules)


# ── 多任务混合 ──

def test_multi_task_aggregation(monkeypatch):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    b_started = (now - timedelta(hours=2)).isoformat()  # 2 小时前启动 → 必卡住
    _install_get(monkeypatch, per_task_response={
        "a": _task("a", status="completed", output_dir="/o/a",
                   finished=(now - timedelta(seconds=30)).isoformat()),
        "b": _task("b", status="running", started=b_started, created=b_started),
        "c": _task("c", status="failed", error="boom",
                   finished=(now - timedelta(seconds=20)).isoformat()),
        "d": _task("d", status="queued", started=None),
    })
    result = invoke("localize_status", _args(["a", "b", "c", "d"]))
    assert result.ok is True
    assert result.data.completed == 1
    assert result.data.failed == 1
    assert result.data.running == 1
    assert result.data.queued == 1
    assert result.data.stalled == 1     # b 卡住
    assert result.data.all_terminal is False  # 还有 running/queued


def test_multi_task_all_terminal(monkeypatch):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    _install_get(monkeypatch, per_task_response={
        "x": _task("x", status="completed", output_dir="/o/x",
                   finished=(now - timedelta(seconds=30)).isoformat()),
        "y": _task("y", status="failed", error="nope",
                   finished=(now - timedelta(seconds=20)).isoformat()),
    })
    result = invoke("localize_status", _args(["x", "y"]))
    assert result.data.all_terminal is True
    chain = result.reasoning[0]
    assert any(r.rule_id == "STAL-04" for r in chain.triggered_rules)


# ── HTTP 错误兜底 ──

def test_task_not_found_returns_internal_error(monkeypatch):
    """GET 返 404 → 该 task 标 not_found，但整体 ok=True；其他 task 继续。"""
    _install_get(monkeypatch, per_task_response={})  # j5 不存在 → 404
    result = invoke("localize_status", _args(["j5"]))
    assert result.ok is True
    t = result.data.tasks[0]
    assert t.status == "not_found"
    assert t.is_terminal is True


def test_connection_error_returns_per_task_unknown(monkeypatch):
    """per-task 通信失败 → 该 task 标 status='unknown' + error 文本，batch 整体仍 ok=True。

    v0.3 设计：partial success 而不是全 batch 失败——这样 Agent 看到 N 个里只 1 个卡住，
    知道任务还在跑，可以继续轮询。
    """
    _install_get(monkeypatch, per_task_response=requests.exceptions.ConnectionError("refused"))
    result = invoke("localize_status", _args(["j6"]))
    assert result.ok is True
    assert result.data.tasks[0].status == "unknown"
    assert "environment" in (result.data.tasks[0].error or "")


# ── 推理链四要素 ──

def test_reasoning_chain_has_four_stages(monkeypatch):
    _install_get(monkeypatch, per_task_response={
        "k": _task("k", status="completed", output_dir="/o/k", finished="2026-07-03T02:01:30"),
    })
    result = invoke("localize_status", _args(["k"]))
    chain = result.reasoning[0]
    assert chain.conclusion
    assert chain.causal_analysis
    assert chain.risk_note
    assert isinstance(chain.triggered_rules, list)
    assert isinstance(chain.evidence, list)


# ── 自定义 stall threshold ──

def test_custom_stall_threshold(monkeypatch):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    started = (now - timedelta(seconds=200)).isoformat()
    _install_get(monkeypatch, per_task_response={
        "s": _task("s", status="running", started=started, created=started),
    })
    # threshold=100s → 200s running 视为 stalled
    result = invoke("localize_status", _args(["s"], stall_threshold_seconds=100))
    assert result.data.tasks[0].is_stalled is True
    # threshold=500s → 200s running 不算 stalled
    result = invoke("localize_status", _args(["s"], stall_threshold_seconds=500))
    assert result.data.tasks[0].is_stalled is False


def test_metrics_and_trace_present(monkeypatch):
    _install_get(monkeypatch, per_task_response={
        "m": _task("m", status="completed", output_dir="/o/m", finished="2026-07-03T02:01:30"),
    })
    result = invoke("localize_status", _args(["m"]))
    assert result.ok is True
    assert result.metrics.sample_size == 1
    assert result.metrics.latency_ms >= 0.0
    assert result.trace.trace_id