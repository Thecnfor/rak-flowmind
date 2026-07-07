"""P0b: localize_status 并发轮询 — ThreadPoolExecutor 限并发。

设计：
- task_ids 数 <= 1 → 串行（无线程开销）
- task_ids 数 > 1 → ThreadPoolExecutor，max_workers = min(N, poll_max_concurrency)
- 并发仅在 IO 阶段；汇总 + 推理链仍单线程（顺序无关）
- 单个 task 404/失败 → 该 task 标 not_found，整体仍 ok=True（与现有行为一致）
- 多 task 时统计正确（completed/failed/running/queued/stalled 累加准确）
"""
from __future__ import annotations

import threading
import time

import requests

import flowmind.skills  # noqa: F401
from flowmind.config import FlowmindConfig, LocalizerConfig
from flowmind.skill import invoke


# ── 工具 ──

def _task(task_id, status="completed", started=None, finished=None, error=None, output_dir=None):
    if started is None:
        from datetime import datetime, timezone, timedelta
        started = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    if finished is None and status == "completed":
        from datetime import datetime, timezone, timedelta
        finished = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    return {
        "task_id": task_id,
        "job_id": task_id,
        "status": status,
        "source_video": "/fake/v.mp4",
        "target_language": "en",
        "output_dir": output_dir,
        "outputs": {} if output_dir is None else {"output_sub.mp4": f"{output_dir}/output_sub.mp4"},
        "error": error,
        "created_at": started,
        "started_at": started,
        "finished_at": finished,
    }


def _install_get_with_concurrency(monkeypatch, per_task_response, *, sleep_seconds=0.0):
    """装 GET mock，记录每次调用的并发瞬间与返回值。

    - per_task_response: dict[task_id, body]
    - sleep_seconds: 每次 GET 模拟耗时；用来暴露「串行 vs 并发」差距
    """
    import flowmind.skills.localize_status as ls
    concurrent_max = [0]
    active = [0]
    lock = threading.Lock()
    calls = []

    def fake_get(url, timeout=None, **_kw):
        task_id = url.rsplit("/", 1)[-1]
        with lock:
            active[0] += 1
            if active[0] > concurrent_max[0]:
                concurrent_max[0] = active[0]
            calls.append({"task_id": task_id, "ts": time.monotonic()})

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

        body = per_task_response.get(task_id) or {}
        with lock:
            active[0] -= 1

        class _R:
            status_code = 200 if body else 404
            _json = body
            def raise_for_status(self):
                if self.status_code == 404:
                    raise requests.HTTPError("404")
            def json(self):
                return self._json
        return _R()
    monkeypatch.setattr(ls.requests, "get", fake_get)
    return calls, concurrent_max


def _set_concurrency(monkeypatch, max_concurrency: int):
    cfg = FlowmindConfig(localizer=LocalizerConfig(poll_max_concurrency=max_concurrency))
    monkeypatch.setattr("flowmind.skills.localize_status.load_config", lambda: cfg)


# ── 单 task 不开线程 ──

def test_single_task_id_uses_no_concurrency(monkeypatch):
    """只查 1 个 task_id → 串行（无并发开销）。"""
    _set_concurrency(monkeypatch, 8)
    calls, concurrent_max = _install_get_with_concurrency(
        monkeypatch, {"j1": _task("j1", status="completed")},
    )
    r = invoke("localize_status", {"task_ids": ["j1"]})
    assert r.ok is True
    assert concurrent_max[0] == 1, f"单 task 不该并发：{concurrent_max[0]}"


# ── 多 task 真正并发 ──

def test_multi_task_uses_concurrent_fetch(monkeypatch):
    """8 个 task_ids、max_concurrency=4 → 实际并发峰 = 4。"""
    _set_concurrency(monkeypatch, 4)
    per_task = {f"j{i}": _task(f"j{i}", status="completed") for i in range(8)}
    calls, concurrent_max = _install_get_with_concurrency(
        monkeypatch, per_task, sleep_seconds=0.05,
    )
    r = invoke("localize_status", {"task_ids": list(per_task.keys())})
    assert r.ok is True
    assert concurrent_max[0] >= 2, f"应该并发，实际峰值 {concurrent_max[0]}"
    assert concurrent_max[0] <= 4, f"应被 max_concurrency 限流：{concurrent_max[0]}"
    assert len(calls) == 8


def test_concurrency_bounded_by_min_of_n_and_max(monkeypatch):
    """3 个 task、max_concurrency=8 → 实际并发 = 3（不超过 N）。"""
    _set_concurrency(monkeypatch, 8)
    per_task = {f"j{i}": _task(f"j{i}", status="completed") for i in range(3)}
    calls, concurrent_max = _install_get_with_concurrency(
        monkeypatch, per_task, sleep_seconds=0.05,
    )
    r = invoke("localize_status", {"task_ids": list(per_task.keys())})
    assert r.ok is True
    assert concurrent_max[0] == 3, f"应等于 N，实际 {concurrent_max[0]}"


# ── 多 task 统计正确 ──

def test_multi_task_aggregation_correct_under_concurrency(monkeypatch):
    """并发查 6 个 task（含 1 failed / 5 completed）→ 统计准。"""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    per_task = {
        "c1": _task("c1", status="completed", output_dir="/o/c1",
                    finished=(now - timedelta(seconds=5)).isoformat()),
        "c2": _task("c2", status="completed", output_dir="/o/c2",
                    finished=(now - timedelta(seconds=5)).isoformat()),
        "c3": _task("c3", status="completed", output_dir="/o/c3",
                    finished=(now - timedelta(seconds=5)).isoformat()),
        "c4": _task("c4", status="completed", output_dir="/o/c4",
                    finished=(now - timedelta(seconds=5)).isoformat()),
        "c5": _task("c5", status="completed", output_dir="/o/c5",
                    finished=(now - timedelta(seconds=5)).isoformat()),
        "f1": _task("f1", status="failed", error="boom",
                    finished=(now - timedelta(seconds=5)).isoformat()),
    }
    _set_concurrency(monkeypatch, 8)
    _install_get_with_concurrency(monkeypatch, per_task)
    r = invoke("localize_status", {"task_ids": list(per_task.keys())})
    assert r.ok is True
    assert r.data.completed == 5
    assert r.data.failed == 1
    assert r.data.all_terminal is True


def test_one_task_404_others_continue_under_concurrency(monkeypatch):
    """并发查 3 个：1 个 404 → 标 not_found；其他正常完成；整体 ok=True。"""
    per_task = {
        "ok1": _task("ok1", status="completed"),
        "missing": None,  # 触发 404
        "ok2": _task("ok2", status="completed"),
    }
    _set_concurrency(monkeypatch, 8)
    _install_get_with_concurrency(monkeypatch, per_task)
    r = invoke("localize_status", {"task_ids": ["ok1", "missing", "ok2"]})
    assert r.ok is True
    by_id = {t.task_id: t for t in r.data.tasks}
    assert by_id["missing"].status == "not_found"
    assert by_id["missing"].is_terminal is True
    assert by_id["ok1"].status == "completed"
    assert by_id["ok2"].status == "completed"


# ── 性能对比（确保并发不是个 dummy）──

def test_concurrent_is_faster_than_serial_would_be(monkeypatch):
    """5 个 task 各 0.05s 延迟：并发应该明显快于 0.25s 串行下限。"""
    _set_concurrency(monkeypatch, 5)
    per_task = {f"j{i}": _task(f"j{i}", status="completed") for i in range(5)}
    _install_get_with_concurrency(monkeypatch, per_task, sleep_seconds=0.05)
    t0 = time.monotonic()
    r = invoke("localize_status", {"task_ids": list(per_task.keys())})
    elapsed = time.monotonic() - t0
    assert r.ok is True
    # 串行 5×0.05=0.25s，并发应该 < 0.15s（容许一些线程开销）
    assert elapsed < 0.15, f"并发应该 < 0.15s，实际 {elapsed:.3f}s"