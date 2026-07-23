# evo/ —— skills-evo 进化层门口卡

> 给 AI / 新人的"最小上下文卡"：改这块，**先读这张卡 + 下面点名的文件**就够，不用翻全仓。
> （引文件名+函数名，不引行号——行号会漂。）

## 这块干什么（一句话）
进化层：把跨 run 的经验（trace / 反馈 / raw W2）归纳成技能包与 policy、5 Gate 门把它们放行 active，并实现 skills-evo 实验真正的差异杠杆——**分批闭包预算 + skill 家族排序**（`EVO_CLOSURE_QUERY_BUDGET`）。**不产合规判定；`allow_stop` 永远是底线层的事。**

## 入口
- `load_skill_package_kg(pkg, ...)` —— 在 `skill_package_loader.py`。技能包 → Neo4j 节点，唯一稳定对外面（`__init__.py` 只 `__all__` 暴露 `skill_package` / `skill_package_loader` 两个子模块）。
- `load_skill_package(path)` —— 在 `skill_package.py`。技能包 4 件目录 → `EvoSkillPackage` DTO + Gate 0 静态安全扫。
- 其余算子（induction / validation / trainer / broker / trace / audits / closure_budget）是**命脉进库、尚未接主编排**的纯算子，各有独立入口函数/类，非 `__all__` 对外面。

## 改这块只需加载（按需，多数任务 2-3 个就够）
| 文件 | 管什么 | 什么时候看 |
|---|---|---|
| `closure_budget.py` | 差异杠杆核心：`order_families_set_cover`（skill→coarse set-cover 排序）+ `PagedClosureController`（分批推进 + 预算） | 改分批预算 / 家族排序机制 |
| `skill_package.py` | 技能包解析 `load_skill_package` + Gate 0 静态安全扫 | 改技能包格式 / Gate 0 |
| `skill_package_loader.py` | 技能包 → `GraphBatch` → Neo4j（`load_skill_package_kg`） | 改技能入库 |
| `skill_induction.py` | 找模式→生 draft 技能包（触发 A 重复失败 / B 重复成功 / C 盲化缺口） | 改技能怎么归纳出来 |
| `skill_validation.py` | 5 Gate 放行门 `validate_skill`（Gate 0-4，runner 可注入） | 改 promotion 门槛 |
| `policy_trainer.py` | `EvoPolicyTrainer`：trace/raw W2/反馈 → candidate policy | 改 policy 训练 |
| `replay_buffer.py` | `ReplayBuffer`：ReplayCase 容器 + 失败/成功模式聚合 | 改经验入库 / 聚合口径 |
| `feedback_broker.py` | raw EvalTruthReport → 盲化 packet（runtime 趋势反馈接口，v1.1 已降级） | 改盲化 packet |
| `trace_capture.py` | 一次 run 各阶段 → `EvoRunTrace` + 4 类 audit | 改 trace 落盘 |
| `audits.py` | 反推 / 反事实 / 泄漏 6 项审计 | 改泄漏诊断 |
| `../contracts.py` | 公开 DTO（`EvoSkillPackage`/`SkillJson`/`EvoRunTrace`/`SkillValidationRecord` 等） | 看输入输出长什么样（只读相关类） |

## 红线 / 不变量（改这块绝不能破）
1. **runtime blind**：runtime-loadable artifact（技能包 / packet）**绝不含 raw W2**（`NormativeProjection` / `expected_verdict` / projection ids 等）；Gate 0 静态扫 + `trace_capture` 的 `forbidden_scan` + `audits` 兜底。技能包泄真值 = agent 抄答案 = 红线违规。
2. **trainer 可看真值**：v1.1 后 trainer / induction **允许**直接读 raw W2 算 reward/loss（训练看 ground truth 是常态）；防泄落点在**输出端 artifact 扫**，不是屏蔽 trainer 输入。别把二者捆绑。
3. **不改 `allow_stop`**：本层任何模块都不产合规判定；`closure_budget` 只是分批"确认覆盖了多少家族"，全量闭包结果内部首次算一次缓存，`allow_stop` 永远由底线层 `validate_building_closure` 定。
4. **分层单向 + spec 单向**：`evo_agent_baseline` ⊥ 感知层 `workflow_engine`（互不 import）；agent runtime 不 import `eval`（`closure_budget` / `audits` 里引 `eval.mapper` 的 crosswalk 属旁路工具，非 runtime 主链）；DTO 形态以 `../contracts.py` 为权威，不自创字段（pydantic `extra=forbid`）。
5. **环境**：导入需 `PYTHONPATH=agent_v1/src`；Neo4j 走 `EVO_AGENT_NEO4J_*` 环境变量（库名 `neo4j`，**不读** `config/kg.yaml`）。

## 改完跑哪个测试
```
$env:PYTHONPATH="agent_v1\src"
python -m pytest agent_v1\src\evo_agent_baseline\evo\tests -q
python -m pytest agent_v1\src\evo_agent_baseline\tests\test_evo_closure_budget.py agent_v1\src\evo_agent_baseline\tests -k evo -q
```
（差异杠杆的确定性单测在本块 `evo/tests/test_closure_budget.py`；其余 evo 算子的测试在**上一层** `evo_agent_baseline/tests/test_evo_*.py`——不在本目录下，别只跑 `evo/tests` 就以为覆盖全了。都不跑 LLM / 不连 Neo4j。）

## 常见任务 → 看哪个文件
- 调分批预算 / 家族排序（family_recall 机制） → `closure_budget.py`（`order_families_set_cover` + `PagedClosureController`）
- 改技能包放行门槛 → `skill_validation.py`（`validate_skill`，Gate 0-4）
- 改技能怎么被归纳出来 → `skill_induction.py`（触发 A/B/C）
- 改盲化 packet / 泄漏审计 → `feedback_broker.py` / `audits.py`
- 技能入 Neo4j → `skill_package_loader.py`（`load_skill_package_kg`）
- 同名坑：本块 `closure_budget` 的分批预算**不是** agent 的 `max_tool_iterations`（后者是 LLM 工具调用上限、五变体一视同仁砍，**非**差异杠杆）——差异杠杆只在闭包分批预算 + 家族排序。

## 不归这块的（别在这找）
- 合规判定 / `allow_stop` → 底线层 `closure/validator.py`（`validate_building_closure`）
- W2 参考真值生成 → 感知层 `workflow_engine/regulation_projection_*`
- 评测阅卷 / 算指标（读真值）→ `eval/`（runtime 不 import 它）
- 技能检索 / 激活（推理时用技能）→ `retrieval/` / `agent/`
