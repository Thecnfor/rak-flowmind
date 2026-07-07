"""失败分类端到端测试：localize_batch 抛分类错误时以 degraded SkillOutput 返回。

`SkillError.category` 字段不存在（contracts.py 不变量）——分类信息存在
`r.data.failure_category` 和 `r.data.retriable` 上。SkillError 的 retriable
字段是契约层的，由 `vlapi_to_skill_error` 写入，但 invoke() 路径上不会用，
因为技能体内 catch 后直接 degraded 返回。
"""
from __future__ import annotations

import requests

import flowmind.skills  # noqa: F401  触发技能注册
from flowmind.errors import _classify_exception
from flowmind.skill import invoke


# ── 分类规则：环境类（外网/HF/DNS）──

def test_classify_environment_for_huggingface_message():
    """VL 报 HuggingFace 下载错 → environment。"""
    exc = Exception("An error happened while trying to locate the files on the Hub "
                    "and we cannot find the appropriate snapshot folder.")
    assert _classify_exception(exc) == "environment"


def test_classify_environment_for_dns_resolution():
    assert _classify_exception(Exception("HTTPSConnectionPool: Failed to resolve 'huggingface.co'")) == "environment"


def test_classify_environment_for_connection_refused():
    assert _classify_exception(requests.exceptions.ConnectionError("refused")) == "environment"


def test_classify_environment_for_timeout():
    assert _classify_exception(requests.exceptions.Timeout("slow")) == "environment"


# ── 分类规则：视频类 ──

def test_classify_video_for_file_not_found_message():
    assert _classify_exception(Exception("Video file not found: /fake/path.mp4")) == "video"


def test_classify_video_for_disallowed_extension_message():
    assert _classify_exception(Exception("File extension '.avi' not in allowed list")) == "video"


# ── 分类规则：transient（5xx）──

def test_classify_transient_for_http_500():
    exc = requests.exceptions.HTTPError("500 Server Error")
    exc.response = requests.Response()
    exc.response.status_code = 500
    assert _classify_exception(exc) == "transient"


def test_classify_transient_for_502_503_504():
    for code in (502, 503, 504):
        exc = requests.exceptions.HTTPError(f"{code}")
        exc.response = requests.Response()
        exc.response.status_code = code
        assert _classify_exception(exc) == "transient", f"{code} should be transient"


# ── 分类规则：unknown 兜底 ──

def test_classify_unknown_for_unrelated_exception():
    assert _classify_exception(ValueError("奇怪")) == "unknown"


# ── 端到端：localize_batch 抛 ConnectionError 时，分类以 degraded SkillOutput 返回 ──

def test_localize_batch_connection_error_is_environment(monkeypatch):
    """submit 时 VL 连不上 → degraded + environment + retriable=False；不让 Agent 傻等。"""
    from tests.test_localize_batch import _install_post
    _install_post(monkeypatch, side_effect=requests.exceptions.ConnectionError("refused"))
    r = invoke("localize_batch", {"video_paths": ["/fake/v.mp4"]})
    # 注意：失败也返回 ok=True（degraded=True）；错误信息在 data 里而非 error 里
    assert r.metrics.degraded is True
    assert r.data.failure_category == "environment"
    assert r.data.retriable is False, "环境问题不该鼓励重试"


def test_localize_batch_video_not_found_is_video(monkeypatch):
    """VL 400 报 Video file not found → degraded + video。"""
    from tests.test_localize_batch import _install_post
    _install_post(
        monkeypatch,
        status_code=400,
        json_data={"detail": "Video file not found: /fake/v.mp4"},
    )
    r = invoke("localize_batch", {"video_paths": ["/fake/v.mp4"]})
    assert r.metrics.degraded is True
    assert r.data.failure_category == "video"
    assert r.data.retriable is False


def test_localize_batch_5xx_is_transient(monkeypatch):
    """VL 返 503 → degraded + transient + retriable=True。"""
    from tests.test_localize_batch import _install_post
    _install_post(monkeypatch, status_code=503, json_data={"detail": "service unavailable"})
    r = invoke("localize_batch", {"video_paths": ["/fake/v.mp4"]})
    assert r.metrics.degraded is True
    assert r.data.failure_category == "transient"
    assert r.data.retriable is True