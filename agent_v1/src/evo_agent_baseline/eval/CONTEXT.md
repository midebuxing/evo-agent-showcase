# eval/ —— 评测阅卷旁路（W2 真值算指标）门口卡

> 给 AI / 新人的"最小上下文卡"：改这块，**先读这张卡 + 下面点名的文件**就够，不用翻全仓。
> （引文件名+函数名，不引行号——行号会漂。）

## 这块干什么（一句话）
独立阅卷程序：读 W2 参考真值算 agent 成绩。吃「agent 侧产物（闭包结果 / obligation / run_audit）+ W2 5 张真值表」，吐「评测报告 JSON（verdict / coverage / threshold / closure 指标 + 泄漏审计）」。**这是评测旁路，不是 agent 的一部分——agent runtime 绝不 import 它。**

## 入口
- `evaluate_run(inputs, crosswalk=None, crosswalk_path=None) -> dict` —— 在 `report.py`。把 truth_loader / mapper / metrics / leakage_audit 串成一次完整评测，产报告 JSON。外部（跑批脚本 `run_evo_smoke.py` / `run_baseline_e2e_smoke.py`）走这一个。
- 真值先落库再评：`load_truth_bundle(...)` —— 在 `truth_loader.py`，读 W2 5 张 parquet 成 `TruthBundle`。

## 改这块只需加载（按需，多数任务 2-3 个就够）
| 文件 | 管什么 | 什么时候看 |
|---|---|---|
| `report.py` | 主入口 `evaluate_run` + 串接顺序 + `EvalInputs` 输入契约 + 报告 JSON 组装 | 改评测总流程 / 报告字段 |
| `truth_loader.py` | 加载 W2 参考真值 5 表（projections / matched_families / threshold_evaluations / basis_items / meta）→ `TruthBundle` | 改真值怎么读 / 加真值列 |
| `mapper.py` | agent obligation → family verdict 聚合 + fine→coarse crosswalk 对齐 | 改 verdict 聚合 / family 对齐 |
| `metrics.py` | verdict / coverage / threshold / closure 四组指标 | 改指标算法 / 加指标 |
| `leakage_audit.py` | 泄漏审计（查 agent 侧产物有没有混入 W2 真值字段），6 项 metric | 改泄漏检测规则 |
| `family_crosswalk_v1.json` | W2 coarse family ↔ rule_card fine family 对照表 | 对照表条目变了 |

`__init__.py` 用 `__all__` 显式暴露对外面（`evaluate_run` / `load_truth_bundle` / 四组 `*Metrics` / `audit_leakage` 等）——想知道"外面能用啥"看它。

## 红线 / 不变量（改这块绝不能破）
1. **evaluator-only**：agent runtime **绝不 import `eval/`**，也不得访问 evaluator 真值库。这块是旁路阅卷程序、跑在 agent 之外。喂 `eval/` 给 agent = agent 抄答案 = blind 红线违规。
2. **读 W2 真值是本职、不是违规**：evaluator 是独立阅卷程序，读 `NormativeProjection` / `expected_verdict` 天经地义；blind 约束的落点是"agent 别看真值"，不是"evaluator 别看真值"。别把 W0/W1/闭包侧的 rule-blind 红线错套到这里。
3. **不反写 agent KG**：本包只产离线报告 JSON，绝不回写 agent 数据库 / 检索上下文；crosswalk 是 evaluator 配置，不进 agent KG。
4. **泄漏即作废**：任一 leakage metric fail → 报告 `valid=false` + `invalid_reasons` 含 `invalid_due_to_answer_leakage`，该 run 成绩作废。
5. **spec→code 单向**：报告字段 / 指标定义 / 禁词清单照 spec，不自创。

## 改完跑哪个测试
```
$env:PYTHONPATH="agent_v1\src"
python -m pytest agent_v1\src\evo_agent_baseline\eval\tests -q
```
（`test_report` 主链 `evaluate_run` + 泄漏作废 + crosswalk 缺失分支；`test_metrics` 四组指标；`test_mapper` / `test_crosswalk` 聚合与对齐；`test_leakage_audit` 六项泄漏；`test_truth_loader` 真值加载。改完这块这个测试必须全绿。）

## 常见任务 → 看哪个文件
- 改评测总流程 / 报告输出字段 → `report.py`（`evaluate_run` + `EvalInputs`）
- 改真值怎么读 / 加真值列 → `truth_loader.py`（`load_truth_bundle` + `TruthBundle`）
- 改 verdict 聚合 / fine→coarse 对齐 → `mapper.py`（对照表条目变了顺带改 `family_crosswalk_v1.json`）
- 加 / 改某组指标 → `metrics.py`
- 改泄漏检测规则 / 禁词 → `leakage_audit.py`
- 同名坑：本块的 `mapper.FamilyCrosswalk`（fine→coarse 阅卷对照）≠ W2 侧的 family 匹配产物；`Obligation` 是从 `../contracts.py` 借来读的（评测消费方），别当成本块自定义。

## 不归这块的（别在这找）
- 确定性合规判定 / allow_stop → `closure/`（`validate_building_closure`；本块只读它的结果，不改判定）
- W2 参考真值**生成** → `workflow_engine/regulation_projection_*`（本块只**读**真值，不产真值）
- 数据 / 世界生成 → `workflow_engine/worldgen/`
- agent 检索 / 底线 / 进化逻辑 → `evo_agent_baseline` 其它子包（它们绝不 import 本块）
