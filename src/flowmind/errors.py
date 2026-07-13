"""错误分类工具:把任意异常归到 4 类语义之一。

本地化技能 (localize_video / localize_retry / localize_status) 都需要它来告诉
Agent「这个错是环境问题、视频问题、可重试的临时故障,还是未知」。

本模块独立于 contracts.py / skill.py,以严守「不修改契约层 / 框架层」的
项目不变量。

最小实现:仅暴露 localize_video 需要的
- FailureCategory (字符串枚举值,值为小写)
- _classify_exception(exc) -> str
- is_retriable(category) -> bool

关键字 → 类别的快速短路表(按优先级排列)
"""
from __future__ import annotations

from enum import Enum


class FailureCategory(str, Enum):
    """失败原因语义分类——Agent 依据此决定后续动作。

    字符串值用小写以匹配 PR 测试断言(直接用 "environment" / "video" 等字面量)。
    """
    ENVIRONMENT = "environment"   # 网络/服务不通——别重试,先查环境
    VIDEO = "video"               # 资源/输入问题——修视频本身或换源
    TRANSIENT = "transient"       # 服务端临时故障——可以重试
    UNKNOWN = "unknown"           # 兜底——具体看错误消息


def _classify_exception(exc: BaseException) -> str:
    """把任意异常归到 'environment' / 'video' / 'transient' / 'unknown' 之一。

    规则:
    - requests.ConnectionError / requests.Timeout → environment
    - 消息含 "timeout" / "Failed to resolve" / "locate the files on the Hub" → environment
    - 消息含 "Video file not found" / 扩展名不在允许列表 → video
    - HTTPError 5xx → transient;4xx → video
    - 其它 → unknown
    """
    msg = str(exc) if exc else ""

    # requests 异常族(只在用户装了 requests 的环境才走;本文件不强制依赖)
    try:
        import requests as _req

        if isinstance(exc, _req.exceptions.ConnectionError):
            return FailureCategory.ENVIRONMENT.value
        if isinstance(exc, _req.exceptions.Timeout):
            return FailureCategory.ENVIRONMENT.value
        if isinstance(exc, _req.exceptions.HTTPError):
            resp = getattr(exc, "response", None)
            status = getattr(resp, "status_code", None)
            if status is None:
                import re as _re
                m = _re.match(r"^\s*(\d{3})\b", msg)
                if m:
                    status = int(m.group(1))
            if status in {500, 502, 503, 504}:
                return FailureCategory.TRANSIENT.value
            if status is not None and 400 <= status < 500:
                return FailureCategory.VIDEO.value
    except ImportError:
        pass

    low = msg.lower()
    if "timeout" in low:
        return FailureCategory.ENVIRONMENT.value
    if "Failed to resolve" in msg or "locate the files on the Hub" in msg:
        return FailureCategory.ENVIRONMENT.value
    if "Video file not found" in msg:
        return FailureCategory.VIDEO.value
    if "extension" in low and "not in allowed list" in low:
        return FailureCategory.VIDEO.value

    return FailureCategory.UNKNOWN.value


def is_retriable(category: str) -> bool:
    """基于分类返回是否值得重试。仅 transient 类值得。"""
    return category == FailureCategory.TRANSIENT.value