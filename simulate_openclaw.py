"""模拟 OpenClaw Agent 走完整业务场景。

流程：飞书送来 N 个视频 → Agent 通过 MCP 协议发现工具 →
调用 localize_batch 提交 → 循环调 localize_status 轮询直到全部终态 →
出汇总报告。

Agent 这一侧**只通过 MCP 协议**与 flowmind-mcp 通信，不直接 import flowmind。
本脚本本身就是「任何 MCP 客户端能用 flowmind」的证明。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ── Agent 视角的"思考"输出 ──

def agent_log(emoji: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {emoji}  {msg}", flush=True)


# ── 飞书通知（模拟事件） ──

def feishu_notification(video_paths: list[str], target_lang: str) -> dict:
    """模拟飞书机器人收到一条 webhook 事件。"""
    return {
        "event": "video_batch_received",
        "from": "feishu_bot",
        "chat_id": "oc_xxx",
        "videos": [{"path": p} for p in video_paths],
        "target_lang": target_lang,
    }


# ── Agent 主循环 ──

async def run_agent(
    video_paths: list[str],
    target_lang: str,
    poll_interval: float,
    max_wait: float,
    enable_tts: bool,
) -> int:
    # 1) 起 flowmind-mcp 子进程（stdio transport）
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "flowmind.server"],
        env=None,
    )
    agent_log("🧠", f"启动 flowmind-mcp 子进程（MCP stdio transport）")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            agent_log("✅", "MCP 会话已建立")

            # 2) tools/list —— 看 server 暴露了哪些工具
            agent_log("🔍", "调用 tools/list 发现可用工具")
            tools_result = await session.list_tools()
            tools = {t.name: t for t in tools_result.tools}
            for name in sorted(tools):
                t = tools[name]
                agent_log("  •", f"{name}: {t.description}")
            assert "localize_batch" in tools, "必须要有 localize_batch"
            assert "localize_status" in tools, "必须要有 localize_status"

            # 3) 模拟飞书通知
            evt = feishu_notification(video_paths, target_lang)
            agent_log(
                "📨",
                f"飞书通知：收到 {len(evt['videos'])} 个视频切片，目标语言 {target_lang}",
            )

            # 4) 调用 localize_batch 提交批量
            agent_log("📤", "调用 tools/call: localize_batch")
            batch_call_args = {
                "inp": {
                    "video_paths": video_paths,
                    "target_lang": target_lang,
                    "source_lang": "zh",
                    "enable_tts": enable_tts,
                }
            }
            agent_log("  args:", json.dumps(batch_call_args["inp"], ensure_ascii=False))
            batch_result = await session.call_tool("localize_batch", batch_call_args)
            batch_payload = _first_text(batch_result)
            batch_data = json.loads(batch_payload)

            if not batch_data.get("ok"):
                agent_log("❌", f"提交失败：{batch_data.get('error')}")
                return 2

            data = batch_data["data"]
            job_ids = data["job_ids"]
            agent_log(
                "📋",
                f"提交成功：batch_id={data['batch_id']}，"
                f"{len(job_ids)} 个 job_ids={job_ids}，"
                f"成本档位={data['cost_band']}",
            )
            agent_log(
                "💡",
                f"推理：{batch_data['reasoning'][0]['conclusion']}",
            )
            if data.get("batch_size_warning"):
                agent_log(
                    "⚠️ ",
                    f"触发批量超额警告：{data['submitted_count']} > max_videos_per_batch",
                )
            if data.get("rejected_count", 0) > 0:
                agent_log(
                    "⚠️ ",
                    f"预检拒收 {data['rejected_count']} 个：{data['rejected_paths']}",
                )

            # 5) 循环轮询 localize_status
            agent_log(
                "🔄",
                f"开始轮询：每 {poll_interval}s 一次，最长等 {max_wait}s",
            )
            deadline = time.monotonic() + max_wait
            poll_round = 0
            final_report = None
            while time.monotonic() < deadline:
                poll_round += 1
                status_result = await session.call_tool(
                    "localize_status",
                    {"inp": {"task_ids": job_ids}},
                )
                status_payload = _first_text(status_result)
                status_data = json.loads(status_payload)

                if not status_data.get("ok"):
                    agent_log(
                        "❌",
                        f"第 {poll_round} 轮轮询失败：{status_data.get('error')}",
                    )
                    return 3

                d = status_data["data"]
                agent_log(
                    "📊",
                    f"轮询 #{poll_round}: "
                    f"完成={d['completed']} 失败={d['failed']} "
                    f"运行中={d['running']} 排队={d['queued']} 卡住={d['stalled']}",
                )
                reasoning = status_data["reasoning"][0]
                if reasoning["triggered_rules"]:
                    rule_names = "、".join(
                        r["name"] for r in reasoning["triggered_rules"]
                    )
                    agent_log("💡", f"推理：{reasoning['conclusion']}  命中规则：{rule_names}")
                    agent_log("⚠️ ", f"建议：{reasoning['risk_note']}")

                if d["all_terminal"]:
                    agent_log("🏁", "全部任务进入终态")
                    final_report = d
                    break

                await asyncio.sleep(poll_interval)
            else:
                agent_log(
                    "⏰",
                    f"达到最长等待 {max_wait}s，停止轮询；"
                    f"最后一轮：完成={d['completed']} 失败={d['failed']} 运行中={d['running']}",
                )
                final_report = d

            # 6) 出最终报告
            agent_log("📑", "=" * 60)
            agent_log("📑", "最终业务报告")
            agent_log("📑", "=" * 60)
            print(json.dumps(final_report, ensure_ascii=False, indent=2))

            # 7) Agent 决策：是否需要重试失败任务（演示：列出失败 job_ids）
            failed_jobs = [
                t["task_id"] for t in final_report["tasks"]
                if t["status"] == "failed"
            ]
            if failed_jobs:
                agent_log(
                    "🔁",
                    f"决策：失败任务 {failed_jobs} 建议人工排查后用 localize_batch 重提",
                )
            stalled_jobs = [
                t["task_id"] for t in final_report["tasks"] if t["is_stalled"]
            ]
            if stalled_jobs:
                agent_log(
                    "🚨",
                    f"决策：卡住任务 {stalled_jobs} 建议查 worker 日志",
                )

            return 0 if final_report["all_terminal"] and not failed_jobs else 1


def _first_text(result) -> str:
    """从 MCP CallToolResult 取第一个 TextContent.text。"""
    for block in result.content:
        if hasattr(block, "text"):
            return block.text
    raise RuntimeError("no text content in MCP result")


# ── 入口 ──

def main():
    p = argparse.ArgumentParser(description="模拟 OpenClaw Agent 跑批量视频本地化全流程")
    p.add_argument(
        "--videos", nargs="+",
        default=["/tmp/vl_smoketest/test_input.mp4", "/tmp/vl_smoketest/test_base.mp4"],
        help="要本地化的视频路径列表",
    )
    p.add_argument("--lang", default="th", help="目标语言代码（默认 th）")
    p.add_argument("--poll-interval", type=float, default=3.0, help="轮询间隔秒")
    p.add_argument("--max-wait", type=float, default=60.0, help="最长等待秒")
    p.add_argument("--tts", action="store_true", help="开启 TTS 配音")
    args = p.parse_args()

    rc = asyncio.run(
        run_agent(
            video_paths=args.videos,
            target_lang=args.lang,
            poll_interval=args.poll_interval,
            max_wait=args.max_wait,
            enable_tts=args.tts,
        )
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()