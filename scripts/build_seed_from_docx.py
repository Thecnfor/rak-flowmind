"""从桌面 FAQ/FAQ问答库/ 下的 docx 文件生成 feishu_kb_seed.json。

一次性脚本:不进入运行时依赖,只供开发者重建 seed 用。
输出 schema 与 src/flowmind/skills/feishu_kb.py 一致:
    [{"id", "category", "question", "answer", "source_url"}, ...]

设计:8 份 docx 用 3 种段落结构,按文件定制解析:
1. 标准 Q&A: "N、问:... 答:..." / "N.问:... 答:..." / "N. 问:..."
2. 指示灯描述: "N、...灯的点亮条件...处理措施..."(无问号)→ 改写为问答
3. 多 part 答案: "N、问:... 答:1).xx 2).yy ..." → answer 字段合并多 part
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from docx import Document  # type: ignore
except ImportError:
    sys.exit("缺少 python-docx。请先 `uv add --dev python-docx`。")


# ----- 配置 -----

# 桌面 FAQ 根目录
DEFAULT_SOURCE = Path(r"C:\Users\nnn\Desktop\FAQ\FAQ问答库")

# 仓库 seed 文件路径
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "src" / "flowmind" / "skills" / "feishu_kb_seed.json"

# 文件名 → category 启发式映射
FILE_CATEGORY = {
    "五菱、宝骏CVT变速器用车常识": "用车指导",
    "五菱、宝骏新能源汽车知识及常见问题解答": "充电补能",
    "五菱凯捷用车常识": "用车指导",
    "五菱宏光MINI电动车知识问答": "用车指导",
    "关于GAMEBOY充电问题答疑指南": "充电补能",
    "华境S体验用户Q&A": "产品咨询",
    "吉林智成五菱、宝骏各车型常用指示灯说明": "故障排查",
    "影响冬季续航里程问题答疑": "充电补能",
}


# ----- docx 抽取 -----


def _extract_paragraphs(docx_path: Path) -> list[str]:
    """读 docx 段落列表(去掉空白段)。"""
    doc = Document(str(docx_path))
    return [p.text.strip() for p in doc.paragraphs if p.text.strip()]


# ----- 模式 1: 标准 Q&A -----

# 匹配 "N、问:..." / "N.问:..." / "N. 问:..." / "一.问:..." 等(支持全/半角冒号)
# 全角冒号：U+FF1A ;半角冒号 : U+003A
_QA_START_RE = re.compile(r"^[一二三四五六七八九十\d]+[、.\s\t]*问\s*[:：]\s*(.+)$")
# 匹配起始"答:"
_ANS_START_RE = re.compile(r"^答\s*[:：]\s*(.*)$")
# 多 part 答案分隔 "1).xx" / "2).xx"
_ANS_PART_RE = re.compile(r"^[\d]+[\)）]\s*")
# 纯编号引导(用于指示灯文档) "1、xxx灯的点亮条件...处理措施..."
_INDICATOR_RE = re.compile(r"^([一二三四五六七八九十\d]+)[、.]\s*(.+)$")
# 标题式条目(无"问"字,通常是"操作方法/注意事项/常识"等):
# "5、关于车辆发动机进水注意事项:" / "6、一键启动车辆应急熄火操作方法。"
_TITLE_MODE_RE = re.compile(r"^([一二三四五六七八九十\d]+)[、.]\s*([^问。]*?(?:方法|注意事项|常识|说明)?[：:]?)\s*$")


def _parse_qa_mode(paragraphs: list[str], file_basename: str) -> list[dict]:
    """解析"问/答"结构 + 标题式条目。多 part 答案合并到 answer 字段。"""
    faqs: list[dict] = []
    i = 0
    seq = 0
    while i < len(paragraphs):
        m = _QA_START_RE.match(paragraphs[i])
        if m:
            question = m.group(1).strip()
            i += 1
        elif _TITLE_MODE_RE.match(paragraphs[i]):
            # 标题式条目:把标题作为 question,后面所有非问句段作为 answer
            tm = _TITLE_MODE_RE.match(paragraphs[i])
            question = f"{tm.group(2).strip().rstrip('：:。.')} 是什么？"
            i += 1
        else:
            i += 1
            continue
        # 收集答案:从当前位置起,直到下一个"问"或文末
        answer_parts: list[str] = []
        while i < len(paragraphs):
            if _QA_START_RE.match(paragraphs[i]) or _TITLE_MODE_RE.match(paragraphs[i]):
                break
            answer_parts.append(paragraphs[i])
            i += 1
        answer = _clean_answer(answer_parts)
        if not answer:
            continue
        seq += 1
        faqs.append(_make_faq(question, answer, file_basename, seq))
    return faqs


def _parse_indicator_mode(paragraphs: list[str], file_basename: str) -> list[dict]:
    """解析指示灯文档:每段都是"X 灯的点亮条件...处理措施..."。"""
    faqs: list[dict] = []
    seq = 0
    for p in paragraphs:
        m = _INDICATOR_RE.match(p)
        if not m:
            continue
        content = m.group(2).strip()
        # 启发:必须含"灯"和"点亮条件"才算指示灯描述
        if "灯" not in content or "点亮条件" not in content:
            continue
        # 解析"X 灯的点亮条件是...、处理措施是..."
        # 拆出"X 灯"作为 question 主体,内容作为 answer
        light_name = _extract_light_name(content)
        question = f"{light_name} 灯的点亮条件和处理措施是什么？"
        answer = content
        seq += 1
        faqs.append(_make_faq(question, answer, file_basename, seq))
    return faqs


def _extract_light_name(content: str) -> str:
    """从"X 灯的点亮条件..."抽取出灯名前缀。"""
    m = re.match(r"^(.+?灯)(?:的点亮条件|的点亮|在)", content)
    name = m.group(1) if m else "该"
    # 去重尾部"灯"(原文偶有"X 灯 灯"现象)
    if name.endswith("灯 灯"):
        name = name[:-1]
    return name


def _clean_answer(parts: list[str]) -> str:
    """合并多段答案,去掉首段"答:"前缀。"""
    if not parts:
        return ""
    cleaned: list[str] = []
    for idx, p in enumerate(parts):
        if idx == 0:
            m = _ANS_START_RE.match(p)
            cleaned.append(m.group(1) if m else p)
        else:
            cleaned.append(p)
    text = " ".join(c.strip() for c in cleaned if c.strip())
    # 折叠空白
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _make_faq(question: str, answer: str, file_basename: str, seq: int) -> dict:
    return {
        "id": f"FAQ-{seq:04d}",
        "category": FILE_CATEGORY.get(file_basename, "用车指导"),
        "question": question,
        "answer": answer,
        "source_url": f"feishu://kb/{file_basename}#{seq}",
    }


# ----- 入口 -----


def build(source_dir: Path) -> list[dict]:
    """遍历 source_dir 下所有 docx,合并所有 FAQ。"""
    docx_files = sorted(source_dir.glob("*.docx"))
    if not docx_files:
        sys.exit(f"未找到 docx 文件: {source_dir}")
    all_faqs: list[dict] = []
    for f in docx_files:
        basename = f.stem
        paras = _extract_paragraphs(f)
        is_indicator = "指示灯" in basename
        if is_indicator:
            faqs = _parse_indicator_mode(paras, basename)
        else:
            faqs = _parse_qa_mode(paras, basename)
        print(f"  {basename}: {len(faqs)} 条")
        all_faqs.extend(faqs)
    # 重排 id(全局连续)
    for idx, faq in enumerate(all_faqs, start=1):
        faq["id"] = f"FAQ-{idx:04d}"
    return all_faqs


def main() -> int:
    parser = argparse.ArgumentParser(description="从 docx FAQ 生成 seed JSON")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                        help=f"docx 源目录(默认: {DEFAULT_SOURCE})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"seed 输出路径(默认: {DEFAULT_OUTPUT})")
    args = parser.parse_args()

    print(f"扫描 {args.source} ...")
    faqs = build(args.source)
    print(f"合计 {len(faqs)} 条 FAQ")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(faqs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"写入 {args.output}")
    # 统计 category 分布
    by_cat: dict[str, int] = {}
    for f in faqs:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())