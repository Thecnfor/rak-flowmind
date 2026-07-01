"""MCP 暴露层测试：工具被发现、调用返回结构化内容。

注：MCP 版本细节多变，本测试仅验证「已登记 + 调用不报错」，
丰富的正确性断言在 test_inventory_risk（invoke 层）中完成。
"""
import pytest
from flowmind.server import mcp


@pytest.mark.asyncio
async def test_tool_is_listed():
    tools = await mcp.list_tools()
    assert any(t.name == "inventory_risk" for t in tools)

@pytest.mark.asyncio
async def test_tool_call_returns_content():
    result = await mcp.call_tool(
        "inventory_risk",
        {"inp": {"items": [{"sku": "A", "on_hand": 100, "unit_cost": 2.0, "sales_30d": 60}]}},
    )
    # FastMCP 不同版本返回形态不一（内容序列 或 (content, structured) 元组），
    # 只断言拿到了非空结果。
    assert result is not None
