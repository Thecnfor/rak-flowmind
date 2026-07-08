"""
localize_retry 技能演示 —— 重提失败任务。

运行：uv run python examples/localize_retry_demo.py
"""

from __future__ import annotations

import flowmind.skills  # noqa: F401
import flowmind.skills.localize_retry as lr
from flowmind.discover import field_names
from flowmind.skill import invoke


def section(title: str) -> None:
    print(f"\n{'─' * 60}\n  {title}\n{'─' * 60}")


def main() -> None:
    section("0) discover('localize_retry')")
    for p, names in field_names("localize_retry").items():
        print(f"  {p}: {names}")

    section("1) Happy path：重提一个 failed 任务")
    def fake_get(url, timeout=None, **_kw):
        class _R:
            status_code = 200
            _json = {
                "task_id": "job-old-001", "status": "failed",
                "source_video": "/old/path/promo.mp4",
                "target_language": "th",
                "source_lang": "zh",
                "enable_tts": True, "remove_subtitles": True,
            }
            def raise_for_status(self): pass
            def json(self): return self._json
        return _R()
    def fake_post(url, json=None, timeout=None, **_kw):
        class _R:
            status_code = 200
            _json = {"task_id": "job-retried-001", "job_id": "job-retried-001"}
            def raise_for_status(self): pass
            def json(self): return self._json
        return _R()
    lr.requests.get = fake_get
    lr.requests.post = fake_post

    r = invoke("localize_retry", {"task_id": "job-old-001"})
    print(f"  ok            : {r.ok}")
    print(f"  original_task : {r.data.original_task_id}")
    print(f"  new_task      : {r.data.new_task_id}（新独立任务）")
    print(f"  original_status : {r.data.original_status}")
    print(f"  沿用参数      :")
    print(f"    source_video : {r.data.source_video}")
    print(f"    target_lang  : {r.data.target_lang}")
    print(f"    enable_tts   : {r.data.enable_tts}")
    print(f"    remove_subtitles : {r.data.remove_subtitles}")
    print(f"  推理          : {r.reasoning[0].conclusion}")

    section("2) 原任务不存在（404）→ degraded + video")
    def fake_get_404(url, timeout=None, **_kw):
        class _R:
            status_code = 404
            def raise_for_status(self): pass
            def json(self): return {}
        return _R()
    lr.requests.get = fake_get_404

    r = invoke("localize_retry", {"task_id": "job-ghost"})
    print(f"  degraded       : {r.metrics.degraded}")
    print(f"  failure_category : {r.data.failure_category}")
    print(f"  message        : {r.data.message}")

    section("3) 原任务缺 source_video（VL 假完成）→ degraded + video")
    def fake_get_no_source(url, timeout=None, **_kw):
        class _R:
            status_code = 200
            _json = {"task_id": "job-fake", "status": "completed",
                     "source_video": None, "target_language": "th"}
            def raise_for_status(self): pass
            def json(self): return self._json
        return _R()
    lr.requests.get = fake_get_no_source

    r = invoke("localize_retry", {"task_id": "job-fake"})
    print(f"  failure_category : {r.data.failure_category}")
    print(f"  message          : {r.data.message}")


if __name__ == "__main__":
    main()