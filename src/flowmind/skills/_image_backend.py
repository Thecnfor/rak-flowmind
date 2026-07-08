"""图像生成后端抽象：可插拔的"出图"接口。

- MockBackend:基于 sha256 的确定性占位,无外部依赖,用于测试/离线场景。
- AllInApiBackend:调用 allin-api.com(OpenAI 兼容协议),模型 gpt-image-2。
- 公开输入/输出契约稳定,业务层只换 backend 类即可。

安全:AllInApiBackend 的 API key 只在 generate 时按 env var 名读取,绝不进
config 文件或 commit。调用方可注入 key 用于测试,但生产路径必须从环境变量走。
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

import httpx


@dataclass
class GeneratedImage:
    """单张生成结果。url / local_path 二选一,base64 也作为 url 透传。"""
    index: int
    url: str
    local_path: str | None = None
    width: int = 0
    height: int = 0
    seed: int | None = None


class ImageBackend:
    """图像生成后端基类。子类实现 ``generate``。"""

    name: str = "base"

    def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        n: int,
        seed: int | None,
        save_dir: str | None,
    ) -> list[GeneratedImage]:
        raise NotImplementedError


class MockBackend(ImageBackend):
    """确定性占位后端:URL 由 sha256(prompt+seed+i) 派生,纯本地,可复现。"""

    name = "mock"

    def generate(self, *, prompt, negative_prompt, width, height, n, seed, save_dir):
        if seed is None:
            seed = int(_sha12(prompt), 16) & 0x7FFFFFFF
        images: list[GeneratedImage] = []
        for i in range(n):
            img_seed = seed + i
            img_id = _sha12(prompt, negative_prompt, width, height, img_seed)
            url = f"https://flowmind.local/mock/{img_id}.png?w={width}&h={height}"
            local = f"{save_dir.rstrip('/')}/{img_id}.png" if save_dir else None
            images.append(GeneratedImage(
                index=i + 1,
                url=url,
                local_path=local,
                width=width,
                height=height,
                seed=img_seed,
            ))
        return images


class AllInApiBackend(ImageBackend):
    """生产后端:allin-api.com 兼容 OpenAI ``/v1/images/generations``。

    - 模型默认 ``gpt-image-2``,可在构造时覆盖。
    - API key 仅从环境变量读取(由调用方传入字符串,本类不直接读 env)。
    - gpt-image-2 不支持单独的 ``negative_prompt``,合并到 prompt 末尾。
    """

    name = "allin_api"

    def __init__(
        self,
        *,
        api_base: str = "https://allin-api.com",
        api_key: str,
        model: str = "gpt-image-2",
        timeout_s: float = 60.0,
        client: httpx.Client | None = None,
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        # 测试时可注入 httpx.Client(配合 respx/transport=MockTransport)
        self._client = client

    def generate(self, *, prompt, negative_prompt, width, height, n, seed, save_dir):
        if not self.api_key:
            raise ValueError(
                "AllInApiBackend 收到空 API key。请检查环境变量 ALLIN_API_KEY 是否设置。"
            )

        final_prompt = prompt
        if negative_prompt:
            # OpenAI 协议不直接支持 negative_prompt —— 合并到 prompt 末尾
            final_prompt = f"{prompt}\n\nAvoid: {negative_prompt}"

        body: dict = {
            "model": self.model,
            "prompt": final_prompt,
            "n": n,
            "size": f"{width}x{height}",
        }
        if seed is not None:
            # 部分实现支持 seed;不支持会被忽略,不会报错
            body["seed"] = seed

        url = f"{self.api_base}/v1/images/generations"
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

        items = data.get("data") or []
        if not items:
            raise RuntimeError(f"allin-api 返回空 data：{data}")

        images: list[GeneratedImage] = []
        for i, item in enumerate(items[:n]):
            img_url = item.get("url")
            if not img_url:
                b64 = item.get("b64_json")
                img_url = f"data:image/png;base64,{b64}" if b64 else ""
            images.append(GeneratedImage(
                index=i + 1,
                url=img_url,
                local_path=None,
                width=width,
                height=height,
                seed=(seed + i) if seed is not None else None,
            ))
        return images


# --- 工具 ---

def _sha12(*parts: object) -> str:
    """对多段输入算 sha256 取前 12 位。"""
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()[:12]


def resolve_api_key(env_var: str) -> str | None:
    """从环境变量读取 API key;找不到返回 None(由调用方决定如何兜底)。"""
    val = os.environ.get(env_var)
    return val.strip() or None if val else None


def select_backend(
    *,
    requested: str | None,
    cfg_allin_key_env: str,
    cfg_allin_base: str,
    cfg_allin_model: str,
    cfg_allin_timeout_s: float,
) -> ImageBackend:
    """根据 cfg 与入参 backend 选择后端。

    - ``backend="mock"`` → MockBackend
    - ``backend="allin_api"`` → AllInApiBackend(必须有 key,否则抛错)
    - ``backend="auto"`` 或 None → 有 key 用 allin_api,否则 mock
    """
    chosen = (requested or "auto").lower()

    if chosen == "mock":
        return MockBackend()

    if chosen == "allin_api":
        api_key = resolve_api_key(cfg_allin_key_env) or ""
        return AllInApiBackend(
            api_base=cfg_allin_base,
            api_key=api_key,
            model=cfg_allin_model,
            timeout_s=cfg_allin_timeout_s,
        )

    if chosen == "auto":
        api_key = resolve_api_key(cfg_allin_key_env)
        if api_key:
            return AllInApiBackend(
                api_base=cfg_allin_base,
                api_key=api_key,
                model=cfg_allin_model,
                timeout_s=cfg_allin_timeout_s,
            )
        return MockBackend()

    raise ValueError(f"未知 backend：{requested}")