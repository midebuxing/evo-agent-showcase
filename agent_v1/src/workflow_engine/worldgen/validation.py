"""W0 worldgen full-coverage validation entry (T-17g + T-28 building-centric v2 only).

T-17h step 2：旧 WorldItem-based run_worldgenerator_fullcoverage_framework + helpers
(_release_coverage_metrics / assert_release_coverage_floors / _build_validation_report /
_build_summary / _hydrate_normalized_world_view / _assert_cross_carrier_consistency) 全部移除。
仅保留 v2 building-centric pipeline（T-17a-g + T-28）。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from workflow_engine.worldgen.constants import (
    DEFAULT_BATCH_RANDOM_SEED,
    DEFAULT_BATCH_WORLD_COUNT,
    DEFAULT_WORLDGEN_FULLCOVERAGE_OUTPUT_DIR,
    GENERATOR_VERSION,
    _hash_payload,
    _resolve_batch_profile,
    _utc_now_iso,
    _write_json,
)
from workflow_engine.worldgen.models import (
    SidecarRuntimeBundle,
    ValidationCheck,
    ValidationReport,
)
from workflow_engine.worldgen.parquet_io import (
    CANONICAL_PROFILE_ID,
    IDENTITY_SCHEMA_PENDING,
    write_world_bundles_parquet,
    write_sidecar_runtime_parquet,
    write_normative_projection_parquet,
)
from workflow_engine.worldgen.registry import (
    _build_registry_bundle,
    _build_sidecar_contract,
)
from workflow_engine.worldgen.sidecar import (
    _build_sidecar_runtime_bundle_for_buildings,
    audit_capture_sidecar_fallback,
)
from workflow_engine.worldgen.generator import generate_world_batch
# 供下方 `run_worldgenerator_fullcoverage_framework_v2` 主入口 Step 7 per-fragment
# 调 W2 phase 3 投影用（详见该函数 docstring + W2 规格 04 §3 phase 3 主入口）。
from workflow_engine.regulation_projection_executor import (
    build_normative_projections_for_world,
    build_sidecar_numeric_index,
)
# DEBT-044 修根 (2026-06-11)：批级楼级取舍入口（spec 11 §3.1 批级 filter；
# candidate = 楼，被接受楼保留全部 fragment projection，详见该函数 docstring）。
from workflow_engine.regulation_coverage_control import (
    apply_coverage_control_rejection_building_level,
)


# 2026-05-10 全替换：3 个大 bundle 切 parquet (>10× 压缩)
# directory 命名沿用 .v2 后缀但拍成 directory 而非 .json file
WORLD_BUNDLES_PARQUET_DIR_NAME = "WorldgenWorldBundles.v2.parquet"
SIDECAR_RUNTIME_PARQUET_DIR_NAME = "WorldgenSidecarRuntimeBundle.v2.parquet"
NORMATIVE_PROJECTION_PARQUET_DIR_NAME = "WorldgenNormativeProjection.v2.parquet"


def build_class_reachability_audit(building_worlds: List[Any]) -> Dict[str, Any]:
    """楼型×组件类×缺陷类三态审计（spec 草案·DEBT-049 第三波 件A A.4，纯函数可单测）。

    三态判定（按 (楼型, 组件类, 类) 聚合，优先级 generated > reachable_not_generated
    > unreachable）：类在 fragment 实际 condition_classes → generated；在机制可达集
    （generatable_absent_classes）→ reachable_not_generated；仅在全集缺席
    （absent_condition_classes）→ unreachable。闭世界总声明把不可达类也发负例后，
    供给侧缺口（该给哪些类建生成路径）由本台账显性化，不再由 eval unknown 承担。
    """
    cells: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    _rank = {"generated": 0, "reachable_not_generated": 1, "unreachable": 2}
    for bw in building_worlds:
        # W0-008 拆分后模板 id 在 building_metadata（BuildingContext 8 字段表无它）。
        bt = str(
            getattr(getattr(bw, "building_metadata", None), "building_template_id", "")
            or getattr(getattr(bw, "building", None), "building_template_id", "")
            or ""
        )
        ctype_by_comp = {
            c.component_id: str(c.component_type)
            for c in (getattr(bw, "components", None) or [])
        }
        comp_by_frag = {
            f.fragment_id: f.component_id
            for f in (getattr(bw, "fragments", None) or [])
        }
        for cond in getattr(bw, "conditions", None) or []:
            frag = str(getattr(cond, "fragment_id", "") or "")
            ctype = ctype_by_comp.get(comp_by_frag.get(frag, ""), "")
            present = set(getattr(cond, "condition_classes", None) or [])
            if getattr(cond, "condition_class", None):
                present.add(str(cond.condition_class))
            reachable_absent = set(getattr(cond, "generatable_absent_classes", None) or [])
            all_absent = set(getattr(cond, "absent_condition_classes", None) or [])
            for cls, status in (
                [(c, "generated") for c in present]
                + [(c, "reachable_not_generated") for c in reachable_absent]
                + [(c, "unreachable") for c in (all_absent - reachable_absent)]
            ):
                key = (bt, ctype, cls)
                cell = cells.setdefault(key, {
                    "building_template_id": bt, "component_type": ctype,
                    "condition_class": cls, "status": status,
                    "fragment_count": 0, "sample_fragment_ids": [],
                })
                if _rank[status] < _rank[cell["status"]]:
                    cell["status"] = status
                cell["fragment_count"] += 1
                if len(cell["sample_fragment_ids"]) < 3 and frag:
                    cell["sample_fragment_ids"].append(frag)
    entries = sorted(
        cells.values(),
        key=lambda e: (e["building_template_id"], e["component_type"],
                       e["condition_class"]),
    )
    summary: Dict[str, int] = {"generated": 0, "reachable_not_generated": 0,
                               "unreachable": 0}
    for e in entries:
        summary[e["status"]] += 1
    return {
        "version": "worldgen.class_reachability_audit.v1",
        "generated_at": _utc_now_iso(),
        "summary_cell_counts": summary,
        "entries": entries,
    }




# ---------- T-17g + T-28: building-centric v2 entry ----------


def _build_v2_validation_report(
    building_worlds: List[Any],  # List[WorldBundle]
    sidecar_runtime_bundle: SidecarRuntimeBundle,
    registry_bundle_hash: str,
    batch_config_hash: str,
    deterministic_key: str,
    sidecar_fallback_counts: Optional[Dict[str, int]] = None,
) -> ValidationReport:
    """T-17g v2 validation report — minimal building-centric checks.

    spec 04 §3 WorldBundle 字段一致性 + spec 09 §1.2 sidecar 派生层产出验证
    （2026-05-09 修订：原"sidecar_missing markers 全覆盖"已废止）。

    W1-RC-02 / spec 10 §6：``sidecar_fallback_counts`` 由 caller 经
    ``audit_capture_sidecar_fallback()`` 收集后传入，落 validation_report 作 batch 级
    silent fallback 可见性 audit 产物（None / 空 dict = 本批次无 conditional fallback）。
    """
    checks: List[ValidationCheck] = []
    # C-V2-001 building 非空
    total_buildings = len(building_worlds)
    total_fragments = sum(len(bw.fragments) for bw in building_worlds)
    total_components = sum(len(bw.components) for bw in building_worlds)
    total_locations = sum(len(bw.locations) for bw in building_worlds)
    checks.append(ValidationCheck(
        check_id="C-V2-001",
        passed=total_buildings >= 1,
        detail=f"buildings_count={total_buildings} (must be >= 1)",
    ))
    checks.append(ValidationCheck(
        check_id="C-V2-002",
        passed=total_fragments >= total_buildings,
        detail=f"fragments={total_fragments}, buildings={total_buildings} (must be >=1 per building)",
    ))
    checks.append(ValidationCheck(
        check_id="C-V2-003",
        passed=total_components >= total_buildings,
        detail=f"components={total_components}, buildings={total_buildings}",
    ))
    checks.append(ValidationCheck(
        check_id="C-V2-004",
        passed=total_locations >= total_buildings,
        detail=f"locations={total_locations}, buildings={total_buildings}",
    ))
    # C-V2-005 per-fragment 1:1
    fragment_state_aligned = all(
        len(bw.fragments) == len(bw.drivers) == len(bw.mechanisms) == len(bw.conditions) == len(bw.repair_assessment_states)
        for bw in building_worlds
    )
    checks.append(ValidationCheck(
        check_id="C-V2-005",
        passed=fragment_state_aligned,
        detail="per-fragment driver / mechanism / condition / repair_assessment 1:1 alignment",
    ))
    # C-V2-006 spec 09 §1.2 (2026-05-09 修订)：sidecar 派生层产出非空
    # 原 check："marker.sidecar_missing 全覆盖"——基于 sidecar 由外部送入的旧前提，已废止。
    # 新 check：每条 sidecar record 的 supervision_runtime_state ∪ procedure_gate_state ∪ facts
    # 至少非空之一（sidecar_measurement_registry 已填 9 个数值 slot 的 distribution，
    # 派生层应对每 fragment emit 至少 1 条 fact；空 = registry 缺数据或派生 bug）。
    fragments_with_facts = sum(
        1 for record in sidecar_runtime_bundle.records
        if (record.supervision_runtime_state or record.procedure_gate_state
            or record.facts or record.artifact_requirement_state
            or record.completion_runtime_state)
    )
    total_records = len(sidecar_runtime_bundle.records)
    checks.append(ValidationCheck(
        check_id="C-V2-006",
        passed=(total_records == 0) or (fragments_with_facts == total_records),
        detail=f"sidecar 派生层产出非空: {fragments_with_facts}/{total_records} records have facts",
    ))
    # C-V2-007 measurements per building >= 1
    measurements_present = all(len(bw.measurements) >= 1 for bw in building_worlds)
    checks.append(ValidationCheck(
        check_id="C-V2-007",
        passed=measurements_present,
        detail="every building has >=1 measurement",
    ))
    # C-V2-008 cross-ref measurement.target_ref 解析到已知锚点实体.
    # SA-1 fix (2026-05-23)：measurement.target_ref 按 spec 04 §16 可为
    # "fragment / component / condition id"——defect_geometry_measurement 锚 condition_id
    # （spec 07 §C017 + spec 04 §17），coverage_sampling 可锚 coverage_id（C018），
    # technical_validation 可锚 repair_assessment_id（C019）。本 batch 级 smoke check
    # 校验 target_ref 解析到全部合法锚点实体之并集即可（精确的 per-family 锚点归属
    # 由 P0 check C017/C018/C019/C020 分别强制）；原实现只比 fragment_ids、会把
    # 合法的 condition 锚定几何测量误判为 cross-ref 失败。
    cross_ref_ok = True
    for bw in building_worlds:
        valid_anchor_ids = (
            {f.fragment_id for f in bw.fragments}
            | {c.condition_id for c in bw.conditions}
            | {c.component_id for c in bw.components}
            | {cr.coverage_id for cr in bw.coverage_relations}
            | {r.repair_assessment_id for r in bw.repair_assessment_states}
        )
        for measurement in bw.measurements:
            if measurement.target_ref and measurement.target_ref not in valid_anchor_ids:
                cross_ref_ok = False
                break
        if not cross_ref_ok:
            break
    checks.append(ValidationCheck(
        check_id="C-V2-008",
        passed=cross_ref_ok,
        detail="measurement.target_ref ⊆ fragment ∪ condition ∪ component ∪ coverage ∪ repair_assessment ids",
    ))
    # C-V2-009 W1-RC-02 / spec 10 §6：sidecar conditional fallback batch 级可见性。
    # conditional formula 异常时 fallback 到 marginal 是预期保险路径（registry build 时
    # validate_formula 已拦截绝大多数），命中率应极低；此 check 把计数显式落 audit，
    # passed 恒 True（fallback 本身不是 validation 失败，仅需可见 / 非 silent）。
    fallback_counts: Dict[str, int] = dict(sidecar_fallback_counts or {})
    total_fallbacks = sum(fallback_counts.values())
    checks.append(ValidationCheck(
        check_id="C-V2-009",
        passed=True,
        detail=f"sidecar conditional fallback 计数: total={total_fallbacks}, by_reason={fallback_counts}",
    ))
    return ValidationReport(
        generated_at=_utc_now_iso(),
        checks=checks,
        sidecar_fallback_counts=fallback_counts,
    )


def run_worldgenerator_fullcoverage_framework_v2(
    output_dir: Path = DEFAULT_WORLDGEN_FULLCOVERAGE_OUTPUT_DIR,
    count: int = DEFAULT_BATCH_WORLD_COUNT,
    seed: int = DEFAULT_BATCH_RANDOM_SEED,
    batch_config: Optional[Dict[str, Any]] = None,
    fragment_count_per_building: int = 4,
    building_workers: int = 1,
    progress_file: Optional[str] = None,
    progress_interval: int = 50,
) -> Dict[str, Any]:
    """W0 + W1 + W2 主 pipeline，按 spec 顺序串行执行 7 步：

    - Step 1：加载 W0 资源（_build_registry_bundle，含 19 张 registry +
      sidecar contract，按 W0 规格 02 §1 资源域 + 规格 11 §4 inventory）
    - Step 2：W1 实例生成（generate_world_batch → List[WorldBundle]，
      按 W0 规格 05 §1 + W1 规格 03 九段函数 + W1 规格 04 实施卡）
    - Step 3：W1 sidecar 派生（_build_sidecar_runtime_bundle_for_buildings，
      按 W0 规格 09 §1.2 双路径派生 + W1 规格 09）
    - Step 4：W1 validation 报告（_build_v2_validation_report，
      按 W1 规格 07 §2 C-V2-001..008 八条 check）
    - Step 5：写 W0+W1 4 个 parquet（registry / world bundles / sidecar contract /
      sidecar runtime / validation report，按 W0 规格 15 parquet schema）
    - Step 6：W2 phase 3 投影（build_normative_projections_for_world，per-fragment
      NormativeProjection 派生，按 W2 规格 04 §3 phase 3 主入口 + 规格 09 §1
      输出契约）
    - Step 7：写 W2 输出 parquet（normative_projection，按 W0 规格 15 parquet
      schema W2 段）

    参数 → 行为：count 决定 batch 规模；seed + registry_bundle_hash +
    batch_config_hash → deterministic_key 保 byte-identical 复现（W1 规格 01 §6
    reproducibility 红线）。building_workers 控制 Step 2 多进程并发数（QA-Parallelize
    2026-05-09）。

    Returns: dict 含 7 个 path（4 个 W0+W1 输出 + 1 个 validation report +
    1 个 W2 projection 输出 + output_dir），加 metadata（deterministic_key /
    registry_bundle_hash / counts / validation_pass）。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    registry_bundle = _build_registry_bundle()
    registry_bundle_hash = _hash_payload(
        {
            "version": registry_bundle.version,
            "source_documents": registry_bundle.source_documents,
            "registries": registry_bundle.model_dump(mode="json")["registries"],
        }
    )
    batch_profile = _resolve_batch_profile(count)
    # 🔴 `batch_config_hash` 名字说是「批配置哈希」，实际是**白名单**取字段
    # （2026-07-29 查实：此前只取 `archetype_distribution` 一个键）。
    # 后果：任何其它 `batch_config` 旋钮都会**影响世界生成但不进哈希**
    # ⇒ 两个内容不同的池拿到**同一个 `deterministic_key`**，锚区分不出它们。
    # 实测：开 `ensure_component_type_coverage` 后 generated 格 23→34，而键逐位相同。
    #
    # 修法保持**缺省等价**：新键**只在为真时**才进哈希载荷 ⇒ 既有池（开关关）
    # 的 `deterministic_key` 一个字节不变、仍可复现；开关一开即得新身份。
    # ⏳ 遗留：白名单本身仍是隐患——下一个旋钮若忘了在这里登记，同样静默同键。
    #    根治要改成「整个 batch_config 规范化后入哈希」，但那会改掉所有既有池的键，
    #    须与换锚一并做，不在本次范围内。
    _batch_hash_payload = {
        "generator_version": GENERATOR_VERSION,
        "requested_count": count,
        "seed": seed,
        "batch_profile": batch_profile,
        "schema": "building_centric.v2",
        "archetype_distribution": (batch_config or {}).get("archetype_distribution"),
    }
    if (batch_config or {}).get("ensure_component_type_coverage"):
        _batch_hash_payload["ensure_component_type_coverage"] = True
    # 🔴 `fragment_count_per_building` 是**函数签名上公开、且真被消费**的旋钮
    #    （见本函数 :267 形参与 :347 传递），却一直不在哈希载荷里
    #    ⇒ `fragment_count_per_building=4` 与 `=8` 会生成**不同世界内容**、
    #    却拿到**同一个 `batch_config_hash` / `deterministic_key`**。
    #    这不是未来风险，是当前可调参数造成的确定性同键（codex 审核门 2026-07-30 指出）。
    #    同样按**缺省等价**处理：只有偏离默认值 4 时才进载荷 ⇒ 既有池键逐位不变。
    if fragment_count_per_building != 4:
        _batch_hash_payload["fragment_count_per_building"] = fragment_count_per_building
    batch_config_hash = _hash_payload(_batch_hash_payload)
    deterministic_key = _hash_payload(
        {
            "generator_version": GENERATOR_VERSION,
            "registry_bundle_hash": registry_bundle_hash,
            "random_seed": seed,
            "batch_config_hash": batch_config_hash,
            "schema": "building_centric.v2",
        }
    )

    building_worlds = generate_world_batch(
        batch_config=batch_config or {},
        registries=registry_bundle,
        count=count,
        seed=seed,
        fragment_count_per_building=fragment_count_per_building,
        building_workers=building_workers,  # QA-Parallelize 2026-05-09
        progress_file=progress_file,
        progress_interval=progress_interval,
    )

    sidecar_contract = _build_sidecar_contract()
    # 🔴🔴 sidecar 随机流：本函数**不再持有** sidecar rng（波次二 #22「rng 隔离 1a」）。
    #
    # 沿革（两步，各自单独验过，别把它们混成一件事）：
    #
    # **1a-0 解绑**：旧写法 `sidecar_rng = Random(int(deterministic_key[:16], 16))`
    # 把 sidecar 流挂在 `deterministic_key` 上，而 `deterministic_key` ←
    # `registry_bundle_hash` ← **全部注册表的完整 model_dump**（见 :302-308 / :340-348）。
    # 后果：改**任何**一张注册表的**任何**字段（哪怕与 sidecar 毫无关系）都换种子、
    # 整批 sidecar 重掷。实测（50 栋 seed401，只把 `RegistryBundle.version` 加个后缀
    # ——generator/sidecar 都不读它，对世界生成完全惰性）：世界侧 13 个比较单元
    # 逐字节不变，而 `sidecar_entries` 变 **8,119/19,090**、`expected_verdict`
    # 翻 **113/340 ＝ 33.2%**、`pass_bool` 差 763/11,318。⇒ 波次二每一件动注册表的改动
    # 都自带一次 33% 量级的背景翻判，任何单件改动自己的效应都会被淹没、无法归因。
    #
    # **1a-i′ 槽级化**：批级流整条退役，采样改由 `rng_domains.sub_rng` 按
    # `(域串, world_id[, fragment_id], slot_id[, combo])` 派生 ⇒ 连「第 i 栋片段数一变、
    # 第 i+1..n 栋全部移位」这条跨栋顺序依赖也一并消失（那是 1a-0 治不了的另一半）。
    #
    # ⚠️ **只解流、不解锚**：`deterministic_key` / `registry_bundle_hash` 照旧计算、
    #    照旧写进各 meta 与 cohort manifest ⇒ 池身份与复现契约一个字节不变。
    #    改注册表仍然换池身份（该换），只是不再改 sidecar 的值。
    #
    # W1-012 / W1-RC-02：sidecar conditional fallback 计数挂入 ContextVar，with 块退出后
    # 把收集到的 dict 接进 validation_report（framework v2 主入口无 BatchGateStats，故落
    # validation_report 作持久化 audit 产物——spec 10 §6 silent fallback 批次级可见性落地点）.
    with audit_capture_sidecar_fallback() as _sidecar_fallback_counts:
        sidecar_runtime_bundle = _build_sidecar_runtime_bundle_for_buildings(
            building_worlds,
            registries=registry_bundle,
        )

    validation_report = _build_v2_validation_report(
        building_worlds=building_worlds,
        sidecar_runtime_bundle=sidecar_runtime_bundle,
        registry_bundle_hash=registry_bundle_hash,
        batch_config_hash=batch_config_hash,
        deterministic_key=deterministic_key,
        sidecar_fallback_counts=dict(_sidecar_fallback_counts),
    )

    registry_bundle_path = _write_json(
        output_dir / "WorldgenRegistryBundle.v2.json",
        registry_bundle.model_dump(mode="json"),
    )
    # 2026-05-10 全替换：world bundles 写 parquet directory
    building_worlds_payload = {
        "version": "worldgen.fullcoverage.building_worlds.v2",
        "generated_at": _utc_now_iso(),
        "registry_bundle_hash": registry_bundle_hash,
        "batch_config_hash": batch_config_hash,
        "deterministic_key": deterministic_key,
        "buildings": [bw.model_dump(mode="json") for bw in building_worlds],
    }
    building_worlds_path = write_world_bundles_parquet(
        output_dir / WORLD_BUNDLES_PARQUET_DIR_NAME, building_worlds_payload,
    )
    sidecar_contract_path = _write_json(
        output_dir / "WorldgenSidecarContract.v2.json",
        sidecar_contract.model_dump(mode="json"),
    )
    sidecar_runtime_bundle_path = write_sidecar_runtime_parquet(
        output_dir / SIDECAR_RUNTIME_PARQUET_DIR_NAME,
        sidecar_runtime_bundle.model_dump(mode="json"),
    )
    validation_report_path = _write_json(
        output_dir / "WorldgenFullCoverageValidation.v2.json",
        validation_report.model_dump(mode="json"),
    )
    # spec 草案·DEBT-049 第三波 件A A.4：可生成性审计台账（硬产物）——闭世界
    # 总声明后"防伪装建模缺口"的新承担者：楼型×组件类×缺陷类三态
    # （generated / reachable_not_generated / unreachable）+ 计数 + 样本 fragment。
    _write_json(
        output_dir / "ClassReachabilityAudit.v1.json",
        build_class_reachability_audit(building_worlds),
    )

    # Missing #2: per fragment 派生 NormativeProjection（spec 04 §16）+ 输出 parquet
    # spec 09 §1.2 修订：传入 sidecar_runtime_bundle 让 sidecar slot 进入 threshold eval
    # Codex W2 perf root cause fix (2026-05-27)：sidecar_numeric_by_fragment 索引
    # 建一次共享给 N building W2 调用，避免 O(N²) 扫 sidecar bundle (1500×1=246s 推
    # 12000×5 理论 33min, 实测卡 67min+ 的根因)
    sidecar_numeric_by_fragment = build_sidecar_numeric_index(
        sidecar_runtime_bundle, registry_bundle
    )
    # DEBT-044 修根 (2026-06-11)：coverage-controlled rejection 改批级楼级取舍.
    # 旧做法（W2-007）逐楼调 _with_coverage_control 入口，把批级配额（ratio×N）
    # 套在单楼 N=4 候选上做 per-fragment 截断 → 每楼 4 candidate 砍剩 1，
    # 被接受楼参考真值残缺（DEBT-044）。
    # 新做法（spec 11 §1.2 原则二 "按 batch 内 NormativeProjection 分布判断" +
    # §3.3 candidate = W1 candidate = building world）：
    #   1) 逐楼产全量 candidate（apply_coverage_control=False）；
    #   2) 收齐全部楼后调 apply_coverage_control_rejection_building_level 一次，
    #      楼级 accept/reject——被接受楼保留全部 fragment projection（真值完整），
    #      被拒楼整楼 0 条（可识别，不进数据池）；
    #   3) per-world coverage_control_metadata（spec 11 §3.2 6 字段，候选计数单位=楼）
    #      仍逐楼挂 payload，execute_projection_batch_v2 phase 4 聚合求和即批级计数.
    per_world_candidates: List[Tuple[str, List[Dict[str, Any]]]] = []
    for bw in building_worlds:
        candidates = build_normative_projections_for_world(
            bw, registry_bundle, sidecar_runtime_bundle=sidecar_runtime_bundle,
            apply_coverage_control=False,
            sidecar_numeric_by_fragment=sidecar_numeric_by_fragment,
        )
        per_world_candidates.append((bw.world_id, candidates))
    accepted_world_ids, per_world_coverage_meta, _batch_coverage_meta = (
        apply_coverage_control_rejection_building_level(per_world_candidates)
    )
    accepted_world_id_set = set(accepted_world_ids)
    normative_projections_by_world: List[Dict[str, Any]] = []
    for world_id, candidates in per_world_candidates:
        accepted_projections = (
            candidates if world_id in accepted_world_id_set else []
        )
        normative_projections_by_world.append({
            "world_id": world_id,
            "projection_count": len(accepted_projections),
            "projections": accepted_projections,
            # W2-007 spec 11 §3.2：per-world coverage_control_metadata（6 字段；
            # 不污染 NormativeProjection 内字段；execute_projection_batch_v2 phase 4
            # 聚合时按 world 维度合并产 batch-level CoverageControlBatchMetadata）.
            "coverage_control_metadata": per_world_coverage_meta[world_id],
        })
    normative_projection_path = write_normative_projection_parquet(
        output_dir / NORMATIVE_PROJECTION_PARQUET_DIR_NAME,
        {
            "version": "worldgen.fullcoverage.normative_projection.v2",
            "generated_at": _utc_now_iso(),
            "registry_bundle_hash": registry_bundle_hash,
            "deterministic_key": deterministic_key,
            # DEBT-054 Block B.5 forward-only 修（2026-07-14）：orchestrator 边界显式传真实
            # profile 标签，令 cohort manifest 绑真实 profile（原空串占位破 B.5 冻结保护）。
            # canonical_profile_id = 顶层中立包真实标签；identity_schema = pending 常量（Block A
            # closure 两阶段身份未落地于 W2 侧，落地后透传真实 closure identity_schema 值）。
            "canonical_profile_id": CANONICAL_PROFILE_ID,
            "identity_schema": IDENTITY_SCHEMA_PENDING,
            "buildings": normative_projections_by_world,
        },
    )

    return {
        "schema": "building_centric.v2",
        "output_dir": str(output_dir),
        "requested_count": count,
        "seed": seed,
        "deterministic_key": deterministic_key,
        "registry_bundle_hash": registry_bundle_hash,
        "registry_bundle_path": str(registry_bundle_path),
        "building_worlds_path": str(building_worlds_path),
        "sidecar_contract_path": str(sidecar_contract_path),
        "sidecar_runtime_bundle_path": str(sidecar_runtime_bundle_path),
        "validation_report_path": str(validation_report_path),
        "normative_projection_path": str(normative_projection_path),
        "normative_projection_count": sum(
            entry["projection_count"] for entry in normative_projections_by_world
        ),
        "validation_pass": all(check.passed for check in validation_report.checks),
        "buildings_count": len(building_worlds),
        "fragments_count": sum(len(bw.fragments) for bw in building_worlds),
        "measurements_count": sum(len(bw.measurements) for bw in building_worlds),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="W0 worldgen full-coverage v2 framework runner.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_WORLDGEN_FULLCOVERAGE_OUTPUT_DIR)
    parser.add_argument("--count", type=int, default=DEFAULT_BATCH_WORLD_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_BATCH_RANDOM_SEED)
    args = parser.parse_args()
    result = run_worldgenerator_fullcoverage_framework_v2(
        output_dir=args.output_dir, count=args.count, seed=args.seed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
