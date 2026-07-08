"""
localize_status 技能演示 —— 批量查询任务状态 + 推理链。

运行：uv run python examples/localize_status_demo.py

展示：
1. discover() 自动字段发现
2. happy path：3 个任务，其中 1 个 stalled（> 600s 未完成）
3. concurrency：ThreadPoolExecutor 并发查 N 个任务
4. per-task 404 → 标 not_found（partial success）
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

import flowmind.skills  # noqa: F401
import flowmind.skills.localize_status as ls
from flowmind.discover import field_names
from flowmind.skill import invoke


def section(title: str) -> None:
    print(f"\n{'─' * 60}\n  {title}\n{'─' * 60}")


def main() -> None:
    section("0) discover('localize_status') —— Agent 自查字段")
    for p, names in field_names("localize_status").items():
        print(f"  {p}: {names}")

    section("1) Happy path：3 个任务（含 1 个卡住超 600s）")
    statuses = ["completed", "running", "failed"]
    now = datetime.now(timezone.utc)
    start_times = {
        "job-0": now - timedelta(minutes=10),     # 已完成
        "job-1": now - timedelta(minutes=15),     # 跑了 15 分钟 → stalled（> 600s）
        "job-2": now - timedelta(minutes=5),      # 已失败
    }
    finished_times = {
        "job-0": now - timedelta(minutes=8),
        "job-1": None,
        "job-2": now - timedelta(minutes=3),
    }

    def fake_get(url, timeout=None, **_kw):
        tid = url.rsplit("/", 1)[-1]
        time.sleep(0.02)  # 模拟 I/O
        class _R:
            status_code = 200
            _json = {
                "task_id": tid,
                "status": statuses[int(tid.split("-")[1])],
                "started_at": start_times[tid].isoformat(),
                "finished_at": finished_times[tid].isoformat() if finished_times[tid] else None,
            }
            def raise_for_status(self): pass
            def json(self): return self._json
        return _R()
    ls.requests.get = fake_get

    t0 = time.time()
    r = invoke("localize_status", {"task_ids": ["job-0", "job-1", "job-2"]})
    elapsed_ms = (time.time() - t0) * 1000

    print(f"  ok         : {r.ok}")
    print(f"  用时       : {elapsed_ms:.0f}ms（3 个并发 × 20ms 模拟 I/O）")
    print(f"  汇总       :")
    print(f"    完成 / 运行 / 失败 / 卡住 = "
          f"{r.data.completed} / {r.data.running} / {r.data.failed} / {r.data.stalled}")
    print(f"    all_terminal = {r.data.all_terminal}")
    print(f"  每个任务：")
    for t in r.data.tasks:
        flags = []
        if t.is_stalled: flags.append("stalled")
        if t.is_terminal: flags.append("terminal")
        print(f"    • {t.task_id}: {t.status:10s}"
              f"  duration={t.duration_seconds:.0f}s"
              + (f"  [{','.join(flags)}]" if flags else ""))
    print(f"  推理：{r.reasoning[0].conclusion}")

    section("2) per-task 404 → 标 not_found（partial success，不影响其他任务）")
    def fake_get_with_404(url, timeout=None, **_kw):
        tid = url.rsplit("/", 1)[-1]
        if tid == "job-ghost":
            class _R:
                status_code = 404
                def raise_for_status(self): pass
                def json(self): return {}
            return _R()
        class _R:
            status_code = 200
            _json = {"task_id": tid, "status": "completed",
                     "started_at": now.isoformat(),
                     "finished_at": now.isoformat()}
            def raise_for_status(self): pass
            def json(self): return self._json
        return _R()
    ls.requests.get = fake_get_with_404

    r = invoke("localize_status", {"task_ids": ["job-0", "job-ghost", "job-2"]})
    print(f"  ok               : {r.ok}（partial success）")
    print(f"  tasks[0].status  : {r.data.tasks[0].status}")
    print(f"  tasks[1].status  : {r.data.tasks[1].status}（not_found）")
    print(f"  tasks[1].error   : {r.data.tasks[1].error}")
    print(f"  tasks[2].status  : {r.data.tasks[2].status}")
    print(f"  all_terminal     : {r.data.all_terminal}")


if __name__ == "__main__":
    main()