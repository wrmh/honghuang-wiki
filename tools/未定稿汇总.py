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
ARCHIVE = ROOT / "tools" / "未定稿已结.json"
SUMMARY = ROOT / "概念" / "未定稿问题.md"

# 五劫的时间先后。只影响「新问题拿到的编号」，不影响已发出的编号。
RANK = {"开天辟地": 0, "龙汉初劫": 1, "巫妖量劫": 2, "封神量劫": 3, "西游量劫": 4}

HEADING = "## 未定稿问题"
ITEM_RE = re.compile(r"^- \[ \]\s*(?:U-\d+\s+)?(.*\S)\s*$")
# 条目下的缩进选项行：`  - A 选项文本`（A~Z 编号，用户选定后写回裁决）
OPT_RE = re.compile(r"^\s+- ([A-Za-z])[\.、）)]?\s+(.*\S)\s*$")
ID_RE = re.compile(r"^U-(\d{3})$")
# 文件名允许排序前缀（00-地图变迁.md → 词条名 地图变迁）
SORT_PREFIX = re.compile(r"^\d{2}-")


def write_lf(path, text):
    """统一按 LF 写盘。Windows 下 Path.write_text 默认把换行翻成 CRLF，
    会和库里其余文件打架（.gitattributes 要求 eol=lf）。"""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def iter_entries():
    """遍历类型目录下所有词条。递归：法宝/人物 有档位子目录（法宝\先天灵宝\…）。"""
    for idx, d in enumerate(TYPE_DIRS):
        p = ROOT / d
        if not p.is_dir():
            continue
        for f in sorted(p.rglob("*.md"), key=lambda x: (RANK.get(x.stem, 99), str(x))):
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
    items = []      # [(问题, [(字母, 选项文本), ...]), ...]
    cur = None
    for ln in body:
        m = ITEM_RE.match(ln)
        if m:
            cur = [m.group(1), []]
            items.append(cur)
            continue
        mo = OPT_RE.match(ln)
        if mo and cur is not None:
            cur[1].append((mo.group(1).upper(), mo.group(2)))
    return lines, start, end, [(q, tuple(o)) for q, o in items]


def load_map():
    if MAP_FILE.exists():
        return json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return {}


def load_archive():
    """已裁决归档。回答过的问题从这里留档：编号不再复用，汇总页也能给出结论。
    归档是手工维护的（裁决一次写一次），脚本只读不写。"""
    if ARCHIVE.exists():
        data = json.loads(ARCHIVE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return {"裁决日期": "", "rulings": []}


def key_of(entry_name, question):
    return hashlib.sha1(f"{entry_name}｜{question}".encode("utf-8")).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查，不改文件")
    args = ap.parse_args()

    id_map = load_map()
    archive = load_archive()
    archived = [
        r for r in archive.get("rulings", []) if ID_RE.match(str(r.get("id", "")))
    ]
    used = {v for v in id_map.values() if isinstance(v, str) and ID_RE.match(v)}
    # 归档里的编号也算「已用」，否则 closed 的号会被重新发给新问题
    used |= {r["id"] for r in archived}
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

        # 文件名带排序前缀（00-地图变迁.md）时，词条名应取 地图变迁
        ename = SORT_PREFIX.sub("", f.stem)
        lines[start + 1:end] = []
        new_body = [""]
        for q, opts in items:
            k = key_of(ename, q)
            uid = id_map.get(k)
            if uid is None:
                uid = f"U-{next_id:03d}"
                next_id += 1
                id_map[k] = uid
            rows.append((uid, f.stem, q, opts))
            new_body.append(f"- [ ] {uid} {q}")
            for letter, txt in opts:
                new_body.append(f"  - {letter} {txt}")
        new_body.append("")

        out = lines[:start + 1] + new_body + lines[end:]
        new_text = "\n".join(out)
        if new_text != text and not args.check:
            write_lf(f, new_text)
            changed_files += 1

    # 清掉已不存在的编号，避免 map 无限膨胀
    live_keys = {key_of(e, q) for _, e, q, _ in rows}
    id_map = {k: v for k, v in id_map.items() if k in live_keys}

    rows.sort(key=lambda r: r[0])

    if args.check:
        print(f"未定稿问题 {len(rows)} 条，编号映射 {len(id_map)} 项")
        for uid, entry, q, opts in rows:
            mark = f"（{len(opts)} 个选项）" if opts else ""
            print(f"  {uid}  {entry}  {q}{mark}")
        return

    MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_lf(
        MAP_FILE,
        json.dumps(dict(sorted(id_map.items())), ensure_ascii=False, indent=2) + "\n",
    )

    # 生成汇总页：按词条分组，组内按编号升序
    by_entry = {}
    for uid, entry, q, opts in rows:
        by_entry.setdefault(entry, []).append((uid, q, opts))

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
        f"共 **{len(rows)}** 条，分布在 **{len(by_entry)}** 个词条里。"
        + (f"另有已裁决 **{len(archived)}** 条（见文末归档）。" if archived else ""),
        "",
        "改完一条就在对应词条里把 `- [ ]` 改成 `- [x]`（或直接删掉该行），然后重跑脚本，汇总页会同步。",
        "",
        "> **怎么回答**：每条问题下面挂着 A~Z 几个选项（写问题时就按「各家既有设定 + 本库口径」先摆好）。"
        "回「U-078 选 B」即可；都不满意就自己给一个，我按你的写。选项写在条目里的缩进行 `  - A …`，"
        "脚本会原样带过来，不会被覆盖。",
        "",
        "## 按编号（全文顺序）",
        "",
    ]
    for uid, entry, q, opts in rows:
        tail = "（附选项）" if opts else ""
        out.append(f"- **{uid}** ｜ [[{entry}]] ｜ {q}{tail}")

    out += [
        "",
        "## 按词条",
        "",
    ]
    for entry in sorted(by_entry, key=lambda e: by_entry[e][0][0]):
        ids = sorted(uid for uid, _, _ in by_entry[entry])
        span = ids[0] if len(ids) == 1 else f"{ids[0]} – {ids[-1]}"
        out.append(f"### [[{entry}]]（{span}）")
        out.append("")
        for uid, q, opts in sorted(by_entry[entry]):
            out.append(f"- `{uid}` {q}")
            for letter, txt in opts:
                out.append(f"  - **{letter}** {txt}")
        out.append("")

    if archived:
        out += [
            "## 已裁决（归档，不再计入未定稿）",
            "",
            f"> 裁决日期：{archive.get('裁决日期') or '未记录'}。结论已写进各词条正文，"
            "编号保留、不再复用。归档文件：`tools/未定稿已结.json`（手工维护）。",
            "",
        ]
        arch_by_entry = {}
        for r in sorted(archived, key=lambda r: r["id"]):
            arch_by_entry.setdefault(r.get("entry", "?"), []).append(r)
        for entry in sorted(arch_by_entry, key=lambda e: arch_by_entry[e][0]["id"]):
            ids = [r["id"] for r in arch_by_entry[entry]]
            span = ids[0] if len(ids) == 1 else f"{ids[0]} – {ids[-1]}"
            out.append(f"### [[{entry}]]（{span}）")
            out.append("")
            for r in arch_by_entry[entry]:
                out.append(f"- `{r['id']}` **已决**：{r.get('decision', '')}")
                out.append(f"  - 原问题：{r.get('question', '')}")
            out.append("")

    out.append("")
    write_lf(SUMMARY, "\n".join(out))

    print(f"未定稿问题 {len(rows)} 条，分布于 {len(by_entry)} 个词条")
    print(f"改写了 {changed_files} 个词条文件")
    print(f"汇总页已写入 {SUMMARY.relative_to(ROOT)}")
    print(f"编号映射已写入 {MAP_FILE.relative_to(ROOT)}")
    ids = [u for u, _, _, _ in rows]
    print(f"编号范围 {ids[0]} – {ids[-1]}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
