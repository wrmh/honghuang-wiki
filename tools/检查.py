# -*- coding: utf-8 -*-
"""词库一致性自检。

目录按「类型」分，一个类型一个目录，目录名必须等于 front matter 里的 `类型`。
这样查资料时可以按类翻，词条数到几百篇也不会乱。

查五件事，都是肉眼最容易漏、错了最难查的：

  E（阻塞）  缺 YAML 头信息 / 缺必填字段 / 词条名与文件名不一致 /
             类型不在枚举内 / 类型与所在目录不符 / 文件不在类型目录下 /
             状态不在枚举内 / 词条重名
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

# 类型枚举 = 目录名枚举，两者必须一一对应
TYPES = ("人物", "势力", "法宝", "阵法", "地理", "功法", "事件", "概念", "原创设定")

# 势力第一层：按「它是哪一类」分（人 / 妖 / 仙 / 神 / 巫 / 佛 / 鬼 / 先天）
FACTION_CLASSES = ("人", "妖", "仙", "神", "巫", "佛", "鬼", "先天")

# 人物第二层：大势力（用户 2026-11-21 定）——人物\<境界>\<大势力>\<词条>.md
# 值与 `势力\` 下的大势力目录同名；没有门派的（散修、散妖、开天之前的存在）统一进「无门」。
FACTION_DIRS = ("佛门", "天庭", "地府", "人族", "巫族", "阐教", "截教", "妖族天庭",
                "龙族", "凤族", "麒麟族", "九尾", "混沌魔神", "先天灵兽", "洪荒凶兽",
                "混世四猴", "三教", "人教", "仙道", "道门", "百家", "无门")

# 原创设定层（2026-11-19 立）：独立于洪荒正史，供二次创作使用（好感度/天赋/关系）。
# 分层暂定为 总览 / 规则 / 天赋 / 关系，后面会长出 道具、事件、门派 等。
ORIGINAL_LAYERS = ("总览", "规则", "天赋", "关系", "玩法", "伏笔")
STATUSES = ("草稿", "待核", "成稿")

# 人物境界阶梯（用户 2026-11-14 定稿）：目录名 = 境界值，两者一一对应。
# 「混沌」不在阶梯内，是盘古与混沌魔神的特例（排在阶梯之前，序 0）。
LEVEL_LADDER = (
    "凡人", "引气入体", "炼气化神", "炼神返虚", "炼虚合道",
    "地仙", "天仙", "玄仙", "金仙", "太乙金仙", "大罗金仙", "准圣", "圣人",
)

# 人物必须带的字段（用户 2026-11-19 定）：外貌与外貌标签先占位，内容可空；
# 三视角评价 + 1-3 个标签；法宝要带类型占位；功法/神通/亲近/仇视有就写、没有可空。
ELEM_YES: list[str] = []
CON_YES: list[str] = []
CON_NO: list[str] = []
EV_YES: list[str] = []
EV_NO: list[str] = []
GUIDE_YES: list[str] = []
GUIDE_NO: list[str] = []
ELEM_NO: list[str] = []
PERSON_KEYS = (
    "外貌", "外貌标签", "评价自视", "评价亲近", "评价旁人", "人物标签",
    "法宝", "功法", "神通", "亲近之人", "仇视之人",
)
LEVEL_RANK = {name: i + 1 for i, name in enumerate(LEVEL_LADDER)}
LEVEL_RANK["混沌"] = 0

# 事件的元会坐标（一元 = 12 会 = 129600 年，是对账周期）。
# 第零元会只装开天这一刻（纪元起点），开完天才进入第一元会；第二元会含龙汉两段与龙汉末期的紫霄宫讲道。
EVENT_ERAS = ("第零元会", "第一元会", "第二元会", "第三元会", "第四元会", "第五元会", "第六元会")

# 地理的空间层：一处理不下的地方按「它在哪一层」放，不按谁的地盘放。
# 天上＝天界（三十三天、天河、星辰都在这一层）；海域单列是因为海眼是龙族岗位、
# 与「陆地」的组织方式完全不同；总目放跨层的总览页（如地图变迁），它不属于任何一层。
SPACE_LAYERS = ("总目", "天上", "陆地", "海域", "幽冥", "域外")
SPACE_RANK = {name: i for i, name in enumerate(SPACE_LAYERS)}

# 概念的门类：照「九问判定链」从上往下问，命中即停（用户 2026-11-22 定，目录名带 L 序号）。
#   00 本源＝不能造、没有它就没有天地；01 法则＝不能造也不能被夺（管该不该、先与后）；
#   02 度量＝有量、能计数能加减；03 势态＝属于某个主体或某段时间；
#   04 认知＝只存在于「知」这一层；05 人为＝有人把它立起来的（有立法者）；
#   06 位格＝格先于官（天给的格子，人只是被填进去）；07 术法＝一招，能当场使出来；
#   08 总览＝只做索引，不产生设定。
CONCEPT_KINDS = ("本源", "法则", "度量", "势态", "认知", "人为", "位格", "术法", "总览")
CONCEPT_RANK = {name: i for i, name in enumerate(CONCEPT_KINDS)}

# 概念正文的九节（用户 2026-11-22 定）。门类「总览」是导航/编年页，不套九节——
# 故事线、人间编年、未定稿问题都是索引，硬套会把编年表塞进「定义」里。
CONCEPT_SECTIONS = (
    "## 定义",
    "## 本源/由来",
    "## 核心特征",
    "## 适用范围",
    "## 类比/具象例子",
    "## 和相近概念对比",
    "## 作用/意义",
    "## 局限与争议",
    "## 简单总结",
)
CONCEPT_SECTIONS_EXEMPT = ("总览",)

# 需要按档位分二级目录的类型：类型 -> (档位字段, 档位枚举)
# 法宝按品阶、人物按境界、事件按元会、地理按空间层、概念按门类；其余类型仍是一层目录。
TIERS = {
    "法宝": ("品阶", ("凡器", "混沌至宝", "混沌灵宝", "先天至宝", "先天灵宝", "后天至宝", "后天灵宝", "功德灵宝")),
    "人物": ("境界", ("混沌",) + LEVEL_LADDER),
    "事件": ("元会", EVENT_ERAS),
    "地理": ("空间层", SPACE_LAYERS),
    "概念": ("门类", CONCEPT_KINDS),
    "原创设定": ("原创层", ORIGINAL_LAYERS),
}

# 法宝的「系列 × 禁制」二级校验（裁决 2026-11-13；功德灵宝追加 2026-11-15）：
#   系列 = 混沌 > 先天 > 后天（混沌是特殊的先天，只有盘古与混沌魔神才有）
#   灵宝：1-12 下品 / 13-24 中品 / 25-36 上品 / 37-48 极品
#   后天专属：炼制上限 42 道；43-48 是靠大功德顶上去的，单列「功德灵宝」；49 是功德至宝
#   至宝：混沌至宝 50 道（大道五十，开天前才容得下）／先天至宝与后天至宝 49 道
#   50 道是大道全数：开天之后天意不容其存在，故必碎或失踪；留存下来的至宝都得「遁去一道」降到 49
SERIES_OF_TIER = {
    "混沌至宝": "混沌", "混沌灵宝": "混沌",
    "先天至宝": "先天", "先天灵宝": "先天",
    "后天至宝": "后天", "后天灵宝": "后天",
    "功德灵宝": "后天",
}
GRADE_BANDS = ((1, 12, "下品"), (13, 24, "中品"), (25, 36, "上品"), (37, 48, "极品"))
GRADES = tuple(g for _, _, g in GRADE_BANDS) + ("至宝", "功德灵宝")
EXEMPT_TAG = "分类条目"
# 先天功德至宝系列仍属先天，但按「功德至宝统一归档」的约定收在 后天至宝/ 目录下 → 豁免系列校验
EXEMPT_SERIES_TAG = "先天功德至宝"

# 凡器（2026-11-21 用户新增）：凡人与低修为者、穷散修用的兵器。
# 它们没有禁制，所以**不在这把「系列 × 禁制」的尺子上**——0 不是最低档，是不进档。
# 凡器改按「器类」分类，这套词是给整个词库的兵器用的，法宝里的兵器也可参照。
WEAPON_CLASSES = ("长兵", "短兵", "抛射", "软兵", "农具改", "护具")

# 至宝档的精确禁制数：混沌至宝 50 道，先天/后天至宝 49 道
TIER_EXACT = {"混沌至宝": 50, "先天至宝": 49, "后天至宝": 49}
MAX_JINZHI = 50

# 后天系列的炼制上限：超过就必须靠功德顶上（43-48 = 功德灵宝）
CRAFT_CAP = {"后天灵宝": 42, "功德灵宝": 48}

def grade_of(num, series=""):
    """禁制道数 → 品级；越界返回 None。

    49/50 都是至宝；后天系列在 43-48 靠功德提升，单列「功德灵宝」；
    混沌/先天的 43-48 仍是「极品」（人家本来就长在那个数上）。
    """
    if num in (49, 50):
        return "至宝"
    if series == "后天" and 43 <= num <= 48:
        return "功德灵宝"
    for lo, hi, grade in GRADE_BANDS:
        if lo <= num <= hi:
            return grade
    return None

# 允许放在库根、不受「目录=类型」约束的文件
ROOT_OK = {"索引.md"}

# 允许文件名带排序前缀（00-、01- …），比对词条名时先剥掉
SORT_PREFIX = re.compile(r"^\d{2}-")

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
    soft: list[str] = []
    entries: dict[str, tuple[Path, dict]] = {}
    refs: dict[str, int] = {}

    # 模板自检：_模板\ 在 SKIP_DIRS 里，所以模板本身从来没被校验过——
    # 而模板一错，照它新建的每一篇都会错（收尾 --- 粘在最后一行 = 整块头信息非法，
    # Obsidian 把这条词条的所有属性都判「无效」）。第 15 条硬规矩就是为这个立的。
    tpl_dir = root / "_模板"
    if tpl_dir.is_dir():
        for tpl in sorted(tpl_dir.glob("*.md")):
            tpath = tpl.relative_to(root)
            try:
                ttext = tpl.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                errors.append(f"{tpath}: 不是 UTF-8 编码，请另存为 UTF-8")
                continue
            if not ttext.startswith("---"):
                errors.append(f"{tpath}: 模板必须以 --- 开头")
                continue
            if not __import__("re").search(r"\n---\n", ttext):
                errors.append(
                    f"{tpath}: 模板头信息收尾的 --- 必须独占一行"
                    "（粘在最后一个字段后面会让照它新建的词条整块判「无效属性」）"
                )
            tdict: dict = {}
            try:
                import yaml as _yaml

                try:
                    tdict = _yaml.safe_load(ttext.split("---", 2)[1]) or {}
                except Exception as _e:  # noqa: BLE001
                    _first = [x for x in str(_e).splitlines() if x.strip()][:3]
                    errors.append(
                        f"{tpath}: 模板头信息不是合法 YAML（照它新建的词条会整块判「无效属性」）："
                        + " / ".join(_first)
                    )
                    continue
            except ImportError:
                pass
            if not isinstance(tdict, dict):
                errors.append(f"{tpath}: 模板头信息必须是键值对")
                continue
            _tpl_need = {
                "人物": ["词条", "类型", "状态", "别名", "aliases", "势力", "境界", "境界序",
                         "境界备注", "首次登场", "时间线", "外貌", "外貌标签", "评价自视",
                         "评价亲近", "评价旁人", "人物标签", "法宝", "功法", "神通",
                         "亲近之人", "仇视之人"],
                "事件": ["词条", "类型", "元会", "元会序", "劫序", "归属", "时间锚点",
                         "时间精度", "定性", "状态"],
                "法宝": ["词条", "类型", "状态", "品阶", "系列", "禁制", "品级"],
            }.get(tpl.stem)
            if _tpl_need:
                _lack = [k for k in _tpl_need if k not in tdict]
                if _lack:
                    errors.append(f"{tpath}: 模板缺字段 {'、'.join(_lack)}（硬规矩第 15 条：先改模板再改存量）")
            if tpl.stem == "事件":
                for _sec in ("### 一、时间", "### 二、地点", "### 三、主体", "### 四、事由",
                             "### 五、经过", "### 六、结果", "### 七、影响", "### 八、史料备注",
                             "### 九、定性", "### 十、关联"):
                    if _sec not in ttext:
                        errors.append(f"{tpath}: 事件模板缺小节 {_sec}")

    # 势力公约：只有「金字塔结构完整的组织」才单独成条，而且**本体也要放进同名目录**
    #   势力\<大势力>\<大势力>.md        本体（第二层，front matter 不写「归属」）
    #   势力\<大势力>\[<组>\]<子条目>.md   组成部分（front matter 写 `归属: <大势力>`）
    moe_first_level = {
        p.stem
        for p in files
        if len(p.relative_to(root).parts) == 4
        and p.relative_to(root).parts[0] == "势力"
        and p.stem == p.relative_to(root).parts[2]
    }

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

        # front matter 必须是合法 YAML：解析不了，Obsidian 整块属性都会显示「无效」。
        # 典型成因是值以 [[ 开头却没加引号（如 法宝: [[覆地印]]（类型：印）），
        # YAML 把它当嵌套序列，后面的中文说明就成了语法错误——而这种错在正则扫描里看不出来。
        try:
            import yaml as _yaml

            try:
                _yaml.safe_load(text.split("---", 2)[1])
            except Exception as _e:  # noqa: BLE001
                _first = [x for x in str(_e).splitlines() if x.strip()][:3]
                errors.append(
                    f"{rel}: 头信息不是合法 YAML（Obsidian 会判「无效属性」）："
                    + " / ".join(_first)
                    + " —— 值里带 [[链接]] 或中文说明时请整体加引号"
                )
        except ImportError:
            pass

        # YAML 里以 * & ! 开头的裸值会被当成别名/锚点/标签，Obsidian 直接判「无效属性」
        for _ln in text.split("---", 2)[1].splitlines():
            _m = __import__("re").match(r"^([^\s:#][^:]*):\s(.*)$", _ln)
            if _m and _m.group(2)[:1] in ("*", "&", "!"):
                errors.append(
                    f"{rel}: 头信息「{_m.group(1)}」的值以 {_m.group(2)[0]} 开头，"
                    f"YAML 会把它当别名/锚点/标签解析（Obsidian 判「无效属性」）——请给值加引号"
                )

        # 重复键：PyYAML 取最后一次、不报错，但 Obsidian 会把整块属性显示成「无效属性」。
        # 2026-11-21 一次批量生成 12 篇就栽在这里（生成器把 别名/标签 写了两遍）。
        _seen_keys = {}
        for _ln in text.split("---", 2)[1].splitlines():
            _m = __import__("re").match(r"^([^\s:#][^:]*):", _ln)
            if _m:
                _seen_keys.setdefault(_m.group(1), 0)
                _seen_keys[_m.group(1)] += 1
        for _k, _n in _seen_keys.items():
            if _n > 1:
                errors.append(
                    f"{rel}: 头信息里「{_k}」写了 {_n} 遍（YAML 取最后一次、不报错，"
                    f"但 Obsidian 会整块判「无效属性」）——删掉多余的行"
                )
                break
        missing = [k for k in REQUIRED if not fm.get(k, "").strip()]
        if missing:
            errors.append(f"{rel}: 缺必填字段 {'、'.join(missing)}")

        # 字段名分裂（2026-11-21 梳理时立的第 15 条）：一个概念只能有一个键名。
        # 旧模板写「阵营」被 17 篇照抄、法宝模板写「别称」被 20 篇照抄，
        # 结果同一件事有两种写法，检索和 Dataview 都只认其中一种。
        for _bad, _good in (("阵营", "势力"), ("别称", "别名")):
            if _bad in fm:
                errors.append(
                    f"{rel}: 用了旧键名「{_bad}」，全库统一写「{_good}」（硬规矩第 15 条）"
                )
        if str(fm.get("别名", "")).strip() and not str(fm.get("aliases", "")).strip():
            errors.append(
                f"{rel}: 有「别名」却没有「aliases」——Obsidian 检索读的是 aliases，两个键都要写"
            )

        name = fm.get("词条", "").strip()
        # 允许「00-」这类排序前缀：文件名 00-地图变迁.md 对应 词条: 地图变迁
        stem_key = SORT_PREFIX.sub("", path.stem)
        if name and name not in (path.stem, stem_key):
            errors.append(
                f"{rel}: 词条「{name}」与文件名「{stem_key}」不一致，[[{name}]] 会接不上"
            )

        kind = fm.get("类型", "").strip()
        # `索引` 是导航页（库根 索引.md），不是词条类型：放行，但不计入分类分布。
        if kind and kind != "索引" and kind not in TYPES:
            errors.append(f"{rel}: 类型「{kind}」不在枚举内（{'/'.join(TYPES)}）")

        # 量劫已并入「事件」（2026-11-15）：不再有单独的 量劫 类型，
        # 一条事件靠 `劫序` 标明它在五大量劫里是第几劫（开天辟地是纪元，不算劫）。
        seq = fm.get("劫序", "").strip()
        if seq:
            if not seq.isdigit() or not (1 <= int(seq) <= 4):
                errors.append(
                    f"{rel}: 「劫序」只能是 1-4（开天辟地是纪元、不算劫），现写「{seq}」"
                )
            if kind and kind != "事件":
                errors.append(
                    f"{rel}: 写了「劫序」就说明它是量劫，类型必须是「事件」（现写「{kind}」）"
                )
            if fm.get("元会", "").strip() == "第零元会":
                errors.append(
                    f"{rel}: 第零元会只装开天这一刻（纪元起点），不得写「劫序」（开天辟地不是量劫）"
                )

        # 第零元会只放「开天辟地」一条：开完天才进入第一元会，这一刻里没有第二件事。
        if (fm.get("元会", "").strip() == "第零元会"
                and fm.get("词条", "").strip() != "开天辟地"
                and fm.get("归属", "").strip() != "开天辟地"):
            errors.append(
                f"{rel}: 第零元会只放「开天辟地」这一刻——除本体外只允许它的分卷子条目（归属: 开天辟地）"
            )

        status = fm.get("状态", "").strip()
        if status and status not in STATUSES:
            errors.append(f"{rel}: 状态「{status}」不在枚举内（{'/'.join(STATUSES)}）")

        # 目录与类型必须一致；库根只允许 ROOT_OK 里的文件
        depth = len(rel.parts)
        top = rel.parts[0] if depth > 1 else None
        if top is None:
            if path.name not in ROOT_OK:
                errors.append(
                    f"{rel}: 词条不能放在库根，请放进类型目录（{'/'.join(TYPES)}）"
                )
        else:
            if top not in TYPES:
                errors.append(f"{rel}: 目录「{top}」不是类型目录（{'/'.join(TYPES)}）")
            elif kind and kind != top:
                errors.append(
                    f"{rel}: 类型「{kind}」与所在目录「{top}」不符，按类型目录约定应放在 {kind}\\"
                )
            elif top == "人物":
                # 人物两层：境界 → 大势力（用户 2026-11-21 定）
                #   人物\<境界>\<大势力>\<词条>.md
                ladder = ("混沌",) + LEVEL_LADDER
                if depth != 4:
                    errors.append(
                        f"{rel}: 人物要先分境界、再分大势力："
                        f"人物\\<境界>\\<大势力>\\{path.name}（境界 = {'/'.join(ladder)}）"
                    )
                else:
                    lv, fac = rel.parts[1], rel.parts[2]
                    if lv not in ladder:
                        errors.append(
                            f"{rel}: 境界目录「{lv}」不在阶梯内（{'/'.join(ladder)}）"
                        )
                    elif fm.get("境界", "").strip() != lv:
                        errors.append(
                            f"{rel}: 境界「{fm.get('境界', '（缺）')}」（境界 字段）"
                            f"与所在境界目录「{lv}」不符"
                        )
                    if fac not in FACTION_DIRS:
                        errors.append(
                            f"{rel}: 大势力目录「{fac}」不在枚举内（{'/'.join(FACTION_DIRS)}）"
                        )
                    elif fm.get("势力", "").strip() != fac:
                        errors.append(
                            f"{rel}: 势力「{fm.get('势力', '（缺）')}」（势力 字段）"
                            f"与所在大势力目录「{fac}」不符——人物要写成 人物\\{lv}\\{fac}\\{path.name}"
                        )
            elif top in TIERS:
                field, allowed = TIERS[top]
                if depth == 3:
                    sub = rel.parts[1]
                    # 允许「01-第一元会」这类排序前缀：目录名去掉前缀后再比对
                    sub_key = SORT_PREFIX.sub("", sub)
                    if sub_key not in allowed:
                        errors.append(
                            f"{rel}: 档位目录「{sub}」不在枚举内（{'/'.join(allowed)}）"
                        )
                    elif fm.get(field, "").strip() != sub_key:
                        errors.append(
                            f"{rel}: 档位「{fm.get(field, '（缺）')}」（{field} 字段）"
                            f"与所在档位目录「{sub_key}」不符"
                        )
                elif depth == 4 and top == "事件":
                    # 事件允许一层「大事件分组」（条目太长时拆卷）：
                    #   事件\<元会>\<大事件>.md            本体
                    #   事件\<元会>\<大事件>\<子条目>.md   分卷（front matter 写 `归属: <大事件>`）
                    sub_key = SORT_PREFIX.sub("", rel.parts[1])
                    grp = rel.parts[2]
                    if sub_key not in allowed:
                        errors.append(
                            f"{rel}: 元会目录「{rel.parts[1]}」不在枚举内（{'/'.join(allowed)}）"
                        )
                    elif fm.get(field, "").strip() != sub_key:
                        errors.append(
                            f"{rel}: 元会「{fm.get(field, '（缺）')}」（{field} 字段）"
                            f"与所在元会目录「{sub_key}」不符"
                        )
                    if path.stem == grp:
                        # 本体住进自己的分卷目录（与势力同一套写法）
                        if fm.get("归属", "").strip():
                            errors.append(
                                f"{rel}: 大事件本体不写「归属」（它本身就是归宿）"
                            )
                    else:
                        if not (root / top / rel.parts[1] / grp / f"{grp}.md").exists():
                            errors.append(
                                f"{rel}: 挂在「{grp}」下，但 事件\\{rel.parts[1]}\\{grp}\\{grp}.md 不存在"
                                f"——大事件本体必须先立条"
                            )
                        if fm.get("归属", "").strip() != grp:
                            errors.append(
                                f"{rel}: 归属「{fm.get('归属', '（缺）')}」与所在大事件目录「{grp}」不符"
                            )
                else:
                    errors.append(
                        f"{rel}: {top}必须放进档位子目录（{'/'.join(allowed)}），"
                        f"即 {top}\\<档位>\\{path.name}"
                    )
            elif top == "势力":
                if depth < 4:
                    errors.append(
                        f"{rel}: 势力要先分「类」，再进同名目录："
                        f"势力\\<类>\\<大势力>\\<大势力>.md"
                        f"（类 = {'/'.join(FACTION_CLASSES)}）"
                    )
                elif depth > 5:
                    errors.append(
                        f"{rel}: 势力最多三层（势力\\<类>\\<大势力>\\<大势力>.md 与 "
                        f"势力\\<类>\\<大势力>\\[<组>\\]<子条目>.md）"
                    )
                elif rel.parts[1] not in FACTION_CLASSES:
                    errors.append(
                        f"{rel}: 势力类目录「{rel.parts[1]}」不在枚举内"
                        f"（{'/'.join(FACTION_CLASSES)}）"
                    )
                elif path.stem == rel.parts[2]:
                    # 大势力本体（第二层）
                    if fm.get("归属", "").strip():
                        errors.append(
                            f"{rel}: 大势力本体不写「归属」（它本身就是归宿）；"
                            f"「归属」只给挂在大势力下的组成部分"
                        )
                    secs = len([ln for ln in body.splitlines() if ln.startswith("## ")])
                    if secs < 3:
                        soft.append(
                            f"{rel}: 只 {secs} 节，金字塔结构可能不足三层——"
                            f"不够就别单独成条，挂到上级势力下"
                        )
                else:
                    parent = rel.parts[2]
                    if parent not in moe_first_level:
                        errors.append(
                            f"{rel}: 挂在「{parent}」下，但 势力\\{rel.parts[1]}\\{parent}\\{parent}.md 不存在"
                            f"——大势力本体必须先立条"
                        )
                    if fm.get("归属", "").strip() != parent:
                        errors.append(
                            f"{rel}: 归属「{fm.get('归属', '（缺）')}」与所在大势力目录「{parent}」不符"
                        )
            elif depth > 2:
                errors.append(f"{rel}: 「{top}」不设子目录，请直接放在 {top}\\{path.name}")

        # 法宝：系列 / 禁制 / 品级 三者必须自洽（分类条目页豁免）
        if kind == "法宝" and EXEMPT_TAG not in fm.get("标签", ""):
            tier = fm.get("品阶", "").strip()
            series = fm.get("系列", "").strip()
            grade = fm.get("品级", "").strip()
            raw_num = fm.get("禁制", "").strip()

            # 凡器：没有禁制、不进系列×禁制体系，改用手艺式的「器类」分类
            if tier == "凡器":
                if fm.get("禁制", "").strip() != "0":
                    errors.append(f"{rel}: 凡器没有禁制，`禁制` 必须写 0（0 不是最低档，是不进档）")
                if series != "凡":
                    errors.append(f"{rel}: 凡器的 `系列` 必须写「凡」")
                if grade != "凡":
                    errors.append(f"{rel}: 凡器的 `品级` 必须写「凡」")
                _cls = fm.get("器类", "").strip()
                if not _cls:
                    errors.append(f"{rel}: 凡器必须写「器类」（{'/'.join(WEAPON_CLASSES)}）")
                elif _cls not in WEAPON_CLASSES:
                    errors.append(f"{rel}: 器类「{_cls}」不在枚举内（{'/'.join(WEAPON_CLASSES)}）")
            else:
                want_series = SERIES_OF_TIER.get(tier)
                if not series:
                    errors.append(f"{rel}: 缺「系列」字段（混沌/先天/后天）")
                elif want_series and series != want_series and EXEMPT_SERIES_TAG not in fm.get("标签", ""):
                    errors.append(
                        f"{rel}: 系列「{series}」与品阶「{tier}」不符，应为「{want_series}」"
                    )
                if not raw_num:
                    errors.append(f"{rel}: 缺「禁制」字段（灵宝 1-48 道，至宝 49 道；混沌至宝 50 道）")
                else:
                    try:
                        num = int(raw_num)
                    except ValueError:
                        errors.append(f"{rel}: 禁制「{raw_num}」不是整数")
                    else:
                        want_grade = grade_of(num, series)
                        if want_grade is None:
                            errors.append(f"{rel}: 禁制 {num} 超出 1-50 范围")
                        elif not grade:
                            errors.append(f"{rel}: 缺「品级」字段（下品/中品/上品/极品/功德灵宝/至宝）")
                        elif grade not in GRADES:
                            errors.append(
                                f"{rel}: 品级「{grade}」不在枚举内（{'/'.join(GRADES)}）"
                            )
                        elif grade != want_grade:
                            errors.append(
                                f"{rel}: 品级「{grade}」与 {num} 道禁制不匹配，应为「{want_grade}」"
                            )
                        exact = TIER_EXACT.get(tier)
                        if exact is not None and num != exact:
                            errors.append(
                                f"{rel}: 品阶「{tier}」须为 {exact} 道禁制，现写 {num}"
                            )
                        if tier == "后天灵宝" and num > CRAFT_CAP["后天灵宝"]:
                            errors.append(
                                f"{rel}: 后天灵宝炼制上限 {CRAFT_CAP['后天灵宝']} 道，现写 {num}；"
                                f"43-48 道请归「功德灵宝」（靠功德顶上）"
                            )
                        if tier == "功德灵宝" and not (43 <= num <= 48):
                            errors.append(
                                f"{rel}: 「功德灵宝」须为 43-48 道，现写 {num}（后天灵宝 1-42，后天至宝 49）"
                            )
                        if tier.endswith("灵宝") and num > 48:
                            errors.append(
                                f"{rel}: {num} 道禁制已是至宝档（49/50），不能再算「{tier}」"
                            )

        # 人物：境界必须在阶梯内，境界序必须与境界一致（给 Dataview 排序用）
        if kind == "人物":
            level = fm.get("境界", "").strip()
            raw_order = fm.get("境界序", "").strip()
            if level and level in LEVEL_RANK:
                want = LEVEL_RANK[level]
                if not raw_order:
                    errors.append(f"{rel}: 缺「境界序」字段（应为 {want}）")
                else:
                    try:
                        got = int(raw_order)
                    except ValueError:
                        errors.append(f"{rel}: 境界序「{raw_order}」不是整数")
                    else:
                        if got != want:
                            errors.append(
                                f"{rel}: 境界序 {got} 与境界「{level}」不符，应为 {want}"
                            )
            if not fm.get("境界备注", "").strip():
                errors.append(f"{rel}: 缺「境界备注」（写具体身份，如 祖巫（肉身成圣））")
            # 人物要素：用户 2026-11-20 定的八项清单（基础标识/外貌体征/性格气质/身份背景/
            # 能力喜好/言行特征/状态与关系/补充标签）。有了就必须写满八项；暂不强制全员补齐。
            if "## 人物要素" in body:
                elem = body.split("## 人物要素", 1)[1]
                elem = re.split(r"\n## ", elem)[0]
                n_elem = len(re.findall(r"^### ", elem, re.M))
                if n_elem < 8:
                    errors.append(
                        f"{rel}: 「人物要素」要写满八项"
                        f"（一、基础标识 … 八、补充标签），现有 {n_elem} 项"
                    )
                ELEM_YES.append(rel)
            else:
                ELEM_NO.append(rel)
            # 时间线：人物必须写清「生 → 关键节点 → 终」，防止把不同元会的人写进同一场戏
            timeline = fm.get("时间线", "").strip()
            if not timeline:
                errors.append(
                    f"{rel}: 缺「时间线」字段（格式：第一元会生 → 第三元会初射十乌 → 战死）"
                )
            elif "→" not in timeline:
                errors.append(f"{rel}: 「时间线」要用 → 连成链（生 → 节点 → 终）")
            # 可攻略性（用户 2026-11-21 定）：原创设定层的后宫/姻缘线必须先在这里标清楚，
            # 免得同一个角色在人物页与名录页说法不一。
            emotion = fm.get("情感状态", "").strip()
            if emotion and emotion not in ("单身", "已婚"):
                errors.append(f"{rel}: 「情感状态」只能是 单身/已婚，现为「{emotion}」")
            guide = fm.get("攻略", "").strip()
            if guide:
                if guide not in ("可攻略", "不可攻略"):
                    errors.append(f"{rel}: 「攻略」只能是 可攻略/不可攻略，现为「{guide}」")
                elif guide == "可攻略":
                    GUIDE_YES.append(rel)
                    if emotion == "已婚":
                        errors.append(
                            f"{rel}: 「已婚」不能是「可攻略」——名分已落定的不能再进后宫线（用户 2026-11-21 纠错）"
                        )
                else:
                    GUIDE_NO.append(rel)
                    if emotion != "已婚":
                        errors.append(f"{rel}: 「不可攻略」必须是「情感状态: 已婚」（有归属才不可攻略）")
            # 三视角评价 / 标签 / 器物 / 人我：字段必须存在（内容允许空＝占位），标签 1-3 个
            for key in PERSON_KEYS:
                if key not in fm:
                    errors.append(f"{rel}: 缺「{key}」字段（有就写，没有可留空，但不能缺字段）")
            tags = [x for x in re.split(r"[、,，;；/]", fm.get("人物标签", "")) if x.strip()]
            if len(tags) > 3:
                errors.append(f"{rel}: 「人物标签」最多三个，现有 {len(tags)} 个")
            if "人物标签" in fm and not tags:
                errors.append(f"{rel}: 「人物标签」不能空（评价三视角至少能推出一个）")
            arts = fm.get("法宝", "").strip()
            if "本命法宝" in fm:
                errors.append(f"{rel}: 「本命法宝」已并入「法宝」（法宝要带类型占位）")
            if arts and "（类型：" not in arts:
                errors.append(f"{rel}: 「法宝」要标注类型占位，如 番天印（类型：待定）")

        # 妖族：必须写「妖身状态」字段与正文「## 妖身」一节
        race = fm.get("种族", "").strip()
        if "妖" in race:
            if not fm.get("妖身状态", "").strip():
                errors.append(
                    f"{rel}: 种族含「妖」，必须写「妖身状态」字段"
                    f"（形态 / 尺寸 / 现状 / 要害，一行说清）"
                )
            if "## 妖身" not in body:
                errors.append(
                    f"{rel}: 种族含「妖」，正文必须有「## 妖身」一节"
                    f"（现形只在特定场合，且要写清状态）"
                )

        # 事件：必须写「事件要素」十项（史书式·时段大事记录）
        if kind == "事件":
            if "## 事件要素" in body:
                seg = body.split("## 事件要素", 1)[1]
                seg = re.split(r"\n## ", seg)[0]
                n_ev = len(re.findall(r"^### ", seg, re.M))
                if n_ev < 10:
                    errors.append(
                        f"{rel}: 「事件要素」要写满十项（一、时间 … 十、关联），现有 {n_ev} 项"
                    )
                EV_YES.append(rel)
            else:
                errors.append(
                    f"{rel}: 事件必须写「## 事件要素」十项"
                    f"（时间/地点/主体/事由/经过/结果/影响/史料备注/定性/关联）"
                )
                EV_NO.append(rel)

        # 概念：正文必须写满九节（门类「总览」豁免——那三篇是导航/编年页）
        if kind == "概念":
            k = fm.get("门类", "").strip()
            if k not in CONCEPT_SECTIONS_EXEMPT:
                missing = [s for s in CONCEPT_SECTIONS if s not in body]
                if missing:
                    errors.append(
                        f"{rel}: 概念正文缺 {len(missing)} 节（定义/本源由来/核心特征/"
                        f"适用范围/类比与实例/相近概念对比/作用意义/局限与争议/简单总结）："
                        + "、".join(s.lstrip("# ").strip() for s in missing)
                    )
                    CON_NO.append(rel)
                else:
                    CON_YES.append(rel)

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

    # 各类计数，顺带看一眼分布是否失衡（重点在量劫，人物/法宝应随之增长）
    dist = {t: 0 for t in TYPES}
    draft = 0
    for _stem, (_rel, fm) in entries.items():
        k = fm.get("类型", "").strip()
        if k in dist:
            dist[k] += 1
        if fm.get("状态", "").strip() == "草稿":
            draft += 1

    # 别名转发：[[玲珑宝塔]] 这类写法指向某个词条的 front matter `别名` 时，
    # 不算「没有正文」，但要单独报出来——别名会掩盖真断链，必须可见。
    def split_list(raw: str):
        raw = (raw or "").strip().strip("[]")
        for sep in ("，", "、", ";"):
            raw = raw.replace(sep, ",")
        return [x.strip().strip("'\"") for x in raw.split(",") if x.strip()]

    alias_of: dict[str, str] = {}
    alias_dupes: dict[str, list[str]] = {}
    for _stem, (_rel, fm) in entries.items():
        owner = fm.get("词条", "").strip() or _stem
        for a in split_list(fm.get("别名", "")):
            if a == owner:
                continue
            # 同一别名被两个词条占用时，Obsidian 的 [[别名]] 会随机落到其中一个，
            # 等于把「同名不同物」的两件事悄悄并成一件——必须阻塞。
            if a in alias_of and alias_of[a] != owner:
                alias_dupes.setdefault(a, [alias_of[a]]).append(owner)
                continue
            # 别名撞上另一个词条的正式名，也是冲突：[[别名]] 会落到那个词条，
            # 别名表却记在别人身上，链接含义被悄悄改写。
            if a in entries and a != owner:
                alias_dupes.setdefault(a, [owner]).append(a)
                continue
            alias_of.setdefault(a, owner)

    if alias_dupes:
        for _a, _owners in alias_dupes.items():
            uniq = list(dict.fromkeys(_owners))
            errors.append(
                "别名「{0}」被多个词条占用：{1}（别名必须唯一，同名的两件事请起不同名）".format(
                    _a, " / ".join(uniq)
                )
            )
            print(f"  ✗ 别名冲突 ×1：「{_a}」→ {' / '.join(uniq)}")

    # 别名只用于检索：正文双链必须写「词条名」。
    # 拿别名当链接目标，Obsidian 的未解析计数、导出与部分第三方工具都会判成空链。
    alias_links = {t: c for t, c in refs.items() if t not in entries and t in alias_of}
    if alias_links:
        errors.append(
            "正文里有链接用的是「别名」而不是词条名（如 [[{0}]]，应写成 [[{1}|{2}]]）".format(
                next(iter(alias_links)),
                alias_of[next(iter(alias_links))],
                next(iter(alias_links)),
            )
        )
        for _t, _c in sorted(alias_links.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  ✗ 别名当链接 ×{_c}：[[{_t}]] → 应写 [[{alias_of[_t]}]]")

    pending = {
        t: c for t, c in refs.items() if t not in entries and t not in alias_of
    }
    alias_hits = {t: c for t, c in refs.items() if t not in entries and t in alias_of}
    ordered = sorted(pending.items(), key=lambda kv: (-kv[1], kv[0]))

    print(f"词库自检  {root}")
    print(f"扫描词条 {len(entries)} 篇，引用 {sum(refs.values())} 处，指向 {len(refs)} 个词条")
    print("分类分布  " + "  ".join(f"{t}{n}" for t, n in dist.items() if n))
    print(f"人物要素  已写 {len(ELEM_YES)} 篇 / 待补 {len(ELEM_NO)} 篇")
    print(f"可攻略性  可攻略 {len(GUIDE_YES)} 篇 / 不可攻略 {len(GUIDE_NO)} 篇")
    print(f"事件要素  已写 {len(EV_YES)} 篇 / 待补 {len(EV_NO)} 篇")
    print(f"概念九节  已写 {len(CON_YES)} 篇 / 待补 {len(CON_NO)} 篇（门类「总览」豁免）")
    for kind_name, (field, allowed) in TIERS.items():
        counts = {}
        for _stem, (_rel, fm) in entries.items():
            # 只统计住在档位子目录里的条目：库根的索引页也声明为「概念」，但它没有门类。
            if len(_rel.parts) >= 3 and fm.get("类型", "").strip() == kind_name:
                v = fm.get(field, "").strip() or "（缺）"
                counts[v] = counts.get(v, 0) + 1
        if counts:
            parts = [f"{t}{counts[t]}" for t in allowed if counts.get(t)]
            parts += [f"{t}{n}" for t, n in counts.items() if t not in allowed]
            print(f"{kind_name}{field}  " + "  ".join(parts))
    print(f"状态     草稿 {draft} 篇，其余 {len(entries) - draft} 篇")
    print()
    print("E 级（阻塞）")
    if errors:
        for item in errors:
            print(f"  ✗ {item}")
    else:
        print("  无")
    print()
    print(f"W 级（待补词条 {len(pending)} 个：被引用但还没有正文）")
    if ordered:
        for target, count in ordered:
            print(f"  · {target}  ×{count}")
    else:
        print("  无")
    if alias_hits:
        print(f"  —— 另有 {len(alias_hits)} 个链接走的是别名（已有正文，不算待补）：")
        for target, count in sorted(alias_hits.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"     ↪ {target} ×{count} → {alias_of[target]}")
    print()
    if soft:
        print("W 级（提示：结构可能不足以单独成条）")
        for item in soft:
            print(f"  ~ {item}")
        print()
    print("结论：" + ("有 E 级问题，先修完再加正文" if errors else "无阻塞问题，可以继续写"))
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
