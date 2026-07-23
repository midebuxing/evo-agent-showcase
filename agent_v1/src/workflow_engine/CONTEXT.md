# workflow_engine 顶层散 .py —— W2 法规映射层门口卡

> 给 AI / 新人的"最小上下文卡"：改这块，**先读这张卡 + 下面点名的文件**就够，不用翻全仓。
> （引文件名+函数名，不引行号——行号会漂。）
> **本卡只管 `workflow_engine/` 顶层散 .py = W2 法规映射层；`worldgen/` 子目录有自己的卡，不在这找。**

## 这块干什么（一句话）
W2 法规映射层：吃 W0+W1 世界（building world + sidecar），把 rule_card 投影到每栋楼上，**产出参考真值 `NormativeProjection`（含 `expected_verdict`）**——只给评测阅卷用，agent 运行时绝不看。

## 入口
- `execute_projection_batch_v2(building_worlds_path, normative_projection_path, sidecar_runtime_path, output_dir) -> paths` —— 在 `regulation_projection.py`。批量主入口，吃三件 parquet 吐 `projection_results/summary/samples.json`。
- `build_normative_projections_for_world(...)` —— 同文件，单栋楼投影核心（batch 内部调）。
- `write_projection_compile_artifacts(output_dir, bundle_dir)` —— 在 `regulation_projection_contract.py`，编译 rule_card bundle → projection contract/spec/manifest（跑投影前的准备步）。

## 改这块只需加载（按需，多数任务 2-3 个就够）
| 文件 | 管什么 | 什么时候看 |
|---|---|---|
| `regulation_projection.py` | 投影主逻辑：family 冲突消解、unknown_reason_code 派生、阈值 regime 分类、单栋/批量投影 | 改投影怎么算/参考真值口径 |
| `regulation_projection_executor.py` | V2 batch executor：读三件 parquet、聚合、落 summary/results/samples | 改批量 I/O、输出契约 |
| `regulation_projection_models.py` | 输出 DTO：`NormativeProjection`/`ProjectionFamilyEval`/`ThresholdEval`/`ReportBasisItem` | 看参考真值长什么样 |
| `regulation_projection_contract.py` | rule_card bundle → 编译产物（contract/spec/manifest）| 改投影编译准备 |
| `regulation_projection_mapping.py` | 加载 `projection_runtime_mapping_v1.json`（slot/measure 别名映射）| 改 W0↔法规 slot 对齐 |
| `regulation_thresholds.py` | 从 `rule_cards_delta.jsonl` 加载真阈值（替 placeholder）| 改阈值取数 |
| `regulation_coverage_control.py` | 楼级 accept/reject 过采控制（近阈值/邻族/可恢复缺失三桶）| 改覆盖率控制/拒采 |
| `rulecard_v2.py` | rule_card v2 bundle loader + 命名规范校验 + 索引重建 | 改 rule_card 结构/校验 |

## 红线 / 不变量（改这块绝不能破）
1. **W2 产真值，是 blind 红线的"另一端"**：`NormativeProjection`/`expected_verdict` 只喂 `eval/` 旁路阅卷，**绝不回传给 W1、绝不进 agent 运行时**。喂真值给 agent = 抄答案。
2. **rule-blind 红线只属 W0/W1，不套 W2**：W2 消费法规（读 rule_card threshold/family/predicate）是本职，别把 worldgen 端"不看法规"红线错套过来。
3. **coverage 控制三不**：per-sample 拒采 trace 不进 `NormativeProjection` 字段；coverage target ratio 不作 evo-agent feature；拒采原因不回传 W1（rule-blind）。
4. **分层单向 + spec 单向**：感知层 `workflow_engine` ⊥ 认知/进化层 `evo_agent_baseline`（互不 import）；W2→W0 单向消费 `worldgen.constants` 是允许边界，反向不行；派生函数接主链前先核 spec 授权。
5. **环境**：导入需 `$env:PYTHONPATH="agent_v1\src"`；rule_card / 阈值走 `regulations/rulecard_v2/mbis_cop_2023/` 文件，不连库。

## 改完跑哪个测试
```
$env:PYTHONPATH="agent_v1\src"
python -m pytest agent_v1\tests\test_regulation_projection_conflict_group.py agent_v1\tests\test_regulation_projection_unknown_reason_code.py agent_v1\tests\test_regulation_projection_threshold_regime.py agent_v1\tests\test_regulation_thresholds.py agent_v1\tests\test_execute_projection_batch_v2.py agent_v1\tests\test_normative_projection_builder.py agent_v1\tests\test_coverage_controlled_rejection.py agent_v1\tests\test_rulecard_v2.py -q
```
（W2 测试在**顶层** `agent_v1\tests\`，不在 `workflow_engine\tests\`——本层没有自己的 tests 目录。）

## 常见任务 → 看哪个文件
- 改投影怎么算 / family 冲突消解 / unknown 归因 → `regulation_projection.py`
- 改批量输入输出（三件 parquet / summary 字段）→ `regulation_projection_executor.py`
- 加 / 改参考真值字段 → `regulation_projection_models.py` 的 `NormativeProjection` 等，再看谁消费
- 改阈值比较取数 → `regulation_thresholds.py`
- 改覆盖率/拒采 → `regulation_coverage_control.py`
- 改 slot/measure 与法规对齐 → `regulation_projection_mapping.py`
- **同名坑**：本层无 `__init__.py`、无 `__all__` 汇总，对外入口就是上面点名的函数；`workflow_engine.closure_validator.validate_closure`（W1 轻量）≠ 底线层 `validate_building_closure`（权威）；`fact_trigger_contract.evaluate_trigger_specs`（W1）≠ 闭包层 `evaluate_trigger`——别导错。

## 不归这块的（别在这找）
- 世界 / 数据生成（W0+W1）→ `workflow_engine/worldgen/`（有自己的卡）
- 底线层确定性闭包判定 → `evo_agent_baseline/closure/`（吃 FactPack+RuleSlice，不吃 W2 真值）
- 评测阅卷（读 W2 真值算指标）→ `eval/`（agent runtime 不 import 它）
- W1 侧散件：`closure_validator.py` / `fact_trigger_contract.py` / `fact_feature_pattern_*` / `skill_*` / `trigger_routing_*` / `obligation_schema.py` / `evidence_schema.py` 属实例生成/技能候选流程，非 W2 投影，本卡不覆盖
- 死壳勿接线：`graph.py` / `state.py` / `nodes.py` 是早期 MVP，不准被主线 import
