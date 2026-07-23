# agent/ —— agent 运行期（认知层）门口卡

> 给 AI / 新人的"最小上下文卡"：改这块，**先读这张卡 + 下面点名的文件**就够，不用翻全仓。
> （引文件名+函数名，不引行号——行号会漂。）

## 这块干什么（一句话）
evo-agent 的认知层运行期：把一次建筑评估串成流程——检索事实/规则 → 组 FactPack+RuleSlice → 调闭包验证器 → 按 `allow_stop` 出报告，全程由 hook 守 blind 红线。**这块只做工具编排 + 报告文字；合规判定权在底线层 `closure/`，这块改不了。**

## 入口
- `RunOrchestrator(...).run(world_id, building_id, ...) -> ComplianceAssessmentRun` —— 在 `run_orchestrator.py`。所有外部跑一次评估都走它。检索/闭包由构造参数注入（`retrieval_fn` / `closure_fn`），便于单测用假桩。
- LLM-as-brain 模式（`llm_mode=True`）走 `llm_orchestrator.py`——LLM 通过 tool use 循环调度 5 个工具，但决策仍由确定性验证器定。

## 改这块只需加载（按需，多数任务 2-3 个就够）
| 文件 | 管什么 | 什么时候看 |
|---|---|---|
| `run_orchestrator.py` | 主编排 `RunOrchestrator`：串流程、组包、调闭包、落库 | 改总流程/产物清单 |
| `llm_orchestrator.py` | LLM 编排（tool use 循环 + 5 工具 + finalize 前强制调闭包） | 改 LLM 怎么调度工具 |
| `llm_client.py` | LLM 客户端封装（OpenAI 兼容 endpoint，本机默认 Ollama） | 改 LLM 接入/换端点 |
| `hooks.py` | 5 个 hard hook（输入/检索/来源审计/停机门/输出语言守卫）+ skill/policy/feedback 系守卫 | 改 blind 守卫逻辑 |
| `skill_runtime.py` | active Skill 加载/触发/冲突消解（`load_active_skills` 等） | 改技能怎么加载/选用 |
| `policy_runtime.py` | EvoPolicy 加载/排序权重应用/候选截断 | 改策略怎么影响排序 |
| `report_writer.py` | 按 `allow_stop` 二选一渲染辅助审查报告 / 闭包未完成说明 | 改报告文字/结构 |

`__init__.py` docstring 已过时（写"地基层不实现 .py"，实际都已落地）——以本卡为准。

## 红线 / 不变量（改这块绝不能破）
1. **判定权不在这**：`allow_stop` / `closure_status` / `satisfaction_status` 只由 `closure/validator.py` 的 `validate_building_closure` 产出；编排器、LLM、技能、策略都**不得改写**。即使 LLM 拒调闭包，finalize 前编排器也强制调一次验证器。
2. **blind 红线**：agent 运行期绝不看 W2 参考真值（`NormativeProjection` / `expected_verdict`）；只吃 FactPack+RuleSlice。5 个 hard hook（`pre_run_input_guard` / `pre_retrieval_query_guard` / `post_retrieval_source_audit` / `post_verifier_stop_gate` / `pre_output_language_guard`）在各时点强拦；违规抛 `SecurityError`（统一在 `../errors.py`，跨层 except 才接得住）。
3. **不 import `eval/`**：`eval/` 是旁路阅卷、读真值算指标，agent runtime 绝不 import 它。
4. **分层单向**：本包（认知层）⊥ 感知层 `workflow_engine`，互不 import。
5. **报告话术**：只说"疑似未满足 / 建议人工复核"，绝不说"最终不合规"；`allow_stop=false` 时不输出完整报告正文（见 `report_writer.py`）。

## 改完跑哪个测试
```
$env:PYTHONPATH="agent_v1\src"
python -m pytest agent_v1\src\evo_agent_baseline\tests\test_agent_control.py agent_v1\src\evo_agent_baseline\tests\test_llm_orchestrator.py agent_v1\src\evo_agent_baseline\tests\test_evo_hooks.py agent_v1\src\evo_agent_baseline\tests\test_policy_runtime.py -q
```
（`test_agent_control` = hooks 5 守卫 + report_writer 两模板 + `RunOrchestrator` 用假桩跑完整流程；`test_llm_orchestrator` = LLM 编排；`test_evo_hooks` = skill/policy/feedback 系守卫；`test_policy_runtime` = 策略应用。改这块这几个必须全绿。注意 tests 在 `evo_agent_baseline/tests/`，本子目录内**没有**独立 tests 目录。）

## 常见任务 → 看哪个文件
- 改一次评估的流程/落库产物 → `run_orchestrator.py`（`RunOrchestrator.run`）
- 改 LLM 工具调度/加减工具 → `llm_orchestrator.py`
- 换 LLM 端点/模型 → `llm_client.py`
- 加/改一道 blind 守卫 → `hooks.py`（先确认它是 hard 还是 soft）
- 改技能加载/触发/冲突消解 → `skill_runtime.py`
- 改报告文字/结构 → `report_writer.py`
- 同名坑：本块 `post_verifier_stop_gate` 只**读**闭包结果做停机门，**不产**判定——真判定在 `closure/validator.py` 的 `validate_building_closure`；别把停机门误当判定源。

## 不归这块的（别在这找）
- 合规判定 / `allow_stop` 生成 → `closure/`（底线层，权威）
- 检索取 FactPack / RuleSlice 的实现 → `retrieval/`（本块只注入调用）
- W2 参考真值生成 → `workflow_engine/regulation_projection_*`
- 评测阅卷（读真值算指标）→ `eval/`（本块绝不 import）
- 技能归纳 / 策略训练 / 反馈回写（离线 evo 侧）→ `evo/`（本块只**用** active 投影，不训练）
