"""配置层：技能内置通用默认，用户配置文件可覆盖。

个性化定制只发生在终端用户的对话式初始化——由消费此包的 Agent
按 README 剧本引导用户，调用 save_config() 写出 flowmind.config.toml。
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path("flowmind.config.toml")  # 相对于当前工作目录（cwd）


class InventoryConfig(BaseModel):
    """库销比/库存风险技能的可配置阈值（附通用默认值）。"""
    dsi_healthy_max: float = 60.0   # 周转天数 <=此值：健康
    dsi_watch_max: float = 90.0     # <=此值：关注
    dsi_warn_max: float = 120.0     # <=此值：预警；超过：危险
    dsi_low: float = 15.0           # 低于此值：断货风险
    capital_high: float = 100000.0  # 资金占用高阈值（货币单位）
    currency: str = "USD"


class FeishuKbConfig(BaseModel):
    """飞书知识库 FAQ 检索技能的可配置参数（附通用默认值）。"""
    data_path: str = ""                # FAQ 数据 JSON 文件路径；空 = 用默认种子
    retrieval_top_n: int = 20           # 每路召回候选上限（融合前）
    chunk_size: int = 400               # 切块字符数（占位用）
    chunk_overlap: int = 60             # 切块重叠（占位用）


class MarketingImageConfig(BaseModel):
    """营销生图技能的可配置默认值（附通用默认）。"""

    default_platform: str = "xiaohongshu"
    default_style: str = "literary"
    default_backend: str = "auto"  # auto 含义见 skills/marketing_image_gen.py
    default_negative_prompt: str = "no text, no watermark, no blurry, no distorted faces"
    credit_per_image: int = 1
    max_variants: int = 4
    platform_aspect_ratio: dict[str, str] = Field(
        default_factory=lambda: {
            "wechat_moment": "1:1",
            "xiaohongshu": "3:4",
            "douyin": "9:16",
            "taobao_main": "1:1",
            "taobao_detail": "3:4",
            "banner": "16:9",
            "weibo": "1:1",
            "video_cover": "16:9",
            "generic": "1:1",
        },
    )
    platform_pixel_hint: dict[str, tuple[int, int]] = Field(
        default_factory=lambda: {
            "wechat_moment": (1080, 1080),
            "xiaohongshu": (1080, 1440),
            "douyin": (1080, 1920),
            "taobao_main": (1200, 1200),
            "taobao_detail": (750, 1000),
            "banner": (1920, 822),
            "weibo": (1080, 1080),
            "video_cover": (1920, 1080),
            "generic": (1024, 1024),
        },
    )


class FlowmindConfig(BaseModel):
    """FlowMind 总配置：每技能一段。"""
    inventory: InventoryConfig = Field(default_factory=InventoryConfig)
    feishu_kb: FeishuKbConfig = Field(default_factory=FeishuKbConfig)
    marketing_image: MarketingImageConfig = Field(default_factory=MarketingImageConfig)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> FlowmindConfig:
    """读取配置文件；不存在则全用通用默认。用户值覆盖默认，缺项回落默认。"""
    if not path.exists():
        return FlowmindConfig()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return FlowmindConfig.model_validate(data)


def save_config(cfg: FlowmindConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    """把配置写回 TOML 文件（供初始化对话调用）。"""
    path.write_text(tomli_w.dumps(cfg.model_dump()), encoding="utf-8")


def is_initialized(path: Path = DEFAULT_CONFIG_PATH) -> bool:
    """判断用户是否已完成个性化初始化。"""
    return path.exists()
