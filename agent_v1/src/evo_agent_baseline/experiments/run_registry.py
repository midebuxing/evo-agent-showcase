"""实验归档工厂：统一实验目录约定 + 强制元数据 + 机器可读索引。

本模块给 evo-agent v1 提供一套"从此往后"的实验产物约定与登记工具，目的是
把当前散落、约定分裂、无机器可读索引的实验产物收口到一套统一结构：

1. 目录约定：``<output_root>/<name>_<YYYYMMDD_HHMMSS>/``
   （默认 ``output_root = <agent_v1>/experiments/``，与现有 run_*.py 脚本一致）。
2. 强制元数据：每个 run 目录写一份 ``run_meta.json``（schema_version="1"），
   起始即落盘（status=running），正常结束更新为 completed、异常更新为 failed。
3. 机器可读索引：每个 run 结束追加一行精简 meta 到
   ``<output_root>/_index/experiments_index.jsonl``。
4. 人类可读索引：``rebuild_index_md()`` 由 jsonl（+可选扫盘）重生成
   ``<output_root>/_index/INDEX.md``。

核心入口是 :func:`open_experiment` 上下文管理器，yield 一个
:class:`ExperimentRun` 句柄。脚本只需：

    with open_experiment("evo_full_experiments", params=vars(args)) as run:
        run.add_artifact(run.path("result.json"))
        ...

边界说明（项目原则）：
- 本模块只做归档登记，**不** 读 W2 字段、**不** 介入 allow_stop 判定、**不**
  消费法规真值——纯工程基础设施。
- 本模块只建工具，不回填历史产物、不清理旧文件；:func:`scan_existing` /
  ``--scan`` 是给将来回填用的可选工具，本任务实现但默认不运行。

Windows 友好：所有路径用 :class:`pathlib.Path`，写文件统一 ``encoding="utf-8"``，
JSON 序列化统一 ``ensure_ascii=False``。
"""

from __future__ import annotations

import json
import platform
import socket
import subprocess
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

#: run_meta.json schema 版本号。
SCHEMA_VERSION: str = "1"

#: run 目录内强制元数据文件名。
RUN_META_FILENAME: str = "run_meta.json"

#: 索引子目录名（落于 output_root 下）。
INDEX_DIRNAME: str = "_index"

#: 机器可读索引文件名（每行一条精简 run_meta）。
INDEX_JSONL_FILENAME: str = "experiments_index.jsonl"

#: 人类可读索引文件名。
INDEX_MD_FILENAME: str = "INDEX.md"

#: 目录时间戳格式：``<name>_<YYYYMMDD_HHMMSS>``。
_DIR_TIMESTAMP_FMT: str = "%Y%m%d_%H%M%S"


# ---------------------------------------------------------------------------
# 路径 / 时间 helper
# ---------------------------------------------------------------------------


def default_output_root() -> Path:
    """默认 run 父目录 = ``<agent_v1>/experiments/``。

    本文件位于 ``<agent_v1>/src/evo_agent_baseline/experiments/run_registry.py``，
    向上 3 级即 ``<agent_v1>``，与现有 run_*.py 脚本（``_REPO_ROOT/experiments``，
    其中 ``_REPO_ROOT = agent_v1``）落点一致。
    """
    return Path(__file__).resolve().parents[3] / "experiments"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    """ISO-8601 字符串（UTC，秒级，带 ``Z``）。"""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_timestamp(dt: Optional[datetime] = None) -> str:
    """本地时区目录时间戳（``YYYYMMDD_HHMMSS``）。

    目录名沿用现有脚本的 ``datetime.now().strftime(...)`` 本地时区风格，
    避免新旧目录命名漂移。
    """
    dt = dt or datetime.now()
    return dt.strftime(_DIR_TIMESTAMP_FMT)


def _write_json(path: Path, obj: Any) -> None:
    """原子性较弱但足够的 JSON 落盘（utf-8 + ensure_ascii=False）。

    ``default=str`` 兜底：params 等字段常含 Path / 自定义对象等非 JSON 原生类型
    （脚本作者很容易忘了先 stringify）；统一退化为字符串而非抛 TypeError，
    保证 run_meta 落盘不因一个 Path 而崩。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    path.write_text(text + "\n", encoding="utf-8")


def _git_info() -> Dict[str, Any]:
    """采集 git commit / branch / dirty；任一失败则该字段为 None，不抛错。"""

    def _run(args: Sequence[str]) -> Optional[str]:
        # 注意：不用 text=True。Windows 控制台默认 GBK code page，git 输出含
        # 中文文件名时 text=True 会在 subprocess 读取线程里抛 UnicodeDecodeError，
        # 主线程拿到 stdout=None（静默失败）。故捕获 bytes 后统一 UTF-8 + replace
        # 解码，跨平台稳健。
        try:
            out = subprocess.run(
                list(args),
                capture_output=True,
                cwd=str(Path(__file__).resolve().parent),
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            return None
        raw = out.stdout if out.stdout is not None else b""
        return raw.decode("utf-8", errors="replace").strip()

    commit = _run(["git", "rev-parse", "HEAD"])
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    status = _run(["git", "status", "--porcelain"])
    dirty: Optional[bool]
    if status is None:
        dirty = None
    else:
        dirty = bool(status.strip())
    return {"commit": commit or None, "branch": branch or None, "dirty": dirty}


def _infer_script() -> Optional[str]:
    """从 ``sys.argv[0]`` 推调用脚本相对仓库根的路径（失败则原值/None）。"""
    argv0 = sys.argv[0] if sys.argv else ""
    if not argv0:
        return None
    try:
        script_abs = Path(argv0).resolve()
    except (OSError, ValueError):
        return argv0
    # 尝试相对仓库根（agent_v1 的上一级）表达。
    try:
        repo_root = Path(__file__).resolve().parents[4]
        return str(script_abs.relative_to(repo_root)).replace("\\", "/")
    except (ValueError, IndexError):
        return str(script_abs).replace("\\", "/")


# ---------------------------------------------------------------------------
# ExperimentRun 句柄
# ---------------------------------------------------------------------------


class ExperimentRun:
    """一次标准化实验运行的句柄。

    由 :func:`open_experiment` 创建并 yield。脚本通过本句柄写产物、补元数据。

    属性：
        dir: run 目录（:class:`pathlib.Path`）。
        meta: 当前 run_meta dict（in-memory，落盘以 :meth:`_flush_meta` 为准）。
        run_id: 本次 run 的唯一 id（= 目录名）。
        log_path: 约定日志路径（``dir/run.log``，本模块不强制写，供脚本用）。
    """

    def __init__(self, run_dir: Path, meta: Dict[str, Any], output_root: Path) -> None:
        self.dir: Path = run_dir
        self.meta: Dict[str, Any] = meta
        self._output_root: Path = output_root

    # -- 只读便捷属性 ------------------------------------------------------

    @property
    def run_id(self) -> str:
        return self.meta["run_id"]

    @property
    def log_path(self) -> Path:
        return self.dir / "run.log"

    # -- 路径 helper -------------------------------------------------------

    def path(self, name: str) -> Path:
        """返回 ``dir/name``（不创建）。便于脚本拼产物路径。"""
        return self.dir / name

    # -- 元数据写入 --------------------------------------------------------

    def set(self, **fields: Any) -> None:
        """往 meta 顶层补/覆盖字段并立即落盘。

        约定字段（schema_version / run_id / status 等）也可被覆盖，但调用方
        应自行确保语义；常规用法是补自定义字段（如 ``n_buildings``）。
        """
        self.meta.update(fields)
        self._flush_meta()

    def add_artifact(self, path: Any, kind: Optional[str] = None) -> Dict[str, Any]:
        """登记一个产物到 meta（按相对 run 目录路径去重），返回该产物条目。

        - ``path``：产物路径（绝对或相对均可；存在则记录 bytes，不存在记 None）。
        - ``kind``：产物分类标签（如 "json"/"report"/"parquet_dir"），缺省按
          后缀推断。

        重复登记同一相对路径会更新（不重复追加）。
        """
        p = Path(path)
        if not p.is_absolute():
            p = self.dir / p
        try:
            rel = str(p.resolve().relative_to(self.dir.resolve())).replace("\\", "/")
        except (ValueError, OSError):
            # 产物落在 run 目录外——记绝对路径（不推荐，但不丢信息）。
            rel = str(p).replace("\\", "/")
        entry = {
            "path": rel,
            "bytes": _path_size(p),
            "kind": kind if kind is not None else _infer_kind(p),
        }
        artifacts: List[Dict[str, Any]] = self.meta.setdefault("artifacts", [])
        for i, existing in enumerate(artifacts):
            if existing.get("path") == rel:
                artifacts[i] = entry
                break
        else:
            artifacts.append(entry)
        self._flush_meta()
        return entry

    # -- 内部 --------------------------------------------------------------

    def _flush_meta(self) -> None:
        _write_json(self.dir / RUN_META_FILENAME, self.meta)

    def _scan_artifacts(self) -> None:
        """退出时扫描 run 目录下所有文件，补齐未显式登记的产物。

        - 跳过 run_meta.json 与 run.log 自身。
        - 已登记（按相对路径）的保留其 kind，仅刷新 bytes。
        """
        existing_by_path = {
            a.get("path"): a for a in self.meta.get("artifacts", [])
        }
        scanned: List[Dict[str, Any]] = []
        run_dir_resolved = self.dir.resolve()
        for fp in sorted(self.dir.rglob("*")):
            if not fp.is_file():
                continue
            if fp.name in (RUN_META_FILENAME,):
                continue
            try:
                rel = str(fp.resolve().relative_to(run_dir_resolved)).replace(
                    "\\", "/"
                )
            except (ValueError, OSError):
                continue
            prev = existing_by_path.get(rel)
            kind = prev.get("kind") if prev else _infer_kind(fp)
            scanned.append({"path": rel, "bytes": _path_size(fp), "kind": kind})
        # 保留登记在 run 目录外的旧产物（扫盘扫不到）。
        scanned_paths = {a["path"] for a in scanned}
        for path_key, a in existing_by_path.items():
            if path_key not in scanned_paths:
                scanned.append(a)
        self.meta["artifacts"] = scanned


def _path_size(p: Path) -> Optional[int]:
    """文件字节数；目录返回 None；不存在返回 None。"""
    try:
        if p.is_file():
            return p.stat().st_size
    except OSError:
        return None
    return None


def _infer_kind(p: Path) -> Optional[str]:
    """按后缀推产物 kind 标签。"""
    suffix = p.suffix.lower().lstrip(".")
    return suffix or None


# ---------------------------------------------------------------------------
# 索引登记
# ---------------------------------------------------------------------------


def _index_dir(output_root: Path) -> Path:
    return output_root / INDEX_DIRNAME


def index_jsonl_path(output_root: Optional[Path] = None) -> Path:
    """机器可读索引 jsonl 路径。"""
    root = Path(output_root) if output_root is not None else default_output_root()
    return _index_dir(root) / INDEX_JSONL_FILENAME


def index_md_path(output_root: Optional[Path] = None) -> Path:
    """人类可读索引 markdown 路径。"""
    root = Path(output_root) if output_root is not None else default_output_root()
    return _index_dir(root) / INDEX_MD_FILENAME


def _slim_meta(meta: Mapping[str, Any], run_dir: Path) -> Dict[str, Any]:
    """从完整 run_meta 抽精简索引条目（jsonl 一行）。"""
    git = meta.get("git") or {}
    return {
        "run_id": meta.get("run_id"),
        "name": meta.get("name"),
        "exp_id": meta.get("exp_id"),
        "status": meta.get("status"),
        "started_at": meta.get("started_at"),
        "finished_at": meta.get("finished_at"),
        "duration_sec": meta.get("duration_sec"),
        "git_commit": git.get("commit"),
        "tags": meta.get("tags") or [],
        "n_artifacts": len(meta.get("artifacts") or []),
        "dir": str(run_dir).replace("\\", "/"),
    }


def _append_index_jsonl(output_root: Path, slim: Mapping[str, Any]) -> Path:
    """追加一行精简 meta 到 jsonl 索引；目录不存在则建。"""
    jl = index_jsonl_path(output_root)
    jl.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(slim, ensure_ascii=False, default=str)
    with jl.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return jl


def _read_index_jsonl(output_root: Path) -> List[Dict[str, Any]]:
    """读 jsonl 索引为 dict 列表（坏行跳过）。"""
    jl = index_jsonl_path(output_root)
    rows: List[Dict[str, Any]] = []
    if not jl.is_file():
        return rows
    for raw in jl.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rows.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return rows


def _md_escape(value: Any) -> str:
    """markdown 表格单元转义（None→空，管道符转义）。"""
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def rebuild_index_md(
    output_root: Optional[Path] = None,
    *,
    scan: bool = False,
) -> Path:
    """由 jsonl（+可选扫盘）重生成人类可读 ``INDEX.md`` 表。

    - ``output_root``：实验父目录，默认 :func:`default_output_root`。
    - ``scan``：True 时先 :func:`scan_existing` 把目录里有 run_meta 但未进 jsonl
      的 run 也并入（去重，jsonl 优先）。

    表列：run_id | name | exp_id | status | started_at | git commit | 产物数 | 目录路径。

    返回写出的 ``INDEX.md`` 路径。
    """
    root = Path(output_root) if output_root is not None else default_output_root()
    rows = _read_index_jsonl(root)
    if scan:
        rows = _merge_scanned(rows, scan_existing(root))
    # 同 run_id 去重（Codex MED）：jsonl 追加写，同一 run（如失败后重跑同 dir）会留多行；
    # 保留最后一条（最新状态）。无 run_id 的行原样保留。
    _by_id: Dict[str, Dict[str, Any]] = {}
    _noid: List[Dict[str, Any]] = []
    for r in rows:
        rid = r.get("run_id")
        if rid:
            _by_id[rid] = r  # 后写覆盖前写
        else:
            _noid.append(r)
    rows = list(_by_id.values()) + _noid
    # 按 started_at 排序（None 排最后），稳定。
    rows.sort(key=lambda r: (r.get("started_at") is None, r.get("started_at") or ""))

    lines: List[str] = []
    lines.append("# 实验索引（INDEX.md）")
    lines.append("")
    lines.append(
        "> 本文件由 `run_registry.rebuild_index_md()` 自动生成，请勿手工编辑。"
    )
    lines.append("")
    lines.append(f"共 {len(rows)} 条 run。")
    lines.append("")
    header = (
        "| run_id | name | exp_id | status | started_at | git commit | 产物数 | 目录 |"
    )
    sep = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    lines.append(header)
    lines.append(sep)
    for r in rows:
        commit = r.get("git_commit")
        commit_short = commit[:8] if isinstance(commit, str) else ""
        lines.append(
            "| {run_id} | {name} | {exp_id} | {status} | {started} | {commit} | "
            "{n} | {dir} |".format(
                run_id=_md_escape(r.get("run_id")),
                name=_md_escape(r.get("name")),
                exp_id=_md_escape(r.get("exp_id")),
                status=_md_escape(r.get("status")),
                started=_md_escape(r.get("started_at")),
                commit=_md_escape(commit_short),
                n=_md_escape(r.get("n_artifacts")),
                dir=_md_escape(r.get("dir")),
            )
        )
    out = index_md_path(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _merge_scanned(
    jsonl_rows: Sequence[Mapping[str, Any]],
    scanned_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """合并 jsonl 行与扫盘行，按 run_id 去重（jsonl 优先）。"""
    by_id: Dict[str, Dict[str, Any]] = {}
    for r in scanned_rows:
        rid = r.get("run_id")
        if rid:
            by_id[rid] = dict(r)
    for r in jsonl_rows:  # jsonl 覆盖扫盘
        rid = r.get("run_id")
        if rid:
            by_id[rid] = dict(r)
        else:
            # 无 run_id 的 jsonl 行也保留。
            by_id[f"_noid_{len(by_id)}"] = dict(r)
    return list(by_id.values())


def scan_existing(root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """遍历实验目录找已有 ``run_meta.json``，收集为精简索引条目列表。

    **给将来回填用：本任务实现但不主动运行。** 不写任何文件，只返回数据；
    调用方（或 ``--scan`` CLI）决定是否落盘 / 并入索引。

    - ``root``：扫描根目录，默认 :func:`default_output_root`。
    - 扫描会跳过 ``_index`` 子目录自身。
    - 坏的 / 不可解析的 run_meta.json 跳过（不抛错）。
    """
    base = Path(root) if root is not None else default_output_root()
    out: List[Dict[str, Any]] = []
    if not base.is_dir():
        return out
    index_dir = _index_dir(base).resolve()
    for meta_path in sorted(base.rglob(RUN_META_FILENAME)):
        try:
            if index_dir in meta_path.resolve().parents:
                continue
        except OSError:
            pass
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        out.append(_slim_meta(meta, meta_path.parent))
    return out


# ---------------------------------------------------------------------------
# open_experiment 上下文管理器
# ---------------------------------------------------------------------------


@contextmanager
def open_experiment(
    name: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    exp_id: Optional[str] = None,
    dir: Optional[Any] = None,
    output_root: Optional[Any] = None,
    tags: Optional[Sequence[str]] = None,
    link_exp: Optional[str] = None,
    notes: Optional[str] = None,
) -> Iterator[ExperimentRun]:
    """开一个标准化实验运行：建目录、写 run_meta.json、登记进索引。

    参数：
        name: 实验名（如 ``"evo_full_experiments"``），用于目录前缀。
        params: 实验参数 dict（脚本的 argparse namespace ``vars(args)`` 即可）。
        exp_id: 可选，关联的 EXP-NNN 台账编号。
        dir: 可选，若脚本已自己算好输出目录，传进来直接 adopt（不另建）。
        output_root: 可选，新建目录的父目录；默认 ``<agent_v1>/experiments/``。
        tags: 可选标签列表。
        link_exp: 可选，关联实验台账（写入 ``links.exp_ledger``）。
        notes: 可选备注文本。

    yield 一个 :class:`ExperimentRun` 句柄。

    正常退出：``status=completed``，写 ``finished_at`` / ``duration_sec``，
    扫描产物，追加索引 jsonl。
    异常退出：``status=failed``，记 ``error={type,message}``，仍更新元数据 +
    追加索引，然后 **重新抛出** 异常。
    """
    root = (
        Path(output_root) if output_root is not None else default_output_root()
    )

    started = _utc_now()
    if dir is not None:
        run_dir = Path(dir)
    else:
        run_dir = root / f"{name}_{_local_timestamp(started)}"
    run_dir.mkdir(parents=True, exist_ok=True)

    run_id = run_dir.name

    meta: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "exp_id": exp_id,
        "run_id": run_id,
        "name": name,
        "script": _infer_script(),
        "argv": list(sys.argv),
        "params": dict(params) if params is not None else {},
        "tags": list(tags) if tags is not None else [],
        "links": {"exp_ledger": link_exp},
        "git": _git_info(),
        "python": platform.python_version(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "started_at": _iso(started),
        "finished_at": None,
        "duration_sec": None,
        "status": "running",
        "error": None,
        "artifacts": [],
        "notes": notes,
    }

    run = ExperimentRun(run_dir, meta, root)
    run._flush_meta()

    try:
        yield run
    except BaseException as exc:  # noqa: BLE001 - 记录后重抛
        finished = _utc_now()
        meta["status"] = "failed"
        meta["finished_at"] = _iso(finished)
        meta["duration_sec"] = round((finished - started).total_seconds(), 3)
        meta["error"] = {
            "type": type(exc).__name__,
            "message": _short_error_message(exc),
        }
        # 清理/索引写入失败不得掩盖原始业务异常（Codex MED）——尽力而为、吞掉清理期错误。
        try:
            run._scan_artifacts()
            run._flush_meta()
            _append_index_jsonl(root, _slim_meta(meta, run_dir))
        except Exception:  # noqa: BLE001 - 清理失败不覆盖在途异常
            pass
        raise
    else:
        finished = _utc_now()
        meta["status"] = "completed"
        meta["finished_at"] = _iso(finished)
        meta["duration_sec"] = round((finished - started).total_seconds(), 3)
        run._scan_artifacts()
        run._flush_meta()
        _append_index_jsonl(root, _slim_meta(meta, run_dir))


def _short_error_message(exc: BaseException) -> str:
    """异常消息（截断，避免巨型 traceback 进 meta）。"""
    msg = str(exc).strip()
    if not msg:
        # 无 message 时退而取 traceback 末行。
        tb = traceback.format_exception_only(type(exc), exc)
        msg = "".join(tb).strip()
    if len(msg) > 2000:
        msg = msg[:2000] + "…(truncated)"
    return msg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m evo_agent_baseline.experiments.run_registry",
        description="实验归档工厂索引工具（重建 / 列表 / 扫盘回填）。",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="实验父目录，默认 <agent_v1>/experiments/。",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--rebuild-index",
        action="store_true",
        help="由 jsonl 重建 INDEX.md。",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="打印索引里的实验列表。",
    )
    group.add_argument(
        "--scan",
        action="store_true",
        help="扫盘回填索引（可选回填工具）：把目录里有 run_meta 但未进 jsonl 的"
        " run 并入 jsonl，并重建 INDEX.md。",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    root = (
        Path(args.output_root)
        if args.output_root is not None
        else default_output_root()
    )

    if args.rebuild_index:
        out = rebuild_index_md(root)
        print(f"INDEX.md 已重建: {out}")
        return 0

    if args.list:
        rows = _read_index_jsonl(root)
        if not rows:
            print(f"(空) 索引无记录: {index_jsonl_path(root)}")
            return 0
        print(f"共 {len(rows)} 条 run @ {index_jsonl_path(root)}")
        for r in rows:
            print(
                "  {rid}  [{status}]  {name}  exp={exp}  artifacts={n}".format(
                    rid=r.get("run_id"),
                    status=r.get("status"),
                    name=r.get("name"),
                    exp=r.get("exp_id"),
                    n=r.get("n_artifacts"),
                )
            )
        return 0

    if args.scan:
        scanned = scan_existing(root)
        existing = _read_index_jsonl(root)
        existing_ids = {r.get("run_id") for r in existing}
        new_rows = [r for r in scanned if r.get("run_id") not in existing_ids]
        for r in new_rows:
            _append_index_jsonl(root, r)
        out = rebuild_index_md(root)
        print(
            f"扫盘发现 {len(scanned)} 条 run_meta，新并入 jsonl {len(new_rows)} 条；"
            f"INDEX.md 已重建: {out}"
        )
        return 0

    return 1


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(_cli())
