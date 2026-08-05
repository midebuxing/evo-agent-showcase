# evo-agent 上手 / 运行手册（QUICKSTART）

资深但没碰过本项目的工程师，照这份从零跑起来。先读 [`../README.md`](../README.md) 了解项目是什么 + 四层架构；本文管"怎么装、怎么跑、各脚本干嘛、哪些坑"。

> **可信度标注**：标 **✅ 已实测** 的命令是写文档时本机真跑通的；标 **🔧 源码已核·待你环境验证** 的是按源码梳理的真实入口、但因依赖 Neo4j/LLM 或耗时，未在写文档时实跑，请在你环境里验证。

---

## 1. 环境前置

- **Python**：本机用 anaconda（`pandas/numpy/pyarrow/scipy/neo4j/pydantic` 等已装齐）。干净环境用 `pip install -r requirements.txt`（核心档即可，见 [`../requirements.txt`](../requirements.txt) 顶部说明）。
- **PYTHONPATH 必须指到 `agent_v1/src`**（所有 `from evo_agent_baseline...` / `from workflow_engine...` 顶层导入靠它）：
  - PowerShell：`$env:PYTHONPATH = "agent_v1\src"`
  - bash：`export PYTHONPATH=agent_v1/src`
- **Windows 中文乱码**：控制台跑出来的中文是 GBK 乱码（落盘文件是正确 UTF-8，不影响结果）。要看清中文输出：
  ```powershell
  chcp 65001
  $env:PYTHONIOENCODING = "utf-8"
  ```

---

## 2. 第一次跑（零依赖，验证装好了）— ✅ 已实测

这两条**不连 Neo4j、不连 LLM**，用来确认环境 OK：

```powershell
cd C:\dell_vs\5993
$env:PYTHONPATH = "agent_v1\src"

# (1) evo-agent 冒烟（mock 检索/闭包，跑 RunOrchestrator，验 5 项验收）
python agent_v1\scripts\run_evo_smoke.py --mock
# 期望尾部：[PASS] evo smoke 5 项验收全通过
#          out_root=...\experiments\evo_smoke_mock_<时间戳>\

# (2) 看实验归档索引（上一步会登记进去）
python -m evo_agent_baseline.experiments.run_registry --list
# 期望：列出刚才那个 evo_smoke_mock_<时间戳> [completed]
```

跑通这两条 = Python 环境、PYTHONPATH、核心包、实验归档系统都正常。还有一条更轻的纯静态命令（连这都不需要 import 业务代码）：`python agent_v1\scripts\gen_api_docs.py` 会重生成 `docs/api/`。

---

## 3. 真实全链路（需 Neo4j + 数据池 + LLM）— 🔧 源码已核·待你环境验证

完整跑一栋楼的合规评估，要四步：**生成数据 → 灌库 → 跑 agent → 评测**。

### 3.1 Neo4j 连接（这里有坑，按这个来）

脚本实际只读 **`EVO_AGENT_*` 环境变量**，默认值就对，**只有密码必填**：

| 变量 | 默认 | 说明 |
|---|---|---|
| `EVO_AGENT_NEO4J_PASSWORD` | 无（必填） | 不填直接报错 |
| `EVO_AGENT_NEO4J_URI` | `bolt://127.0.0.1:7687` | |
| `EVO_AGENT_NEO4J_USER` | `neo4j` | |
| `EVO_AGENT_NEO4J_DATABASE` | `neo4j` | **主线库名就是 `neo4j`**（S00042 主线池资产，别动）；**换池实验必须配独立库**（企业版多库，先例 `s25smoke`），防同号 world_id 覆写主线 |

```powershell
$env:EVO_AGENT_NEO4J_PASSWORD = "你的密码"
```

> ⚠️ **别被另外两套配置误导**：`src/evo_agent_baseline/config/kg.yaml` 里写的 `evo_agent_baseline` 库名、以及 `.env` / `.env.example` 里的 `NEO4J_*` 变量，**当前主线脚本都不用**（前者是 spec 残留，后者只被死 MVP 代码读）。新人只管设 `EVO_AGENT_NEO4J_PASSWORD`、用库 `neo4j`。

### 3.2 LLM 端点

| 变量 | 默认 | 说明 |
|---|---|---|
| `EVO_AGENT_LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | 默认本地 Ollama |
| `EVO_AGENT_LLM_MODEL` | `qwen3.5:latest` | |
| `EVO_AGENT_LLM_API_KEY` | `ollama`（占位） | |

> 论文那批真 LLM 跑批用的是 **sixthsense（deepseek）**，配置在 gitignored 草稿 `杂物箱/run_paired_real_pipeline.py` 里，key 走运行时 `SIXTHSENSE_KEY` 不写文件。

### 3.3 四步链路

1. **生成数据池**（W0/W1/W2 parquet，含 W2 参考真值）：
   ```powershell
   python agent_v1\run_worldgenerator_fullcoverage_framework.py --output-dir <池路径> --count N --seed S
   ```
   （薄壳，真入口 `workflow_engine.worldgen.validation:main`。一函数串 7 步产齐 W0+W1+W2。）
2. **灌 5 路 KG**（顺序固定）：`regulation → rulecard → fact → sidecar → skill`。唯一把这套顺序编排好的入口是 `scripts/run_baseline_e2e_smoke.py`（建 schema → 5 路 loader）。
3. **跑 agent**：核心是 `RunOrchestrator`（`src/evo_agent_baseline/agent/run_orchestrator.py`），`run(world_id, building_id, ...)` 跑 11 步主链，闭包判定走 `validate_building_closure`。
4. **评测**：`eval/` 读 W2 真值离线阅卷（agent runtime 不碰 eval，blind 红线）。

> ⚠️⚠️ **`run_baseline_e2e_smoke.py` 是上面 2-3-4 的一键编排入口，但带 `--wipe` 灌库会污染 Neo4j——本项目明令谨慎/不要随意跑它**。默认源池是内置主线池；换池用 `--worldgen-run-dir <池路径>`（2026-07 新增），**换池必须同时配独立 `EVO_AGENT_NEO4J_DATABASE`**（同 seed 会产同号 world_id，直灌主库 = 覆写主线资产）。日常验证用 §2 的 mock 路径。
>
> ⚠️ **本机严禁调用 `python3` / `py`**：Windows 商店 stub 会弹商店窗口（stub 删过会随系统更新复活）。一律用 `python`（anaconda 已上 PATH）或绝对路径 `C:\Users\<用户名>\anaconda3\python.exe`，控制台中文输出配 `PYTHONUTF8=1`。
>
> 🛡️ **本仓库有一整套工程护栏**（pre-commit / CI / 架构契约 / 编辑钩子 / 上下文工具）：完整索引（每道护栏的文件位置 + 红了怎么办）见 `团队文档/我的笔记/AI编码工程化_落地清单.md` 的"护栏索引"节；上下文经济工具（任务打包器 `pack_context.py` / ast-grep / testmon）用法见 [`../scripts/README_context_tools.md`](../scripts/README_context_tools.md)。总纪律：护栏红了修问题本身，禁 `--no-verify`。

---

## 4. 脚本矩阵（`agent_v1/scripts/`）

| 脚本 | 用途 | Neo4j | LLM | 无依赖快验 | 前置 | ⚠️假桩指标 |
|---|---|:--:|:--:|:--:|---|:--:|
| `run_evo_smoke.py` | evo-agent 冒烟，验 5 项验收 | 真模式要 | 否 | **`--mock`** | mock 无 | 否 |
| **`run_baseline_batch.py`** | **【正式入口】多栋 baseline 批跑+断点续跑+自动聚合(收官批/重锚批唯一入口，见 §4.1)** | **要** | **须`--llm`** | 无 | 密码+**隔离库**+池 | 否 |
| `aggregate_baseline_batch.py` | 批产物聚合出 `batch_summary`(批跑已自动调，单独重算时用) | 否 | 否 | 是 | 须有批产物 | 否 |
| `run_baseline_e2e_smoke.py` | 端到端基线：灌库→跑**1栋**→评测(单栋，非批跑) | **要** | 可选`--llm` | `--evo`转mock | 密码+源池 | 否（但⚠️见§3.3） |
| `run_evo_batch_experiment.py` | N 栋 baseline vs evo 配对，产 `evo_traces/` | **要** | 默认要 | 无 | **库须已灌** | 否 |
| `run_evo_full_experiments.py` | "实验⑨"框架：5消融×配对+学习曲线 | 否 | 否 | 是（离线） | 须有 `evo_batch_*/evo_traces/` | **是！** |
| `run_evo_scaling_demo.py` | "实验④" scaling_law 函数 demo | 否 | 否 | 是 | 同上 | **是（demo）** |
| `run_evo_induction_experiment.py` | "实验③" trace→draft 技能（无 LLM 模板） | 否 | 否 | 是 | 同上 | 否 |
| `run_evo_llm_induction_experiment.py` | "实验⑤" LLM 生成 SKILL.md + Gate0 | 否 | **要(Ollama)** | 无 | 同上 | 否 |
| `run_evo_broker_audit_experiment.py` | "实验⑥" feedback broker + 审计 | 否 | 否 | 是 | 同上 | 混合(输入真值合成) |
| `run_evo_artifact_audit_experiment.py` | "实验⑧" 制品侧重建/投毒/泄漏审计 | 否 | 否 | 是 | 同上 | 混合(输入真值合成) |
| `run_evo_llm_paired.py` | LLM 驱动配对(mock检索/闭包,真LLM) | 否 | **要(Ollama)** | 无 | Ollama | 否 |
| `run_long_run_qa.py` | worldgen QA 基准(多seed+4审计) | 否 | 否 | `--count`小=快 | `--output-dir`必填 | 否 |
| `gen_api_docs.py` | AST 抽 `docs/api/`（零依赖零副作用） | 否 | 否 | 是 | 无 | 否 |
| `analyze_paired_results.py` | 聚合 `evo_llm_paired_*`+拟合+出图 | 否 | 否 | 须有 paired 产物 | numpy/scipy/matplotlib | 否 |

辅助：`profile_worldgen.py`(性能)、`diagnose_leakage_surface.py`(诊断)、`migrate_json_to_parquet.py`(`--dry-run`)、`benchmark_parquet.py`。

### 4.1 复现 baseline 收官/重锚批(正式入口 `run_baseline_batch.py`)

**这是复现论文冻结数字的唯一正式入口**，与 `run_baseline_e2e_smoke.py`(单栋、有污染风险)不同：它多栋顺序批跑、断点续跑、自动聚合，并焊了库名护栏(拒主库)、队列健康门、三锚校验。完整参数说明跑 `python agent_v1\scripts\run_baseline_batch.py --help`。

**红线**：`--llm` 加 = 满血 LLM 档(基线本体)，不加 = 确定性地板档(**不得用于收官验收**)。复现冻结数字**必须加 `--llm`**，漏加会静默跑出地板档。

**必需环境变量**(缺任一会跑出错误档位或报错)：
- `EVO_AGENT_NEO4J_PASSWORD`(必填)
- `EVO_AGENT_NEO4J_DATABASE=<隔离库>`——**必须显式指隔离库**，缺省或指主库 `neo4j` 会被驱动**直接拒跑**；隔离库需 **Neo4j 企业版**(社区版只有单库 `neo4j`)
- `EVO_AGENT_LLM_THINK_OFF=1`(原生 `/api/chat` 关思考，治"推理内容进错字段致正文空转")
- `EVO_AGENT_LLM_NUM_CTX`(默认 16384，防对话前端被静默截断——曾致 42% 空转)
- `EVO_AGENT_LLM_MAX_TOOL_ITERATIONS`(如 64)

**三锚**(池 seed + commit + 库名)与每次批跑的具体值见对应 `实验记录/EXP-NNN`。**注意池锚与批锚可能是不同 commit**(如 EXP-014:池生成于 `f0821a9`、批跑于 `5c531cc`)——复现须先在池 commit 造池、再在批 commit 跑批。

> **造池用哪个脚本**:baseline 批跑的池由 `run_long_run_qa.py` 生成(带 `--fragment-count`、产物落 `gen_seed_<S>/` 子目录)，**不是** §3.3 演示用的 `run_worldgenerator_fullcoverage_framework.py`(无 `--fragment-count`、目录形状不同)。EXP-014 池的完整生成命令记在 `实验记录/EXP-014` 三锚表。

示例(EXP-014 收官批)：

```bash
# 前置:Neo4j 企业版起、隔离库可写;环境变量按上面设好
python agent_v1/scripts/run_baseline_batch.py \
  --worldgen-run-dir agent_v1/experiments/qa_reports/_reanchor_50x1_seed301/gen_seed_301 \
  --batch-root <你的批产物目录> --count 30 --llm --dry-run   # 先 --dry-run 核对档位与规模,再去掉它实跑
```

> `.env.example` 里的 `NEO4J_*`/`LLM_MODEL` 变量名是**死 MVP 遗留、主线不读**(主线只认 `EVO_AGENT_NEO4J_*`/`EVO_AGENT_LLM_*`)；别 `cp .env.example .env` 就以为配好了。

---

## 5. ⚠️ 假桩指标警告（别把合成数字当真实结果）

下列脚本产的是 **mock/硬编码合成数字**，是跑通框架用的占位，**不能当真实实验结果引用**：

- **`run_evo_full_experiments.py`** —— `aggregate_delta=+0.07` 等增量是硬编码（`ablations.py` 里 baseline runner 是 v0.4 frozen mock，evo runner 叠固定 delta+随机抖动），学习曲线喂的也是硬编码经验映射。`full_experiments_summary.json` 是合成数字上的框架演示。
- **`run_evo_scaling_demo.py`** —— demo：真值 `random.choice`、误差曲线自指拟合（按已知公式生成再拟回）。
- **`run_evo_broker_audit_experiment.py` / `run_evo_artifact_audit_experiment.py`** —— 审计代码真跑，但**输入真值是合成的**。

真实的 evo 结果走 `run_evo_batch_experiment.py`（真 LLM + 真闭包，产 `evo_traces/`）→ `run_evo_llm_paired.py`（真 LLM 配对）这条线；论文级数据见 `实验记录/EXP-NNN`。

---

## 6. 评测：安全跑 + 读懂 verdict / coverage / threshold / closure 四组指标

### 6.1 安全跑出评测指标 — ✅ 已实测，无 Neo4j

```powershell
# (a) mock 跑 + 演示评测流水线：产 eval_report.json + 打印四组指标
python agent_v1\scripts\run_evo_smoke.py --mock --eval
#   实测输出（节选）：
#   coverage : family_recall=1.0 family_precision=1.0 rule_card_recall_proxy=1.0 slot_requirement_recall=0.0
#   verdict  : expected_verdict_accuracy=None compared_pairs=0      ← 见 §6.4「null≠0」
#   ⚠️ 指标基于 mock 数据，仅演示流水线 + 指标形状，非真实成绩

# (b) 跑评测单测：看四组 compute_*_metrics 被真实 fixture 验证
python -m pytest agent_v1\src\evo_agent_baseline\eval\tests\ -q     # 67 passed
```

> **真实评测**（对真 W2 参考真值离线阅卷）只在 `run_baseline_e2e_smoke.py` 那条链产 `eval_report.json`，⚠️ 它要 Neo4j 且有污染风险（见 §3.3）。已有真实样例可直接看：`experiments/baseline_e2e_smoke_<ts>/eval_report.json`（7 份）。

### 6.2 eval_report.json 结构

四组指标**全部平铺进 `metrics` 一个 dict**（不分块嵌套），靠字段名前缀区分归属。下面是真实跑出文件的精简样例——⚠️ **它是"W2 覆盖拒绝 bug 时期"产物：verdict 维度全 `null`（每栋楼真值只剩 1 fragment、`fragment_id=null` 致对齐失配），是报告"形状"示例，不是健康结果**：

```json
{
  "eval_run_id": "EVAL-...", "agent_run_id": "CAR-...",
  "world_id": "...", "building_id": "...",
  "evaluation_status": "completed", "valid": true, "invalid_reasons": [],
  "metrics": {
    "expected_verdict_accuracy": null, "compared_pairs": 0, "confusion": {},
    "family_recall": 1.0, "family_precision": 0.7, "slot_requirement_recall": 0.186,
    "threshold_pass_bool_match": null,
    "allow_stop_precision": null,
    "blocked_rate_by_reason": {"missing_rule_edge": 0.0106, "unsupported_predicate_kind": 0.0015}
  },
  "per_fragment_results": [{"fine_family_id": "...", "agent_family_verdict": "unknown",
                            "reference_expected_verdict": null, "verdict_match": null, "obligation_count": 24}],
  "leakage_audit": {"forbidden_source_loaded": false, "expected_verdict_text_leak": false, "...": false},
  "leakage_findings": []
}
```

### 6.3 四组指标释义

verdict 枚举（4 类）：`unknown` / `fail` / `pass` / `not_applicable`。所有比率分母为 0 → `null`。

| 组 | 关键字段 | 含义 | 取值 / 好坏方向 |
|---|---|---|---|
| **verdict** | `expected_verdict_accuracy` | agent family verdict 对齐 W2 expected_verdict 的命中率 | 0-1，越高越好（应接近 oracle 天花板）|
| | `pass_fail_macro_f1` / `severity_weighted_accuracy` | pass/fail 宏 F1 / 按严重度加权命中 | 0-1，越高越好 |
| | `compared_pairs` | 实际对齐上的 (agent,真值) 对数 | 计数；**诊断锚：0=没对齐上，上面全 null** |
| **coverage** | `family_recall` / `family_precision` | W2 命中 family 被 agent 覆盖 / agent 选的命中 W2（coarse 粒度）| 0-1，越高越好；漏 family=漏整块法规 |
| | `rule_card_recall_proxy` | W2 rule_ids 被 agent 检索 rule_card 覆盖 | 0-1，越高越好 |
| | `slot_requirement_recall` | W2 required_slots 被 agent 义务 slot 覆盖（分子并入 measure_keys）| 0-1，越高越好 |
| **threshold** | `threshold_pass_bool_match` | agent 阈值判定 vs W2 pass_bool 一致率 | 0-1，越高越好（阈值判对没）|
| | `threshold_operator_match` / `_value_match` / `observed_value_tolerance_match` | operator / 阈值 / 观测值匹配率 | 0-1，越高越好 |
| **closure** | `allow_stop_precision` / `_recall` | agent allow_stop 行为 vs W2（单 run）| 0/1/null，越高越好 |
| | `blocked_rate_by_reason` | 各 blocked 原因码比率 dict | **越低越好；必下钻** |
| | `closed_violated_detection_rate` | W2=fail 被 agent closed+fail 检出 | 0-1，越高越好；漏检违规=危险 |

### 6.4 读指标三条纪律

1. **`null` ≠ 0**：`null` = 该指标本次"不可算"（分母 0），不是 0 分。如 §6.1 的 `--eval`：verdict 全 `null`（`compared_pairs=0`，agent verdict 与真值 fragment_id 对齐键没接上），而 coverage 对齐上了所以 =1.0。**先看 `compared_pairs` 是不是 0，再看比率才有意义。**
2. **跑批必下钻 `blocked_reason_counts` / `open_reason_counts`**：`metrics.blocked_rate_by_reason` 只给比率；原始计数在 run 目录 `closure_validation_result.json → closure_summary`。
3. **high-level PASS ≠ 实验有效**：曾有 trigger 字段错位让 98% 义务 blocked，但顶层指标全 PASS、潜伏多日。判"这次实验有效"要看 `compared_pairs>0` + `blocked/open_reason_counts` 分布健康。

### 6.5 一次 run 目录产物速览

run 目录 = `<out_root>/runs/<run_id>/`。**`eval_report.json` 不在 run 目录里**（它是 evaluator 旁路产物，落在 experiment 根）。

| 文件 | 是什么 | 看序 |
|---|---|---|
| `closure_validation_result.json` | **闭包验证器最终输出**：allow_stop + closure_summary + obligation_set | **① 先看** |
| `run.json` | run 元数据：status / allow_stop / *_ref 路径 | ② 整体状态 |
| `run_audit.json` | hook_results / forbidden_sources_loaded / status_trace | ③ 审计/泄漏 |
| `obligation_set.json` | 全部义务明细（逐条 closure_status / open_reason_code）| ④ 下钻 |
| `auxiliary_review_report.md` **或** `incomplete_closure_notice.md` | 二选一：allow_stop=true 出辅助审查报告，否则出未完成说明 | 给人看 |
| `fact_pack.json` / `rule_slice.json` / `evo_run_trace.json` | 检索事实包 / 法规切片 / evo 链路审计（evo_mode）| 按需 |

`closure_summary` 关键字段：`allow_stop`（唯一停机权威 = `open_count==0 且 blocked_count==0 且 schema/forbidden 校验过`；`violated_count>0 不影响`）、`open_count` / `open_reason_counts`、`blocked_count` / `blocked_reason_counts`、`closed/satisfied/violated/unknown/not_applicable_count`、`stop_reason`。

---

## 7. 数据池现状（诚实交代）

- §2/§3 的冒烟脚本**硬编码**指向 `experiments/qa_reports/release_batch_post_W0005_full_align/gen_seed_1`（存在）。
- 另有更新的命名池 `release_batch_evo_v11_data_pool_20260527`（存在），但**无主线脚本引用**，且它有"每栋楼真值被 W2 coverage-rejection 砍到 1 fragment、全 fail"的已知 bug（见技术债 / 记忆 `project_w2_coverage_rejection_bug`）。
- **DEBT-044（W2 楼级取舍）的修复只在代码层（`worldgen/validation.py`），落盘的数据池都还是旧的砍-fragment 行为**——要做完整闭包核验需用修后代码**重新生成**数据池。
- 哪个池算"权威主线池"目前未定，以 `团队文档/我的笔记/项目跟踪表.md` 为准。

---

## 8. 死代码勿动 & 实验归档

- **死代码清单**（早期 MVP，勿照其接线）见 [`../README.md`](../README.md) 末节：`src/knowledge_base/`、`src/domain_tools/`、`workflow_engine/{nodes,graph,state}.py`、顶层 `app.py`/`main.py`/`run_phase*.py` 等，以及 `README_legacy_mvp.md`（历史存档别照跑）。
- **实验归档约定**（`run_meta.json` / 索引 / `open_experiment`）见 [`experiments/README.md`](experiments/README.md)。
