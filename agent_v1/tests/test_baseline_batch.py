"""baseline 批跑驱动纯逻辑与聚合器单测。"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]   # agent_v1/
SCRIPTS = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import aggregate_baseline_batch as aggregate_module  # noqa: E402
import run_baseline_batch as batch_module  # noqa: E402
from aggregate_baseline_batch import (  # noqa: E402
    add_completion,
    aggregate_batch,
    aggregate_reports,
    render_markdown,
)
from run_baseline_batch import (  # noqa: E402
    anchor_mismatches,
    build_command,
    check_pool_health,
    child_environment,
    classify_run,
    queue_verdict_distribution,
    require_isolated_database,
    run_profile,
    select_buildings,
    should_skip,
    verdict_distribution,
)


def test_database_guard_has_no_main_database_bypass():
    with pytest.raises(ValueError):
        require_isolated_database(None)
    with pytest.raises(ValueError):
        require_isolated_database("neo4j")
    assert require_isolated_database("exp_008_isolated") == "exp_008_isolated"


def test_building_selection_sorted_count_and_explicit_order():
    available = ["BLD-03", "BLD-01", "BLD-02", "BLD-02"]
    assert select_buildings(available, 2) == ["BLD-01", "BLD-02"]
    assert select_buildings(available, 30, ["BLD-03,BLD-01"]) == ["BLD-03", "BLD-01"]
    with pytest.raises(ValueError):
        select_buildings(available, 30, ["BLD-99"])


def test_health_gate_and_full_distribution():
    distribution = verdict_distribution(["pass", "fail", "unknown", "pass", None])
    assert distribution == {"<missing>": 1, "fail": 1, "pass": 2, "unknown": 1}
    assert check_pool_health({"pass": 3, "fail": 7}) == (True, 0.3)
    assert check_pool_health({"pass": 1, "fail": 9}) == (False, 0.1)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "baseline_batch"


# 真函数引用在 stub 之前抓住，供下面专门测试直调（stub 只挡 main 路径）
_REAL_RESOLVE_BUNDLE = batch_module.resolve_applicability_bundle
_REAL_CODE_STATE = batch_module.code_state_sha256
_REAL_PREFLIGHT = batch_module.preflight
_REAL_DERIVED_RELEASE = batch_module.ensure_rulecard_derived_release
_REAL_RULECARD_CONTRACT = batch_module.ensure_rulecard_contract


@pytest.fixture(autouse=True)
def stub_applicability_bundle(monkeypatch):
    """挡掉 main() 里的 bundle 解析——本文件测的是批驱动其余逻辑（劈锚/契约/工具调用门）。

    不在生产代码里给资产根目录开测试后门：解析本身 fail-closed 是判定面安全语义
    （缺 bundle 会静默退化为"一律不早退"），它由下面三个专门测试直调真函数覆盖。
    """
    monkeypatch.setattr(batch_module, "resolve_applicability_bundle", lambda pool_dir: {
        "EVO_APPLICABILITY_BUNDLE": str(pool_dir / "applicability_bundle_v1.json"),
        "EVO_APPLICABILITY_BUNDLE_SHA256": "stub-sha-for-tests",
        "EVO_APPLICABILITY_BUNDLE_RELATIVE_PATH":
            "agent_v1/experiments/_applicability_assets/test/applicability_bundle_v1.json",
        "EVO_APPLICABILITY_WORLDGEN_DIR": str(pool_dir),
    })
    # 同理挡掉外部前置探测(密码/Neo4j/Ollama/显存)——单测环境本就没有这些服务，
    # 真行为由 test_preflight_* 直调真函数覆盖。
    monkeypatch.setattr(batch_module, "preflight", lambda llm, **_kwargs: [])
    monkeypatch.setattr(batch_module, "ensure_rulecard_derived_release", lambda: None)
    monkeypatch.setattr(batch_module, "ensure_rulecard_contract", lambda **kwargs: [])
    # 代码状态指纹要真跑 `git status`：测试里 subprocess 被 stub 成返回 str，
    # 且 fake_run 会把 git 调用误当成建筑子进程。它的真实行为由下面
    # test_code_state_* 三个专测直调真函数覆盖。
    monkeypatch.setattr(batch_module, "code_state_sha256", lambda: {
        "code_state_sha256": "stub-code-state",
        "git_commit": "commit",
        "dirty_path_count": 0,
        "workspace_clean": True,
    })


def _write_bundle(asset_dir: Path, *, worldgen_name: str | None,
                  sha: str | None = "deadbeef") -> Path:
    asset_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {"version": "applicability_bundle.v1"}
    if worldgen_name is not None:
        payload["worldgen_run_dir"] = worldgen_name
    if sha is not None:
        payload["bundle_sha256"] = sha
    path = asset_dir / "applicability_bundle_v1.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_resolve_bundle_returns_pointer_triplet(work_path, monkeypatch):
    """正常路径：返回三元指针，sha 取自 bundle 自身。"""
    pool = work_path / "gen_seed_777"
    pool.mkdir()
    monkeypatch.setattr(batch_module, "AGENT_ROOT", work_path)
    # 约定落点：AGENT_ROOT/experiments/_applicability_assets/<池目录名>/
    _write_bundle(work_path / "experiments" / "_applicability_assets" / "gen_seed_777",
                  worldgen_name="gen_seed_777", sha="abc123")
    pointer = _REAL_RESOLVE_BUNDLE(pool)
    assert pointer["EVO_APPLICABILITY_BUNDLE_SHA256"] == "abc123"
    # 必须是**目录名**：runtime 拿它跟 bundle 的 `worldgen_run_dir` 字段直接相等比，
    # 而那个字段存的是目录名。本行原来断言 `str(pool)`（绝对路径）——那是把 2026-07-25
    # 的真 bug 当成正确行为写死了，测试与实现出自同一个误解，于是一起绿。
    assert pointer["EVO_APPLICABILITY_WORLDGEN_DIR"] == "gen_seed_777"
    assert pointer["EVO_APPLICABILITY_BUNDLE"].endswith("applicability_bundle_v1.json")
    assert pointer["EVO_APPLICABILITY_BUNDLE_RELATIVE_PATH"].endswith(
        "experiments/_applicability_assets/gen_seed_777/applicability_bundle_v1.json"
    )



def test_applicability_replay_contract_freezes_recipe_pool_and_relative_path(tmp_path):
    pool = tmp_path / "gen_seed_777"
    pointer = {
        "EVO_APPLICABILITY_BUNDLE_SHA256": "sha-x",
        "EVO_APPLICABILITY_BUNDLE_RELATIVE_PATH":
            "agent_v1/experiments/_applicability_assets/gen_seed_777/applicability_bundle_v1.json",
    }

    contract = batch_module.applicability_replay_contract(pool, pointer, "pool-sha")

    assert contract["world_pool"] == {
        "path": str(pool), "directory_name": "gen_seed_777", "content_sha256": "pool-sha"
    }
    assert contract["bundle_relative_path"].startswith("agent_v1/")
    assert contract["bundle_sha256"] == "sha-x"
    assert [step["entrypoint"] for step in contract["generator_steps"]] == [
        "agent_v1/scripts/check_rulecard_derived_release.py",
        "agent_v1/scripts/check_rulecard_derived_release.py",
        "agent_v1/scripts/build_w0_fragment_identity_manifest.py",
        "agent_v1/scripts/build_applicability_bundle.py",
        "agent_v1/scripts/check_applicability_release.py",
    ]
    assert contract["generator_steps"][2]["arguments"] == [str(pool)]


def test_applicability_replay_contract_participates_in_anchor_split():
    old = {"applicability_replay": {"bundle_relative_path": "old.json"}}
    new = {"applicability_replay": {"bundle_relative_path": "new.json"}}
    assert "applicability_replay" in batch_module.anchor_mismatches(old, new)


def test_rulecard_derived_release_failure_is_explicit(monkeypatch):
    import check_rulecard_derived_release as release

    monkeypatch.setattr(release, "release_problems", lambda: ["缺失：x.json"])
    with pytest.raises(ValueError, match="(?s)派生链未发布.*缺失：x.json"):
        _REAL_DERIVED_RELEASE()

def test_driver_env_is_accepted_by_real_loader():
    """🔴 端到端契约闸:驱动产出的环境值必须能被**真实** `load_bundle` 接受。

    为什么单独焊这条(2026-07-25 血泪):上面三个测试只验了解析器**自身**的行为,
    从没验证过它的输出**能不能被真实消费者用**。结果我把
    `EVO_APPLICABILITY_WORLDGEN_DIR` 设成了绝对路径,而 runtime 拿它跟 bundle 里的
    **目录名**直接相等比 → 每栋都 `worldgen_dir_mismatch` → bundle 禁用 → 组件结构
    早退全关 → 判定面静默移动(义务多出约 4%),12 项发布门禁和 2588 个单测**全绿**,
    跑了 8 栋才被「新批 vs 旧批逐栋对账」抓出来。

    本测试用仓库里真实的 bundle 与池,走真实 loader,故任何格式漂移都会当场炸。
    """
    pool = (PROJECT_ROOT / "experiments" / "qa_reports"
            / "_reanchor_50x1_seed301" / "gen_seed_301")
    asset = (PROJECT_ROOT / "experiments" / "_applicability_assets" / pool.name
             / "applicability_bundle_v1.json")
    if not (pool.is_dir() and asset.is_file()):
        pytest.skip("本机无 seed301 池或未生成 bundle(派生资产不入库)")

    env = _REAL_RESOLVE_BUNDLE(pool)

    from evo_agent_baseline.closure.applicability_v3 import (
        load_bundle, rulecard_content_digests,
    )
    # 2026-07-27 P1-B:时效参数改必传，本闸也必须按**生产调用形态**传，
    # 否则它验的是一个生产里不存在的宽松加载器。
    pack_sha, card_shas = rulecard_content_digests(PROJECT_ROOT.parent)
    bundle, reason = load_bundle(
        env["EVO_APPLICABILITY_BUNDLE"],
        env["EVO_APPLICABILITY_BUNDLE_SHA256"],
        repo_root=PROJECT_ROOT.parent,
        worldgen_run_dir=env["EVO_APPLICABILITY_WORLDGEN_DIR"],
        rulecard_pack_sha256=pack_sha, card_content_shas=card_shas,
    )
    assert reason is None, f"驱动产出的环境值被真实 loader 拒绝:{reason}"
    assert bundle is not None and bundle.card_targets, "bundle 空载=早退恒关"


def test_preflight_blocks_missing_password(monkeypatch):
    """缺密码必须**当场**拒跑——这是"一键跑批"验收的实质。

    2026-07-25 实证:此前零前置校验,子进程缺 `EVO_AGENT_NEO4J_PASSWORD` 时驱动
    照样发批,**30 栋每栋 2 秒失败、跑完整整 30 栋才报 0/30**。
    """
    monkeypatch.delenv("EVO_AGENT_NEO4J_PASSWORD", raising=False)
    issues = _REAL_PREFLIGHT(llm=False)
    assert any("EVO_AGENT_NEO4J_PASSWORD" in i for i in issues)


def test_main_actually_calls_preflight_and_refuses(work_path, monkeypatch, capsys):
    """🔴 接线闸:`main()` 必须真的调用 preflight——**本文件其余测试把它 stub 成空操作**。

    为什么必须单独焊(2026-07-25 用户质问"安全机制该不该跳过"后补):autouse fixture 为了
    让单测能在无库无模型环境跑,把 `preflight` / `resolve_applicability_bundle` /
    `code_state_sha256` 三个**安全机制全换成了空操作**。各自都有直调真函数的专测,但
    **没有任何测试验证 `main()` 真的调用了它们**——把 main 里那行删掉,全套测试照样绿。

    本测试反其道:恢复真 preflight、造一个必然不满足的前置(无密码),断言 main 拒跑。
    删掉接线即失败。
    """
    monkeypatch.setattr(batch_module, "preflight", _REAL_PREFLIGHT)
    # 库守卫必须先放行，否则 rc=2 会来自它而与 preflight 无关——
    # 初版就栽在这里：变异测试（删掉接线）时测试照样通过，因为断言认的是别的原因。
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "s25smoke")
    monkeypatch.delenv("EVO_AGENT_NEO4J_PASSWORD", raising=False)
    pool = work_path / "gen_seed_301"
    pool.mkdir()

    rc = batch_module.main([
        "--worldgen-run-dir", str(pool),
        "--count", "1",
        "--batch-root", str(work_path / "batch"),
    ])
    assert rc == 2, "前置不满足时 main 必须非零退出(2 = 参数/前置错)"
    captured = capsys.readouterr()
    assert "开跑前置未就绪" in (captured.err + captured.out), (
        "rc=2 必须来自 preflight 而不是别的守卫——否则删掉接线也能通过"
    )
    assert not (work_path / "batch" / "buildings").exists(), \
        "拒跑时不该已经建出批次目录——说明前置检查在建目录之后才跑"


def test_ensure_rulecard_contract_on_real_bundle_lists_exactly_known_exemptions():
    """真实卡包：契约违规必须与豁免表逐条相等（一条不多、一条不少）。

    同时证明 `collect_rulecard_bundle_violations` 一次列出全部，不是遇错即停。
    2026-08-07 卡包合流事务后基线 3 → **16**（13 张裁定删 trigger 卡的空
    slot_role_map 属机械后果，见 `重核准记录_卡包合流_20260807.md`）。
    """
    violations = _REAL_RULECARD_CONTRACT()
    assert len(violations) == 18, violations  # 2026-08-08 残差57A：+2（s6_2_4/s5_3_1 删 trigger 后空 map，重核准记录_残差57三卡_20260808.md）
    assert set(violations) == set(batch_module.RULECARD_CONTRACT_EXEMPTIONS)


def test_ensure_rulecard_contract_rejects_unexpected_violation(monkeypatch):
    """变异闸：豁免表少一条 → 拒跑。证明闸不是「有豁免表就放行」。"""
    trimmed = dict(batch_module.RULECARD_CONTRACT_EXEMPTIONS)
    dropped = next(iter(trimmed))
    del trimmed[dropped]
    with pytest.raises(ValueError) as excinfo:
        _REAL_RULECARD_CONTRACT(exemptions=trimmed)
    assert dropped in str(excinfo.value)
    assert "非豁免违规" in str(excinfo.value)


def test_ensure_rulecard_contract_rejects_stale_exemption():
    """变异闸：豁免表多一条幽灵 → 拒跑。证明过期豁免不能永驻。"""
    bloated = dict(batch_module.RULECARD_CONTRACT_EXEMPTIONS)
    ghost = "ghost.card.slot_role_map must not be empty"
    bloated[ghost] = {"why": "假豁免", "lift_when": "立刻删"}
    with pytest.raises(ValueError) as excinfo:
        _REAL_RULECARD_CONTRACT(exemptions=bloated)
    assert ghost in str(excinfo.value)
    assert "豁免已过期" in str(excinfo.value)


def test_main_actually_calls_rulecard_contract_and_refuses(work_path, monkeypatch, capsys):
    """🔴 接线闸：`main()` 必须真的调用 `ensure_rulecard_contract`。

    autouse 把它 stub 成空操作；本条恢复真函数并故意掏空豁免表，断言拒跑。
    把 main 里那行删掉 → 本测试绿不了。
    """
    monkeypatch.setattr(batch_module, "ensure_rulecard_contract", _REAL_RULECARD_CONTRACT)
    monkeypatch.setattr(batch_module, "RULECARD_CONTRACT_EXEMPTIONS", {})
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "s25smoke")
    # preflight 仍 stub；派生发布仍 stub——只让契约闸成为拒跑原因。
    pool = work_path / "gen_seed_301"
    pool.mkdir()
    # read_pool 会在契约之后才跑；契约先炸即可。
    rc = batch_module.main([
        "--worldgen-run-dir", str(pool),
        "--count", "1",
        "--batch-root", str(work_path / "batch"),
    ])
    assert rc == 2
    captured = capsys.readouterr()
    assert "卡包契约" in (captured.err + captured.out) or "slot_role_map" in (
        captured.err + captured.out
    ), (captured.err + captured.out)
    assert not (work_path / "batch" / "buildings").exists()


def test_preflight_checks_model_resident_in_vram(monkeypatch):
    """满血档必须查模型在显存——size_vram=0 是静默 CPU 回退，慢约 10 倍。"""
    import inspect
    src = inspect.getsource(_REAL_PREFLIGHT)
    assert "/api/ps" in src and "size_vram" in src, "须探测显存驻留，不能只查服务活着"
    assert "if not llm:" in src, "地板档不该被 LLM 前置卡住"


def test_think_off_pinned_for_local_ollama(monkeypatch):
    """本地 Ollama 的满血档必须由驱动下发关思考模式,不吃外壳残留。

    2026-07-25 实证:外壳忘了 export `EVO_AGENT_LLM_THINK_OFF=1`,qwen3.5 推理模型
    输出全进 `reasoning`、`content` 为空 → `llm_forced_finalize` 3 栋 → **30 栋(全部)**,
    A 门 30/30 → 27/30,绑定分母 960 → 429。而判定层是确定性的、完全正常,
    **逐栋对账全绿也照不出来**,只有 LLM 审计那一行露了馅。
    """
    monkeypatch.delenv("EVO_AGENT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("EVO_AGENT_LLM_THINK_OFF", raising=False)
    assert batch_module.resolve_think_off() == "1"

    bundle = {"EVO_APPLICABILITY_BUNDLE": "/tmp/b.json",
              "EVO_APPLICABILITY_BUNDLE_SHA256": "sha-x",
              "EVO_APPLICABILITY_WORLDGEN_DIR": "gen_seed_1"}
    env = batch_module.child_environment("v4", bundle, batch_module.resolve_think_off())
    assert env["EVO_AGENT_LLM_THINK_OFF"] == "1"


def test_think_off_not_forced_for_remote_endpoint(monkeypatch):
    """云端端点不得强开:think_off 走 Ollama 原生 /api/chat,对云端是打错端点。"""
    monkeypatch.setenv("EVO_AGENT_LLM_BASE_URL", "https://api.openai.com/v1")
    assert batch_module.resolve_think_off() is None


def test_silent_degradation_family_is_pinned_and_anchored(monkeypatch):
    """「关键配置静默退化」族的成员必须**驱动下发 + 记实际值 + 参与劈锚**，三缺一不可。

    2026-07-25 主动排查所得(此前该族已咬三次:bundle 世界目录格式 / role-roles /
    think_off)。`num_ctx` 有前科——默认 4096 会静默截断对话前端(系统提示词与提交
    契约正在那里)，是 EXP-015 四病灶之一。
    """
    monkeypatch.delenv("EVO_AGENT_LLM_NUM_CTX", raising=False)
    monkeypatch.delenv("EVO_AGENT_LLM_BASE_URL", raising=False)

    # ① 驱动下发:外壳没设也必须有
    pinned = batch_module.resolve_llm_runtime_env()
    assert pinned["EVO_AGENT_LLM_NUM_CTX"] == "16384", "num_ctx 未被驱动钉死"
    assert pinned["EVO_AGENT_LLM_BASE_URL"]

    bundle = {"EVO_APPLICABILITY_BUNDLE": "/tmp/b.json",
              "EVO_APPLICABILITY_BUNDLE_SHA256": "sha-x",
              "EVO_APPLICABILITY_WORLDGEN_DIR": "gen_seed_1"}
    env = batch_module.child_environment("v4", bundle, "1")
    assert env["EVO_AGENT_LLM_NUM_CTX"] == "16384"

    # ② 参与劈锚:换了就该拒跑，不许混批
    for key in ("num_ctx", "llm_base_url", "max_tool_iterations"):
        base = {"environment": {key: "a"}}
        changed = {"environment": {key: "b"}}
        assert key in batch_module.anchor_mismatches(base, changed), \
            f"{key} 变化未劈锚——续跑换它会静默混两种口径"


def test_bundle_disabled_run_is_failed(work_path):
    """bundle 未加载的 run 必须判废——早退全关 = 判定面已静默移动。

    2026-07-25 实证:世界目录格式不符导致 bundle 全批禁用，整批多出 2~10% 义务，
    **12 项发布门禁与 2588 单测全绿、逐栋计数也自洽**，跑了 8 栋才被跨批对账抓到。
    """
    run_dir = work_path / "runs" / "CAR-x"
    run_dir.mkdir(parents=True)
    (run_dir / "run_audit.json").write_text(json.dumps({
        "llm_tool_call_count": 4,
        "applicability_bundle_loaded": False,
        "applicability_bundle_disabled_reason": "worldgen_dir_mismatch",
    }), encoding="utf-8")
    reason = batch_module.llm_tool_call_failure(work_path)
    assert reason and reason.startswith("bundle_disabled:"), \
        "bundle 禁用未判废——这种批会带着移动过的判定面混进结果"
    assert "worldgen_dir_mismatch" in reason, "原因码要带上，否则事后无法诊断"

    # 正常 run 不误伤
    (run_dir / "run_audit.json").write_text(json.dumps({
        "llm_tool_call_count": 4, "applicability_bundle_loaded": True,
    }), encoding="utf-8")
    assert batch_module.llm_tool_call_failure(work_path) is None


def test_code_state_scope_excludes_notes(monkeypatch):
    """`code_state` 作用域只覆盖运行时路径:改笔记不该劈锚。

    初版覆盖整个工作树，2026-07-25 实测跑批期间改了几次 `团队文档/` 的计划文件就
    把锚劈了(`77918e1f`→`89f81a4c`)，而 `agent_v1/` 零改动——锚过敏等于没锚。
    """
    scope = batch_module.CODE_STATE_SCOPE
    assert "agent_v1/src/" in scope and "agent_v1/scripts/" in scope
    assert "agent_v1/regulations/" in scope, "法规卡与派生资产是输入，必须在作用域内"
    assert not any(s.startswith("团队文档") for s in scope), "笔记不该进作用域"
    # 作用域必须进清单:换过作用域的两次跑批不可比，读清单的人要能看出来
    # (直调真函数——autouse 的 stub 挡的是 main() 路径)
    assert "scope" in _REAL_CODE_STATE()


def test_think_off_participates_in_anchor_check():
    """think_off 变化必须劈锚——它不动判定层但决定叙述层能否产出。"""
    base = {"environment": {"think_off": "1"}}
    changed = {"environment": {"think_off": None}}
    assert "think_off" in batch_module.anchor_mismatches(base, changed)


def test_resolve_bundle_missing_refuses_to_run(work_path, monkeypatch):
    """fail-closed 第一条：bundle 不存在必须拒跑，不得静默退化为「一律不早退」。"""
    pool = work_path / "gen_seed_888"
    pool.mkdir()
    monkeypatch.setattr(batch_module, "AGENT_ROOT", work_path)
    with pytest.raises(SystemExit) as excinfo:
        _REAL_RESOLVE_BUNDLE(pool)
    assert "不存在" in str(excinfo.value)


def test_resolve_bundle_world_mismatch_refuses_to_run(work_path, monkeypatch):
    """fail-closed 第二条：bundle 绑定的世界目录与本批不符必须拒跑（片段身份来自别的世界）。"""
    pool = work_path / "gen_seed_999"
    pool.mkdir()
    monkeypatch.setattr(batch_module, "AGENT_ROOT", work_path)
    _write_bundle(work_path / "experiments" / "_applicability_assets" / "gen_seed_999",
                  worldgen_name="gen_seed_301")
    with pytest.raises(SystemExit) as excinfo:
        _REAL_RESOLVE_BUNDLE(pool)
    assert "世界目录与本批不符" in str(excinfo.value)


def test_resolve_bundle_without_sha_refuses_to_run(work_path, monkeypatch):
    """fail-closed 第三条：缺 bundle_sha256 则判据锚无从冻结，拒跑。"""
    pool = work_path / "gen_seed_555"
    pool.mkdir()
    monkeypatch.setattr(batch_module, "AGENT_ROOT", work_path)
    _write_bundle(work_path / "experiments" / "_applicability_assets" / "gen_seed_555",
                  worldgen_name="gen_seed_555", sha=None)
    with pytest.raises(SystemExit) as excinfo:
        _REAL_RESOLVE_BUNDLE(pool)
    assert "bundle_sha256" in str(excinfo.value)


def test_code_state_fingerprint_is_deterministic_and_sensitive(tmp_path):
    """代码状态指纹必须①确定性②对源码改动敏感——否则它不构成锚。

    为什么要这个锚(2026-07-25):三锚里的 commit 在**脏工作区下是空头支票**。
    实证:重锚批清单记 `355d2d5`,而该 commit 不含当时实际运行的 v3 判据代码。
    """
    first = _REAL_CODE_STATE()
    assert set(first) == {"code_state_sha256", "git_commit", "scope",
                          "dirty_path_count", "workspace_clean"}
    assert len(first["code_state_sha256"]) == 64
    assert _REAL_CODE_STATE() == first, "同一状态两次必须一致"

    probe = batch_module.REPO_ROOT / "agent_v1" / "src" / "evo_agent_baseline" \
        / "closure" / "validator.py"
    original = probe.read_bytes()
    try:
        probe.write_bytes(original + b"\n# fingerprint probe\n")
        changed = _REAL_CODE_STATE()
    finally:
        probe.write_bytes(original)
    assert changed["code_state_sha256"] != first["code_state_sha256"], (
        "改源码不改指纹 = 锚失效")
    assert _REAL_CODE_STATE()["code_state_sha256"] == \
        first["code_state_sha256"], "还原后指纹必须回到原值"


def test_code_state_participates_in_anchor_mismatch():
    """代码状态锚必须参与劈锚:commit 相同但工作区代码变了，续跑不得静默混批。"""
    base = {"worldgen_run_dir": "p", "git_commit": "c", "building_ids": ["B1"],
            "pool_content_sha256": "s",
            "code_state": {"code_state_sha256": "aaa"}}
    same = dict(base)
    assert batch_module.anchor_mismatches(base, same) == []

    drifted = dict(base, code_state={"code_state_sha256": "bbb"})
    assert "code_state_sha256" in batch_module.anchor_mismatches(base, drifted)


def test_sealed_code_state_resolution_prefers_cli_and_normalises():
    """封存值解析:命令行优先于环境变量;大小写与空白归一;两处都空 = 不启用本闸。"""
    env = {batch_module.SEALED_CODE_STATE_ENV: "b" * 64}
    assert batch_module.resolve_sealed_code_state("A" * 64, env) == "a" * 64
    assert batch_module.resolve_sealed_code_state(None, env) == "b" * 64
    assert batch_module.resolve_sealed_code_state("  " + "c" * 64 + " ", {}) == "c" * 64
    assert batch_module.resolve_sealed_code_state(None, {}) is None
    assert batch_module.resolve_sealed_code_state("   ", {}) is None


def test_sealed_code_state_gate_passes_only_on_exact_match():
    """开跑前硬闸:声明值与实测逐位相同才放行,不同即拦,且报文要同时给出两个值。

    不声明 = 不启用(既有地板批/试验批不受影响),这一支必须仍为空清单——
    否则本闸会把所有历史调用姿势一次性拦死。
    """
    observed = {"code_state_sha256": "a" * 64, "git_commit": "c" * 40,
                "dirty_path_count": 3, "workspace_clean": False}
    assert batch_module.sealed_code_state_problems(None, observed) == []
    assert batch_module.sealed_code_state_problems("a" * 64, observed) == []

    drifted = batch_module.sealed_code_state_problems("b" * 64, observed)
    assert len(drifted) == 1
    assert "封存已失效" in drifted[0]
    assert "a" * 64 in drifted[0] and "b" * 64 in drifted[0], \
        "报文必须同时给出封存值与实测值，否则读的人无法判断该回退还是该重封存"


def test_sealed_code_state_gate_rejects_malformed_seal():
    """形态错的封存值必须当场拒跑,不许当成「不启用」悄悄放行。

    这是本闸最容易被绕过的口子:传个截断值或带 `sha256:` 前缀,若按「不等于就报错」
    去实现，读的人会以为闸开着；若按「解析失败就当没传」去实现，闸直接静默失效。
    """
    observed = {"code_state_sha256": "a" * 64}
    for bad in ("a" * 63, "a" * 65, "sha256:" + "a" * 64, "z" * 64):
        problems = batch_module.sealed_code_state_problems(bad, observed)
        assert len(problems) == 1 and "64 位十六进制" in problems[0], bad


def test_main_actually_wires_sealed_code_state_gate(work_path, monkeypatch, capsys):
    """🔴 接线闸:`main()` 必须真的调用封存值硬闸,并且拦在任何生成动作之前。

    与 `test_main_actually_calls_preflight_and_refuses` 同形状——纯函数测试证明闸本身
    会红，但**证明不了 main 调用了它**。本测试给一个必然不符的封存值（autouse fixture
    把 `code_state_sha256` stub 成 `stub-code-state`），断言 main 非零退出、报文里是
    封存值那条原因、且批目录一个字节都没落。
    """
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "s25smoke")
    pool = work_path / "gen_seed_301"
    pool.mkdir()

    rc = batch_module.main([
        "--worldgen-run-dir", str(pool),
        "--count", "1",
        "--batch-root", str(work_path / "batch"),
        "--sealed-code-state", "a" * 64,
    ])
    assert rc == 2, "封存值不符时 main 必须非零退出"
    captured = capsys.readouterr()
    combined = captured.err + captured.out
    assert "封存已失效" in combined, \
        "rc=2 必须来自封存值硬闸而不是别的守卫——否则删掉接线也能通过"
    assert not (work_path / "batch").exists(), \
        "拒跑时不该已经建出批目录——说明闸没有排在生成动作之前"


def test_sealed_code_state_lands_in_manifest(work_path, monkeypatch):
    """过闸的封存值必须写进批清单,不声明时留 null——清单里看得出这批走没走硬闸。"""
    batch_root = work_path / "batch"
    sealed = "d" * 64
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "test_database")
    monkeypatch.setenv(batch_module.SEALED_CODE_STATE_ENV, sealed)
    monkeypatch.setattr(batch_module, "code_state_sha256", lambda: {
        "code_state_sha256": sealed, "git_commit": "commit",
        "dirty_path_count": 0, "workspace_clean": True,
        "scope": ["agent_v1/src/"]})
    monkeypatch.setattr(batch_module, "read_pool", lambda _p: (
        ["B1"], {"fail": 7, "pass": 3}, {"B1": "W1"},
        {"W1": ["pass"] * 3 + ["fail"] * 7}))
    monkeypatch.setattr(batch_module, "git_commit", lambda: "commit")

    def fake_run(command, **kwargs):
        if "--output-dir" not in command:
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "runs" / "R1").mkdir(parents=True)
        (output_dir / "eval_report.json").write_text("{}", encoding="utf-8")
        (output_dir / "runs" / "R1" / "run_audit.json").write_text(
            json.dumps({"llm_tool_call_count": 3}), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)
    monkeypatch.setattr(aggregate_module, "aggregate_batch", lambda _root: {
        "completion": {"completed_count": 1, "failed_count": 0}})

    batch_module.main([
        "--worldgen-run-dir", str(work_path / "pool"),
        "--batch-root", str(batch_root),
    ])
    manifest = json.loads(
        (batch_root / "batch_manifest.json").read_text(encoding="utf-8"))
    assert manifest["code_state"]["sealed_code_state_sha256"] == sealed
    assert manifest["code_state"]["code_state_sha256"] == sealed


@pytest.fixture
def work_path():
    root = Path(__file__).parent / ".baseline_batch_test_tmp"
    root.mkdir(exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        resolved = path.resolve()
        if resolved.parent == root.resolve():
            shutil.rmtree(resolved)
        try:
            root.rmdir()
        except OSError:
            pass


def test_resume_skip_requires_completed_and_eval_report():
    output = FIXTURE_ROOT / "B1"
    latest = {"BLD-01": {"status": "completed"}}
    assert not should_skip("BLD-01", latest, FIXTURE_ROOT / "missing")
    latest = {"B1": {"status": "completed"}}
    assert should_skip("B1", latest, output)
    latest["B1"]["status"] = "failed"
    assert not should_skip("B1", latest, output)


def test_anchor_validation_covers_commit_pool_cohort_and_database():
    base = {"git_commit": "a", "worldgen_run_dir": "C:/pool", "building_ids": ["B1"],
            "environment": {"neo4j_database": "exp_a"}}
    assert anchor_mismatches(base, dict(base)) == []
    changed = {**base, "git_commit": "b", "worldgen_run_dir": "C:/other",
               "building_ids": ["B2"],
               "environment": {"neo4j_database": "exp_b"}}
    assert anchor_mismatches(base, changed) == [
        "worldgen_run_dir", "git_commit", "building_ids", "neo4j_database"]


def test_build_command_wipe_then_skip_ingest_policy(work_path):
    wipe = build_command("B1", work_path / "pool", work_path / "out", False, True)
    skip = build_command("B2", work_path / "pool", work_path / "out2", True, False)
    assert "--wipe" in wipe and "--skip-ingest" not in wipe and "--llm" not in wipe
    assert "--skip-ingest" in skip and "--wipe" not in skip and "--llm" in skip


def test_llm_tool_call_zero_or_missing_fails_and_is_not_skipped(work_path):
    for name, audit, expected_reason in (
        ("zero", {"llm_tool_call_count": 0}, "tool_call_zero"),
        ("missing", {"llm_turns": [{"tool_call_count": 1}]}, "tool_call_missing"),
    ):
        output = work_path / name
        (output / "runs" / "R1").mkdir(parents=True)
        (output / "eval_report.json").write_text("{}", encoding="utf-8")
        (output / "runs" / "R1" / "run_audit.json").write_text(
            json.dumps(audit), encoding="utf-8")
        status, reason = classify_run(0, True, True, output)
        assert (status, reason) == ("failed", expected_reason)
        assert not should_skip(name, {name: {"status": status, "reason": reason}}, output)


def test_floor_run_does_not_apply_tool_call_gate(work_path):
    output = work_path / "floor"
    output.mkdir()
    assert classify_run(0, True, False, output) == ("completed", None)


@pytest.mark.parametrize(("audit", "expected_reason"), [
    ({"llm_tool_call_count": 0}, "tool_call_zero"),
    ({"llm_turns": [{"tool_call_count": 1}]}, "tool_call_missing"),
])
def test_llm_main_writes_tool_call_failure_reason(
        work_path, monkeypatch, audit, expected_reason):
    batch_root = work_path / "batch"
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "test_database")
    monkeypatch.setattr(batch_module, "read_pool", lambda _path: (
        ["B1"], {"fail": 7, "pass": 3}, {"B1": "W1"},
        {"W1": ["pass"] * 3 + ["fail"] * 7}))
    monkeypatch.setattr(batch_module, "git_commit", lambda: "commit")

    def fake_run(command, **_kwargs):
        if "--output-dir" not in command:
            # 消费者门(A/B)子进程调用(2026-07-23 正式入口自动跑门):桩过
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "runs" / "R1").mkdir(parents=True)
        (output_dir / "eval_report.json").write_text("{}", encoding="utf-8")
        (output_dir / "runs" / "R1" / "run_audit.json").write_text(
            json.dumps(audit), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)
    monkeypatch.setattr(aggregate_module, "aggregate_batch", lambda _root: {
        "completion": {"completed_count": 0, "failed_count": 1}})

    result = batch_module.main([
        "--worldgen-run-dir", str(work_path / "pool"),
        "--batch-root", str(batch_root), "--llm",
    ])

    row = json.loads((batch_root / "progress.jsonl").read_text(encoding="utf-8"))
    assert result == 1
    assert row["status"] == "failed"
    assert row["reason"] == expected_reason


def test_queue_health_uses_only_selected_worlds():
    building_worlds = {"B1": "W1", "B2": "W2"}
    world_verdicts = {
        "W1": ["pass"] + ["fail"] * 9,
        "W2": ["pass"] * 5 + ["fail"] * 5,
    }
    full = verdict_distribution(v for values in world_verdicts.values() for v in values)
    queue = queue_verdict_distribution(["B1"], building_worlds, world_verdicts)
    assert full == {"fail": 14, "pass": 6}
    assert queue == {"fail": 9, "pass": 1}
    assert check_pool_health(full) == (True, 0.3)
    assert check_pool_health(queue) == (False, 0.1)


def test_run_profile_marks_floor_and_full_llm():
    """档位×契约矩阵(2026-07-23 codex 收官商议第 1 步):满血+v4=收官形态可验收;
    满血+v3=历史兼容/对照形态不具收官资格;地板档不变。"""
    floor = run_profile(False, None)
    full_v4 = run_profile(True, "v4")
    full_v3 = run_profile(True, "v3")
    assert floor["kind"] == "deterministic_floor"
    assert floor["baseline_acceptance_eligible"] is False
    assert "不得用于五道门验收" in floor["warning"]
    assert full_v4["kind"] == "full_llm"
    assert full_v4["report_contract"] == "v4"
    assert full_v4["baseline_acceptance_eligible"] is True
    assert full_v3["kind"] == "full_llm_v3_legacy"
    assert full_v3["baseline_acceptance_eligible"] is False
    assert "不具收官资格" in full_v3["warning"]


def test_child_environment_pins_report_contract():
    """契约由驱动显式下发:满血批写死 EVO_REPORT_CONTRACT,地板批清除环境残留。"""
    import os
    os.environ["EVO_REPORT_CONTRACT"] = "v3"  # 模拟外壳残留
    try:
        bundle = {"EVO_APPLICABILITY_BUNDLE": "/tmp/b.json",
                  "EVO_APPLICABILITY_BUNDLE_SHA256": "sha-x",
                  "EVO_APPLICABILITY_WORLDGEN_DIR": "/tmp/pool"}
        env_v4 = child_environment("v4", bundle)
        assert env_v4["EVO_REPORT_CONTRACT"] == "v4"
        # 判据指针同样由驱动下发（否则外壳里的别的 bundle 会静默换掉判定面）
        assert env_v4["EVO_APPLICABILITY_BUNDLE_SHA256"] == "sha-x"
        env_floor = child_environment(None, bundle)
        assert "EVO_REPORT_CONTRACT" not in env_floor
        assert env_floor["EVO_APPLICABILITY_BUNDLE"] == "/tmp/b.json"
    finally:
        os.environ.pop("EVO_REPORT_CONTRACT", None)


def test_anchor_mismatch_covers_contract_and_pool_hash():
    """续跑劈锚检查覆盖契约与池内容哈希(2026-07-23 codex 收官商议第 2 步)。"""
    base = {"worldgen_run_dir": "p", "git_commit": "c", "building_ids": ["B1"],
            "pool_content_sha256": "h1",
            "environment": {"neo4j_database": "db", "report_contract": "v4"}}
    other = json.loads(json.dumps(base))
    other["pool_content_sha256"] = "h2"
    other["environment"]["report_contract"] = "v3"
    assert anchor_mismatches(base, base) == []
    got = anchor_mismatches(base, other)
    assert "pool_content_sha256" in got and "report_contract" in got


def test_aggregate_uses_pair_denominators_and_rolls_up_audits(work_path):
    report_dirs = []
    for building_id, hits, compared in (("B1", 1, 2), ("B2", 6, 6)):
        report = json.loads(
            (FIXTURE_ROOT / building_id / "eval_report.json").read_text(encoding="utf-8")
        )
        metrics = report["metrics"]
        for prefix, metric_hits in (
            ("threshold_value", hits),
            ("threshold_pass_bool", hits),
            ("threshold_operator", compared),
        ):
            metrics[f"{prefix}_hits"] = metric_hits
            metrics[f"{prefix}_compared"] = compared
        target = work_path / building_id
        shutil.copytree(FIXTURE_ROOT / building_id, target)
        (target / "eval_report.json").write_text(json.dumps(report), encoding="utf-8")
        report_dirs.append(target)
    summary = aggregate_reports(report_dirs)

    threshold = summary["threshold_subset"]
    assert threshold["threshold_compared_pairs"] == 8
    assert threshold["value_match"] == pytest.approx(0.875)
    assert threshold["pass_bool_match"] == pytest.approx(0.875)
    assert threshold["operator_match"] == 1.0

    n1 = summary["coarse_family_n1"]
    assert n1["compared_pairs"] == 8
    assert n1["unknown_to_fail"] == 2
    assert n1["unknown_to_pass"] == 1
    assert summary["verifiable_subuniverse"]["fragment_level"][
        "expected_verdict_accuracy"] == pytest.approx(0.875)

    ledger = summary["obligation_ledger"]
    assert ledger["closed_ratio"] == 0.4
    assert ledger["open_reason_counts"] == {"missing_observation": 10}
    assert ledger["blocked_reason_counts"] == {"missing_rule_edge": 2}

    llm = summary["llm_audit"]
    assert llm["tool_call_count"] == {"min": 0, "median": 1.5, "max": 3}
    assert llm["tool_call_zero_buildings"] == ["B2"]
    assert llm["llm_forced_finalize_buildings"] == ["B2"]
    assert summary["leakage_audit"]["any_leakage_buildings"] == ["B2"]

    summary["completion"] = {"completed_count": 1, "planned_count": 2,
                             "failed_buildings": ["B2"]}
    markdown = render_markdown(summary)
    assert "公式" in markdown
    assert "reason_code" in markdown


def test_aggregate_does_not_fall_back_to_nested_tool_counts(work_path):
    output = work_path / "B-NESTED"
    (output / "runs" / "R1").mkdir(parents=True)
    (output / "eval_report.json").write_text(json.dumps({
        "building_id": "B-NESTED", "metrics": {},
        "leakage_audit": {}, "leakage_findings": [],
    }), encoding="utf-8")
    (output / "runs" / "R1" / "run_audit.json").write_text(json.dumps({
        "llm_turns": [{"tool_call_count": 1},
                      {"tool_call_count": 1, "llm_forced_finalize": True}],
        "status_trace": ["created", "report_ready"],
    }), encoding="utf-8")

    llm = aggregate_reports([output])["llm_audit"]
    assert llm["tool_call_count"] == {"min": None, "median": None, "max": None}
    assert llm["tool_call_missing_buildings"] == ["B-NESTED"]
    assert llm["llm_forced_finalize_buildings"] == []


def test_add_completion_uses_manifest_and_latest_progress(work_path):
    (work_path / "batch_manifest.json").write_text(json.dumps({
        "building_ids": ["B1", "B2", "B3"]}), encoding="utf-8")
    (work_path / "progress.jsonl").write_text("\n".join(json.dumps(row) for row in (
        {"building_id": "B1", "status": "failed"},
        {"building_id": "B1", "status": "completed"},
        {"building_id": "B2", "status": "completed"},
    )), encoding="utf-8")
    (work_path / "buildings" / "B1").mkdir(parents=True)
    (work_path / "buildings" / "B1" / "eval_report.json").write_text(
        "{}", encoding="utf-8")
    summary = {"building_ids": ["IGNORED"]}

    add_completion(summary, work_path)

    assert summary["completion"] == {
        "planned_count": 3,
        "completed_count": 1,
        "failed_count": 2,
        "completed_buildings": ["B1"],
        "failed_buildings": ["B2", "B3"],
    }


def test_aggregate_batch_excludes_failed_run_from_metrics(work_path):
    batch_root = work_path / "batch"
    buildings = batch_root / "buildings"
    for building_id, tool_calls, value_match, confusion in (
        ("GOOD", 5, 1.0, {"pass->pass": 100}),
        ("VACUOUS", 0, 0.0, {"unknown->fail": 100}),
    ):
        output = buildings / building_id
        run_dir = output / "runs" / "R1"
        run_dir.mkdir(parents=True)
        (output / "eval_report.json").write_text(json.dumps({
            "building_id": building_id,
            "metrics": {
                "threshold_compared_pairs": 100,
                "threshold_value_match": value_match,
                "threshold_value_hits": int(value_match * 100),
                "threshold_value_compared": 100,
                "threshold_pass_bool_match": value_match,
                "threshold_pass_bool_hits": int(value_match * 100),
                "threshold_pass_bool_compared": 100,
                "threshold_operator_match": value_match,
                "threshold_operator_hits": int(value_match * 100),
                "threshold_operator_compared": 100,
                "confusion": confusion,
            },
            "leakage_audit": {},
            "leakage_findings": [],
        }), encoding="utf-8")
        (run_dir / "run_audit.json").write_text(json.dumps({
            "llm_tool_call_count": tool_calls,
            "status_trace": ["created", "report_ready"],
        }), encoding="utf-8")

    (batch_root / "batch_manifest.json").write_text(json.dumps({
        "building_ids": ["GOOD", "VACUOUS"],
    }), encoding="utf-8")
    (batch_root / "progress.jsonl").write_text("\n".join((
        json.dumps({"building_id": "GOOD", "status": "completed"}),
        json.dumps({"building_id": "VACUOUS", "status": "failed",
                    "reason": "tool_call_zero"}),
    )) + "\n", encoding="utf-8")

    summary = aggregate_batch(batch_root)

    threshold = summary["threshold_subset"]
    assert threshold["threshold_compared_pairs"] == 100
    assert threshold["value_match"] == 1.0
    assert "unknown->fail" not in summary["coarse_family_n1"]["confusion"]
    assert summary["excluded_from_metrics"] == [{
        "building_id": "VACUOUS",
        "status": "failed",
        "reason": "tool_call_zero",
    }]
    markdown = (batch_root / "batch_summary.md").read_text(encoding="utf-8")
    assert "分母只包含状态为 completed" in markdown
    assert "VACUOUS：status=failed；reason=tool_call_zero" in markdown


def test_force_anchor_mismatch_migrates_only_when_no_progress(
        work_path, monkeypatch, capsys):
    """--force 越锚只许**空进度原地迁移**(旧 manifest 备份 superseded 后重写);
    已有进度的场景由 test_force_with_existing_progress_refuses_anchor_change
    锁定为拒绝(codex 审阻断#2:原测试固化"复用 completed+重写 manifest"危险行为)。"""
    batch_root = work_path / "batch"
    (batch_root / "buildings").mkdir(parents=True)  # 无 progress.jsonl=空进度
    old_manifest = {
        "worldgen_run_dir": str((work_path / "pool").resolve()),
        "git_commit": "old-commit",
        "building_ids": ["B1"],
        "environment": {"neo4j_database": "old_database"},
    }
    old_text = json.dumps(old_manifest, ensure_ascii=False, indent=2) + "\n"
    manifest_path = batch_root / "batch_manifest.json"
    manifest_path.write_text(old_text, encoding="utf-8")
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "new_database")
    monkeypatch.setattr(batch_module, "read_pool", lambda _path: (
        ["B1"], {"fail": 7, "pass": 3}, {"B1": "W1"},
        {"W1": ["pass"] * 3 + ["fail"] * 7}))
    monkeypatch.setattr(batch_module, "git_commit", lambda: "new-commit")
    monkeypatch.setattr(aggregate_module, "aggregate_batch", lambda _root: {
        "completion": {"completed_count": 1, "failed_count": 0}})

    def fake_run(command, **_kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "runs" / "R1").mkdir(parents=True)
        (output_dir / "eval_report.json").write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    result = batch_module.main([
        "--worldgen-run-dir", str(work_path / "pool"),
        "--batch-root", str(batch_root), "--force",
    ])

    assert result == 0
    backups = list(batch_root.glob("batch_manifest.superseded_*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == old_text
    rewritten = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rewritten["git_commit"] == "new-commit"
    assert rewritten["environment"]["neo4j_database"] == "new_database"
    assert rewritten["pool_health"]["queue"] == {
        "expected_verdict_distribution": {"fail": 7, "pass": 3},
        "pass_ratio": 0.3,
    }
    assert rewritten["pool_health"]["gate_basis"] == "queue"
    assert rewritten["run_profile"]["kind"] == "deterministic_floor"
    assert "非基线本体，不得用于五道门验收" in capsys.readouterr().out


def test_aggregate_sums_each_metric_real_denominator_with_none_metric(work_path):
    """逐指标直接累加 hits/compared；比例 None 不得触发统一分母推算。"""
    b3 = work_path / "B3"
    b3.mkdir()
    (b3 / "eval_report.json").write_text(json.dumps({
        "building_id": "B3",
        "metrics": {
            "threshold_compared_pairs": 100,
            "threshold_value_match": None,
            "threshold_pass_bool_match": None,
            "threshold_operator_match": 0.5,
            "threshold_value_hits": 0,
            "threshold_value_compared": 0,
            "threshold_pass_bool_hits": 0,
            "threshold_pass_bool_compared": 0,
            "threshold_operator_hits": 50,
            "threshold_operator_compared": 100,
            "confusion": {},
        },
        "leakage_audit": {},
        "leakage_findings": [],
    }, ensure_ascii=False), encoding="utf-8")

    b1_report = json.loads(
        (FIXTURE_ROOT / "B1" / "eval_report.json").read_text(encoding="utf-8")
    )
    b1_report["metrics"].update({
        "threshold_value_hits": 1, "threshold_value_compared": 2,
        "threshold_pass_bool_hits": 1, "threshold_pass_bool_compared": 2,
        "threshold_operator_hits": 2, "threshold_operator_compared": 2,
    })
    b1 = work_path / "B1"
    b1.mkdir()
    (b1 / "eval_report.json").write_text(json.dumps(b1_report), encoding="utf-8")
    summary = aggregate_reports([b1, b3])
    threshold = summary["threshold_subset"]
    # 总配对数保留兼容口径；三个指标只按自己的真实分母累加。
    assert threshold["threshold_compared_pairs"] == 102
    assert threshold["metric_pair_denominators"] == {
        "value_match": 2, "pass_bool_match": 2, "operator_match": 102}
    assert threshold["value_match"] == pytest.approx(0.5)
    assert threshold["pass_bool_match"] == pytest.approx(0.5)
    assert threshold["operator_match"] == pytest.approx((1.0 * 2 + 0.5 * 100) / 102)


def test_pool_content_sha256_framing_distinguishes_path_content_split(work_path):
    """长度前缀框架:文件 a+内容 bc 与文件 ab+内容 c 必须不同哈希(codex 审边界坑)。"""
    d1 = work_path / "p1"
    d2 = work_path / "p2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "a").write_bytes(b"bc")
    (d2 / "ab").write_bytes(b"c")
    assert (batch_module.pool_content_sha256(d1)
            != batch_module.pool_content_sha256(d2))


def test_anchor_mismatch_covers_model_and_digest():
    """模型锚参与劈锚比较(codex 审阻断#1:落清单不比较=续跑换模型静默混批)。"""
    base = {"worldgen_run_dir": "p", "git_commit": "c", "building_ids": ["B1"],
            "pool_content_sha256": "h",
            "environment": {"neo4j_database": "db", "report_contract": "v4",
                            "llm_model_resolved": "m1", "llm_model_digest": "d1"}}
    other = json.loads(json.dumps(base))
    other["environment"]["llm_model_resolved"] = "m2"
    other["environment"]["llm_model_digest"] = "d2"
    got = anchor_mismatches(base, other)
    assert "llm_model_resolved" in got and "llm_model_digest" in got


def test_force_with_existing_progress_refuses_anchor_change(
        work_path, monkeypatch, capsys):
    """--force 只许空进度原地迁移:已有进度时锚变必须拒绝(codex 审阻断#2:
    复用旧锚 completed 再重写 manifest = 伪造统一锚)。"""
    batch_root = work_path / "batch"
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "test_database")
    monkeypatch.setattr(batch_module, "read_pool", lambda _p: (
        ["B1"], {"fail": 7, "pass": 3}, {"B1": "W1"},
        {"W1": ["pass"] * 3 + ["fail"] * 7}))
    monkeypatch.setattr(batch_module, "git_commit", lambda: "commit-new")
    (batch_root / "buildings").mkdir(parents=True)
    (batch_root / "batch_manifest.json").write_text(json.dumps({
        "worldgen_run_dir": str(work_path / "pool"), "git_commit": "commit-old",
        "building_ids": ["B1"], "pool_content_sha256": "old",
        "environment": {"neo4j_database": "test_database", "report_contract": "v3"},
    }), encoding="utf-8")
    (batch_root / "progress.jsonl").write_text(
        json.dumps({"building_id": "B1", "status": "completed"}) + "\n",
        encoding="utf-8")
    rc = batch_module.main([
        "--worldgen-run-dir", str(work_path / "pool"),
        "--batch-root", str(batch_root), "--llm", "--force",
    ])
    assert rc == 2
    assert "不得复用旧锚产物" in capsys.readouterr().err


def test_main_records_v4_default_and_fails_on_gate_failure(work_path, monkeypatch):
    """满血批缺省契约 v4 入清单/子环境;消费者门失败时批级非零退出且
    consumer_gates.json 落盘(codex 审测试覆盖缺口)。"""
    batch_root = work_path / "batch"
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "test_database")
    monkeypatch.setenv("EVO_AGENT_LLM_MODEL", "fake-model:test")
    monkeypatch.setattr(batch_module, "read_pool", lambda _p: (
        ["B1"], {"fail": 7, "pass": 3}, {"B1": "W1"},
        {"W1": ["pass"] * 3 + ["fail"] * 7}))
    monkeypatch.setattr(batch_module, "git_commit", lambda: "commit")
    monkeypatch.setattr(batch_module, "ollama_model_digest", lambda _m: "digest-x")
    calls = []

    def fake_run(command, **kwargs):
        if "--output-dir" not in command:
            calls.append(Path(command[1]).name)  # 门脚本名
            return SimpleNamespace(returncode=1, stdout="gate out", stderr="gate err")
        env = kwargs.get("env") or {}
        assert env.get("EVO_REPORT_CONTRACT") == "v4"  # 契约显式下发
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "runs" / "R1").mkdir(parents=True)
        (output_dir / "eval_report.json").write_text("{}", encoding="utf-8")
        (output_dir / "runs" / "R1" / "run_audit.json").write_text(
            json.dumps({"llm_tool_call_count": 3}), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)
    monkeypatch.setattr(aggregate_module, "aggregate_batch", lambda _root: {
        "completion": {"completed_count": 1, "failed_count": 0}})

    rc = batch_module.main([
        "--worldgen-run-dir", str(work_path / "pool"),
        "--batch-root", str(batch_root), "--llm",
    ])
    assert rc == 1  # 跑批全成但门失败 → 非零
    # C 门 = DEBT-065 shadow 度量（S_new ⊆ S_old），2026-07-25 挂成批后常驻门
    # 门清单锚定:加门要有意识地改这里(A 可读性 / B 权威 / C shadow / D 契约覆盖)
    # E 门是驱动内联自检、不派子进程，故不在 calls 里——见下面两个专测。
    assert calls == ["check_report_usability.py", "check_report_authority.py",
                     "shadow_measure_applicability.py",
                     "check_sidecar_contract_coverage.py"]
    manifest = json.loads(
        (batch_root / "batch_manifest.json").read_text(encoding="utf-8"))
    assert manifest["environment"]["report_contract"] == "v4"
    assert manifest["environment"]["llm_model_resolved"] == "fake-model:test"
    assert manifest["environment"]["llm_model_digest"] == "digest-x"
    assert manifest["params"]["report_contract"] == "v4"
    assert len(manifest["pool_content_sha256"]) == 64
    assert manifest["applicability_replay"]["bundle_relative_path"].startswith("agent_v1/")
    assert manifest["applicability_replay"]["world_pool"]["content_sha256"] == (
        manifest["pool_content_sha256"]
    )
    gates = json.loads(
        (batch_root / "consumer_gates.json").read_text(encoding="utf-8"))
    assert gates["usability_gate_a"]["exit_code"] == 1
    assert gates["authority_gate_b"]["exit_code"] == 1
    # shadow 门失败同样必须拦批：扩大假 NA 面是判定面安全问题，不是可容忍的告警
    assert gates["applicability_shadow_gate_c"]["exit_code"] == 1
    assert "gate out" in gates["usability_gate_a"]["output_tail"]


# ===== E 门:代码状态自证(DEBT-069) =====
#
# 为什么这两个测试要成对写:只测"不变时通过"等于没测——那种测试在把门整段删掉之后
# 照样绿。第二个是**变异测试**:让批末重算值与开跑冻结值不同，断言门真的红、且批级
# 非零退出。本项目已四次栽在"绿灯掩盖断路"上，加门必配变异验证。


def _gate_e_harness(work_path, monkeypatch, code_states):
    """跑一次满血批，`code_state_sha256` 按 code_states 依次返回(开跑一次、批末一次)。"""
    batch_root = work_path / "batch"
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "test_database")
    monkeypatch.setenv("EVO_AGENT_LLM_MODEL", "fake-model:test")
    monkeypatch.setattr(batch_module, "read_pool", lambda _p: (
        ["B1"], {"fail": 7, "pass": 3}, {"B1": "W1"},
        {"W1": ["pass"] * 3 + ["fail"] * 7}))
    monkeypatch.setattr(batch_module, "git_commit", lambda: "commit")
    monkeypatch.setattr(batch_module, "ollama_model_digest", lambda _m: "digest-x")

    seq = list(code_states)

    def fake_code_state():
        value = seq.pop(0) if len(seq) > 1 else seq[0]
        return {"code_state_sha256": value, "git_commit": "commit",
                "dirty_path_count": 0, "workspace_clean": True,
                "scope": ["agent_v1/src/"]}

    monkeypatch.setattr(batch_module, "code_state_sha256", fake_code_state)

    def fake_run(command, **kwargs):
        if "--output-dir" not in command:
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "runs" / "R1").mkdir(parents=True)
        (output_dir / "eval_report.json").write_text("{}", encoding="utf-8")
        (output_dir / "runs" / "R1" / "run_audit.json").write_text(
            json.dumps({"llm_tool_call_count": 3}), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)
    monkeypatch.setattr(aggregate_module, "aggregate_batch", lambda _root: {
        "completion": {"completed_count": 1, "failed_count": 0}})

    rc = batch_module.main([
        "--worldgen-run-dir", str(work_path / "pool"),
        "--batch-root", str(batch_root), "--llm",
    ])
    gates = json.loads(
        (batch_root / "consumer_gates.json").read_text(encoding="utf-8"))
    return rc, gates["code_state_selfcheck_gate_e"]


def test_code_state_selfcheck_passes_when_code_unchanged(work_path, monkeypatch):
    """作用域内全程未变 → E 门绿，且批级退出 0。"""
    rc, gate = _gate_e_harness(work_path, monkeypatch, ["same-fingerprint"])
    assert gate["exit_code"] == 0
    assert gate["frozen_at_start"] == gate["recomputed_at_end"] == "same-fingerprint"
    assert rc == 0


def test_code_state_selfcheck_fails_when_code_changed_mid_batch(work_path, monkeypatch):
    """🔴 变异测试:批期间作用域内代码被改过 → E 门必须红，且**拦批**(非零退出)。

    这正是 2026-07-25 那批的形状:批期间做了一次变异测试改到驱动文件，事后再也无法
    取得"这批结果由这份代码产出"的证明。当时的补救是"下次记得在批末手工核"——那不是
    修法。本门把它焊成机器行为。
    """
    rc, gate = _gate_e_harness(
        work_path, monkeypatch, ["frozen-at-start", "drifted-at-end"])
    assert gate["exit_code"] == 1, "代码在批期间变过，E 门却放行"
    assert gate["frozen_at_start"] == "frozen-at-start"
    assert gate["recomputed_at_end"] == "drifted-at-end"
    assert "不得用于冻结数字" in gate["output_tail"]
    assert rc != 0, "E 门红了却没拦批——门必须影响退出码，否则等于告警"


def test_active_zh_switch_is_recorded_and_retired_threshold_switch_is_rejected():
    base = {"PYTHONUTF8": "1", "PYTHONPATH": "x"}
    off = batch_module._redacted_environment(dict(base))
    assert off["EVO_ZH_AUTHORITY"] == "0"
    assert "EVO_THRESHOLD_SIDECAR" not in off
    assert "EVO_ZH_AUTHORITY" in batch_module.anchor_mismatches(
        {"environment": {"EVO_ZH_AUTHORITY": "0"}},
        {"environment": {"EVO_ZH_AUTHORITY": "1"}},
    )
    assert "EVO_THRESHOLD_SIDECAR" not in batch_module.anchor_mismatches(
        {"environment": {"EVO_THRESHOLD_SIDECAR": "0"}},
        {"environment": {"EVO_THRESHOLD_SIDECAR": "1"}},
    )
    assert batch_module.retired_experiment_switch_problems(
        {"EVO_THRESHOLD_SIDECAR": "1"}
    ) == [
        "EVO_THRESHOLD_SIDECAR 已正式停用；阈值旁路不会参与法规卡加载，"
        "请删除该环境变量"
    ]

@pytest.mark.parametrize(
    ("ratio", "expect_rejection", "expected_phrase"),
    [
        (0.0, True, "全 CPU 回退"),
        (0.40, True, "部分 CPU 回退"),
        (0.599, True, "部分 CPU 回退"),
        (0.60, False, None),
        (0.724, False, None),   # v2 证据点：三连批成功的实测驻留
        (1.0, False, None),
    ],
)
def test_preflight_rejects_partial_gpu_offload(
    ratio, expect_rejection, expected_phrase, monkeypatch
):
    """伪造真实接口响应，按 v2 阈值（0.60）测边界行为（2026-08-04 升版同步）。"""
    import contextlib
    import io
    import socket
    import urllib.request

    model = "gpu-boundary-model"
    total = 10_000
    monkeypatch.setenv("EVO_AGENT_NEO4J_PASSWORD", "test-only")
    monkeypatch.setenv("EVO_AGENT_LLM_MODEL", model)
    monkeypatch.setattr(
        socket, "create_connection", lambda *_args, **_kwargs: contextlib.nullcontext()
    )

    def fake_urlopen(url, timeout):
        if str(url).endswith("/api/tags"):
            payload = {"models": [{"name": model, "model": model}]}
        elif str(url).endswith("/api/ps"):
            payload = {"models": [{
                "name": model,
                "size": total,
                "size_vram": int(total * ratio),
            }]}
        else:  # pragma: no cover - 意外端点本身就是测试失败
            raise AssertionError(f"意外端点：{url}")
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    issues = _REAL_PREFLIGHT(llm=True)
    gpu_issues = [issue for issue in issues if "CPU 回退" in issue]

    assert bool(gpu_issues) is expect_rejection
    if expected_phrase:
        assert any(expected_phrase in issue for issue in gpu_issues)
    assert not any("Neo4j" in issue or "Ollama" in issue for issue in issues)


def test_gpu_residency_threshold_is_versioned_and_evidence_bounded():
    """冻结 v2 策略及其证据边界（2026-08-04 升版）。

    v1=0.95 是一次 73% 失败观测后的保守拍数；v2=0.60 的依据是 72.4% 驻留三连批
    30/30 全成＋锚批 ~61% 完成先例（混杂因子 FA+KV 量化已在证据结构里如实记）。
    本测试锁两件事：①阈值改动必须伴随版本升级与证据更新（裸改常量会在这里红）；
    ②失败与成功两侧观测都必须在案——只留一侧就是把单点观测扩写成定律。"""
    assert batch_module.GPU_RESIDENCY_POLICY_VERSION == "lab_gpu_residency.v2"
    assert batch_module.MIN_GPU_RESIDENCY_RATIO == 0.60
    assert batch_module.GPU_RESIDENCY_EVIDENCE["failed_observation_ratio"] == 0.73
    assert batch_module.GPU_RESIDENCY_EVIDENCE["succeeded_observation_ratio"] == 0.724
    assert "配对边界观测" in batch_module.GPU_RESIDENCY_EVIDENCE["missing_evidence"]


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--llm", "--batch-root", "EXP"], "显式指定 --count"),
        (["--llm", "--count", "3", "--batch-root", "EXP"], "1..2"),
        (["--llm", "--count", "1"], "独立 --batch-root"),
        (["--count", "1", "--batch-root", "EXP"], "同时显式指定 --llm"),
    ],
)
def test_gpu_residency_experiment_static_refusal_paths(work_path, extra, message):
    argv = ["--worldgen-run-dir", str(work_path / "pool"),
            "--gpu-residency-experiment"]
    argv.extend(str(work_path / value) if value == "EXP" else value for value in extra)
    args = batch_module.parse_args(argv)
    with pytest.raises(ValueError, match=message):
        batch_module.validate_gpu_residency_experiment_request(args, argv)


def test_gpu_layers_must_be_strictly_below_automatic_value():
    observation = {"automatic_gpu_layers": 23}
    batch_module.validate_downward_gpu_layers(22, observation)
    with pytest.raises(ValueError, match="严格小于自动值 23"):
        batch_module.validate_downward_gpu_layers(23, observation)
    with pytest.raises(ValueError, match="严格小于自动值 23"):
        batch_module.validate_downward_gpu_layers(24, observation)


def test_experiment_profile_and_child_env_are_ineligible_and_pass_num_gpu(monkeypatch):
    monkeypatch.setenv("EVO_AGENT_LLM_NUM_GPU", "31")
    bundle = {
        "EVO_APPLICABILITY_BUNDLE": "/tmp/b.json",
        "EVO_APPLICABILITY_BUNDLE_SHA256": "sha-x",
        "EVO_APPLICABILITY_WORLDGEN_DIR": "gen_seed_1",
    }
    ordinary = batch_module.child_environment("v4", bundle, "1")
    assert "EVO_AGENT_LLM_NUM_GPU" not in ordinary
    experimental = batch_module.child_environment("v4", bundle, "1", 12)
    assert experimental["EVO_AGENT_LLM_NUM_GPU"] == "12"
    profile = batch_module.run_profile(
        True, "v4", gpu_residency_experiment=True
    )
    assert profile["baseline_acceptance_eligible"] is False
    assert profile["experiment_purpose"] == "gpu_residency_boundary"
    assert profile["numbers_frozen"] is False


def test_llm_client_num_gpu_and_elapsed_contract(monkeypatch):
    import inspect
    from evo_agent_baseline.agent.llm_client import LLMConfig, LLMClient, LLMTurn

    monkeypatch.setenv("EVO_AGENT_LLM_NUM_GPU", "12")
    assert LLMConfig().num_gpu == 12
    turn = LLMTurn(0, "", [], "stop", 10, 4, 1.5)
    assert turn.elapsed_seconds == 1.5
    source = inspect.getsource(LLMClient._native_chat_think_off)
    assert 'body["options"]["num_gpu"] = self.config.num_gpu' in source


def test_experiment_preflight_records_and_bypasses_only_partial_residency(monkeypatch):
    import contextlib
    import io
    import socket
    import urllib.request

    model = "gpu-boundary-model"
    monkeypatch.setenv("EVO_AGENT_NEO4J_PASSWORD", "test-only")
    monkeypatch.setenv("EVO_AGENT_LLM_MODEL", model)
    monkeypatch.setattr(
        socket, "create_connection", lambda *_args, **_kwargs: contextlib.nullcontext()
    )

    def fake_urlopen(url, timeout):
        if str(url).endswith("/api/tags"):
            payload = {"models": [{"name": model, "model": model, "digest": "digest-x"}]}
        elif str(url).endswith("/api/ps"):
            payload = {"models": [{
                # v2 阈值 0.60（2026-08-04 升版）：取 0.55 保持「低于门槛才走旁路记录」的语义
                "name": model, "digest": "digest-x", "size": 10_000, "size_vram": 5_500,
            }]}
        else:  # pragma: no cover
            raise AssertionError(f"意外端点：{url}")
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        batch_module, "_complete_gpu_experiment_observation",
        lambda _root, _model, observation, _problems: observation.update({
            "ollama_version": "test", "gpu_driver_versions": ["test"],
            "request_timeout_seconds": 600, "model_total_layers": 33,
            "automatic_gpu_layers": 24,
        }),
    )
    observation = {}
    issues = _REAL_PREFLIGHT(
        llm=True, allow_low_gpu_residency=True, gpu_observation=observation
    )
    assert not any("CPU 回退" in issue for issue in issues)
    assert observation["residency_ratio"] == pytest.approx(0.55)
    assert observation["threshold_bypassed"] is True
    assert observation["model_digest"] == "digest-x"


def test_experiment_results_mark_manifest_summary_and_turn_metrics(work_path, monkeypatch):
    batch_root = work_path / "experiment"
    output = batch_root / "buildings" / "B1"
    run_dir = output / "runs" / "R1"
    run_dir.mkdir(parents=True)
    (output / "eval_report.json").write_text("{}", encoding="utf-8")
    (run_dir / "run_audit.json").write_text(json.dumps({
        "llm_tool_call_count": 2,
        "status_trace": ["created", "llm_orchestrating", "report_ready"],
        "llm_turns": [{
            "iteration": 0, "prompt_tokens": 10, "completion_tokens": 4,
            "elapsed_seconds": 1.25,
        }],
    }), encoding="utf-8")
    manifest_path = batch_root / "batch_manifest.json"
    manifest_path.write_text(json.dumps({
        "baseline_acceptance_eligible": False,
        "experiment_purpose": "gpu_residency_boundary",
        "numbers_frozen": False,
        "gpu_residency_experiment": {
            "success_criteria": dict(
                batch_module.GPU_RESIDENCY_EXPERIMENT_SUCCESS_CRITERIA
            ),
        },
    }), encoding="utf-8")
    (batch_root / "batch_summary.md").write_text("# 摘要\n", encoding="utf-8")
    monkeypatch.setattr(batch_module, "current_gpu_residency_observation", lambda _model: {
        "model": "m", "size": 100, "size_vram": 70, "residency_ratio": 0.7,
        "num_ctx": 16384,
    })

    success = batch_module.persist_gpu_experiment_results(
        batch_root=batch_root, manifest_path=manifest_path,
        summary={"completion": {"completed_count": 1, "failed_count": 0}},
        building_ids=["B1"], runner_logs={"B1": {"stdout": "ok", "stderr": ""}},
        preflight_observation={"model": "m", "size": 100, "size_vram": 72,
                               "residency_ratio": 0.72},
        requested_gpu_layers=None,
    )
    assert success is True
    summary = json.loads((batch_root / "batch_summary.json").read_text(encoding="utf-8"))
    assert summary["baseline_acceptance_eligible"] is False
    assert summary["experiment_purpose"] == "gpu_residency_boundary"
    assert summary["numbers_frozen"] is False
    turn = summary["gpu_residency_experiment"]["per_building"]["B1"]["turns"][0]
    assert turn == {"iteration": 0, "prompt_tokens": 10, "completion_tokens": 4,
                    "total_tokens": 14, "elapsed_seconds": 1.25}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["gpu_residency_experiment"]["success_criteria_all_met"] is True
    assert "数字不得冻结" in (batch_root / "batch_summary.md").read_text(encoding="utf-8")


def test_acceptance_script_is_importable():
    """🔴 批后验收脚本必须能 import——语法错误不许被 `try/except` 静默吞掉。

    2026-07-29 实证：我给 `check_batch_acceptance.py` 引入了一个语法错误
    （heredoc 里的 `\n` 变成真实换行，字符串未闭合），
    而**全量 2,950 个测试照样全绿**——因为批驱动里那句
    `except Exception: print("[acceptance] 验收脚本未能运行…")` 把它吞了。

    那句吞是**有意的**（验收自己挂了不该把真实批产物判废），
    但代价是「验收脚本坏了」这件事没有任何闸会报。本测试补上这一格。
    """
    import importlib.util
    import pathlib

    p = (pathlib.Path(__file__).resolve().parents[1]
         / "scripts" / "check_batch_acceptance.py")
    assert p.is_file(), f"验收脚本不存在：{p}"
    spec = importlib.util.spec_from_file_location("check_batch_acceptance", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # 语法/导入错误在这里炸
    assert callable(mod.main)


# ===========================================================================
# DEBT-083 哨兵边界开关转正常开启（工单①②③，2026-08-02）
# ===========================================================================


def test_child_environment_always_pins_fallback_boundary(monkeypatch):
    """驱动无条件显式下发 EVO_FALLBACK_BOUNDARY：默认 "1"（正常开启是新常态）、
    反事实态 "0"，且外壳残留一律被覆盖（静默退化族同一规矩）。"""
    bundle = {"EVO_APPLICABILITY_BUNDLE": "/tmp/b.json",
              "EVO_APPLICABILITY_BUNDLE_SHA256": "sha-x",
              "EVO_APPLICABILITY_WORLDGEN_DIR": "/tmp/pool"}
    monkeypatch.setenv("EVO_FALLBACK_BOUNDARY", "0")  # 外壳残留反事实值
    assert child_environment("v4", bundle)["EVO_FALLBACK_BOUNDARY"] == "1"
    assert child_environment(None, bundle)["EVO_FALLBACK_BOUNDARY"] == "1"
    env_cf = child_environment("v4", bundle, fallback_boundary=False)
    assert env_cf["EVO_FALLBACK_BOUNDARY"] == "0"


def test_sentinel_registry_digest_deterministic_and_content_sensitive():
    """digest 两次调用同值；对三冻结常量内容敏感（拿改过的集合手算不同，
    不动真常量）；驱动转调与 fact_binding 源函数同值（驱动不重算逻辑）。"""
    import hashlib

    from evo_agent_baseline.closure import fact_binding as fb

    d1 = fb.sentinel_registry_digest()
    assert d1 == fb.sentinel_registry_digest()
    assert len(d1) == 64
    tampered_payload = {
        "non_adjudicative_outcome_groups": sorted(
            set(fb.NON_ADJUDICATIVE_OUTCOME_GROUPS) | {"tampered_group"}),
        "non_adjudicative_reason_codes": sorted(fb.NON_ADJUDICATIVE_REASON_CODES),
        "non_adjudicative_sentinel_value": fb.NON_ADJUDICATIVE_SENTINEL_VALUE,
    }
    tampered = hashlib.sha256(
        fb.canonical_json(tampered_payload).encode("utf-8")).hexdigest()
    assert tampered != d1
    assert batch_module.sentinel_registry_digest() == d1


def test_legacy_fallback_behavior_flag_isolates_counterfactual_batch(
        work_path, monkeypatch):
    """--legacy-fallback-behavior 三联动（工单③）：批目录强制 _legacyfb 后缀、
    manifest fallback_boundary 节 enabled=false + counterfactual=true、
    run_profile.baseline_acceptance_eligible=false（连满血 v4 的 True 也覆盖）。"""
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "test_database")
    monkeypatch.setattr(batch_module, "read_pool", lambda _path: (
        ["B1"], {"fail": 7, "pass": 3}, {"B1": "W1"},
        {"W1": ["pass"] * 3 + ["fail"] * 7}))
    monkeypatch.setattr(batch_module, "git_commit", lambda: "commit")
    monkeypatch.setattr(aggregate_module, "aggregate_batch", lambda _root: {
        "completion": {"completed_count": 1, "failed_count": 0}})
    captured_envs = []

    def fake_run(command, **kwargs):
        if "--output-dir" not in command:
            # 批后 A/B/C/D 门子进程：桩过
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        captured_envs.append(kwargs.get("env") or {})
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "runs" / "R1").mkdir(parents=True)
        (output_dir / "eval_report.json").write_text("{}", encoding="utf-8")
        (output_dir / "runs" / "R1" / "run_audit.json").write_text(
            json.dumps({"llm_tool_call_count": 1}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    result = batch_module.main([
        "--worldgen-run-dir", str(work_path / "pool"),
        "--batch-root", str(work_path / "batch"),
        "--legacy-fallback-behavior",
    ])
    assert result == 0
    legacy_root = work_path / "batch_legacyfb"
    manifest = json.loads(
        (legacy_root / "batch_manifest.json").read_text(encoding="utf-8"))
    # 联动一：目录后缀（且不带后缀的原目录不得有产物）
    assert not (work_path / "batch" / "batch_manifest.json").exists()
    # 联动二：manifest 反事实标记 + 开关值 + 策略版本 + 登记摘要
    fb_section = manifest["fallback_boundary"]
    assert fb_section["enabled"] is False
    assert fb_section["counterfactual"] is True
    assert fb_section["policy"] == "DEBT-083 四门收口 2026-08-02"
    assert len(fb_section["sentinel_registry_digest"]) == 64
    # 联动三：永不具基线验收资格 + 环境摘要记实际下发值
    assert manifest["run_profile"]["baseline_acceptance_eligible"] is False
    assert manifest["environment"]["fallback_boundary"] == "0"
    # 子进程环境实收 0（驱动显式下发，不吃外壳残留）
    assert captured_envs
    assert all(e.get("EVO_FALLBACK_BOUNDARY") == "0" for e in captured_envs)

    # 满血 v4 档 profile 本来 eligible=True——反事实覆盖必须连它也压成 False。
    captured_envs.clear()
    batch_module.main([
        "--worldgen-run-dir", str(work_path / "pool"),
        "--batch-root", str(work_path / "batch_llm"), "--llm",
        "--legacy-fallback-behavior",
    ])
    llm_manifest = json.loads(
        (work_path / "batch_llm_legacyfb" / "batch_manifest.json")
        .read_text(encoding="utf-8"))
    assert llm_manifest["run_profile"]["kind"] == "full_llm"
    assert llm_manifest["run_profile"]["baseline_acceptance_eligible"] is False
    assert "不得用于基线验收" in llm_manifest["run_profile"]["warning"]
    assert llm_manifest["fallback_boundary"]["counterfactual"] is True
