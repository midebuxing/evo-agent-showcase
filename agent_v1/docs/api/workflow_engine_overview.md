# `workflow_engine` 架构导航（人工补充）

> 自动 API 参考（每模块函数/类签名 + docstring + pydantic 字段表）：[`workflow_engine.md`](./workflow_engine.md)
>
> 本文聚焦“怎么用、入口在哪、别踩哪些坑”，不复述每个函数签名（那是自动参考的事），也不复述 spec 正文。设计背景见文末“设计背景导航”。

---

## 1. 一句话定位

`workflow_engine` 是 evo-agent 四层架构里的**数据生成与法规投影层**——它产出实验台的“世界”：

- **W0/W1（worldgen）**：按注册表 + 物理公式生成一批 building world（建筑实例），rule-blind（不读法规），输出 `WorldBundle` + sidecar 派生 + parquet 列存。
- **W2（法规映射层）**：在 W1 输出之上做 per-fragment 法规投影（threshold regime 评估、family 适用性、unknown 归因、coverage-controlled rejection），产出 `NormativeProjection` 参考真值——给评测阅卷用，**不喂给 evo-agent**（否则 agent 抄答案、违反 blind）。

它**不是** evo-agent 本身（感知/认知/底线/进化四层的运行体在 `evo_agent_baseline` 包），也**不是**闭包验证器。本包是“出题 + 标准答案”的一侧。

> 注意命名：本包内有 `closure_validator.py` / `nodes.py` / `graph.py` / `state.py` 一组 LangGraph 工件，那是早期 baseline 工作流台架（`RuleCard + FactPack → EvidencePack`），跟 worldgen/W2 主线是**两条相对独立的支线**，共享本包命名空间但数据流不交叉。见 §3.3 与 §5 消歧。

---

## 2. 子包 / 核心模块职责表

### 2.1 W0/W1 数据生成（`worldgen/` 子包）

| 模块 | 职责（一行） |
| --- | --- |
| `worldgen/generator.py` | building world 生成主体：archetype 抽样 → building/component/location/fragment → driver/mechanism/condition/measurement。入口 `generate_world_bundle`（单楼）/ `generate_world_batch`（批） |
| `worldgen/models.py` | W0/W1 全部 pydantic 输出对象（`WorldBundle` / `FragmentContext` / `ComponentNode` / `MechanismState` / `SidecarRuntimeBundle` / `FrameworkSummary` 等 38 个），是 worldgen 的 schema 契约 |
| `worldgen/registry.py` | 19 张注册表 + sidecar contract 的构造（`_build_registry_bundle` / `_build_sidecar_contract`）；所有结构数据来源，无 hardcoded business data |
| `worldgen/validation.py` | **W0+W1+W2 串行主 pipeline 入口** `run_worldgenerator_fullcoverage_framework_v2`（7 步：注册表→实例→sidecar→校验→parquet→投影→W2 parquet）。本包对外最重要的总入口 |
| `worldgen/gates.py` | 生成时 P0/P1/P2 gate 框架：P0 reject 触发整楼重采、P1 repair、P2 inline clamp。入口 `apply_gate_with_retry` |
| `worldgen/checks.py` | C001-C032 gate check 函数，import 时副作用注册进 `gates.py`（无公开 API，靠 import 触发） |
| `worldgen/conditional_eval.py` | sidecar bool/enum slot 的条件公式采样器（sigmoid/softmax + centered 变体），spec 06 §11.6 |
| `worldgen/round6_formulas.py` | 45 个 sidecar slot 的 centered conditional formula 数据定义（`get_round6_round7_formulas`） |
| `worldgen/sidecar.py` | sidecar 派生层（procedure/supervision/artifact/facts 桶），静态注册表驱动、不收外部 runtime 输入 |
| `worldgen/noise_models.py` | spec 06 §14 命名噪声模型 + precision rounding（pure function） |
| `worldgen/parquet_io.py` | W0/W1/W2 三层共用 parquet 列存读写（9+3+6 张子表）。`write_*_parquet` / `read_*_parquet` / `is_*_parquet_dir` |
| `worldgen/p2_audit.py` | P2 inline clamp 的 contextvar accumulator（`audit_capture` context manager） |
| `worldgen/seed.py` / `worldgen/constants.py` | 确定性种子工具 / 常量（无公开顶层 API） |
| `worldgen/audits/` | W1 输出反作弊/反泄漏 audit 套件（5 项）：见下表 |

### 2.2 W1 输出审计（`worldgen/audits/` 子子包）

| 模块 | 职责（一行） |
| --- | --- |
| `audits/schema_firewall.py` | 静态扫：W1 输出对象字段名禁含 `rule_family`/`threshold`/`gold`/`verdict` 等 token（`schema_firewall_audit`） |
| `audits/projection_rule_use.py` | 静态扫：`worldgen/` 主代码不得 import rule_card / W2 模块（`projection_rule_use_audit`） |
| `audits/round_trip_parse.py` | bundle parquet write→read→byte-identical 一致性（`round_trip_parse_audit`） |
| `audits/leakage_surface.py` | W1 surface 特征不能用 logreg probe 反推 family（`leakage_on_surface_audit`） |
| `audits/held_out_split.py` | family stratified 三段 split + 约束校验（`held_out_family_split` / `validate_held_out_split`） |

### 2.3 W2 法规映射层（包根下 `regulation_*` 模块）

| 模块 | 职责（一行） |
| --- | --- |
| `regulation_projection_executor.py` | **W2 投影核心**：per-fragment family 冲突解析 / threshold regime 5-bin 分类 / unknown 归因 / sidecar join 状态 / per-world 投影 + 批级 v2 聚合。入口 `build_normative_projections_for_world` + `execute_projection_batch_v2` |
| `regulation_projection_models.py` | W2 输出对象：`NormativeProjection`（per-fragment 主输出）/ `ThresholdEval` / `ProjectionFamilyEval` / `ReportBasisItem` / `CoverageControlBatchMetadata` |
| `regulation_coverage_control.py` | W2 coverage-controlled rejection（楼级 accept/reject filter）。批级入口 `apply_coverage_control_rejection_building_level`（见 §3.2 + §4 坑） |
| `regulation_thresholds.py` | 从 `rule_cards_delta.jsonl` 加载真阈值（替代占位阈值），按 W0 family prefix 匹配（`get_thresholds_for_w0_family` 等，带缓存索引） |
| `regulation_projection.py` | **W2 CLI**：`compile` / `execute` / `run-worldgen-batch` 三子命令；`execute` 调 `execute_projection_batch_v2` |
| `regulation_projection_contract.py` | 把 rule_card bundle 编译成 projection contract / compiled spec（`compile_projection_contract` 等） |
| `regulation_projection_mapping.py` | runtime mapping JSON 的小 loader（`load_runtime_mapping`）；轻量工具 |
| `rulecard_v2.py` | RuleCard v2 bundle loader + 语义规范化校验 + 派生索引重建（`load_rulecard_bundle` / `RuleCardBundle` + CLI `main`） |

### 2.4 baseline LangGraph 工作流台架（包根，支线）

| 模块 | 职责（一行） |
| --- | --- |
| `graph.py` / `nodes.py` / `state.py` | LangGraph build/节点/状态：`build_graph` 接 retrieve→assess→human_review→generate_report；`nodes.py` 构造 `EvidencePack` |
| `evidence_schema.py` | `EvidencePack` 及其子对象（`TaskGraph` / `RuleCard` / `FactPack` / `DecisionTrace` / `Obligation` 引用） |
| `obligation_schema.py` | `Obligation` / `ObligationSet` / `ClosureSummary` / `ClosureValidationResult` |
| `closure_validator.py` | `validate_closure(rule_cards, fact_pack) -> ClosureValidationResult`（本包内的轻量闭包评估，**非** evo-agent 底线层权威，见 §5） |
| `fact_feature_pattern_schema.py` / `_matcher.py` | fact feature/pattern 目录 schema + 匹配（`match_fact_pack`） |
| `fact_trigger_contract.py` | seed trigger spec 评估（`evaluate_trigger_specs`，见 §5 消歧） |
| `skill_candidate_*.py` / `skill_eval_*.py` / `trigger_routing_*.py` | 技能候选草稿构建 / 技能评测报告 / trigger 路由数据集 + ranker（baseline 侧实验工件） |

---

## 3. 关键入口与数据流

### 3.1 主线：从 batch_config 到 W2 参考真值（一次跑通全链）

唯一的“全链总入口”是 `worldgen/validation.py::run_worldgenerator_fullcoverage_framework_v2`。典型调用（见 `scripts/run_long_run_qa.py`）：

```python
from workflow_engine.worldgen.validation import run_worldgenerator_fullcoverage_framework_v2

result = run_worldgenerator_fullcoverage_framework_v2(
    output_dir=Path(...),      # 输出目录
    count=1500,                # batch 楼数
    seed=42,                   # 确定性种子
    building_workers=8,        # Step 2 多进程并发
)
# result: dict，含 7 个产物 path + deterministic_key / counts / validation_pass
```

数据流（该函数 docstring 列的 7 步）：

```
batch_config + registries(19 张)            [Step 1 registry.py]
        │
        ▼  generate_world_batch (多进程, 每楼 deterministic seed)
List[WorldBundle]  (building/fragment/mechanism/condition/measurement)   [Step 2 generator.py]
        │
        ▼  _build_sidecar_runtime_bundle_for_buildings
SidecarRuntimeBundle  (procedure/supervision/artifact/facts 桶)          [Step 3 sidecar.py]
        │
        ▼  _build_v2_validation_report (C-V2-001..008)                    [Step 4 validation.py]
        ▼  写 4 个 parquet (registry/world/sidecar contract/sidecar runtime) [Step 5 parquet_io.py]
        │
        ▼  build_normative_projections_for_world (per 楼, per fragment)   [Step 6 W2 executor.py]
        │     + 收齐全部楼后 apply_coverage_control_rejection_building_level (楼级取舍)
List[NormativeProjection]  (参考真值)
        │
        ▼  写 normative_projection parquet                                [Step 7 parquet_io.py]
```

要点：Step 6 的 W2 投影由 `validation.py` 在收齐全部楼的全量 candidate 后**一次性**调批级 coverage control（`apply_coverage_control_rejection_building_level`），而非每楼单独裁剪——这是 DEBT-044 修根后的关键约束（见 §4 坑 1）。

### 3.2 W2 单独跑（已有 worldgen 输出，只补投影聚合）

不重新生成世界、只对已有 parquet 跑 W2 聚合时走 `regulation_projection.py` CLI：

```
python -m workflow_engine.regulation_projection run-worldgen-batch <batch_dir> <output_dir>
```

`run-worldgen-batch` 从 `batch_dir` 读三件 parquet（`WorldgenWorldBundles.v2.parquet/` 等），调 `execute_projection_batch_v2` 输出 `projection_results/summary/samples`。`execute_projection_batch_v2` **只做批级聚合**——per-fragment 投影评估在 worldgen Step 6 已完成并落 `NormativeProjection` parquet。

### 3.3 支线：baseline LangGraph 工作流

`graph.py::build_graph()` 装配 LangGraph（`AgentState` 流过 retrieve→assess→human_review→generate_report 节点），`nodes.py::build_evidence_pack_for_case` 把 `TaskGraph + RuleCard + FactPack + DecisionTrace` 组装成 `EvidencePack` 写盘。这条支线产出 `EvidencePack` artifact，跟 worldgen/W2 的 `WorldBundle`/`NormativeProjection` 数据流不交叉。技能候选/评测/路由（`skill_*` / `trigger_routing_*`）是在这些 run artifact 之上做的离线分析工件。

---

## 4. 必须避开的坑

1. **不要每楼单独调 coverage control 当批级用**。`apply_coverage_control_rejection`（单楼版）DEBT-044 修根后语义改成“单楼无批内分布可参照、不做任何裁剪、全量接受 + 出楼级分类 metadata”。真正的 accept/reject 是楼级取舍，只能走 `apply_coverage_control_rejection_building_level`（收齐全部楼后调一次）。历史 bug：旧实现把批级配额套在单楼 N=4 列表上 per-fragment 截断，每楼砍剩 1 个 fragment，把被接受楼的参考真值砍残，导致下游无法做完整闭包核验（DEBT-044 / 项目记忆 `project_w2_coverage_rejection_bug`）。
2. **`build_normative_projections_for_world` 的 `apply_coverage_control=True/False` 现在返回相同列表**（均为该楼全量 candidate）——这个参数在单楼粒度下已无裁剪效果，别指望它做楼内过滤。
3. **`generate_world_bundle` 不自动 wrap P2 audit**。要 P2 clamp audit trace 必须自己 `with audit_capture() as acc:`。走 `generate_world_batch_with_stats` 已内置 wrap；单独调 `generate_world_bundle` 不 wrap 不会报错，但 P2 事件会 silently 丢（spec 边界设计）。
4. **`worldgen/checks.py` 靠 import 副作用注册 check**。`generator.py` 顶部有 `import workflow_engine.worldgen.checks  # noqa: F401` 触发注册；绕过这条 import 直接用 gate 会得到空 check 列表。
5. **W2 输出是参考真值、不喂 agent**。`NormativeProjection` / coverage bucket / target ratio 都是阅卷与审计材料，不进 evo-agent feature pipeline（spec 11 NI-004 / 项目记忆 `feedback_closure_verification_agent_not_datagen`）。
6. **跑批 high-level 指标 PASS 不代表实验有效**。下钻 `closure_summary.blocked_reason_counts` / regime 分布再下结论（项目记忆 `feedback_drill_down_run_results`）。
7. **本包无顶层 `__init__.py`**（命名空间包），`worldgen/__init__.py` 也基本是空的。导入要靠 `PYTHONPATH=agent_v1/src` + 全限定模块名（如 `from workflow_engine.worldgen.validation import ...`），没有“`from workflow_engine import X`”的捷径。

---

## 5. 公开 API 面 vs 内部实现

本包**没有用 `__init__.py` 的 `__all__` 显式声明公开面**（包根无 `__init__.py`，`worldgen/__init__.py` 仅留 docstring，无 re-export）。因此“公开面”靠**约定**判断：

- **稳定对外入口（调用方该用这些）**：
  - 全链总入口 `worldgen.validation.run_worldgenerator_fullcoverage_framework_v2`
  - W2 批级聚合 `regulation_projection_executor.execute_projection_batch_v2` + CLI `regulation_projection.main`
  - 单元入口 `worldgen.generator.generate_world_bundle` / `generate_world_batch` / `generate_world_batch_with_stats`
  - W2 per-fragment 投影 `regulation_projection_executor.build_normative_projections_for_world`
  - coverage control 批级入口 `regulation_coverage_control.apply_coverage_control_rejection_building_level`
  - parquet 读写 `worldgen.parquet_io.{write,read,is}_*`
  - audit 套件（5 个 `*_audit` 函数）
  - baseline 侧 `graph.build_graph` / `nodes.build_evidence_pack_for_case`
- **内部实现（前缀 `_` 或仅被主入口调用，外部别直接接线）**：
  - `worldgen.registry._build_registry_bundle` / `_build_sidecar_contract`
  - `worldgen.sidecar._build_sidecar_runtime_bundle_for_buildings`
  - `worldgen.validation._build_v2_validation_report`
  - `worldgen.constants._hash_payload` / `_resolve_batch_profile` / `_write_json` 等
  - `regulation_coverage_control.apply_coverage_control_rejection`（单楼版，DEBT-044 后已是“无裁剪 + 楼级分类 metadata”语义，外部别当批级 filter 用）
  - `regulation_projection_executor` 里的 `resolve_family_conflict` / `derive_unknown_reason_code` / `classify_threshold_regime` 等是投影内部组件，正常通过 `build_normative_projections_for_world` 间接走

---

## 6. 同名消歧（容易用错的）

### 6.1 `build_fact_pack` — 两个不同包，别混

| 位置 | 签名 | 干嘛 |
| --- | --- | --- |
| `workflow_engine.nodes.build_fact_pack` | `(*, case_id, phase, description, case_dir: Path) -> FactPack` | baseline LangGraph 工作流里从 case 目录组装 `FactPack`（本包 §3.3 支线用） |
| `evo_agent_baseline.retrieval.pack_builder.build_fact_pack` | （不同包，retrieval 侧检索打包） | evo-agent 检索层的 fact pack 构建，跟本包无关 |

→ 在 `workflow_engine` 里说 `build_fact_pack` 默认指 `nodes.py` 那个；跨包引用务必写全限定路径。

### 6.2 `evaluate_trigger` vs `evaluate_trigger_specs` — 名字像、不是一回事

| 名字 | 位置 | 签名要点 |
| --- | --- | --- |
| `evaluate_trigger_specs` | `workflow_engine.fact_trigger_contract` | `(*, trigger_specs: List[SeedTriggerSpec], matched_feature_ids, matched_pattern_ids) -> List[Dict]`——批量评估 seed trigger spec（本包内） |
| `evaluate_trigger`（单数） | `evo_agent_baseline.closure.obligation_deriver` | 不同包的 obligation 派生用 trigger 评估，签名不同 |

→ 本包内只有复数的 `evaluate_trigger_specs`；单数 `evaluate_trigger` 不在本包，别张冠李戴。

### 6.3 `validate_closure`（本包）vs `validate_building_closure`（evo-agent 底线层）

| 名字 | 位置 | 定位 |
| --- | --- | --- |
| `workflow_engine.closure_validator.validate_closure` | 本包 baseline 支线 | `(rule_cards, fact_pack, seed_rule_bridge?) -> ClosureValidationResult`，本包内轻量闭包评估 |
| `evo_agent_baseline.closure.validator.validate_building_closure` | **另一个包** | evo-agent 底线层**权威**闭包验证器入口（`RuleSlice + FactPack → ClosureValidationResult`，`allow_stop` 唯一权威，见项目记忆 `feedback_closure_verifier_definition`） |

→ 谈“闭包验证器”默认指 evo-agent 那个 `validate_building_closure`，**不是**本包的 `validate_closure`。本包的 `validate_closure` 只是 baseline 台架内的实现。

### 6.4 `main` / `build_parser` — 多个模块各有 CLI

`main` 在本包出现于 `regulation_projection` / `rulecard_v2` / `fact_feature_pattern_matcher` / `worldgen.validation`（还跟 `research_kg` 包同名）。`build_parser` 在 `regulation_projection` 与 `fact_feature_pattern_matcher` 各一份。都是各模块自己的 CLI 入口，按 `python -m <模块全路径>` 调，互不相干。

---

## 7. 设计背景导航（spec 包路径，本文不复述其内容）

- W0/W1 数据生成：`团队文档/我的笔记/蓝图汇总/W0新版全量实现级设计规格包/`（registry / 生成流程 / surrogate 公式噪声 / parquet schema / sidecar 边界）
- W2 法规映射层：`团队文档/我的笔记/蓝图汇总/W2法规映射层全量实现级设计规格包/`（projection executor 函数总览 / threshold regime 与冲突回退 / unknown 策略 / 输出契约 NormativeProjection / `11_coverage_controlled_rejection.md`）
- evo-agent 总设计：`团队文档/我的笔记/蓝图汇总/evo-agent_v1_设计规格.md`
- 技术债与跟踪：`团队文档/我的笔记/技术与研究债.md`（DEBT-031 coverage target ratio gap / DEBT-044 coverage rejection 修根）
