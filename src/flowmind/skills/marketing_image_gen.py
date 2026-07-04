"""营销生图技能：多平台多风格的营销视觉生成规划。

返回「生成计划 + 候选图占位」。后端实现位可插拔：默认返回由 sha256
派生的确定性占位 URL（mock 后端），真实后端（Doubao/Midjourney/SDXL
等）可在后端实现位替换。无外部依赖——纯确定性，可在离线/测试环境跑。
"""
from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

from flowmind.config import MarketingImageConfig, load_config
from flowmind.contracts import Evidence, ReasoningChain, SkillOutput
from flowmind.rules import Rule, evaluate_rules
from flowmind.skill import skill

_VERSION = "0.1.0"

Platform = Literal[
    "wechat_moment",
    "xiaohongshu",
    "douyin",
    "taobao_main",
    "taobao_detail",
    "banner",
    "weibo",
    "video_cover",
    "generic",
]
Style = Literal[
    "minimal",
    "literary",
    "promo",
    "festival",
    "tech",
    "editorial",
    "warm",
    "auto",
]
Backend = Literal[
    "auto",
    "doubao_seedream",
    "volc_jimeng",
    "tongyi_wanxiang",
    "midjourney_api",
    "openai_gpt_image",
    "sdxl_local",
]
AspectRatio = Literal["1:1", "3:4", "9:16", "4:3", "16:9", "21:9", "2:3", "3:2", "auto"]

_VALID_ASPECT_RATIOS = {"1:1", "3:4", "9:16", "4:3", "16:9", "21:9", "2:3", "3:2"}


class BrandInfo(BaseModel):
    """覆盖默认品牌配置（请求内透传，不必让用户重复说品牌）。"""
    name: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    logo_url: str | None = None
    font_pref: str | None = None
    tagline: str | None = None


class MarketingImageInput(BaseModel):
    """营销生图入参。prompt 必填,其余字段 Agent 应尽量从上下文推断。"""
    prompt: str = Field(min_length=1, max_length=4096)
    platform: Platform | None = None
    style: Style | None = None
    aspect_ratio: AspectRatio | None = None
    negative_prompt: str | None = None
    brand: BrandInfo | None = None
    reference_image_url: str | None = None
    num_variants: int = Field(default=1, ge=1, le=4)
    seed: int | None = None
    save_dir: str | None = None
    backend: Backend | None = None


class GeneratedImage(BaseModel):
    """单张候选图(mock 后端的产物；接入真实后端后保留同一形状)。"""
    index: int
    url: str
    local_path: str | None = None
    width: int
    height: int
    seed: int


class MarketingImagePlan(BaseModel):
    """营销生图技能的业务载荷。"""
    prompt: str
    resolved_prompt: str
    platform: str
    style: str
    aspect_ratio: str
    width: int
    height: int
    backend: str
    num_variants: int
    images: list[GeneratedImage]
    negative_prompt: str
    estimated_cost_credit: int
    brand_name: str | None = None
    sampling_notes: list[str] = Field(default_factory=list)


# --- helpers ---------------------------------------------------------------

def _platform_label(p: str) -> str:
    table = {
        "wechat_moment": "朋友圈",
        "xiaohongshu": "小红书",
        "douyin": "抖音",
        "taobao_main": "淘宝主图",
        "taobao_detail": "淘宝详情",
        "banner": "Banner",
        "weibo": "微博",
        "video_cover": "视频封面",
        "generic": "通用",
    }
    return table.get(p, p)


def _hash_id(*parts: object) -> str:
    """对多段输入算 sha256 取前 12 位。"""
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()[:12]


def _dimensions(aspect: str, hint: tuple[int, int]) -> tuple[int, int]:
    """按比例计算尺寸：以 hint 长边为基准,按 aspect 比例缩放。"""
    w_hint, h_hint = hint
    try:
        a, b = (int(x) for x in aspect.split(":", 1))
    except (ValueError, AttributeError):
        return w_hint, h_hint
    if a <= 0 or b <= 0:
        return w_hint, h_hint
    base = max(w_hint, h_hint)
    if b >= a:  # portrait or square
        height = base
        width = max(1, round(base * a / b))
    else:  # landscape
        width = base
        height = max(1, round(base * b / a))
    return int(width), int(height)


def _build_rules(cfg: MarketingImageConfig) -> list[Rule]:
    """基于配置阈值构造规则集。推理链的第二、三段由 evaluate_rules 自动产出。"""
    return [
        Rule(
            id="MIG-PLATFORM-01",
            name="平台未指定回退默认",
            expression=f"platform 输入为空 → 默认 {cfg.default_platform}",
            predicate=lambda m: m["platform_input"] is None,
            evidence=lambda m: [
                Evidence(
                    metric="platform 输入",
                    value="未提供",
                    threshold=cfg.default_platform,
                    comparison="==",
                    window="本次请求",
                ),
            ],
        ),
        Rule(
            id="MIG-STYLE-01",
            name="风格未指定回退默认",
            expression=f"style 输入为空 → 默认 {cfg.default_style}",
            predicate=lambda m: m["style_input"] is None,
            evidence=lambda m: [
                Evidence(
                    metric="style 输入",
                    value="未提供",
                    threshold=cfg.default_style,
                    comparison="==",
                    window="本次请求",
                ),
            ],
        ),
        Rule(
            id="MIG-RATIO-01",
            name="比例由平台默认",
            expression="aspect_ratio 未指定或为 auto → 按平台默认",
            predicate=lambda m: m["aspect_ratio_input"] in (None, "auto"),
            evidence=lambda m: [
                Evidence(
                    metric="aspect_ratio 输入",
                    value=m["aspect_ratio_input"] or "auto",
                    threshold=m["aspect_ratio_resolved"],
                    comparison="==",
                    window="本次请求",
                ),
            ],
        ),
        Rule(
            id="MIG-NEGATIVE-01",
            name="默认 negative_prompt 已追加",
            expression="negative_prompt 输入为空 → 用 config 默认",
            predicate=lambda m: m["negative_prompt_added"],
            evidence=lambda m: [
                Evidence(
                    metric="default_negative_prompt 长度",
                    value=m["negative_prompt_length"],
                    threshold=len(cfg.default_negative_prompt),
                    comparison="==",
                ),
            ],
        ),
        Rule(
            id="MIG-BRAND-01",
            name="品牌覆盖",
            expression="brand 输入非空 → 命中=应用请求 brand 覆盖",
            predicate=lambda m: m["brand_overridden"],
            evidence=lambda m: [
                Evidence(
                    metric="brand.name 覆盖值",
                    value=m["brand_name_override"] or "未提供",
                    threshold="未提供",
                    comparison="覆盖",
                    window="本次请求",
                ),
            ],
        ),
        Rule(
            id="MIG-VARIANTS-01",
            name="多版本测款",
            expression=f"num_variants > 1 → 按 {cfg.max_variants} 张上限生成候选",
            predicate=lambda m: m["num_variants"] > 1,
            evidence=lambda m: [
                Evidence(
                    metric="num_variants",
                    value=m["num_variants"],
                    threshold=cfg.max_variants,
                    comparison="<=",
                    window="本次请求",
                ),
            ],
        ),
        Rule(
            id="MIG-DEGRADE-01",
            name="backend=auto 路由",
            expression="backend=auto → 由 Agent / 配置自动挑选后端",
            predicate=lambda m: m["backend"] == "auto",
            evidence=lambda m: [
                Evidence(
                    metric="backend 输入",
                    value=m["backend"],
                    threshold="auto",
                    comparison="==",
                    window="本次请求",
                ),
            ],
        ),
    ]


@skill(id="marketing_image_gen", name="营销生图（多平台多风格）", version=_VERSION)
def marketing_image_gen(inp: MarketingImageInput) -> SkillOutput[MarketingImagePlan]:
    """解析并规划营销视觉生成任务,产出生成计划与候选图占位。

    后端实现位为可插拔 adapter：默认返回由 sha256 派生的确定性占位
    URL，真实后端（Doubao/Midjourney/SDXL 等）可在后端实现位替换。
    无外部依赖，纯确定性，可离线运行。
    """
    cfg = load_config().marketing_image
    notes: list[str] = []

    platform = inp.platform or cfg.default_platform
    if platform not in cfg.platform_aspect_ratio:
        # 防御性兜底：Pydantic Literal 已校验,这里只是预防 cfg 损坏。
        raise ValueError(f"未知 platform：{platform}")

    style = inp.style or cfg.default_style

    if inp.aspect_ratio and inp.aspect_ratio != "auto":
        aspect_ratio = inp.aspect_ratio
    else:
        aspect_ratio = cfg.platform_aspect_ratio[platform]

    if aspect_ratio not in _VALID_ASPECT_RATIOS:
        raise ValueError(f"非法 aspect_ratio：{aspect_ratio}")

    if inp.negative_prompt:
        negative_prompt = inp.negative_prompt
        neg_added = False
    else:
        negative_prompt = cfg.default_negative_prompt
        neg_added = True
        notes.append("未提供 negative_prompt,已自动追加默认排斥词")

    brand_overridden = inp.brand is not None
    brand_name = inp.brand.name if inp.brand else None
    backend = inp.backend or cfg.default_backend

    if brand_overridden:
        notes.append(f"已使用请求内 brand 覆盖;name={brand_name!r}")
    else:
        notes.append("使用 config 默认 brand profile(请求内未提供)")

    hint = cfg.platform_pixel_hint.get(platform, (1024, 1024))
    width, height = _dimensions(aspect_ratio, hint)

    if inp.seed is not None:
        base_seed = inp.seed
    else:
        # 32 位正整数派生,给同 prompt 同平台产出稳定 seed
        base_seed = int(_hash_id(inp.prompt), 16) & 0x7FFFFFFF

    images: list[GeneratedImage] = []
    for i in range(inp.num_variants):
        image_seed = base_seed + i
        img_id = _hash_id(inp.prompt, platform, style, aspect_ratio, image_seed)
        url = f"https://flowmind.local/mock/{img_id}.png?w={width}&h={height}"
        local = None
        if inp.save_dir:
            local = f"{inp.save_dir.rstrip('/')}/{img_id}.png"
        images.append(GeneratedImage(
            index=i + 1,
            url=url,
            local_path=local,
            width=width,
            height=height,
            seed=image_seed,
        ))

    metrics = {
        "platform_input": inp.platform,
        "platform": platform,
        "style_input": inp.style,
        "style": style,
        "aspect_ratio_input": inp.aspect_ratio,
        "aspect_ratio_resolved": aspect_ratio,
        "negative_prompt_added": neg_added,
        "negative_prompt_length": len(negative_prompt),
        "brand_overridden": brand_overridden,
        "brand_name_override": brand_name,
        "num_variants": inp.num_variants,
        "backend": backend,
    }
    hits, evidence = evaluate_rules(_build_rules(cfg), metrics)

    chain = ReasoningChain(
        conclusion=(
            f"为本次请求产出 {len(images)} 张 {aspect_ratio} {style} 营销图;"
            f"目标平台：{platform}({_platform_label(platform)});backend：{backend}。"
        ),
        triggered_rules=hits,
        evidence=evidence,
        causal_analysis=(
            f"prompt 长度 {len(inp.prompt)}、平台 {platform}、风格 {style}、"
            f"比例 {aspect_ratio},命中 {len(hits)} 条规则,按既定优先级推断参数。"
        ),
        risk_note=(
            "本技能默认后端为确定性 mock,产出仅作为创意草稿;"
            "正式投放前请人工挑选,或接真实图像生成后端。"
        ),
    )

    return SkillOutput(
        data=MarketingImagePlan(
            prompt=inp.prompt,
            resolved_prompt=inp.prompt,
            platform=platform,
            style=style,
            aspect_ratio=aspect_ratio,
            width=width,
            height=height,
            backend=backend,
            num_variants=inp.num_variants,
            images=images,
            negative_prompt=negative_prompt,
            estimated_cost_credit=len(images) * cfg.credit_per_image,
            brand_name=brand_name,
            sampling_notes=notes,
        ),
        reasoning=[chain],
        confidence=1.0,
        sample_size=len(images),
    )
