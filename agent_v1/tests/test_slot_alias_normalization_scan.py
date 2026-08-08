"""AST 级静态扫描：卡侧/世界侧槽名裸比对的护栏（2026-07-27，别名归一收口）。

## 为什么有这个扫描

卡侧槽名与世界侧槽名存在命名分叉（卡侧 `repair.prescribed.started` vs 世界侧
`procedure.repair.prescribed.started`），权威对照在卡包
`projection_runtime_mapping_v1.json` 的 `slot_aliases`（15 个键，其中 14 个真别名）。
**同一形状的病一天之内咬了三次**：闭包 deadline 锚点两级查找裸查、大模型工具
`get_facts_by_slot` 裸比、脚本 `analyze_seam_gap` 裸比世界槽集合——三处都不是
"忘了写"，而是**写的时候看不出来这里有两套命名**。人工 review 抓不住，因为裸比
对的代码读起来完全正常。

⇒ 把"哪些地方在拿名字直接比"这件事变成机器可检的结构事实。

## 判据

扫 `agent_v1/src/` + `agent_v1/scripts/`，AST 里出现下列任一形态：

- `<expr>.slot_id == / != <expr>`
- `slot_index` / `measure_index` 的 `.get(...)` / `[...]` / `in` 三种访问

而**该函数（含其外层函数链）内没有任何归一调用**（`canonical_slot` /
`canonical_measure` / `slot_alias_policy.*` / `slot_aliases` / `aliases` 等标识符）
⇒ 报警，除非在下面两张白名单里。

## 🔴 诚实边界（别把这个测试当成"别名问题已解决"的证明）

1. **"这个名字是卡侧还是世界侧"机器判不了**——判据只看"有没有过归一"，不看
   被比的字面量究竟属于哪一侧。故白名单每条的理由**是人裁的**，会随代码演进
   腐化：一个今天"两侧同为世界侧名"的函数，明天被改成接收卡侧入参，白名单
   不会自己失效。**改到白名单里的函数时，必须回来重判理由是否还成立。**
2. **完全挡不住"别名表里缺条目"**。本扫描只管"已登记的别名有没有被查"，
   `defect.ubw.present` 这种卡侧有、世界侧有近名、**别名表里根本没这一行**的缺口，
   它一条都看不见——那是数据问题，由 `test_slot_alias_reconciliation.py` 盯。
3. **只查两种语法形态**。`f.slot_id in some_set`、`sorted(pack.slot_index)`、
   经中间变量绕一手（`sid = f.slot_id` 后再比）等形态都漏。故本扫描是**下界**，
   "扫描通过"≠"全仓已归一"。
4. **测试模块整体不扫**（见 `_is_test_module`）：测试造具的两侧名字都是自己
   写的字面量，同源，按定义不需要归一；把它们纳进来只会得到 40 余条毫无信息量
   的白名单条目、淹掉真信号。代价是**测试里的裸比对不受本护栏保护**——但测试
   本来就不是生产路径。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

AGENT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (AGENT_ROOT / "src", AGENT_ROOT / "scripts")

# 归一标识符：函数（或其外层函数）里出现任一即视为"已过归一"。
# 只认 Name / Attribute / keyword 三种**标识符**位置，**不认字符串常量**——
# 否则 docstring 里提一嘴 "canonical_slot" 的函数会被误判成已归一。
_NORMALIZER_IDENTIFIERS: Set[str] = {
    "canonical_slot",
    "canonical_measure",
    "normalize_alias_map",
    "slot_aliases_from_policy",
    "measure_aliases_from_policy",
    "reverse_alias_index",
    "card_slot_candidates",
    "slot_alias_policy",
    "slot_aliases",
    "measure_aliases",
    "aliases",
}

_INDEX_NAMES: Set[str] = {"slot_index", "measure_index"}


# --------------------------------------------------------------------------- #
# 白名单甲：**结构上不需要归一**——两侧同源，过不过归一逐字节同结果。
# 每条必须写清"为什么不需要"，不接受"应该没事"。
# --------------------------------------------------------------------------- #
_NO_NORMALIZATION_NEEDED: Dict[Tuple[str, str], str] = {
    ("src/evo_agent_baseline/closure/applicability.py", "_collect_slot_values"): (
        "入参 slot_id 来自卡侧 applicability scope 字典的键；实测现语料该字典的键"
        "只有 regime / actors / actor 三类，**没有任何一个是槽名**（调用方 "
        "_scope_conflicts 已把这三个 continue 掉），故三条 dict scope 路径全不触发、"
        "别名归一无从生效。函数体处已有同内容注释。"
        "⚠️ 若将来 scope 出现真槽名键，此条理由立刻失效，须接 slot_alias_policy。"
    ),
    ("src/evo_agent_baseline/closure/applicability.py", "_match_component_scope"): (
        "同 _collect_slot_values：比的是卡侧 component_scope 字典的键，现语料该键"
        "同样不含槽名。⚠️ 理由与上条共存亡。"
    ),
    ("src/evo_agent_baseline/closure/obligation_deriver.py", "_bind_artifact_fact"): (
        "查的 slot 取自模块常量 ARTIFACT_KEY_TO_SIDECAR_SLOT 的值（17 个 "
        "`artifact.*` 名）。实测这 17 个值与别名表 15 个键**交集为空**，且它们本身"
        "就是世界侧名（`artifact.plan.annotated` 正是卡侧 "
        "`reporting.annotated_location_plan.present` 的别名目标），归一是恒等。"
    ),
    (
        "src/evo_agent_baseline/closure/obligation_deriver.py",
        "_check_required_field_groups",
    ): (
        "查的是硬编码字面量 `qual.artifact_field_group`——sidecar 世界侧产出的槽，"
        "不在别名表键里，归一恒等。"
    ),
    ("src/evo_agent_baseline/retrieval/fact_retriever.py", "facts_from_raw"): (
        "比的是硬编码字面量 `actor.representative.assigned_role`，且比较对象 "
        "atom 是本函数刚从 sidecar entry 造出来的**世界侧**事实——两侧同为世界侧，"
        "该名也不在别名表键里。"
    ),
    (
        "src/evo_agent_baseline/retrieval/fact_retriever.py",
        "infer_method_class_for_verification_flags",
    ): (
        "比的是硬编码字面量 `verification.test.failed`，两侧同为世界侧事实原子，"
        "该名不在别名表键里。"
    ),
    ("src/evo_agent_baseline/retrieval/fact_retriever.py", "derive_risk_slot_facts"): (
        "比的是 `risk_slot_derivations` 的**值**——该表方向是「卡端消费槽 → W0 "
        "事实端源槽」，值这一侧本就是世界侧名（现语料唯一一条："
        "`risk.fire_safety.adverse_impact` → `fire_safety.deficiency.present`），"
        "与 `a.slot_id` 同侧；实测值集与别名表键交集为空，归一恒等。"
        "（表的**键**才是卡侧名，而键在此只用作输出槽名、不参与比较。）"
    ),
    ("src/workflow_engine/worldgen/generator.py", "_lookup_fragment_fsp_measurement"): (
        "感知层 worldgen 内部（1b / 波次二 #31 新增）：比的是硬编码字面量 "
        "`ratio.fsp.structural_performance`——W1 Step 8 自己刚写出来的**世界侧**量测槽名，"
        "与被比的 `measurement.slot_id` 同源同侧。该名不在别名表键里；且卡侧名按分层单向"
        "红线根本不进入 workflow_engine（该包不 import evo_agent_baseline），"
        "此层结构上不存在卡/世界分叉。"
    ),
    ("src/workflow_engine/worldgen/generator.py", "_compute_derived_flags_for_condition"): (
        "感知层 worldgen 内部：`strength.pull_test.reported` / "
        "`stress.pull_test.minimum` 两个字面量与被比的测量记录**同属世界侧**。"
        "卡侧名按分层单向红线根本不进入 workflow_engine（该包不 import "
        "evo_agent_baseline），故此层结构上不存在卡/世界分叉。"
    ),
    ("src/workflow_engine/rulecard_v2.py", "summary"): (
        "🔴 本条是**扫描器自身的假阳**，留在白名单里当活样本：这里的 "
        "`self.slot_index` 是卡包 `slot_index.json` **反序列化出来的普通 dict**"
        "（`.get(\"slots\", [])` 取的是文件顶层键），与 FactIndex.slot_index "
        "只是重名。判据按名字匹配，分不出来——这正是诚实边界 1 说的"
        "「机器判不了这个名字是什么」。"
    ),
    ("scripts/check_override_registry_reconciliation.py", "reconcile"): (
        "P5（W2 override 对账闸，2026-08-06 归属裁定）：`:306` 的 `b.slot_id == "
        "slot_id` 两侧都出自**同一** `_collect_bindings(mapping)` 结果集"
        "（`{b.slot_id for b in bindings}` 迭代自身再回头过滤自身），同源同侧、"
        "过不过归一逐字节同结果。该闸对账的三份资产（`projection_runtime_mapping` "
        "覆盖表 / `semantic_slot_registry` / `override_trigger_whitelist`）全部是"
        "**卡侧**权威文件，槽名同一命名域；跨侧（卡↔世界）对账不是本闸职责——"
        "闸文件头自述它只堵『覆盖表引用未登记槽/未授权角色/两侧漂移』三个卡侧洞。"
        "⚠️ 若将来本闸引入世界侧槽名（如按运行时事实校验覆盖谓词），此条理由失效，"
        "须接 slot_alias_policy。"
    ),
}

# --------------------------------------------------------------------------- #
# 白名单乙：**真实的未归一暴露**，但当前不咬人。
# 与甲的区别：甲是"过了归一也一样"，乙是"过归一会不一样、但这条路现在没通电"。
# 🔴 乙里的每一条，在对应功能激活前**必须先接归一**。
# --------------------------------------------------------------------------- #
_KNOWN_UNNORMALIZED: Dict[Tuple[str, str], str] = {
}

_WHITELIST: Dict[Tuple[str, str], str] = {
    **_NO_NORMALIZATION_NEEDED,
    **_KNOWN_UNNORMALIZED,
}


def _is_test_module(path: Path) -> bool:
    """测试模块整体不扫（诚实边界 4：两侧同源字面量，纳入只会淹掉真信号）。"""
    return path.name.startswith("test_") or "tests" in path.parts


def _normalizes(func: ast.AST) -> bool:
    """函数子树里是否出现归一标识符（只认标识符位置，不认字符串常量）。"""
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and node.id in _NORMALIZER_IDENTIFIERS:
            return True
        if isinstance(node, ast.Attribute) and node.attr in _NORMALIZER_IDENTIFIERS:
            return True
        if isinstance(node, ast.keyword) and node.arg in _NORMALIZER_IDENTIFIERS:
            return True
    return False


def _base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _bare_lookups(func: ast.AST) -> List[Tuple[int, str]]:
    """函数子树里的裸比对/裸索引形态，返回 [(行号, 形态标签)]。"""
    out: List[Tuple[int, str]] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Compare) and node.ops:
            op = node.ops[0]
            if isinstance(op, (ast.Eq, ast.NotEq)):
                for side in [node.left, *node.comparators]:
                    if isinstance(side, ast.Attribute) and side.attr == "slot_id":
                        out.append((node.lineno, ".slot_id ==/!="))
            elif isinstance(op, (ast.In, ast.NotIn)):
                for side in node.comparators:
                    if _base_name(side) in _INDEX_NAMES:
                        out.append((node.lineno, f"in {_base_name(side)}"))
        elif isinstance(node, ast.Call):
            fn = node.func
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr == "get"
                and _base_name(fn.value) in _INDEX_NAMES
            ):
                out.append((node.lineno, f"{_base_name(fn.value)}.get("))
        elif isinstance(node, ast.Subscript):
            if _base_name(node.value) in _INDEX_NAMES:
                out.append((node.lineno, f"{_base_name(node.value)}["))
    return out


def scan() -> Dict[Tuple[str, str], List[Tuple[int, str]]]:
    """全仓扫描，返回 {(相对路径, 函数名): [(行号, 形态), ...]}。"""
    findings: Dict[Tuple[str, str], List[Tuple[int, str]]] = {}

    def walk_scope(node: ast.AST, enclosing: List[ast.AST], rel: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chain = [*enclosing, child]
                # 外层函数已归一 ⇒ 视为已归一（先归一再往下传是正当写法）。
                if not any(_normalizes(f) for f in chain):
                    hits = _bare_lookups(child)
                    if hits:
                        findings.setdefault((rel, child.name), []).extend(hits)
                walk_scope(child, chain, rel)
            else:
                walk_scope(child, enclosing, rel)

    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or _is_test_module(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            walk_scope(tree, [], path.relative_to(AGENT_ROOT).as_posix())
    return findings


def test_scan_roots_exist_and_are_nonempty() -> None:
    """自检：扫描目标存在且真扫到了函数——否则"零发现"是假绿。"""
    for root in SCAN_ROOTS:
        assert root.is_dir(), f"扫描目标不存在: {root}"
    n_files = sum(
        1
        for root in SCAN_ROOTS
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and not _is_test_module(p)
    )
    assert n_files > 100, f"只扫到 {n_files} 个生产模块，扫描器多半被路径问题掐了"


def test_no_unwhitelisted_bare_slot_comparison() -> None:
    """新增的裸比对必须显式入白名单（附理由），否则报警。"""
    findings = scan()
    unlisted = {k: v for k, v in findings.items() if k not in _WHITELIST}
    assert not unlisted, (
        "发现未归一的槽名裸比对/裸索引（新写的代码请先过 "
        "`evo_agent_baseline.slot_alias_policy`；确属同源字面量则加进本文件的 "
        "`_NO_NORMALIZATION_NEEDED` 并写明为什么不需要归一）：\n"
        + "\n".join(
            f"  {f}::{fn}  {hits}" for (f, fn), hits in sorted(unlisted.items())
        )
    )


def test_whitelist_has_no_stale_entries() -> None:
    """白名单不许留僵尸条目——函数改名/删除/已接归一后必须撤条目。

    没有这一条，白名单会单向膨胀：条目失效了也没人知道，下一个人以为
    "这里已经审过了"。
    """
    findings = scan()
    stale = sorted(set(_WHITELIST) - set(findings))
    assert not stale, (
        "白名单里这些条目已经扫不到了（函数改名/删除/已接归一）——请删掉：\n"
        + "\n".join(f"  {f}::{fn}" for f, fn in stale)
    )


def test_every_whitelist_entry_has_a_reason() -> None:
    """理由不许留空或敷衍——白名单的价值全在理由上。"""
    for key, reason in _WHITELIST.items():
        assert isinstance(reason, str) and len(reason.strip()) >= 30, (
            f"白名单条目 {key} 的理由太短，必须写清「此处为什么不需要归一」"
        )
