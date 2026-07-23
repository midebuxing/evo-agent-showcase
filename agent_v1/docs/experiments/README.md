# 实验归档约定（run_registry）

> 本文档讲清 evo-agent v1 实验产物的**统一约定**：目录结构、强制元数据
> `run_meta.json`、机器可读索引，以及新脚本怎么接入。
>
> 实现在 `agent_v1/src/evo_agent_baseline/experiments/run_registry.py`，
> 单测在同包 `tests/test_run_registry.py`。本文档只讲约定，不重复源码。

---

## 1. 为什么有这套系统

在建立本约定之前，实验产物的状况是：

- **散在 5 处、约 38 GB**：`evo_*` 系自动落 `agent_v1/experiments/`、QA 系
  靠手动 `--output-dir`、`baseline` 冒烟测试、`杂物箱/` 一次性脚本各落各的。
- **目录约定分裂成 4 套**，互不一致：
  1. `evo_*` 系：自动时间戳目录（`<name>_<时间戳>`）；
  2. QA 系：手动 `--output-dir` 指定，无统一前缀；
  3. `baseline` 冒烟测试：又一套写法；
  4. `杂物箱/` 一次性脚本：各写各的。
- **零机器可读索引**：想知道"哪个 run 用了哪个 commit、跑了多少栋、产物在哪、
  关联哪个 EXP-NNN"，只能靠人翻目录名 + 记忆，没有任何可以 `grep` / 程序读的
  清单。

`run_registry` 是一套**"从此往后"**的统一约定，解决三件事：

1. **统一目录**：所有 run 一律落 `<agent_v1>/experiments/<name>_<时间戳>/`。
2. **强制元数据**：每个 run 目录都有一份 `run_meta.json`，记全 commit / 参数 /
   产物 / 状态 / 关联台账，起始即落盘、结束自动收尾。
3. **机器可读索引**：每个 run 追加一行到 `experiments_index.jsonl`，配一份
   人类可读 `INDEX.md`。

边界说明（项目原则）：本模块**只做归档登记**——不读 W2 字段、不介入
`allow_stop` 判定、不消费法规真值，纯工程基础设施。

---

## 2. 目录约定

每个 run 独占一个目录：

```
<agent_v1>/experiments/<name>_<YYYYMMDD_HHMMSS>/
├── run_meta.json        ← 强制元数据（本模块写）
├── run.log              ← 约定日志路径（脚本自己写，本模块不强制）
└── ...                  ← 脚本产物（json / parquet / 报告 / 子目录等）
```

- `<name>`：实验名，作目录前缀（如 `evo_full_experiments`）。
- `<YYYYMMDD_HHMMSS>`：**本地时区**时间戳，沿用现有脚本
  `datetime.now().strftime(...)` 风格，避免新旧目录命名漂移。
- 父目录默认 `<agent_v1>/experiments/`（`default_output_root()`，与现有
  `run_*.py` 脚本落点一致），可用 `output_root=` 覆盖。
- 索引落在父目录下的 `_index/` 子目录（见 §5）。

---

## 3. `run_meta.json` 契约

`schema_version="1"`。起始即落盘（`status="running"`），正常结束更新为
`completed`、异常更新为 `failed`。逐字段：

| 字段 | 含义 |
| --- | --- |
| `schema_version` | meta 结构版本号，当前 `"1"`。 |
| `exp_id` | 关联的 EXP-NNN 人肉台账编号（无则 `null`）。见 §7。 |
| `run_id` | 本次 run 唯一 id，**等于目录名**（`<name>_<时间戳>`）。 |
| `name` | 实验名（目录前缀）。 |
| `script` | 调用脚本相对仓库根的路径（由 `sys.argv[0]` 推断，失败则 `null`）。 |
| `argv` | 完整 `sys.argv` 列表（原样命令行）。 |
| `params` | 实验参数 dict（脚本传 `vars(args)`）。 |
| `tags` | 标签列表（如 `["smoke", "unit"]`）。 |
| `links` | 关联对象，目前含 `links.exp_ledger`（= 入参 `link_exp`）。 |
| `git` | `{commit, branch, dirty}`；采集失败的子字段为 `null`，不抛错。 |
| `python` | Python 版本（`platform.python_version()`）。 |
| `host` | 主机名（`socket.gethostname()`）。 |
| `platform` | 平台串（`platform.platform()`）。 |
| `started_at` | 起始时刻，ISO-8601 UTC 秒级带 `Z`（如 `2026-06-17T08:30:00Z`）。 |
| `finished_at` | 结束时刻，同格式；运行中为 `null`。 |
| `duration_sec` | 运行秒数（保留 3 位小数）；运行中为 `null`。 |
| `status` | `running` / `completed` / `failed` 三态。 |
| `error` | 失败时 `{type, message}`（message 截断到 2000 字），否则 `null`。 |
| `artifacts` | 产物列表，每条 `{path, bytes, kind}`；`path` 相对 run 目录，目录类产物 `bytes` 为 `null`，`kind` 缺省按后缀推断。 |
| `notes` | 自由备注文本（入参 `notes`，无则 `null`）。 |

说明：

- `git` 用 bytes 解码（UTF-8 + replace），避免 Windows GBK 控制台在含中文文件名时
  静默失败。
- `artifacts` 在退出时自动全目录扫描补齐（`run_meta.json` 自身不计入）；显式
  `add_artifact` 登记过的保留其 `kind`、只刷新 `bytes`。
- 路径分隔符统一正斜杠 `/`（跨平台稳定）。

---

## 4. 怎么在新脚本里用

核心入口是 `open_experiment` 上下文管理器：

```python
import argparse
from evo_agent_baseline.experiments.run_registry import open_experiment


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-buildings", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    # params 直接传 vars(args)：整个 argparse namespace 进 run_meta。
    with open_experiment(
        "evo_full_experiments",
        params=vars(args),
        tags=["evo", "paired"],
        link_exp="EXP-009",          # 关联 EXP-NNN 台账，写入 links.exp_ledger
        notes="留出集配对消融",
    ) as run:
        # run.dir 是 run 目录；run.path(name) 拼产物路径（不创建）。
        result_path = run.path("full_experiments_summary.json")
        result_path.write_text("{...}", encoding="utf-8")

        # 产物退出时自动全目录扫描，一般无需手动登记；
        # 想立刻打 kind 标签或登记到 run 目录外的产物时再 add_artifact：
        run.add_artifact(result_path, kind="summary")

        # 自定义字段进 run_meta 顶层（即时落盘）：
        run.set(n_buildings=args.n_buildings, kg_snapshot_id="KGS-035427")

    # 退出后 run_meta.json 自动 status=completed + finished_at + duration_sec
    # + 产物清单，并追加一行到索引 jsonl。
```

要点：

- **`params` 传 `vars(args)`**：直接把 argparse namespace 转 dict 存进 meta。
- **已自算目录的脚本用 `dir=` adopt**：很多现有脚本已自己拼好输出目录，例如
  `run_evo_full_experiments.py` 里：

  ```python
  out_root = exp_dir / f"evo_full_experiments_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
  ```

  这种把算好的目录传 `dir=out_root`，归档工厂**直接 adopt**——不另建目录、不
  改变产物落点，只在该目录里写 `run_meta.json`：

  ```python
  with open_experiment("evo_full_experiments", params=vars(args), dir=out_root) as run:
      ...  # 产物照旧写 out_root，run.dir 就是 out_root
  ```

- **自定义字段用 `run.set(**fields)`**：补 `n_buildings` / `kg_snapshot_id` 等
  契约外字段到 meta 顶层，即时落盘。
- **产物自动扫描，也可手动 `add_artifact`**：退出时自动扫全目录补齐
  `artifacts`；想提前打 `kind` 标签、或登记落在 run 目录外的产物时手动调。
- **异常自动收尾**：上下文里抛异常会记 `status=failed` + `error{type,message}`，
  仍更新 meta + 追加索引，然后**重新抛出**异常（不吞）。

`ExperimentRun` 句柄常用成员：

| 成员 | 说明 |
| --- | --- |
| `run.dir` | run 目录（`pathlib.Path`）。 |
| `run.run_id` | run 唯一 id（= 目录名）。 |
| `run.path(name)` | 返回 `run.dir / name`（不创建）。 |
| `run.log_path` | 约定日志路径 `run.dir / "run.log"`（本模块不强制写）。 |
| `run.add_artifact(path, kind=None)` | 登记一个产物（按相对路径去重）。 |
| `run.set(**fields)` | 往 meta 顶层补/覆盖字段并即时落盘。 |

---

## 5. 索引

两份索引都落在 `<agent_v1>/experiments/_index/`：

- **机器可读 `experiments_index.jsonl`**：每个 run 结束追加**一行**精简 meta，
  字段为 `run_id` / `name` / `exp_id` / `status` / `started_at` /
  `finished_at` / `duration_sec` / `git_commit` / `tags` / `n_artifacts` /
  `dir`。程序按行 `json.loads` 即可消费（坏行跳过）。
- **人类可读 `INDEX.md`**：由 `rebuild_index_md()` 从 jsonl（+可选扫盘）重生成的
  表格，列为 `run_id | name | exp_id | status | started_at | git commit |
  产物数 | 目录`，按 `started_at` 排序。**自动生成，请勿手工编辑。**

命令行：

```bash
# PYTHONPATH=src（包导入需要）
python -m evo_agent_baseline.experiments.run_registry --rebuild-index   # 由 jsonl 重建 INDEX.md
python -m evo_agent_baseline.experiments.run_registry --list            # 打印索引里的实验列表
python -m evo_agent_baseline.experiments.run_registry --scan            # 扫盘回填（见 §6）
```

可加 `--output-root <路径>` 指定非默认父目录。三个模式互斥、必选其一。

---

## 6. 回填历史产物

`scan_existing()` / CLI `--scan` 是**可选回填工具**：遍历实验目录找已有
`run_meta.json`、把目录里有 meta 但未进 jsonl 的 run 并入索引、并重建
`INDEX.md`（按 `run_id` 去重，jsonl 优先）。

**当前状态：未运行。** 那约 38 GB 历史产物按用户决定**暂不回填**——它们大多没有
`run_meta.json`，`--scan` 只能收到将来用 `open_experiment` 新产生的、含 meta 的
run。将来若要回填，跑：

```bash
python -m evo_agent_baseline.experiments.run_registry --scan
```

`scan_existing()` 本身不写任何文件、只返回数据；是否落盘由调用方 / `--scan`
决定。

---

## 7. 与 EXP-NNN 台账的关系

项目有一套人肉实验台账：`实验记录/EXP-NNN_主题_日期.md`（一实验一文件）。
机器可读索引与人肉台账靠 **`exp_id`** 衔接：

- 调 `open_experiment(..., exp_id="EXP-009")` 或 `link_exp="EXP-009"`，会把编号
  写进 `run_meta.exp_id` 和 `run_meta.links.exp_ledger`。
- 之后从 `experiments_index.jsonl` 按 `exp_id` 过滤，就能把一个 EXP-NNN 台账下的
  所有 run（含跨 commit / 多次重跑）全部捞出，再回查每个 run 目录的
  `run_meta.json` 看具体参数与产物。

简言之：**`exp_id` 是 machine-readable 索引 ↔ 人肉台账之间的外键**。台账写
"为什么做、结论是什么"，`run_meta` + 索引记"哪次跑、什么 commit、产物在哪"。
