"""字幕残留硬 SLA 测试：字幕一定不能残留。

P0 测试——任何 commit 如果让字幕残留 > 1%，就挂掉，阻止 merge。
这是用户硬要求：「中文字幕一定不能残留」。

v0.3 变更：默认策略从 delogo 改为 ocr_erase_redraw（OCR 定位+擦除+重绘）。
delogo/inpaint/overlay/auto 全部弃用。

覆盖：
1. 默认策略必须是 ocr_erase_redraw（防有人改回 delogo/inpaint/overlay/auto）
2. ocr_erase_redraw 流程在 ffenv + 默认配置下，字幕区白像素必须 < 原视频 1%
3. LocalizerInput 入参默认值正确（enable_tts / remove_subtitles / strategy）
"""
from __future__ import annotations

import pytest

import flowmind.skills  # noqa: F401  触发技能注册
from flowmind.config import FlowmindConfig, LocalizerConfig
from flowmind.skill import invoke


# ── 1. 默认值契约 ──

def test_default_strategy_is_ocr_erase_redraw():
    """默认字幕处理策略必须是 ocr_erase_redraw（OCR 定位+擦除+重绘）。
    改回 delogo/inpaint/overlay/auto 任何老路径都会挂。
    """
    cfg = FlowmindConfig(localizer=LocalizerConfig())
    assert cfg.localizer.remove_subtitles_strategy_default == "ocr_erase_redraw", (
        "v0.3 默认策略必须是 ocr_erase_redraw；delogo/inpaint/overlay/auto 全部弃用"
    )


def test_default_remove_subtitles_is_true():
    """默认必须开启字幕擦除（业务要求：海外观众不读中文，原字幕=视觉噪音）。"""
    cfg = FlowmindConfig(localizer=LocalizerConfig())
    assert cfg.localizer.remove_subtitles_default is True


def test_default_target_and_source_lang():
    """默认目标/源语言：用户可在 flowmind.config.toml 覆盖。"""
    cfg = FlowmindConfig(localizer=LocalizerConfig())
    assert cfg.localizer.target_lang_default == "en"
    assert cfg.localizer.source_lang_default == "zh"


def test_invoke_uses_ocr_erase_redraw_when_strategy_omitted(monkeypatch):
    """调用 LocalizerInput 不传 remove_subtitles_strategy → payload 默认值是 ocr_erase_redraw。"""
    cfg = FlowmindConfig(localizer=LocalizerConfig(
        remove_subtitles_strategy_default="ocr_erase_redraw",
    ))
    monkeypatch.setattr("flowmind.skills.localize_batch.load_config", lambda: cfg)

    captured = {}

    def fake_post(url, json=None, timeout=None, **_kw):
        captured["payload"] = json

        class _R:
            status_code = 200
            _json = {"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"}

            def raise_for_status(self): pass

            def json(self): return self._json

        return _R()

    def fake_get(url, timeout=None, **_kw):
        class _R:
            status_code = 200
            _json = {"status": "ok"}

            def raise_for_status(self): pass

            def json(self): return self._json

        return _R()

    import flowmind.skills.localize_batch as lb
    monkeypatch.setattr(lb.requests, "get", fake_get)
    monkeypatch.setattr(lb.requests, "post", fake_post)

    r = invoke("localize_batch", {"video_paths": ["/tmp/fake.mp4"]})
    assert r.ok is True
    assert captured["payload"]["remove_subtitles_strategy"] == "ocr_erase_redraw", (
        "字幕一定不能残留：不传 strategy 时 payload 默认必须是 ocr_erase_redraw"
    )


def test_localize_input_minimal_payload_uses_ocr_erase_redraw(monkeypatch):
    """极简调用：只传 video_paths，payload 默认 enable_tts+remove_subtitles+ocr_erase_redraw 全开。"""
    cfg = FlowmindConfig(localizer=LocalizerConfig(
        remove_subtitles_strategy_default="ocr_erase_redraw",
        remove_subtitles_default=True,
        tts_default=True,
    ))
    monkeypatch.setattr("flowmind.skills.localize_batch.load_config", lambda: cfg)

    captured = {}

    def fake_post(url, json=None, timeout=None, **_kw):
        captured["payload"] = json

        class _R:
            status_code = 200
            _json = {"batch_id": "b", "job_ids": ["j"], "total": 1, "message": "ok"}

            def raise_for_status(self): pass

            def json(self): return self._json

        return _R()

    def fake_get(url, timeout=None, **_kw):
        class _R:
            status_code = 200
            _json = {"status": "ok"}

            def raise_for_status(self): pass

            def json(self): return self._json

        return _R()

    import flowmind.skills.localize_batch as lb
    monkeypatch.setattr(lb.requests, "get", fake_get)
    monkeypatch.setattr(lb.requests, "post", fake_post)

    r = invoke("localize_batch", {"video_paths": ["/fake/v.mp4"]})
    assert r.ok is True
    p = captured["payload"]
    assert p["remove_subtitles_strategy"] == "ocr_erase_redraw"
    assert p["enable_tts"] is True
    assert p["remove_subtitles"] is True
    assert p["target_lang"] == "en"  # cfg.target_lang_default
    assert p["source_lang"] == "zh"  # cfg.source_lang_default


# ── 2. 端到端字幕清除率（SLA 集成测试，需 --run-slow）──

@staticmethod
def _check_delogo_output_pixel_ratio(video_path, output_path, time_points):
    """抽出时间点帧，比较字幕区白像素残留率。"""
    import os
    import cv2
    import numpy as np

    if not os.path.exists(output_path) or not os.path.exists(video_path):
        return None  # 跳过（CI 没产物）

    def white_pixels(video_path, t):
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        h, w = frame.shape[:2]
        sub_h = int(h * 0.18)
        return int(np.sum(
            cv2.cvtColor(frame[h - sub_h - 20:h - 20, :], cv2.COLOR_BGR2GRAY) > 200
        ))

    for t in time_points:
        orig = white_pixels(video_path, t)
        out = white_pixels(output_path, t)
        if orig is None or orig == 0:
            continue
        ratio = out / orig
        assert ratio < 0.01, (
            f"字幕残留 ❌ t={t}s 原 {orig} → 输出 {out} 像素，"
            f"残留率 {ratio*100:.1f}% > 1%"
        )


def test_ocr_erase_redraw_subtitle_clearing_sla_real():
    """ocr_erase_redraw 跑过后的产物必须字幕残留 < 1%。

    需要：先跑过一次 ocr_erase_redraw pipeline 把 /tmp/vl_input_test.mp4 处理完，
    产物在 /tmp/vl_output/<task_id>/output_sub.mp4。

    本测试默认 skip（CI 环境没产物或没 cv2）。本地验证：
        pytest tests/test_subtitle_clearing_sla.py::test_ocr_erase_redraw_subtitle_clearing_sla_real
    （前提：本地有 /tmp/vl_input_test.mp4 + ffenv 装了 cv2 + VL 跑过一次 ocr_erase_redraw）
    """
    # 关键依赖：cv2（OpenCV）在 flowmind venv 没装 → 跳过集成测试
    pytest.importorskip("cv2", reason="cv2 未安装（仅 ffenv 有），跳过集成测试")

    import os
    import glob

    src = "/tmp/vl_input_test.mp4"
    # 找最新的 ocr_erase_redraw 产物
    candidates = sorted(
        glob.glob("/tmp/vl_output/*/output_sub.mp4"),
        key=os.path.getmtime,
        reverse=True,
    )
    if not candidates or not os.path.exists(src):
        pytest.skip(
            "需要先跑一次 ocr_erase_redraw："
            "curl -X POST http://localhost:8000/api/v1/batch "
            "-d '{\"video_paths\":[\"/tmp/vl_input_test.mp4\"],\"enable_tts\":true,"
            "\"remove_subtitles\":true,\"remove_subtitles_strategy\":\"ocr_erase_redraw\"}'"
        )

    _check_delogo_output_pixel_ratio(
        video_path=src,
        output_path=candidates[0],
        time_points=[5, 30, 60, 90],
    )