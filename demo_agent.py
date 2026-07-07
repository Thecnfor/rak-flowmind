"""演示 Agent 通过 MCP 协议调用 FlowMind 技能。

起 `flowmind-mcp`（stdio transport）作为子进程，用 MCP 客户端连接，
列工具，再调 `localize_batch`。这正是 Claude Desktop / Cursor 等
MCP 兼容 Agent 实际做的事。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    # 1) 起 flowmind-mcp 子进程（stdio transport）
    server_params = StdioServerParameters(
        command=sys.executable,                          # 当前 venv 的 python
        args=["-m", "flowmind.server"],                  # 直接跑 server 模块
        env=None,                                         # 继承当前环境
    )
    print("→ 起 MCP server 子进程: python -m flowmind.server")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✓ MCP 会话已建立\n")

            # 2) tools/list —— 看 server 暴露了哪些技能
            print("→ tools/list:")
            tools_result = await session.list_tools()
            for t in tools_result.tools:
                print(f"   • {t.name}  ——  {t.description}")
            print()

            # 3) tools/call —— 模拟 Agent 真调 localize_batch
            print("→ tools/call: localize_batch")
            print("  args:")
            call_args = {
                "inp": {
                    "video_paths": ["/tmp/vl_smoketest/test_input.mp4"],
                    "target_lang": "th",
                    "source_lang": "zh",
                    "enable_tts": False,
                }
            }
            print(f"    {json.dumps(call_args, ensure_ascii=False, indent=2)}")

            result = await session.call_tool("localize_batch", call_args)
            print("\n→ 返回:")
            # FastMCP 的 content 是 list[TextContent | ...]
            for block in result.content:
                if hasattr(block, "text"):
                    # 尝试按 JSON 美化输出（flowmind 返回 SkillResult JSON）
                    try:
                        parsed = json.loads(block.text)
                        print(json.dumps(parsed, ensure_ascii=False, indent=2))
                    except (json.JSONDecodeError, TypeError):
                        print(block.text)
                else:
                    print(repr(block))
            print(f"\n  is_error={result.isError}")


if __name__ == "__main__":
    asyncio.run(main())