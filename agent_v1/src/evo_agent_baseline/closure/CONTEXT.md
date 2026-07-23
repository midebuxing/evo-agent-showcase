# closure/ —— 闭包验证（底线层）门口卡

> 给 AI / 新人的"最小上下文卡"：改这块，**先读这张卡 + 下面点名的文件**就够，不用翻全仓。
> （引文件名+函数名，不引行号——行号会漂。）

## 这块干什么（一句话）
确定性合规判定：吃「事实包 + 规则切片」，吐「义务集 + 是否可停机」。**这是底线层，judgment 权威——LLM/编排/技能/策略都改不了它的结论。**

## 入口
- `validate_building_closure(rule_slice, fact_pack, config=None, *, skill_invocation_ids, policy_version_id) -> ClosureValidationResult` —— 在 `validator.py`。几乎所有外部调用走这一个。

## 改这块只需加载（按需，多数任务 2-3 个就够）
| 文件 | 管什么 | 什么时候看 |
|---|---|---|
| `validator.py` | 主入口 + 编排 8 步生成顺序 + `summarize()` 重算 summary | 改总流程/allow_stop 口径 |
| `obligation_deriver.py` | 从 rule_card 派生义务、`evaluate_trigger` 触发器求值、threshold 义务标注 | 改义务怎么生成/触发判定 |
| `applicability.py` | 适用性判定（这条规则适不适用本楼） | 改适用性 |
| `threshold_eval.py` | 阈值义务的 operator/值/通过判定 | 改阈值比较 |
| `fact_binding.py` | 义务怎么绑到 FactPack 里的事实 | 改事实绑定 |
| `schema.py` | 闭包内部小类型 | 改内部数据结构 |
| `../contracts.py` | 公开 DTO：`FactPack`/`RuleSlice`/`Obligation`/`ObligationSet`/`ClosureSummary`/`ClosureValidationResult` | 看输入输出长什么样（只读相关类即可，别全读 949 行）|

`__init__.py` 用 `__all__` 显式暴露稳定对外面（`validate_building_closure`/`VerifierConfig`/各 DTO/`summarize`/`assert_no_forbidden_sources` 等）——想知道"外面能用啥"看它。

## 红线 / 不变量（改这块绝不能破）
1. **`allow_stop` 是唯一权威**：`allow_stop = (open_count==0 且 blocked_count==0 且 schema 校验过 且 forbidden 校验过)`；`violated_count>0 不影响 allow_stop`。LLM/编排/技能/策略都不能改写它。
2. **blind**：闭包**只吃 `FactPack`+`RuleSlice`，绝不吃 W2 `NormativeProjection`/`expected_verdict`**。入口第一步 `assert_no_forbidden_sources` 守这条。喂真值给闭包 = agent 抄答案 = 红线违规。
3. **blind 违规抛 `SecurityError`**（统一定义在 `../errors.py`，hooks/guard 共用同一类，跨层 except 才接得住）。
4. 生成顺序固定：applicability → triggers → slot roles → thresholds → obligation graph → evidence → exceptions → definitions → sort/dedupe（`validator.py` 内）。

## 改完跑哪个测试
```
$env:PYTHONPATH="agent_v1\src"
python -m pytest agent_v1\src\evo_agent_baseline\closure\tests -q
```
（`test_validator` 主链 + allow_stop 全分支；`test_derivation` 义务派生/触发器；`test_artifact_and_binding` 证据绑定。改完这块这个测试必须全绿。）

## 常见任务 → 看哪个文件
- 调 allow_stop / 停机口径 → `validator.py`（`summarize` + `compute_allow_stop_and_reason`）
- 改某类义务怎么派生 / 触发器判定 → `obligation_deriver.py`
- 改阈值比较（operator/容差） → `threshold_eval.py`
- 改"规则适不适用本楼" → `applicability.py`
- 加 / 改义务字段 → 先改 `../contracts.py` 的 `Obligation`，再看谁消费
- 同名坑：`evaluate_trigger`（本块，单 Obligation）≠ `workflow_engine.fact_trigger_contract.evaluate_trigger_specs`（W1 侧）；`validate_building_closure`（本块权威）≠ `workflow_engine.closure_validator.validate_closure`（W1 轻量版）——别导错。

## 不归这块的（别在这找）
- W2 参考真值生成 → `workflow_engine/regulation_projection_*`
- 评测阅卷（读真值算指标）→ `eval/`（agent runtime 不 import 它）
- 数据/世界生成 → `workflow_engine/worldgen/`
