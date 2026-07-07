"""errors.py 单元测试：错误分类规则与枚举值。"""
from __future__ import annotations

import requests

from flowmind.errors import (
    ErrorCode,
    FailureCategory,
    _classify_exception,
    is_retriable,
)


# ── 枚举值测试 ──

def test_error_code_not_found_value():
    assert ErrorCode.NOT_FOUND == "NOT_FOUND"


def test_error_code_validation_value():
    assert ErrorCode.VALIDATION == "VALIDATION"


def test_error_code_internal_value():
    assert ErrorCode.INTERNAL == "INTERNAL"


def test_failure_category_values_are_lowercase():
    """测试断言用小写字面量；FailureCategory 字符串值必须是小写以兼容 == 比较。"""
    assert FailureCategory.ENVIRONMENT.value == "environment"
    assert FailureCategory.VIDEO.value == "video"
    assert FailureCategory.TRANSIENT.value == "transient"
    assert FailureCategory.UNKNOWN.value == "unknown"


# ── environment 分类 ──

def test_environment_for_huggingface_message():
    assert _classify_exception(Exception("locate the files on the Hub")) == "environment"


def test_environment_for_dns_resolution():
    assert _classify_exception(Exception("Failed to resolve foo.example")) == "environment"


def test_environment_for_connection_refused():
    exc = requests.exceptions.ConnectionError("refused")
    assert _classify_exception(exc) == "environment"


def test_environment_for_timeout():
    exc = requests.exceptions.Timeout("slow")
    assert _classify_exception(exc) == "environment"


def test_environment_for_lowercase_timeout_in_message():
    """通用 Exception 文本里含 'timeout' 也归 environment（不区分大小写）。"""
    assert _classify_exception(Exception("Connection timeout occurred")) == "environment"


# ── video 分类 ──

def test_video_for_file_not_found_message():
    assert _classify_exception(Exception("Video file not found: /x.mp4")) == "video"


def test_video_for_disallowed_extension_message():
    exc = Exception("File extension '.avi' not in allowed list ['.mp4']")
    assert _classify_exception(exc) == "video"


# ── transient 分类 ──

def _http_error(status: int) -> requests.exceptions.HTTPError:
    """构造一个带 response.status_code 的 HTTPError。"""
    resp = requests.Response()
    resp.status_code = status
    err = requests.exceptions.HTTPError(f"{status} Server Error")
    err.response = resp
    return err


def test_transient_for_http_500():
    assert _classify_exception(_http_error(500)) == "transient"


def test_transient_for_http_502_503_504():
    assert _classify_exception(_http_error(502)) == "transient"
    assert _classify_exception(_http_error(503)) == "transient"
    assert _classify_exception(_http_error(504)) == "transient"


# ── unknown 兜底 ──

def test_unknown_for_unrelated_exception():
    assert _classify_exception(ValueError("奇怪")) == "unknown"


# ── is_retriable ──

def test_is_retriable_true_only_for_transient():
    assert is_retriable("transient") is True
    assert is_retriable("environment") is False
    assert is_retriable("video") is False
    assert is_retriable("unknown") is False