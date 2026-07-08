"""
localize_cancel 技能演示 —— 取消运行中任务。

运行：uv run python examples/localize_cancel_demo.py
"""

from __future__ import annotations

import flowmind.skills  # noqa: F401
import flowmind.skills.localize_cancel as lc
from flowmind.discover import field_names
from flowmind.skill import invoke


def section(title: str) -> None:
    print(f"\n{'─' * 60}\n  {title}\n{'─' * 60}")


def main() -> None:
    section("0) discover('localize_cancel')")
    for p, names in field_names("localize_cancel").items():
        print(f"  {p}: {names}")

    section("1) Happy path：取消 queued/running 任务")
    def fake_delete(url, timeout=None, **_kw):
        class _R:
            status_code = 200
            _json = {"message": "task cancelled"}
            def raise_for_status(self): pass
            def json(self): return self._json
        return _R()
    lc.requests.delete = fake_delete

    r = invoke("localize_cancel", {"task_id": "job-running-001"})
    print(f"  ok        : {r.ok}")
    print(f"  task_id   : {r.data.task_id}")
    print(f"  cancelled : {r.data.cancelled}")
    print(f"  message   : {r.data.message}")
    print(f"  推理      : {r.reasoning[0].conclusion}")

    section("2) 任务已完成（400）→ degraded + video（资源状态不对）")
    def fake_delete_400(url, timeout=None, **_kw):
        class _R:
            status_code = 400
            _json = {"detail": "Cannot cancel task (already finished)"}
            def raise_for_status(self): pass
            def json(self): return self._json
        return _R()
    lc.requests.delete = fake_delete_400

    r = invoke("localize_cancel", {"task_id": "job-finished-001"})
    print(f"  degraded        : {r.metrics.degraded}")
    print(f"  failure_category : {r.data.failure_category}（video）")
    print(f"  cancelled        : {r.data.cancelled}")
    print(f"  message         : {r.data.message}")


if __name__ == "__main__":
    main()