"""发现 C-1 回归闸：单栋跑批入口的**评测段**必须与编排层用同一套判定语义。

背景（2026-08-06 步 C 查实）：`run_baseline_e2e_smoke.py` 第 5 步为拿
`ClosureValidationResult` 实例喂 evaluator，**又重跑了一次** `validate_building_closure`。
该调用点过去只传 `identity_blueprint_catalog`，**不传 `applicability_bundle`、
不传 DEBT-083 三个开关** ⇒ 评测段看到的是组件结构早退全关、哨兵边界／作用域授权／
查询行遮蔽全关的另一套语义。同栋同次运行实测：权威闭包 10,323 条 vs 评测段 11,272 条。

危害面不在这个脚本自己，而在下游：`eval_report.json` 由该结果算出 →
`aggregate_baseline_batch.aggregate_reports` 取它的 confusion／threshold／
verifiable_subuniverse 三组指标 → `batch_summary.json` → `check_batch_acceptance.py`
（批级验收闸）。而批驱动 `run_baseline_batch.py` 每栋正是以子进程调这个脚本
（`SINGLE_RUNNER`），故**不修则整批验收建在非生产判定语义上**。

本模块用结构闸（AST）而非端到端跑批来守，理由：该调用点埋在需要 Neo4j 与真实检索的
长函数里，端到端复现代价极高，而「漏传一个 kwarg」这种缺陷在结构层是**可判定**的。
两条闸：
  1. 评测段调用点必须把整套 kwarg 传齐；
  2. 这套 kwarg 必须与编排层权威调用点（`_wrap_closure_fn_with_catalog`）**逐名相等**
     —— 将来谁在编排层加第五个开关而忘了同步评测段，这条会当场红。
并配变异对照：把任一 kwarg 从源码里摘掉，闸必须报出来（防「闸写了但抓不到」）。
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SMOKE = _REPO / "agent_v1" / "scripts" / "run_baseline_e2e_smoke.py"
_REPLAY = _REPO / "agent_v1" / "scripts" / "replay_closure_offline.py"
_ORCH = (_REPO / "agent_v1" / "src" / "evo_agent_baseline" / "agent"
         / "run_orchestrator.py")

_CLOSURE_CALLEE = "validate_building_closure"
_ORCH_WRAPPER = "_wrap_closure_fn_with_catalog"

# 编排层现行权威形态（catalog + bundle + DEBT-083 三开关）。这里写死一份是为了让
# 「两边同时漏同一个」也能被抓到——只比两边相等的话，同步地漏掉就静默过了。
_EXPECTED = {
    "identity_blueprint_catalog",
    "applicability_bundle",
    "exclude_fallback_reasons_facts",
    "authorized_scope_selection",
    "mask_lookup_targets",
}


def _closure_call_kwargs(source: str) -> list[set[str]]:
    """取源码里每个 `validate_building_closure(...)` 调用的关键字实参名集合。"""
    tree = ast.parse(source)
    found: list[set[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else None)
        if name != _CLOSURE_CALLEE:
            continue
        found.append({kw.arg for kw in node.keywords if kw.arg is not None})
    return found


def _orchestrator_kwarg_names(source: str) -> set[str]:
    """取编排层包装器里真正下发给 closure 的 kwarg 名。

    覆盖两种写法：字典字面量 `{"a": ...}` 与后续 `kwargs["b"] = ...` 下标赋值。
    """
    tree = ast.parse(source)
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == _ORCH_WRAPPER:
            target = node
            break
    if target is None:
        raise AssertionError(
            f"{_ORCH.name} 里找不到 {_ORCH_WRAPPER}——权威调用点被改名或删除，"
            "本闸的锚点失效，必须先确认新的权威形态。"
        )
    names: set[str] = set()
    for node in ast.walk(target):
        # `kwargs: Dict[str, Any] = {...}` 是 AnnAssign，`kwargs["x"] = ...` 是 Assign，
        # 两种都要收（只收前者会静默漏掉 catalog/bundle 两个名）。
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
        else:
            continue
        for tgt in targets:
            # `kwargs: Dict[str, Any] = {...}` / `kwargs = {...}`
            if (isinstance(tgt, ast.Name) and tgt.id == "kwargs"
                    and isinstance(node.value, ast.Dict)):
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        names.add(key.value)
            # `kwargs["x"] = ...`
            elif (isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id == "kwargs"
                    and isinstance(tgt.slice, ast.Constant)
                    and isinstance(tgt.slice.value, str)):
                names.add(tgt.slice.value)
    if not names:
        raise AssertionError(
            f"{_ORCH_WRAPPER} 里没解析出任何 kwargs 名——权威调用点的写法变了"
            "（例如改成直接展开传参），本闸的解析器必须跟着改。"
        )
    return names


def _drop_kwarg(source: str, kwarg: str) -> str:
    """变异用：把评测段调用里某个 kwarg 那一行摘掉（不落盘，只在内存里改）。"""
    lines = source.splitlines(keepends=True)
    out = [ln for ln in lines if not ln.strip().startswith(f"{kwarg}=")]
    assert len(out) < len(lines), f"变异无效：源码里没有 `{kwarg}=` 行"
    return "".join(out)


class TestEvalSegmentClosureParity(unittest.TestCase):

    def setUp(self) -> None:
        self.smoke_src = _SMOKE.read_text(encoding="utf-8")
        self.orch_src = _ORCH.read_text(encoding="utf-8")

    def test_eval_segment_passes_full_kwarg_set(self) -> None:
        """评测段的闭包调用必须把整套 kwarg 传齐（漏一个即非生产语义）。"""
        calls = _closure_call_kwargs(self.smoke_src)
        self.assertEqual(
            len(calls), 1,
            f"{_SMOKE.name} 里 {_CLOSURE_CALLEE} 调用点数量变了（实得 {len(calls)}）——"
            "新增调用点同样要传齐 kwarg，请先确认后再改本闸。",
        )
        missing = _EXPECTED - calls[0]
        self.assertFalse(
            missing,
            f"评测段闭包调用漏传 {sorted(missing)} ⇒ 它算出的 eval_report.json "
            "不是生产判定语义，会毒化 batch_summary 与批级验收闸（发现 C-1）。",
        )

    def test_eval_segment_matches_orchestrator_authority(self) -> None:
        """评测段与编排层权威调用点逐名相等——防将来单边加开关造成语义再分叉。"""
        orch_names = _orchestrator_kwarg_names(self.orch_src)
        self.assertEqual(
            orch_names, _EXPECTED,
            f"编排层权威 kwarg 集变成 {sorted(orch_names)}：判定语义的开关面动了，"
            "评测段与本闸的 _EXPECTED 必须同步复核后再改。",
        )
        eval_names = _closure_call_kwargs(self.smoke_src)[0]
        self.assertEqual(
            eval_names & _EXPECTED, orch_names,
            "评测段与编排层下发的 kwarg 集不一致 ⇒ 同一次运行两套判定语义。",
        )

    def test_switch_resolvers_are_not_redefined_locally(self) -> None:
        """三个开关只许有编排层一份解析，脚本里不得另立缺省。

        「同一假设散在三层」是本仓记过的形状：脚本里自己写一份 `os.environ.get(...)`
        缺省，将来编排层改了缺省而这里不改，就又是静默分叉。
        """
        tree = ast.parse(self.smoke_src)
        local_defs = {
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        for resolver in (
            "resolve_fallback_boundary_enabled",
            "resolve_authorized_scope_selection_enabled",
            "resolve_mask_lookup_targets_enabled",
            "load_applicability_bundle_once",
        ):
            self.assertNotIn(
                resolver, local_defs,
                f"{_SMOKE.name} 自己定义了 {resolver}——必须复用编排层那一份。",
            )
            self.assertIn(
                resolver, self.smoke_src,
                f"{_SMOKE.name} 没有引用 {resolver}，开关值来源不明。",
            )

    def test_replay_offline_matches_orchestrator_authority(self) -> None:
        """离线重放脚本的闭包调用与编排层权威调用点逐名相等（DEBT-088 重开条件）。

        replay_closure_offline.py 曾同形漏传三开关（DEBT-088 未修部分），冻结窗口
        结束后照评测段同一形状补齐。本闸守「补齐后不许再漏」--将来谁在编排层加
        开关而忘了同步重放脚本，这条会当场红。
        """
        replay_src = _REPLAY.read_text(encoding="utf-8")
        orch_names = _orchestrator_kwarg_names(self.orch_src)
        calls = _closure_call_kwargs(replay_src)
        self.assertEqual(
            len(calls), 1,
            f"{_REPLAY.name} 里 {_CLOSURE_CALLEE} 调用点数量变了（实得 {len(calls)}）--"
            "新增调用点同样要传齐 kwarg，请先确认后再改本闸。",
        )
        self.assertEqual(
            calls[0] & _EXPECTED, orch_names,
            "离线重放脚本与编排层下发的 kwarg 集不一致 ⇒ 同一次运行两套判定语义。",
        )

    def test_mutation_dropping_any_kwarg_is_caught(self) -> None:
        """变异对照：摘掉任一 kwarg，第一条闸必须报出来（防闸空转）。"""
        for kwarg in sorted(_EXPECTED - {"identity_blueprint_catalog"}):
            with self.subTest(dropped=kwarg):
                mutated = _drop_kwarg(self.smoke_src, kwarg)
                calls = _closure_call_kwargs(mutated)
                self.assertEqual(len(calls), 1)
                self.assertTrue(
                    _EXPECTED - calls[0],
                    f"摘掉 {kwarg} 后闸仍认为齐全——闸没在咬。",
                )
                self.assertIn(kwarg, _EXPECTED - calls[0])


if __name__ == "__main__":
    unittest.main()
