# worldgen/ —— 世界/建筑实例数据生成（感知层 W0/W1）门口卡

> 给 AI / 新人的"最小上下文卡"：改这块，**先读这张卡 + 下面点名的文件**就够，不用翻全仓。
> （引文件名+函数名，不引行号——行号会漂。）

## 这块干什么（一句话）
纯函数、registry 驱动地生成建筑实例数据：W0 建筑壳 + 组件/位置 + W1 每 fragment 状态（driver/mechanism/condition/drainage/UBW/fire + sidecar 派生 facts + measurements），过 P0/P1/P2 生成期 gate 后落 parquet。**这是感知层（数据生产端），不做任何合规判定。**

## 入口
- `generate_world_bundle(batch_config, registries, seed, building_index, fragment_count) -> WorldBundle` —— 在 `generator.py`。**单楼**主入口，几乎所有直接调用走它。
- `generate_world_batch` / `generate_world_batch_with_stats` —— 在 `generator.py`。**批量**入口（多进程，每楼确定性 seed）；`_with_stats` 内置 `audit_capture` 包 P2 clamp trace，单调 `generate_world_bundle` 不自动 wrap（P2 事件会静默丢，spec 边界设计）。
- `run_worldgenerator_fullcoverage_framework_v2(...)` —— 在 `validation.py`。命令行/整批流程主入口（registry→生成→gate→sidecar→W2 投影→parquet→报告）。

## 改这块只需加载（按需，多数任务 2-3 个就够）
| 文件 | 管什么 | 什么时候看 |
|---|---|---|
| `generator.py` | 生成主链：archetype 抽样 → building/component/location → fragment → driver/mechanism/condition/measurement | 改生成流程/字段/采样 |
| `generator_{base,defect,drainage,ubw,fire,sampling}.py` | 拆出的子域打分/采样公式（generator.py re-export，旧 import 路径不断） | 改某机制族公式 |
| `registry.py` | 从源文档构建 `RegistryBundle`（所有结构数据 = registry，无 hardcoded 业务数据） | 改 slot/分布参数/registry 表 |
| `round6_formulas.py` | Round6/7 锚点 + 分布来源 + 采样顺序 | 改分布锚点/采样顺序 |
| `models.py` | pydantic DTO：`WorldBundle`/`RegistryBundle`/`MeasurementRecord` 等 | 看输入输出长什么样 |
| `gates.py` | P0/P1/P2 生成期 gate 框架 + `apply_gate_with_retry`（P0 违规整楼 resample，P1 repair） | 改 gate/重采样/修复 |
| `checks.py` | C001-C0xx 具体 gate check 函数注册 | 加/改某条 check |
| `sidecar.py` | W1 sidecar 派生层（bool/categorical/数值 slot facts，静态 registry 采样） | 改 sidecar facts 派生 |
| `parquet_io.py` | W0/W1/W2 三层共用 parquet 列存 I/O | 改落盘 schema/读写 |
| `audits/` | W1 反作弊/反泄漏审计（schema_firewall / projection_rule_use / leakage_surface 等） | 改泄漏面/审计红线 |
| `p2_audit.py` | P2 inline clamp 的 aggregate summary 累加器（contextvar） | 改 P2 clamp 采样口径 |

`__init__.py` 是空的（无 `__all__`）——**对外入口不看它，看上面 `generator.py` 三个 `generate_world_*` + `validation.py` 的 `run_..._v2`**（`validation.py`/`p2_audit.py`/外部 `tests/` 都从 `worldgen.generator` 直接导）。

## 红线 / 不变量（改这块绝不能破）
1. **rule-blind（只属 W0/W1）**：worldgen / sidecar 主代码**绝不读 rule_card**（threshold/family/predicate）。字段/公式只按物理/RI 报告/业务真实自洽，不看下游怎么消费；`audits/projection_rule_use.py` 静态扫这条。
2. **分层单向**：本包属感知层 `workflow_engine`，**⊥ 认知/底线/进化层 `evo_agent_baseline`**；两包互不 import，别打破。
3. **纯函数 + registry 驱动**：`generate_X(...) -> result` 无副作用；所有结构数据来自 registry，**不接收 runtime 调参输入**，无 hardcoded 业务数据。
4. **spec→code 单向**：`蓝图汇总/` 的 spec 是当前权威；派生函数/公式接主链前先核 spec 授权，没 spec 不写、不接。
5. **反泄漏**：字段名禁夹 `token`/状态旗标不得进 salient facts 泄漏 verdict；改 sidecar/measurement 后过 `audits/` 全套。
6. **跑批安全**：**绝不随意跑 `run_baseline_e2e_smoke.py`**（污染 Neo4j、错位 seed 致 reference 全 null）；连库/`--wipe` 前确认目标库。

## 改完跑哪个测试
```
$env:PYTHONPATH="agent_v1\src"
python -m pytest agent_v1\src\workflow_engine\worldgen\tests -q
```
（`test_generator` 主链 + 打分公式；`test_gates`/`test_checks` gate 与 check；`test_registry`/`test_models` 数据结构；`test_audits_*` 反泄漏；`test_parquet_io`/`test_sidecar` I/O 与派生。）

## 常见任务 → 看哪个文件
- 改某机制族打分/采样 → `generator_{defect,drainage,ubw,fire}.py`（generator.py 已 re-export）
- 改 slot 分布参数/加 registry 表 → `registry.py` + `round6_formulas.py`
- 加/改生成期 gate 检查 → `checks.py`（框架在 `gates.py`）
- 改落盘 schema / parquet 列 → `parquet_io.py` + `models.py`
- 改 sidecar facts 派生 → `sidecar.py`（+ `conditional_eval.py`）
- 同名坑：本块 `generate_world_*` 产 W0/W1 数据；**别把它跟底线层混**——`worldgen.closure_validator.validate_closure`（W1 轻量校验）≠ `evo_agent_baseline.closure.validate_building_closure`（底线权威判定）；`worldgen.fact_trigger_contract.evaluate_trigger_specs`（W1 侧）≠ `evo_agent_baseline.closure.evaluate_trigger`（闭包侧）；跨包同名不同义，别导错。

## 不归这块的（别在这找）
- 合规判定 / allow_stop / 义务派生 → `evo_agent_baseline/closure/`（底线层，本包不 import 它）
- W2 法规映射层参考真值生成 → `workflow_engine/regulation_projection_*`（本包只在 `validation.py` 主流程里调它，不产真值）
- 评测阅卷（读真值算指标）→ `eval/`（agent runtime 不 import 它）
- 死壳勿接线 → `workflow_engine.{nodes,graph,state}` 是早期 MVP，不准被主线 import
