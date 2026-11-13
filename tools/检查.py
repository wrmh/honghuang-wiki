# -*- coding: utf-8 -*-
"""词库一致性自检。

查四件事，都是肉眼最容易漏、错了最难查的：

  E（阻塞）  缺 YAML 头信息 / 缺必填字段 / 词条名与文件名不一致 / 类型不在枚举内 / 词条重名
  W（待补）  [[链接]] 指向尚不存在的词条

用法:
    python tools\\检查.py            # 检查脚本所在目录的上一级
    python tools\\检查.py --root F:\\世界观设定

退出码: 0 = 无 E 级问题；1 = 有 E 级问题
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SKIP_DIRS = {"_模板", "tools", ".obsidian", ".git", "site", "node_modules", "__pycache__"}
SKIP_FILES = {"README.md"}
TYPES = {"量劫", "人物", "势力", "法宝", "阵法", "地理", "功法", "事件", "概念"}
REQUIRED = ("词条", "类型", "状态")
LINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
CODE_FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def strip_code(body: str) -> str:
    """去掉代码块与行内代码，避免把示例里的 [[链接]] 当成真引用。"""
    return INLINE_CODE_RE.sub("", CODE_FENCE_RE.sub("", body))


def parse_front_matter(text: str):
    """返回 (字段字典 或 None, 正文)。字段只认单行 key: value。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            data = {}
            for line in lines[1:i]:
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip()
            return data, "\n".join(lines[i + 1:])
    return None, text


def collect(root: Path):
    files = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if set(rel.parts) & SKIP_DIRS:
            continue
        if path.name in SKIP_FILES or path.name.startswith("."):
            continue
        files.append(path)
    return files


def main() -> int:
    # 被管道 / 编辑器捕获时强制 UTF-8，避免中文乱码；直接跑在终端时沿用控制台编码
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.isatty():
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()
    root = Path(args.root).resolve()

    files = collect(root)
    errors: list[str] = []
    entries: dict[str, tuple[Path, dict]] = {}
    refs: dict[str, int] = {}

    for path in files:
        rel = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            errors.append(f"{rel}: 不是 UTF-8 编码，请另存为 UTF-8")
            continue

        fm, body = parse_front_matter(text)
        if fm is None:
            errors.append(f"{rel}: 缺头信息（文件必须以 --- 开头，并用 --- 收尾）")
            continue

        missing = [k for k in REQUIRED if not fm.get(k, "").strip()]
        if missing:
            errors.append(f"{rel}: 缺必填字段 {'、'.join(missing)}")

        name = fm.get("词条", "").strip()
        if name and name != path.stem:
            errors.append(
                f"{rel}: 词条「{name}」与文件名「{path.stem}」不一致，[[{name}]] 会接不上"
            )

        kind = fm.get("类型", "").strip()
        if kind and kind not in TYPES:
            errors.append(f"{rel}: 类型「{kind}」不在枚举内（{'/'.join(sorted(TYPES))}）")

        entries[path.stem] = (rel, fm)

        for raw in LINK_RE.findall(strip_code(body)):
            target = raw.split("|")[0].split("#")[0].strip()
            if target:
                refs[target] = refs.get(target, 0) + 1

    by_name: dict[str, list[Path]] = {}
    for rel, fm in entries.values():
        name = fm.get("词条", "").strip()
        if name:
            by_name.setdefault(name, []).append(rel)
    for name, paths in by_name.items():
        if len(paths) > 1:
            errors.append(
                "词条重名「{}」：{}".format(name, " / ".join(str(p) for p in paths))
            )

    pending = {t: c for t, c in refs.items() if t not in entries}

    print(f"词库自检  {root}")
    print(f"扫描词条 {len(entries)} 篇，引用 {sum(refs.values())} 处，指向 {len(refs)} 个词条")
    print()
    print("E 级（阻塞）")
    if errors:
        for item in errors:
            print(f"  ✗ {item}")
    else:
        print("  无")
    print()
    print(f"W 级（待补词条 {len(pending)} 个：被引用但还没有正文）")
    if pending:
        for target, count in sorted(pending.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  · {target}  ×{count}")
    else:
        print("  无")
    print()
    print("结论：" + ("有 E 级问题，先修完再加正文" if errors else "无阻塞问题，可以继续写"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
