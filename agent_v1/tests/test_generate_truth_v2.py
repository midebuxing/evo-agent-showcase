# -*- coding: utf-8 -*-
"""真值 v2 生成器与两道闸的契约测试 ＋ **变异对照**。

## 为什么必须有变异对照

「加了断言」和「断言真的会响」是两件事。本项目已经栽过：闸显示 Passed 而规则
从没被检查过、测试跑在缺陷不可能显现的输入上。故本文件的每一道闸都配一条
**主动破坏**：把源数据/输出改成该闸要挡的形状，断言它**抛错**；不抛就是闸没接上。

四条变异（工单_真值v2落地事务_20260807 §三）：

1. `test_mutation_grid_hole_raises`      —— 删网格一格 ⇒ 网格契约抛错
2. `test_mutation_duplicate_row_raises`  —— 植入重复 (项,栋) 行 ⇒ 唯一键断言抛错
3. `test_mutation_constant_flip_changes_exactly_ten_rows`
                                          —— 改模板一项常量 ⇒ 对应 10 行齐变、其余零变
4. `test_mutation_forged_out_of_pool_building_fails_gate`
                                          —— disjoint 闸对 v2 断言真值⊆池；
                                             伪造一条非池栋行 ⇒ exit 1

⚠️ 变异一律做在**临时副本**上，绝不改仓库里的权威产物（改坏了不还原是本项目
栽过的形状）。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "agent_v1" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gen = _load("generate_truth_v2")
gate = _load("assert_pool_truth_disjoint")

POOL_DIR = REPO / "agent_v1/experiments/qa_reports/_poolv2_50x1_seed401/gen_seed_401"

pytestmark = pytest.mark.skipif(
    not gen.PARTITION_PATH.is_file() or not gen.GRID_PATH.is_file(),
    reason="内容层产物（final_partition / final_grid）不在盘上——experiments/ 不入库",
)


# ── 正向：结构与契约 ────────────────────────────────────────────────────

def test_contract_numbers_match_content_layer_ledger():
    """契约常量必须与内容层终局 §一 的终数同源（161/110/7/278×10）。"""
    assert gen.CONTRACT_CONSTANT_ITEMS == 161
    assert gen.CONTRACT_GRID_ITEMS == 110
    assert gen.CONTRACT_PENDING_ITEMS == 7
    assert gen.CONTRACT_TOTAL_ITEMS == 278
    assert gen.CONTRACT_BUILDINGS == 10
    assert gen.CONTRACT_TOTAL_ROWS == 2780


def test_build_rows_satisfies_grid_contract():
    rows, stats = gen.build_rows()
    assert len(rows) == gen.CONTRACT_TOTAL_ROWS
    assert stats["constant_items"] == gen.CONTRACT_CONSTANT_ITEMS
    assert stats["grid_items"] == gen.CONTRACT_GRID_ITEMS
    assert stats["pending_items"] == gen.CONTRACT_PENDING_ITEMS
    keys = {(r["normative_item_id"], r["building_id"]) for r in rows}
    assert len(keys) == len(rows), "唯一键：去重后行数必须不变"
    per_item: dict[str, int] = {}
    for row in rows:
        per_item[row["normative_item_id"]] = per_item.get(row["normative_item_id"], 0) + 1
    assert set(per_item.values()) == {gen.CONTRACT_BUILDINGS}, "每项恰 10 行，零空洞"


def test_applicable_is_three_valued_only():
    rows, _ = gen.build_rows()
    for row in rows:
        value = row["applicable"]
        assert value is True or value is False or value == gen.TRUTH_PENDING


def test_pending_bucket_is_all_unknown_pending():
    rows, _ = gen.build_rows()
    pending = [r for r in rows if r["truth_source"] == gen.TRUTH_SOURCE_PENDING]
    assert len(pending) == gen.CONTRACT_PENDING_ITEMS * gen.CONTRACT_BUILDINGS
    assert {r["applicable"] for r in pending} == {gen.TRUTH_PENDING}


def test_constant_bucket_is_constant_per_item():
    """恒常桶：同一项在 10 栋上必须同值（这正是"恒常"的定义）。"""
    rows, _ = gen.build_rows()
    by_item: dict[str, set] = {}
    for row in rows:
        if row["truth_source"] != gen.TRUTH_SOURCE_CONSTANT:
            continue
        by_item.setdefault(row["normative_item_id"], set()).add(row["applicable"])
    assert by_item, "恒常桶不该为空"
    bad = {k: v for k, v in by_item.items() if len(v) != 1}
    assert not bad, f"恒常桶内出现分化：{list(bad)[:5]}"


def test_no_fragment_scope_in_v2():
    """v2 无 `fragment` 档 —— FRG- 片段 id 逐池不同，新池上结构性不可用。"""
    rows, _ = gen.build_rows()
    assert {r["scope_type"] for r in rows} <= {"building", "component_class"}
    assert not [r for r in rows if r["scope_id"].startswith("FRG-")]


def test_deterministic_two_builds_are_byte_identical():
    truth_a, probe_a, _ = gen.build_all()
    truth_b, probe_b, _ = gen.build_all()
    assert truth_a == truth_b, "同输入两跑真值不逐字节同"
    assert probe_a == probe_b, "同输入两跑探针清单不逐字节同"


def test_no_timestamp_in_products():
    """产物里不许有时间戳 —— 带日期的字段会让「同输入重跑逐字节同」跨日失效。"""
    truth_bytes, probe_bytes, _ = gen.build_all()
    for key in ("generated_at", "timestamp", "created_at", "run_at"):
        assert key not in truth_bytes.decode("utf-8")
        assert key not in probe_bytes.decode("utf-8")


def test_pool_identity_carries_five_pool_intrinsic_anchors_and_no_code_state():
    """池身份五件套：五件齐、且**不含** code_state（自指、无不动点）。"""
    rows, _ = gen.build_rows()
    identity = rows[0]["pool_identity"]
    assert set(identity) == {
        "worldgen_run_dir", "pool_content_sha256", "generation_config_sha256",
        "sampled_building_id_member_digest", "sampled_world_id_member_digest",
    }
    assert "code_state" not in json.dumps(identity)
    assert all(r["pool_identity"] == identity for r in rows), "五件套须逐行一致"


def test_generator_source_has_no_agent_runtime_import():
    """blind 红线：生成器（及它唯一 import 的同目录脚本）源码里没有 agent runtime import。

    🔴 **这条判据是修出来的，值得留住教训**：首版写成「扫全进程 `sys.modules`，
    出现 `evo_agent_baseline.*` 即抛」。单跑本文件 28 条全绿，**一进全量 pytest
    就 18 条全红** —— 同进程里别的测试合法 import 了 agent runtime，而那与生成器
    读了什么毫无关系。那条判据在「嵌入式 import」这个人群上没有意义
    （它量的是「进程里有没有别人加载过」，不是「生成器自己有没有依赖」）。
    改成静态扫源码后，判据与进程状态无关，在任何人群上都是同一句话。
    """
    gen._assert_producer_import_graph_clean()   # 抛即失败
    gen.build_all()
    gen._assert_producer_import_graph_clean()


_CLEAN_BORROWED = (
    "import hashlib\n"
    "def pool_content_sha256(pool_dir):\n"
    "    return hashlib.sha256(b'').hexdigest()\n"
)


def _fake_scripts(tmp_path, strict_src: str, borrowed_src: str):
    (tmp_path / "generate_truth_v2.py").write_text(strict_src, encoding="utf-8")
    (tmp_path / "run_baseline_batch.py").write_text(borrowed_src, encoding="utf-8")
    return tmp_path


def test_import_graph_guard_fires_on_generator_import(tmp_path, monkeypatch):
    """变异对照 A：生成器自身**任何层级**出现 agent runtime import ⇒ 抛。"""
    monkeypatch.setattr(gen, "SCRIPT_DIR", _fake_scripts(
        tmp_path,
        "def f():\n    from evo_agent_baseline.closure import validator\n",
        _CLEAN_BORROWED))
    with pytest.raises(gen.TruthContractError, match="generate_truth_v2.py"):
        gen._assert_producer_import_graph_clean()


def test_import_graph_guard_fires_on_borrowed_module_level_import(tmp_path, monkeypatch):
    """变异对照 B：被借脚本的**模块级**出现 agent runtime import ⇒ 抛。

    模块级才是 `import` 它时真正会执行的那层 —— 那一层脏了，借它就等于加载 runtime。
    """
    monkeypatch.setattr(gen, "SCRIPT_DIR", _fake_scripts(
        tmp_path, "import json\n",
        "import evo_agent_baseline.closure\n" + _CLEAN_BORROWED))
    with pytest.raises(gen.TruthContractError, match="模块级"):
        gen._assert_producer_import_graph_clean()


def test_import_graph_guard_fires_when_borrowed_function_imports(tmp_path, monkeypatch):
    """变异对照 C：被借函数体内出现 import ⇒ 抛（调用路径可能把东西拉进来）。"""
    monkeypatch.setattr(gen, "SCRIPT_DIR", _fake_scripts(
        tmp_path, "import json\n",
        "def pool_content_sha256(pool_dir):\n"
        "    import evo_agent_baseline.closure\n"
        "    return ''\n"))
    with pytest.raises(gen.TruthContractError, match="体内出现"):
        gen._assert_producer_import_graph_clean()


def test_import_graph_guard_tolerates_lazy_import_off_the_call_path(tmp_path, monkeypatch):
    """阳性对照：被借脚本在**别的函数**里惰性 import agent runtime ⇒ **不**抛。

    这正是仓库现状（`run_baseline_batch.py` :463/:555/:905/:917-919 六处）。
    判据若不区分「会不会被执行」，就会把一个正确的现状判成违规
    —— 那种闸只会被关掉，不会被遵守。
    """
    monkeypatch.setattr(gen, "SCRIPT_DIR", _fake_scripts(
        tmp_path, "import json\n",
        "import hashlib\n"
        "def other():\n    import evo_agent_baseline.closure\n"
        "def pool_content_sha256(pool_dir):\n"
        "    return hashlib.sha256(b'').hexdigest()\n"))
    gen._assert_producer_import_graph_clean()   # 抛即失败


def test_borrowed_function_really_has_no_imports_in_repo():
    """现状核实：仓库里真实的 `pool_content_sha256` 体内确实零 import 节点。"""
    gen._assert_producer_import_graph_clean()


def test_cli_entry_runs_in_a_clean_process():
    """CLI 的进程级断言只在**干净子进程**里成立 —— 用真子进程跑一遍，断言它数出来的数。

    🔴 **这条测试的判据改过（2026-08-07 官方审核门 MF-1）**：原写法只断言
    `exit 0`，并在 docstring 里写「整条链跑完仍 exit 0，说明生成器自己确实没把
    agent runtime 拉进来」—— **那句推理不成立**：当时断言排在 `main()` 之前、
    在 t=0 就跑完了，`exit 0` 与链上加载了什么毫无关系；把断言整个删掉，
    这条测试照样绿（不可证伪 ⇒ 不是证据）。
    现在断言的是被测进程**跑完后自己数出来的模块数**，且断言排在 `main()` 之后
    （见 `gen.cli`）；配套的反向变异见 `test_cli_post_run_assertion_catches_lazy_import`。
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "generate_truth_v2.py"),
         "--dry-run", "--verify-deterministic"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stderr[-2000:]
    assert "确定性（同输入两跑逐字节比对）: 同" in result.stdout
    assert f"{gen.RUNTIME_SELF_PROOF_PREFIX}0" in result.stdout, result.stdout[-2000:]


# 注入变异驱动：在**干净**子进程里把 `agent_v1/src` 放进 `sys.path`（模拟
# `PYTHONPATH=agent_v1/src` 这条本仓日常用法），再按开关往**调用路径**上注入
# 一条惰性 import —— 这正是第 ③ 层（只查被借函数体内，不做调用图闭包）看不见的形状。
_INJECTION_DRIVER = '''# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"{scripts}")
sys.path.insert(0, r"{src}")
import generate_truth_v2 as gen

if {poison}:
    _real = gen._pool_content_sha256

    def _poisoned(pool_dir):
        import evo_agent_baseline.contracts  # noqa: F401  ← 注入的惰性 import
        return _real(pool_dir)

    gen._pool_content_sha256 = _poisoned

try:
    _code = gen.cli(["--dry-run"])
except gen.TruthContractError as exc:
    print("[前提不成立/契约破裂] {{}}".format(exc))
    sys.exit(2)
sys.exit(_code)
'''


def _run_injection_driver(tmp_path, *, poison: bool):
    driver = tmp_path / f"driver_{'poison' if poison else 'clean'}.py"
    driver.write_text(_INJECTION_DRIVER.format(
        scripts=str(SCRIPTS), src=str(REPO / "agent_v1" / "src"),
        poison="True" if poison else "False"), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(driver)], cwd=REPO,
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def test_cli_post_run_assertion_catches_lazy_import(tmp_path):
    """反向变异：调用路径上注入一条惰性 import ⇒ **跑完后**那次断言必须当场抛。

    这是 MF-1 的复现与回归：修**前**（断言只排在 `main()` 之前）同一注入下
    `main(["--dry-run"])` 返回 0、闸一声不响，跑完后进程里躺着 2 个 runtime 模块；
    修**后**跑完后那次断言当场抛、exit 2。

    ⚠️ 它同时是第 ③ 层已知边界的兜底证据：③ 只查被借函数**体内**的 import 节点、
    **不做调用图闭包**，故这种「调用路径上另一个函数惰性 import」的形状 ③ 看不见 ——
    在 **CLI 路径**上由本层兜住。（import 生成器直接调 `build_all()` 的用法不走
    `cli()`，那条路上仍没有兜底，见模块 docstring §二。）
    """
    result = _run_injection_driver(tmp_path, poison=True)
    assert result.returncode == 2, (result.returncode, result.stdout[-2000:],
                                    result.stderr[-2000:])
    combined = result.stdout + result.stderr
    assert "blind 红线（跑完后）" in combined, combined[-2000:]
    assert "evo_agent_baseline" in combined
    # 可证伪的观测数：污染时它必须 > 0（阳性对照里它是 0）
    tail = combined.split(gen.RUNTIME_SELF_PROOF_PREFIX)[-1].splitlines()[0].strip()
    assert int(tail) > 0, combined[-2000:]


def test_injection_driver_is_clean_without_the_injection(tmp_path):
    """阳性对照：同一个驱动、同样把 `agent_v1/src` 放进 `sys.path`，**不**注入 ⇒ exit 0、数为 0。

    没有这条，上一条测的可能是「驱动本身有问题」而不是「注入被抓住」。
    """
    result = _run_injection_driver(tmp_path, poison=False)
    assert result.returncode == 0, (result.stdout[-2000:], result.stderr[-2000:])
    assert f"{gen.RUNTIME_SELF_PROOF_PREFIX}0" in result.stdout, result.stdout[-2000:]


def test_guarded_open_rejects_closure_products(tmp_path):
    fake = tmp_path / "fact_pack.json"
    fake.write_text("{}", encoding="utf-8")
    with pytest.raises(gen.TruthContractError, match="blind"):
        gen._guarded_open(fake, "r", encoding="utf-8")


def test_disk_products_match_recompute():
    """盘上产物必须与重算逐字节相同（生成器 `--check` 的测试面）。"""
    if not gen.OUT_TRUTH_PATH.is_file():
        pytest.skip("truth v2 尚未落盘")
    truth_bytes, probe_bytes, _ = gen.build_all()
    assert gen.OUT_TRUTH_PATH.read_bytes() == truth_bytes
    assert gen.OUT_PROBE_PATH.read_bytes() == probe_bytes


def test_probe_manifest_registers_shared_gate_groups():
    """探针清单必须按**组**登记共轴项（换池时整组一次报警，不按项刷屏）。"""
    _, stats = gen.build_rows()
    manifest = gen.build_probe_manifest(stats)
    groups = manifest["shared_gate_axes"]["groups"]
    tiers = {g["tier"]: g["member_count"] for g in groups}
    assert tiers == {"structured_registry": 7,
                     "text_cited_both_axes": 36,
                     "building_axis_only": 21}
    # A ⊆ B（内容层 R15 断言过，这里复算一次，防清单被改坏）
    members = {g["tier"]: set(g["members"]) for g in groups}
    assert members["structured_registry"] <= members["text_cited_both_axes"]
    assert not (members["building_axis_only"] & members["text_cited_both_axes"])


def test_probe_manifest_keeps_loud_failure_expectation():
    """`registered_predicate_unresolvable_in_pool` 必须留在清单里并标必须响亮失败。

    错误注册的失败方向是「静默压掉真报警」，比不注册更坏 ⇒ 这条不许被优化掉。
    """
    _, stats = gen.build_rows()
    manifest = gen.build_probe_manifest(stats)
    loud = [i for i in manifest["registered_predicates"]["items"]
            if i.get("must_fail_loudly")]
    assert loud, "必须响亮失败的探针一条都没有 —— 清单被改坏了"
    assert any("unresolvable_in_pool" in e
               for i in loud for e in i["probe_expectation"])


# ── 变异一：删网格一格 ⇒ 网格契约抛错 ──────────────────────────────────

def test_mutation_grid_hole_raises(tmp_path, monkeypatch):
    grid = json.loads(gen.GRID_PATH.read_text(encoding="utf-8"))
    item_id = sorted(grid["grid"])[0]
    victim = sorted(grid["grid"][item_id])[0]
    del grid["grid"][item_id][victim]
    mutated = tmp_path / "final_grid_hole.json"
    mutated.write_text(json.dumps(grid, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(gen, "GRID_PATH", mutated)

    with pytest.raises(gen.TruthContractError) as excinfo:
        gen.build_rows()
    assert "空洞" in str(excinfo.value)
    assert victim in str(excinfo.value)


def test_assert_grid_contract_catches_hole_on_its_own():
    """空洞有**两层**捕获：`build_rows` 的内联检查 ＋ `_assert_grid_contract`。

    反向变异实测：拆掉 `_assert_grid_contract` 后内联检查仍会抛 —— 说明上面那条
    变异测试其实测的是内联层。故这里**单独**把 `_assert_grid_contract` 喂一份
    带洞的行，证明第二层也真的会响（不然它就是个装饰，等哪天内联层被改掉才发作）。
    """
    rows, stats = gen.build_rows()
    victim = rows[0]
    holed = [r for r in rows
             if not (r["normative_item_id"] == victim["normative_item_id"]
                     and r["building_id"] == victim["building_id"])]
    items = {r["normative_item_id"] for r in rows}
    with pytest.raises(gen.TruthContractError):
        gen._assert_grid_contract(holed, stats["building_ids"], items)


def test_mutation_grid_extra_item_raises(tmp_path, monkeypatch):
    """网格多一项 ⇒ 项数契约抛错（空洞的对称面，别只测一侧）。"""
    grid = json.loads(gen.GRID_PATH.read_text(encoding="utf-8"))
    donor = sorted(grid["grid"])[0]
    grid["grid"]["mbis.cop2023.zzz_injected.not_a_real_item"] = grid["grid"][donor]
    mutated = tmp_path / "final_grid_extra.json"
    mutated.write_text(json.dumps(grid, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(gen, "GRID_PATH", mutated)

    with pytest.raises(gen.TruthContractError, match="网格项"):
        gen.build_rows()


# ── 变异二：植入重复 (项,栋) 行 ⇒ 唯一键断言抛错 ───────────────────────

def test_mutation_duplicate_row_raises():
    rows, _ = gen.build_rows()
    poisoned = list(rows)
    poisoned.append(dict(rows[0]))      # 逐字节相同的重复行 —— v1 实测的那 4 条就是这形状
    with pytest.raises(gen.TruthContractError) as excinfo:
        gen._assert_unique_keys(poisoned)
    assert "唯一键" in str(excinfo.value)
    assert rows[0]["normative_item_id"] in str(excinfo.value)


def test_unique_key_assertion_passes_on_clean_rows():
    """阳性对照：干净行上不许误报（不然这道闸只是个恒抛的装饰）。"""
    rows, _ = gen.build_rows()
    gen._assert_unique_keys(rows)


# ── 变异三：改模板一项常量 ⇒ 对应 10 行齐变 ────────────────────────────

def test_mutation_constant_flip_changes_exactly_ten_rows(tmp_path, monkeypatch):
    baseline_rows, _ = gen.build_rows()
    partition = json.loads(gen.PARTITION_PATH.read_text(encoding="utf-8"))
    target = sorted(partition["final_buckets"]["keep_constant"])[0]

    before = {r["applicable"] for r in baseline_rows
              if r["normative_item_id"] == target}
    assert len(before) == 1, "恒常项在基线上应当 10 栋同值"
    old_value = next(iter(before))

    for item in partition["items"]:
        if item["item_id"] == target:
            item["constant_value"] = not old_value
            break
    else:                                     # pragma: no cover - 契约已保证在
        pytest.fail(f"{target} 不在 partition.items 里")

    mutated = tmp_path / "final_partition_flip.json"
    mutated.write_text(json.dumps(partition, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(gen, "PARTITION_PATH", mutated)

    flipped_rows, _ = gen.build_rows()
    assert len(flipped_rows) == len(baseline_rows)

    base_map = {(r["normative_item_id"], r["building_id"]): r["applicable"]
                for r in baseline_rows}
    changed = [key for key, value in
               {(r["normative_item_id"], r["building_id"]): r["applicable"]
                for r in flipped_rows}.items()
               if base_map[key] != value]
    assert len(changed) == gen.CONTRACT_BUILDINGS, "常量翻转必须恰好改 10 行"
    assert {k[0] for k in changed} == {target}, "只许改目标项，别的项一格不许动"
    after = {r["applicable"] for r in flipped_rows
             if r["normative_item_id"] == target}
    assert after == {not old_value}


# ── 变异四：disjoint 闸对 v2 的契约与伪造行 ────────────────────────────

@pytest.mark.skipif(not POOL_DIR.is_dir(), reason="池 v2 不在盘上")
def test_gate_contract_is_taken_from_schema_version():
    assert gate.SCHEMA_CONTRACT["applicable_normative_item_truth_v1"] == gate.CONTRACT_DISJOINT
    assert (gate.SCHEMA_CONTRACT["applicable_normative_item_truth_v2"]
            == gate.CONTRACT_TRUTH_SUBSET_POOL)


@pytest.mark.skipif(not POOL_DIR.is_dir(), reason="池 v2 不在盘上")
def test_gate_v2_subset_passes_and_v1_disjoint_passes():
    if not gen.OUT_TRUTH_PATH.is_file():
        pytest.skip("truth v2 尚未落盘")
    assert gate.main([str(POOL_DIR), "--truth-file", "v2"]) == gate.EXIT_OK
    assert gate.main([str(POOL_DIR), "--truth-file", "v1"]) == gate.EXIT_OK


@pytest.mark.skipif(not POOL_DIR.is_dir(), reason="池 v2 不在盘上")
def test_mutation_forged_out_of_pool_building_fails_gate(tmp_path):
    """伪造一条非池栋的 v2 真值行 ⇒ `真值 ⊆ 池` 不成立 ⇒ exit 1。"""
    if not gen.OUT_TRUTH_PATH.is_file():
        pytest.skip("truth v2 尚未落盘")
    forged = tmp_path / "truth_v2_forged.jsonl"
    shutil.copyfile(gen.OUT_TRUTH_PATH, forged)
    with forged.open("r", encoding="utf-8") as handle:
        first = json.loads(handle.readline())
    first["building_id"] = "BLD-HK-FORGED-NOT-IN-POOL-9999"
    with forged.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(first, ensure_ascii=False) + "\n")

    assert gate.main([str(POOL_DIR), "--truth", str(forged)]) == gate.EXIT_VIOLATION


@pytest.mark.skipif(not POOL_DIR.is_dir(), reason="池 v2 不在盘上")
def test_gate_rejects_unknown_schema(tmp_path):
    """未登记 schema 的真值 ⇒ 前提不成立，不许按缺省方向蒙混过去。"""
    weird = tmp_path / "truth_weird.jsonl"
    weird.write_text(
        json.dumps({"schema_version": "applicable_normative_item_truth_v9",
                    "building_id": "BLD-X"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        gate.main([str(POOL_DIR), "--truth", str(weird)])
    assert excinfo.value.code == gate.EXIT_PRECONDITION


# ── 阅卷器侧：显式换锚 ────────────────────────────────────────────────

def test_scorer_named_truth_table_matches_gate():
    """两个消费者认同一组名字 —— 否则会出现「批前闸看 v1、阅卷看 v2」。"""
    scorer = _load("score_clause_coverage")
    assert scorer.NAMED_TRUTH_FILES == gate.NAMED_TRUTH_FILES


def test_scorer_default_truth_is_still_v1():
    """缺省不许跟着换锚：旧命令行必须继续阅 v1。"""
    scorer = _load("score_clause_coverage")
    parser_default = scorer.NAMED_TRUTH_FILES["v1"]
    assert parser_default.endswith("applicable_normative_item_truth_v1.jsonl")
    truth_v1 = REPO / parser_default
    if not truth_v1.is_file():
        pytest.skip("v1 真值不在盘上")
    items, schema = scorer._load_jsonl(truth_v1)
    assert schema == "applicable_normative_item_truth_v1"
    assert items


def test_scorer_rejects_schema_mismatch_against_selection():
    """选了 v2 却指到 v1 文件 ⇒ 必须抛，不许按其中一个猜。"""
    scorer = _load("score_clause_coverage")
    truth_v1 = REPO / scorer.NAMED_TRUTH_FILES["v1"]
    if not truth_v1.is_file():
        pytest.skip("v1 真值不在盘上")
    with pytest.raises(ValueError, match="换锚必须显式"):
        scorer._load_jsonl(truth_v1, "applicable_normative_item_truth_v2")


def test_scorer_three_state_caliber_unchanged_for_v2():
    """三值判据对 v2 逐字通用（`is True` / `is False` / 字符串常量）。"""
    scorer = _load("score_clause_coverage")
    assert scorer._truth_applicable_state({"applicable": True}) == "applicable"
    assert scorer._truth_applicable_state({"applicable": False}) == "not_applicable"
    assert scorer._truth_applicable_state(
        {"applicable": "unknown_pending"}) == "pending"
    with pytest.raises(ValueError):
        scorer._truth_applicable_state({"applicable": "yes"})
