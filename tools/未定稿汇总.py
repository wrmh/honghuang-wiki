#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""未定稿问题汇总器

做两件事：
1. 给全库每个未定稿问题发一个**稳定编号**（U-001、U-002…），写回它所在的词条；
2. 重新生成汇总页 概念/未定稿问题.md。

编号稳定的机制：不按位置编号，按「词条名 + 问题原文」的哈希查表。
所以新增一条不会打乱已有编号，删一条也不会让其他条目前移——这在跨轮次引用时是硬要求。

用法：
    python tools\\未定稿汇总.py          # 编号 + 生成汇总页
    python tools\\未定稿汇总.py --check  # 只报有没有问题，不改文件
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 编号按叙事顺序发：从开天往下读，先事件、再量劫、再人与势力、再器物阵法、
# 最后是统摄性的概念。目录枚举顺序变了不影响已有编号（编号靠哈希表锚定）。
TYPE_DIRS = ("事件", "量劫", "人物", "势力", "阵法", "法宝", "地理", "功法", "概念")
MAP_FILE = ROOT / "tools" / "未定稿编号.json"
SUMMARY = ROOT / "概念" / "未定稿问题.md"

# 五劫的时间先后。只影响「新问题拿到的编号」，不影响已发出的编号。
RANK = {"开天辟地": 0, "龙汉初劫": 1, "巫妖量劫": 2, "封神量劫": 3, "西游量劫": 4}

HEADING = "## 未定稿问题"
ITEM_RE = re.compile(r"^- \[ \]\s*(?:U-\d+\s+)?(.*\S)\s*$")
ID_RE = re.compile(r"^U-(\d{3})$")


def iter_entries():
    for idx, d in enumerate(TYPE_DIRS):
        p = ROOT / d
        if not p.is_dir():
            continue
        for f in sorted(p.glob("*.md"), key=lambda x: (RANK.get(x.stem, 99), x.stem)):
            yield idx, f


def split_sections(text):
    """返回 (前段, 未定稿问题条目原文列表, 后段)。没有该小节则返回 None。"""
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == HEADING:
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    body = lines[start + 1:end]
    items = []
    for ln in body:
        m = ITEM_RE.match(ln)
        if m:
            items.append(m.group(1))
    return lines, start, end, items


def load_map():
    if MAP_FILE.exists():
        return json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return {}


def key_of(entry_name, question):
    return hashlib.sha1(f"{entry_name}｜{question}".encode("utf-8")).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查，不改文件")
    args = ap.parse_args()

    id_map = load_map()
    used = {v for v in id_map.values() if isinstance(v, str) and ID_RE.match(v)}
    next_id = 1 + max((int(ID_RE.match(v).group(1)) for v in used), default=0)

    rows = []          # (id, entry_name, question)
    changed_files = 0

    for _idx, f in iter_entries():
        text = f.read_text(encoding="utf-8")
        parsed = split_sections(text)
        if parsed is None:
            continue
        lines, start, end, items = parsed
        if not items:
            continue

        lines[start + 1:end] = []
        new_body = [""]
        for q in items:
            k = key_of(f.stem, q)
            uid = id_map.get(k)
            if uid is None:
                uid = f"U-{next_id:03d}"
                next_id += 1
                id_map[k] = uid
            rows.append((uid, f.stem, q))
            new_body.append(f"- [ ] {uid} {q}")
        new_body.append("")

        out = lines[:start + 1] + new_body + lines[end:]
        new_text = "\n".join(out)
        if new_text != text and not args.check:
            f.write_text(new_text, encoding="utf-8")
            changed_files += 1

    # 清掉已不存在的编号，避免 map 无限膨胀
    live_keys = {key_of(e, q) for _, e, q in rows}
    id_map = {k: v for k, v in id_map.items() if k in live_keys}

    rows.sort(key=lambda r: r[0])

    if args.check:
        print(f"未定稿问题 {len(rows)} 条，编号映射 {len(id_map)} 项")
        for uid, entry, q in rows:
            print(f"  {uid}  {entry}  {q}")
        return

    MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    MAP_FILE.write_text(
        json.dumps(dict(sorted(id_map.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # 生成汇总页：按词条分组，组内按编号升序
    by_entry = {}
    for uid, entry, q in rows:
        by_entry.setdefault(entry, []).append((uid, q))

    out = [
        "---",
        "词条: 未定稿问题",
        "类型: 概念",
        "状态: 草稿",
        "标签: [概念, 索引, 待决]",
        "---",
        "",
        "# 未定稿问题汇总",
        "",
        "> 由 `python tools\\未定稿汇总.py` 自动生成，**不要手改**——手改的内容下次运行就没了。",
        "> 编号 U-xxx 是稳定的：新增问题不会让已有编号变动，所以引用「U-007」永远指同一条。",
        "",
        f"共 **{len(rows)}** 条，分布在 **{len(by_entry)}** 个词条里。",
        "",
        "改完一条就在对应词条里把 `- [ ]` 改成 `- [x]`（或直接删掉该行），然后重跑脚本，汇总页会同步。",
        "",
        "## 按词条",
        "",
        "| 编号 | 词条 | 未定稿问题 |",
        "|---|---|---|",
    ]
    for entry in sorted(by_entry, key=lambda e: by_entry[e][0][0]):
        for uid, q in sorted(by_entry[entry]):
            out.append(f"| {uid} | [[{entry}]] | {q} |")

    out += [
        "",
        "## 按编号",
        "",
        "引用时用编号即可，不必抄问题全文。",
        "",
        "| 编号 | 一句话 |",
        "|---|---|",
    ]
    for uid, entry, q in rows:
        out.append(f"| {uid} | [[{entry}]]：{q} |")

    out.append("")
    SUMMARY.write_text("\n".join(out), encoding="utf-8")

    print(f"未定稿问题 {len(rows)} 条，分布于 {len(by_entry)} 个词条")
    print(f"改写了 {changed_files} 个词条文件")
    print(f"汇总页已写入 {SUMMARY.relative_to(ROOT)}")
    print(f"编号映射已写入 {MAP_FILE.relative_to(ROOT)}")
    ids = [u for u, _, _ in rows]
    print(f"编号范围 {ids[0]} – {ids[-1]}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
