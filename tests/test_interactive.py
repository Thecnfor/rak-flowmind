"""flowmind.interactive —— 对话式可交互初始化测试。"""
from __future__ import annotations

import pytest

from flowmind.config import FlowmindConfig
from flowmind.interactive import (
    QUESTIONS,
    _coerce,
    _parse_bool,
    _parse_choice,
    run_interactive_init,
)


# ── Question 数据完整性 ──

def test_questions_covers_all_init_for_user_params():
    """QUESTIONS 的 id 必须覆盖 init_for_user 的所有非废弃参数。"""
    expected = {
        "target_lang", "source_lang", "enable_tts", "remove_subtitles",
        "remove_subtitles_strategy", "tts_voice", "subtitle_font_size",
        "subtitle_position", "output_filename_suffix",
    }
    actual = {q.id for q in QUESTIONS}
    assert actual == expected, f"差异: missing={expected-actual}, extra={actual-expected}"


def test_every_question_has_default():
    for q in QUESTIONS:
        assert q.default is not ..., f"{q.id} 缺 default"
        assert q.prompt, f"{q.id} 缺 prompt"


# ── 类型转换 ──

def test_parse_bool():
    assert _parse_bool("y") is True
    assert _parse_bool("n") is False
    assert _parse_bool("yes") is True
    assert _parse_bool("YES") is True
    assert _parse_bool("no") is False
    assert _parse_bool("") is True    # 默认 = True
    assert _parse_bool("0") is False
    with pytest.raises(ValueError):
        _parse_bool("maybe")


def test_parse_choice_case_insensitive():
    assert _parse_choice("TH", ("en", "th"), "en") == "th"
    assert _parse_choice("th", ("en", "th"), "en") == "th"
    assert _parse_choice("", ("en", "th"), "en") == "en"  # 空 → 默认
    with pytest.raises(ValueError):
        _parse_choice("klingon", ("en", "th"), "en")


def test_coerce_for_all_question_types():
    assert _coerce("target_lang", "th") == "th"
    assert _coerce("enable_tts", "y") is True
    assert _coerce("enable_tts", "n") is False
    assert _coerce("tts_voice", "th-TH-NiwatNeural") == "th-TH-NiwatNeural"
    assert _coerce("tts_voice", "") is None
    assert _coerce("subtitle_font_size", "26") == 26
    assert _coerce("subtitle_position", "bottom_safe") == "bottom_safe"
    assert _coerce("output_filename_suffix", "_th") == "_th"


# ── run_interactive_init 端到端 ──

@pytest.fixture
def in_tmp_cwd(tmp_path, monkeypatch):
    """每个 test 在独立 tmp 目录跑（避免污染真实 flowmind.config.toml）。"""
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def test_run_interactive_init_with_scripted_inputs(in_tmp_cwd):
    """东南亚营销负责人 9 个回答 → 写 TOML → reload 拿回一致。"""
    scripted = iter([
        "th",                          # target_lang
        "zh",                          # source_lang
        "y",                           # enable_tts
        "th-TH-NiwatNeural",           # tts_voice
        "y",                           # remove_subtitles
        "",                            # strategy（用默认）
        "26",                          # font_size
        "",                            # position（用默认）
        "_th",                         # suffix
    ])
    ask_log = []
    def ask(prompt):
        val = next(scripted)
        ask_log.append(val)
        return val

    cfg = run_interactive_init(ask_fn=ask, quiet=True, save_path=in_tmp_cwd / "flowmind.config.toml")
    assert isinstance(cfg, FlowmindConfig)
    assert cfg.localizer.target_lang_default == "th"
    assert cfg.localizer.source_lang_default == "zh"
    assert cfg.localizer.tts_default is True
    assert cfg.localizer.tts_voice == "th-TH-NiwatNeural"
    assert cfg.localizer.remove_subtitles_default is True
    assert cfg.localizer.subtitle_font_size == 26
    assert cfg.localizer.output_filename_suffix == "_th"
    assert len(ask_log) == 9


def test_run_interactive_init_all_defaults(in_tmp_cwd):
    """用户一路按 Enter（9 次空回答）→ 全默认生效。"""
    def always_enter(prompt):
        return ""

    cfg = run_interactive_init(ask_fn=always_enter, quiet=True, save_path=in_tmp_cwd / "flowmind.config.toml")
    assert cfg.localizer.target_lang_default == "en"  # 默认
    assert cfg.localizer.source_lang_default == "zh"
    assert cfg.localizer.tts_voice is None            # 默认 None
    assert cfg.localizer.subtitle_font_size == 22     # 默认 22


def test_run_interactive_init_writes_toml_file(in_tmp_cwd):
    """写完文件应该真存在且可重新 load。"""
    def ask(prompt):
        return ""

    target = in_tmp_cwd / "flowmind.config.toml"
    run_interactive_init(ask_fn=ask, quiet=True, save_path=target)
    assert target.exists()
    # 文件含 [localizer] 段
    text = target.read_text()
    assert "[localizer]" in text
    # 由于全默认，所有 None 字段被 exclude_none 排除
    assert "tts_voice" not in text  # None → 不写


def test_run_interactive_init_choice_validation_retries(in_tmp_cwd):
    """输入无效选项时循环重新问，直到给合法值。"""
    scripted = iter([
        "klingon",      # Q1 target_lang 第一次 → 错（klingon 不在 choices）
        "th",           # Q1 target_lang 第二次 → 对
        "zh",           # Q2 source_lang
        "y",            # Q3 enable_tts
        "",             # Q4 tts_voice（默认 None）
        "y",            # Q5 remove_subtitles
        "ocr_erase_redraw",  # Q6 strategy（只有这一个选项）
        "22",           # Q7 font_size
        "bottom_safe",  # Q8 position
        "sub",          # Q9 suffix
    ])
    def ask(prompt):
        return next(scripted)

    cfg = run_interactive_init(ask_fn=ask, quiet=True, save_path=in_tmp_cwd / "flowmind.config.toml")
    assert cfg.localizer.target_lang_default == "th"


def test_run_interactive_init_keyboard_interrupt_safe(in_tmp_cwd):
    """用户 Ctrl-C 中断：不留半成品配置文件。"""
    def raise_eof(prompt):
        raise EOFError("user pressed Ctrl-D / Ctrl-C")

    target = in_tmp_cwd / "flowmind.config.toml"
    with pytest.raises(SystemExit) as excinfo:
        run_interactive_init(ask_fn=raise_eof, quiet=True, save_path=target)
    assert excinfo.value.code == 1
    # 中断 → 不写文件
    assert not target.exists()