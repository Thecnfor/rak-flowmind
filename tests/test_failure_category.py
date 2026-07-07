"""失败分类测试：invoke() 把异常按根因归到 environment/video/transient/unknown。

为什么需要：VL 一旦报 HuggingFace / DNS / NLLB 下载失败，那是「环境问题」，
Agent 不该傻乎乎地按视频问题重试 30 分钟。该机制让 Agent 立刻看到根因。
"""
from __future__ import annotations

import requests

import flowmind.skills  # noqa: F401  触发技能注册
from flowmind.contracts import SkillError
from flowmind.skill import _classify_exception, invoke


# ── 契约：SkillError.category 字段存在且默认 unknown ──

def test_skill_error_has_category_field_with_default_unknown():
    err = SkillError(code="INTERNAL", message="x")
    assert err.category == "unknown"


def test_skill_error_category_accepts_known_values():
    for cat in ("environment", "video", "transient", "unknown"):
        err = SkillError(code="INTERNAL", message="x", category=cat)
        assert err.category == cat


# ── 分类规则：环境类（外网/HF/DNS）──

def test_category_environment_for_huggingface_message():
    """VL 报 HuggingFace 下载错 → environment（让 Agent 知道去开外网/换模型）。"""
    exc = Exception("An error happened while trying to locate the files on the Hub "
                    "and we cannot find the appropriate snapshot folder for the "
                    "specified revision on the local disk.")
    assert _classify_exception(exc) == "environment"


def test_category_environment_for_dns_resolution():
    exc = Exception("HTTPSConnectionPool: Failed to resolve 'huggingface.co'")
    assert _classify_exception(exc) == "environment"


def test_category_environment_for_connection_refused():
    assert _classify_exception(requests.exceptions.ConnectionError("refused")) == "environment"


def test_category_environment_for_timeout():
    assert _classify_exception(requests.exceptions.Timeout("slow")) == "environment"


# ── 分类规则：视频类 ──

def test_category_video_for_file_not_found_message():
    exc = Exception("Video file not found: /fake/path.mp4")
    assert _classify_exception(exc) == "video"


def test_category_video_for_disallowed_extension_message():
    exc = Exception("File extension '.avi' not in allowed list")
    assert _classify_exception(exc) == "video"


# ── 分类规则：transient（5xx）──

def test_category_transient_for_http_500():
    exc = requests.exceptions.HTTPError("500 Server Error: Internal Server Error")
    assert _classify_exception(exc) == "transient"


def test_category_transient_for_502_503_504():
    for code in (502, 503, 504):
        exc = requests.exceptions.HTTPError(f"{code} Bad Gateway/Service Unavailable/Gateway Timeout")
        assert _classify_exception(exc) == "transient", f"{code} should be transient"


# ── 分类规则：unknown 兜底 ──

def test_category_unknown_for_unrelated_exception():
    assert _classify_exception(ValueError("奇怪")) == "unknown"


# ── 端到端：localize_batch 抛 ConnectionError 时，invoke() 透出 category ──

def test_localize_batch_connection_error_is_environment_category(monkeypatch):
    """submit 时 VL 连不上 → INTERNAL + environment；不让 Agent 傻等。"""
    from tests.test_localize_batch import _install_post
    _install_post(monkeypatch, side_effect=requests.exceptions.ConnectionError("refused"))
    r = invoke("localize_batch", {"video_paths": ["/fake/v.mp4"]})
    assert r.ok is False
    assert r.error.code == "INTERNAL"
    assert r.error.category == "environment"
    assert r.error.retriable is False, "环境问题不该鼓励重试"


def test_localize_batch_video_not_found_is_video_category(monkeypatch):
    """VL 400 报 Video file not found → INTERNAL + video。"""
    from tests.test_localize_batch import _install_post
    _install_post(
        monkeypatch,
        status_code=400,
        json_data={"detail": "Video file not found: /fake/v.mp4"},
        raise_for_status_exc=requests.HTTPError("400"),
    )
    r = invoke("localize_batch", {"video_paths": ["/fake/v.mp4"]})
    assert r.ok is False
    assert r.error.code == "INTERNAL"
    assert r.error.category == "video"


def test_localize_batch_5xx_is_transient_category(monkeypatch):
    """VL 返 5xx → INTERNAL + transient + retriable。"""
    from tests.test_localize_batch import _install_post
    _install_post(
        monkeypatch,
        status_code=503,
        json_data={"detail": "service unavailable"},
        raise_for_status_exc=requests.HTTPError("503"),
    )
    r = invoke("localize_batch", {"video_paths": ["/fake/v.mp4"]})
    assert r.ok is False
    assert r.error.code == "INTERNAL"
    assert r.error.category == "transient"
    assert r.error.retriable is True