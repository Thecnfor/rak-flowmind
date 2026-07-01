"""MCP 暴露层：遍历注册表，把每个技能登记为一个 MCP 工具。

skills 融合 mcp——技能只需 @skill 定义，无需改动本文件即被暴露。
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import flowmind.skills  # noqa: F401  触发技能注册
from flowmind.contracts import SkillResult
from flowmind.skill import invoke, registry

mcp = FastMCP("FlowMind Skills")


def _make_tool(spec):
    """为一个技能构造 MCP 工具函数（输入=其 pydantic 模型，输出=SkillResult）。"""
    input_model = spec.input_model
    skill_id = spec.id

    def tool(inp) -> SkillResult:
        raw = inp.model_dump() if hasattr(inp, "model_dump") else dict(inp)
        return invoke(skill_id, raw)

    # 让 FastMCP 从注解推断输入 schema 与返回类型
    tool.__name__ = skill_id
    tool.__doc__ = spec.name
    tool.__annotations__ = {"inp": input_model, "return": SkillResult}
    return tool


def register_all(server: FastMCP) -> None:
    """把注册表中所有技能登记为 MCP 工具。"""
    for spec in registry().values():
        server.add_tool(_make_tool(spec), name=spec.id, description=spec.name)


register_all(mcp)


def main() -> None:
    """flowmind-mcp 入口：以 stdio 传输启动 MCP 服务器。"""
    mcp.run()


if __name__ == "__main__":
    main()
