"""营销文案 → 画面描述 提取器。

- PassthroughExtractor:直接把营销文案作为画面描述,零网络调用。
- ChatExtractor:调 allin-api.com ``/v1/chat/completions`` 把营销文案
  转成具体的画面描述。模型默认 ``gpt-4o-mini``,可在 config 覆盖。

安全:ChatExtractor 的 API key 只在 extract 时按入参字符串使用(由调用方
从环境变量读后传入),本模块不直接读 env,不进 config 文件。
"""
from __future__ import annotations

import httpx

_SYSTEM_PROMPT = (
    "你是一名营销视觉设计师。你的任务是把用户的营销文案转化为一段"
    "具体的、可直接交给图像生成模型的画面描述。"
    "要求:1) 用中文输出;2) 包含主体、场景、光线、氛围、构图;3) 不要"
    "出现解释、前缀、引号或代码块;4) 字数 80~200 字。"
)


class SceneExtractor:
    """提取器基类。子类实现 ``extract``。"""

    name: str = "base"

    def extract(self, *, marketing_copy: str, hint: str | None = None) -> str:
        raise NotImplementedError


class PassthroughExtractor(SceneExtractor):
    """透传:marketing_copy 原样作为画面描述。零网络、零成本,用于离线/测试。"""

    name = "passthrough"

    def extract(self, *, marketing_copy, hint=None):
        text = (marketing_copy or "").strip()
        if hint and hint.strip():
            return f"{text}\n{hint.strip()}"
        return text


class ChatExtractor(SceneExtractor):
    """Chat LLM 提取器:把营销文案改写为画面描述。

    兼容 OpenAI ``/v1/chat/completions`` 协议,默认 base ``https://allin-api.com``,
    默认模型 ``gpt-4o-mini``(轻量便宜)。
    """

    name = "chat"

    def __init__(
        self,
        *,
        api_base: str = "https://allin-api.com",
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self._client = client

    def extract(self, *, marketing_copy, hint=None):
        if not self.api_key:
            raise ValueError(
                "ChatExtractor 收到空 API key。请检查环境变量 ALLIN_API_KEY 是否设置。"
            )

        user_msg = f"营销文案：{marketing_copy}"
        if hint and hint.strip():
            user_msg += f"\n附加要求：{hint.strip()}"

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.7,
        }
        url = f"{self.api_base}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if self._client is not None:
            resp = self._client.post(url, headers=headers, json=body)
        else:
            with httpx.Client(timeout=self.timeout_s) as client:
                resp = client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"allin-api chat 返回结构异常：{data}") from exc
        return content.strip()


def select_extractor(
    *,
    mode: str,
    cfg_api_base: str,
    cfg_api_key_env: str,
    cfg_extractor_model: str,
    cfg_extractor_timeout_s: float,
) -> SceneExtractor:
    """按 config.extractor_mode 选择提取器。

    - ``passthrough`` → 永远 Passthrough(零网络)
    - ``auto`` → 有 key 走 ChatExtractor,无 key 回落 Passthrough(与 backend 对称)
    - ``chat`` → 永远 ChatExtractor(无 key 时 extract 时报错)
    """
    from flowmind.skills._image_backend import resolve_api_key  # 复用 env 读取

    mode = (mode or "auto").lower()
    if mode == "passthrough":
        return PassthroughExtractor()
    if mode == "auto":
        api_key = resolve_api_key(cfg_api_key_env)
        if api_key:
            return ChatExtractor(
                api_base=cfg_api_base,
                api_key=api_key,
                model=cfg_extractor_model,
                timeout_s=cfg_extractor_timeout_s,
            )
        return PassthroughExtractor()
    if mode == "chat":
        api_key = resolve_api_key(cfg_api_key_env) or ""
        return ChatExtractor(
            api_base=cfg_api_base,
            api_key=api_key,
            model=cfg_extractor_model,
            timeout_s=cfg_extractor_timeout_s,
        )
    raise ValueError(f"未知 extractor_mode：{mode}")