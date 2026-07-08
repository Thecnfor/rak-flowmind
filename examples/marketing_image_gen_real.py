"""
marketing_image_gen 真打 allin-api 的集成示例。

不 mock，直接走 AllInApiBackend + ChatExtractor（如果 env 有 key）。
无 ALLIN_API_KEY 时优雅跳过（CI / 离线场景零依赖）。

运行：
    export ALLIN_API_KEY="sk-..."      # 运维导出
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python examples/marketing_image_gen_real.py

输出：
    ✓ health: allin-api reachable
    ✓ scene extracted (gpt-4o-mini): ...
    ✓ generated 1 image: https://...
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 让 SDK 加载（注册 skill + 配置）
import flowmind.skills  # noqa
from flowmind.config import FlowmindConfig, MarketingImageConfig, save_config
from flowmind.skill import invoke

KEY_ENV = "ALLIN_API_KEY"
KEY = os.environ.get(KEY_ENV)


def banner(s: str) -> None:
    print(f"\n{'─' * 60}\n  {s}\n{'─' * 60}")


def main() -> None:
    if not KEY:
        print(f"⚠️  未设置 ${KEY_ENV}，跳过真打集成。")
        print(f"   启用方式：export {KEY_ENV}='sk-...' 后重跑本脚本。")
        print(f"   当前 marketing_image_gen 仍可用 mock 后端（CI 友好）。")
        sys.exit(0)

    print(f"✓ 读取 {KEY_ENV}（长度 {len(KEY)}，前 4 字符：{KEY[:4]}...）")

    # 配置：显式 allin_api（不走 auto），写入临时 flowmind.config.toml
    tmpdir = Path(tempfile.mkdtemp(prefix="flowmind_real_"))
    os.chdir(tmpdir)
    cfg = FlowmindConfig(marketing_image=MarketingImageConfig(
        default_backend="allin_api",
        extractor_mode="chat",
    ))
    save_config(cfg)
    print(f"✓ 配置：default_backend=allin_api, extractor_mode=chat（写到 {tmpdir}）")

    banner("Case 1: 仅 prompt，无文案")
    r1 = invoke("marketing_image_gen", {
        "prompt": "一杯冒着热气的酸菜鱼,白瓷盘,自然光,电商产品摄影,1080x1440",
        "save_dir": str(tmpdir / "case1"),
    })
    print(f"  ok           = {r1.ok}")
    print(f"  degraded     = {r1.metrics.degraded}")
    if r1.ok:
        for v in r1.data.variants:
            print(f"  url          = {v.url[:80]}...")
        print(f"  推理结论     = {r1.reasoning[0].conclusion[:100]}")
        print(f"  latency_ms   = {r1.metrics.latency_ms:.0f}")
    else:
        print(f"  error.code   = {r1.error.code}")
        print(f"  error.message= {r1.error.message[:120]}")

    banner("Case 2: 仅 marketing_copy（自动抽画面描述再出图）")
    r2 = invoke("marketing_image_gen", {
        "marketing_copy": "酸菜鱼预制菜,山野到家,一口酸爽,酸辣开胃",
        "save_dir": str(tmpdir / "case2"),
    })
    print(f"  ok           = {r2.ok}")
    if r2.ok:
        for v in r2.data.variants:
            print(f"  url          = {v.url[:80]}...")
        # 看 plan 字段：抽取出的画面描述
        if hasattr(r2.data, "plan") and r2.data.plan:
            for step in r2.data.plan[:3]:
                print(f"  plan step    = {step[:100]}")
    else:
        print(f"  error.code   = {r2.error.code}")
        print(f"  error.message= {r2.error.message[:120]}")

    banner("Case 3: 混合（marketing_copy + 额外 prompt 修饰）")
    r3 = invoke("marketing_image_gen", {
        "marketing_copy": "酸菜鱼预制菜,山野到家",
        "prompt": "电商产品摄影,木桌背景,暖色调",
        "save_dir": str(tmpdir / "case3"),
    })
    print(f"  ok           = {r3.ok}")
    if r3.ok:
        for v in r3.data.variants:
            print(f"  url          = {v.url[:80]}...")
    else:
        print(f"  error.code   = {r3.error.code}")

    print(f"\n✅ 真打集成 OK。产物在 {tmpdir}")


if __name__ == "__main__":
    main()