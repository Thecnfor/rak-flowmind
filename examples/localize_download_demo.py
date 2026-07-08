"""
localize_download 技能演示 —— 拉取已完成任务的产物清单 + VL 下载 URL。

运行：uv run python examples/localize_download_demo.py
"""

from __future__ import annotations

import flowmind.skills  # noqa: F401
import flowmind.skills.localize_download as ld
from flowmind.discover import field_names
from flowmind.skill import invoke


def section(title: str) -> None:
    print(f"\n{'─' * 60}\n  {title}\n{'─' * 60}")


def main() -> None:
    section("0) discover('localize_download')")
    for p, names in field_names("localize_download").items():
        print(f"  {p}: {names}")

    section("1) Happy path：completed 任务 3 个产物")
    def fake_get(url, timeout=None, **_kw):
        class _R:
            status_code = 200
            _json = {
                "task_id": "job-completed-001",
                "status": "completed",
                "output_dir": "/tmp/vl_output/job-completed-001",
                "outputs": {
                    "output_sub.mp4": "/tmp/vl_output/job-completed-001/output_sub.mp4",
                    "dubbed_video.mp4": "/tmp/vl_output/job-completed-001/dubbed_video.mp4",
                    "trans.srt": "/tmp/vl_output/job-completed-001/trans.srt",
                },
            }
            def raise_for_status(self): pass
            def json(self): return self._json
        return _R()
    ld.requests.get = fake_get

    r = invoke("localize_download", {"task_id": "job-completed-001"})
    print(f"  ok          : {r.ok}")
    print(f"  task_id     : {r.data.task_id}")
    print(f"  status      : {r.data.status}")
    print(f"  files ({len(r.data.files)})：")
    for f in r.data.files:
        print(f"    • {f.filename:20s} → {f.url}")

    section("2) VL 假完成：completed 但 outputs 空 → degraded")
    def fake_get_empty(url, timeout=None, **_kw):
        class _R:
            status_code = 200
            _json = {"task_id": "job-fake-done", "status": "completed",
                     "output_dir": "/tmp/vl/job-fake-done", "outputs": {}}
            def raise_for_status(self): pass
            def json(self): return self._json
        return _R()
    ld.requests.get = fake_get_empty

    r = invoke("localize_download", {"task_id": "job-fake-done"})
    print(f"  degraded     : {r.data.degraded}（VL 假完成信号）")
    print(f"  files        : {len(r.data.files)}")
    print(f"  warning      : {r.data.warning}")

    section("3) 任务不存在（404）→ degraded + video category")
    def fake_get_404(url, timeout=None, **_kw):
        class _R:
            status_code = 404
            def raise_for_status(self): pass
            def json(self): return {}
        return _R()
    ld.requests.get = fake_get_404

    r = invoke("localize_download", {"task_id": "job-ghost"})
    print(f"  degraded          : {r.metrics.degraded}")
    print(f"  failure_category  : {r.data.failure_category}（video → 任务不存在）")
    print(f"  retriable         : {r.data.retriable}")


if __name__ == "__main__":
    main()