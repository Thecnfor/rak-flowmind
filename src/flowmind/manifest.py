"""能力清单：由注册表生成机器可读描述，供龙虾/Agent 发现与挂载。"""
from __future__ import annotations

from flowmind.skill import registry


def build_manifest() -> dict:
    """生成能力清单。每个技能附输入 schema 与可靠性画像。"""
    skills = []
    for spec in registry().values():
        skills.append({
            "id": spec.id,
            "name": spec.name,
            "version": spec.version,
            "input_schema": spec.input_model.model_json_schema(),
            "reliability_profile": {
                "deterministic": True,     # 纯确定性计算
                "emits_reasoning_chain": True,
                "typical_latency_ms": "<50",
                "confidence": 1.0,
            },
        })
    return {"skills": skills}