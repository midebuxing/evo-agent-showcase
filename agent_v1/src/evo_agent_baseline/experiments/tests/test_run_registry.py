"""实验归档工厂单测（run_registry）。

覆盖：
- ``open_experiment`` 建目录 + 写 run_meta（status running→completed）；
- 传 ``dir=`` adopt 现有目录（不另建）；
- 异常路径 status=failed + error 记录 + 仍登记索引 + 异常重抛；
- ``add_artifact`` + 退出时扫描产物；
- 索引 jsonl 追加 + ``rebuild_index_md`` 产出 INDEX.md；
- ``scan_existing`` 回填；CLI ``--list`` / ``--scan`` / ``--rebuild-index``。

隔离约束：全程用 ``tmp_path`` 作 ``output_root``，**绝不写真实 experiments/**。
单测不连 Neo4j、不跑真实验。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evo_agent_baseline.experiments import run_registry as rr
from evo_agent_baseline.experiments.run_registry import (
    RUN_META_FILENAME,
    SCHEMA_VERSION,
    ExperimentRun,
    index_jsonl_path,
    index_md_path,
    open_experiment,
    rebuild_index_md,
    scan_existing,
)


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------


def _read_meta(run: ExperimentRun) -> dict:
    return json.loads((run.dir / RUN_META_FILENAME).read_text(encoding="utf-8"))


def _read_jsonl(root: Path) -> list:
    jl = index_jsonl_path(root)
    if not jl.is_file():
        return []
    return [
        json.loads(line)
        for line in jl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# open_experiment: 建目录 + run_meta running→completed
# ---------------------------------------------------------------------------


def test_open_experiment_creates_dir_and_meta(tmp_path: Path) -> None:
    running_snapshot = {}
    with open_experiment(
        "demo_exp",
        params={"n": 3, "seed": 42},
        exp_id="EXP-099",
        output_root=tmp_path,
        tags=["smoke", "unit"],
        link_exp="EXP-099",
        notes="单测 happy path",
    ) as run:
        # run 目录已建，meta 已落盘且 status=running。
        assert run.dir.is_dir()
        assert run.dir.parent == tmp_path
        assert run.dir.name.startswith("demo_exp_")
        running_snapshot.update(_read_meta(run))
        assert running_snapshot["status"] == "running"
        assert running_snapshot["finished_at"] is None

    # 上下文退出后 status=completed。
    meta = _read_meta(run)
    assert meta["schema_version"] == SCHEMA_VERSION
    assert meta["name"] == "demo_exp"
    assert meta["exp_id"] == "EXP-099"
    assert meta["params"] == {"n": 3, "seed": 42}
    assert meta["tags"] == ["smoke", "unit"]
    assert meta["links"] == {"exp_ledger": "EXP-099"}
    assert meta["notes"] == "单测 happy path"
    assert meta["status"] == "completed"
    assert meta["finished_at"] is not None
    assert meta["duration_sec"] is not None and meta["duration_sec"] >= 0
    assert meta["error"] is None
    # 元数据采集字段存在。
    assert "git" in meta and set(meta["git"]) == {"commit", "branch", "dirty"}
    assert meta["python"]
    assert meta["host"]
    assert meta["platform"]
    assert isinstance(meta["argv"], list)
    # run_id == 目录名。
    assert meta["run_id"] == run.dir.name == run.run_id


def test_default_output_root_is_under_agent_v1() -> None:
    # 默认落点 = <agent_v1>/experiments（不实际写，只检查路径推断）。
    root = rr.default_output_root()
    assert root.name == "experiments"
    assert root.parent.name == "agent_v1"


# ---------------------------------------------------------------------------
# dir= adopt 现有目录
# ---------------------------------------------------------------------------


def test_open_experiment_adopts_explicit_dir(tmp_path: Path) -> None:
    explicit = tmp_path / "preexisting_run_dir"
    explicit.mkdir()
    (explicit / "marker.txt").write_text("已存在", encoding="utf-8")

    with open_experiment(
        "adopt_exp",
        dir=explicit,
        output_root=tmp_path,
    ) as run:
        assert run.dir == explicit
        # 没有另建 <name>_<ts> 目录。
        siblings = [p for p in tmp_path.iterdir() if p.is_dir() and p != explicit]
        siblings = [p for p in siblings if p.name != "_index"]
        assert siblings == []

    meta = _read_meta(run)
    assert meta["run_id"] == "preexisting_run_dir"
    assert meta["status"] == "completed"
    # 预存文件被扫描为产物。
    paths = {a["path"] for a in meta["artifacts"]}
    assert "marker.txt" in paths


# ---------------------------------------------------------------------------
# 异常路径：status=failed + error + 仍登记索引 + 重抛
# ---------------------------------------------------------------------------


def test_open_experiment_failure_records_and_reraises(tmp_path: Path) -> None:
    captured_run = {}

    with pytest.raises(ValueError, match="boom 故障"):
        with open_experiment("fail_exp", output_root=tmp_path) as run:
            captured_run["dir"] = run.dir
            raise ValueError("boom 故障")

    meta = json.loads(
        (captured_run["dir"] / RUN_META_FILENAME).read_text(encoding="utf-8")
    )
    assert meta["status"] == "failed"
    assert meta["error"] == {"type": "ValueError", "message": "boom 故障"}
    assert meta["finished_at"] is not None
    assert meta["duration_sec"] is not None

    # 失败也登记进索引。
    rows = _read_jsonl(tmp_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["run_id"] == meta["run_id"]


# ---------------------------------------------------------------------------
# add_artifact + 退出扫描
# ---------------------------------------------------------------------------


def test_add_artifact_and_exit_scan(tmp_path: Path) -> None:
    with open_experiment("artifact_exp", output_root=tmp_path) as run:
        # 显式登记一个 json 产物。
        result = run.path("result.json")
        result.write_text(json.dumps({"ok": True}), encoding="utf-8")
        entry = run.add_artifact(result, kind="result")
        assert entry["path"] == "result.json"
        assert entry["kind"] == "result"
        assert entry["bytes"] is not None and entry["bytes"] > 0

        # 另写一个未显式登记的文件，退出扫描应自动收进来。
        run.path("extra.log").write_text("行1\n行2\n", encoding="utf-8")

        # 嵌套子目录产物也应被扫描。
        sub = run.path("nested")
        sub.mkdir()
        (sub / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    meta = _read_meta(run)
    by_path = {a["path"]: a for a in meta["artifacts"]}
    # run_meta.json 本身不计入产物。
    assert RUN_META_FILENAME not in by_path
    # 显式登记的保留其 kind。
    assert by_path["result.json"]["kind"] == "result"
    # 未登记的被扫描进来，kind 按后缀推断。
    assert "extra.log" in by_path and by_path["extra.log"]["kind"] == "log"
    assert "nested/data.csv" in by_path and by_path["nested/data.csv"]["kind"] == "csv"
    for entry in meta["artifacts"]:
        assert entry["bytes"] is not None and entry["bytes"] >= 0


def test_add_artifact_dedup_updates_in_place(tmp_path: Path) -> None:
    with open_experiment("dedup_exp", output_root=tmp_path) as run:
        p = run.path("r.json")
        p.write_text("{}", encoding="utf-8")
        run.add_artifact(p, kind="first")
        run.add_artifact(p, kind="second")
        # 同一相对路径只应有一条（去重更新）。
        same = [a for a in run.meta["artifacts"] if a["path"] == "r.json"]
        assert len(same) == 1
        assert same[0]["kind"] == "second"


def test_set_appends_custom_fields(tmp_path: Path) -> None:
    with open_experiment("set_exp", output_root=tmp_path) as run:
        run.set(n_buildings=200, kg_snapshot_id="KGS-test-001")
    meta = _read_meta(run)
    assert meta["n_buildings"] == 200
    assert meta["kg_snapshot_id"] == "KGS-test-001"


def test_non_json_native_params_serialize_via_default_str(tmp_path: Path) -> None:
    """params 含 Path 等非 JSON 原生类型不应让落盘崩（``default=str`` 兜底）。

    回归点：run_long_run_qa.py 的 --output-dir 是 Path；若工厂不兜底，脚本作者
    必须记得手动 stringify，否则 run_meta.json 落盘抛 TypeError。
    """
    out_dir = tmp_path / "some" / "nested"
    with open_experiment(
        "path_param_exp",
        params={"output_dir": out_dir, "seed": 7},
        output_root=tmp_path,
    ) as run:
        pass
    # 不抛异常即通过；Path 退化为字符串落盘。
    meta = _read_meta(run)
    assert meta["status"] == "completed"
    assert meta["params"]["output_dir"] == str(out_dir)
    assert meta["params"]["seed"] == 7


# ---------------------------------------------------------------------------
# 索引 jsonl 追加 + rebuild_index_md
# ---------------------------------------------------------------------------


def test_index_jsonl_appends_per_run(tmp_path: Path) -> None:
    with open_experiment("multi_a", output_root=tmp_path):
        pass
    with open_experiment("multi_b", params={"x": 1}, output_root=tmp_path):
        pass

    rows = _read_jsonl(tmp_path)
    assert len(rows) == 2
    names = [r["name"] for r in rows]
    assert names == ["multi_a", "multi_b"]
    for r in rows:
        assert r["status"] == "completed"
        assert "git_commit" in r
        assert "dir" in r
        assert "n_artifacts" in r


def test_rebuild_index_md(tmp_path: Path) -> None:
    with open_experiment("md_exp", exp_id="EXP-007", output_root=tmp_path) as run:
        run.path("a.json").write_text("{}", encoding="utf-8")

    out = rebuild_index_md(tmp_path)
    assert out == index_md_path(tmp_path)
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    # 表头列齐全。
    assert "| run_id | name | exp_id | status | started_at | git commit | 产物数 | 目录 |" in text
    # 数据行包含本 run。
    assert run.run_id in text
    assert "md_exp" in text
    assert "EXP-007" in text
    assert "completed" in text


# ---------------------------------------------------------------------------
# scan_existing 回填
# ---------------------------------------------------------------------------


def test_scan_existing_collects_run_meta(tmp_path: Path) -> None:
    # 造两个 run（产生 run_meta.json）。
    with open_experiment("scan_a", output_root=tmp_path):
        pass
    with open_experiment("scan_b", output_root=tmp_path):
        pass

    scanned = scan_existing(tmp_path)
    names = sorted(r["name"] for r in scanned)
    assert names == ["scan_a", "scan_b"]
    # 扫描跳过 _index 目录自身（不会把 INDEX 当 run）。
    rebuild_index_md(tmp_path)  # 产生 _index/INDEX.md
    scanned_again = scan_existing(tmp_path)
    assert sorted(r["name"] for r in scanned_again) == ["scan_a", "scan_b"]


def test_scan_existing_missing_root_returns_empty(tmp_path: Path) -> None:
    assert scan_existing(tmp_path / "does_not_exist") == []


def test_rebuild_index_md_with_scan_merges(tmp_path: Path) -> None:
    # 手工造一个有 run_meta 但 jsonl 没登记的目录（模拟历史产物）。
    legacy = tmp_path / "legacy_run_20200101_000000"
    legacy.mkdir()
    legacy_meta = {
        "schema_version": SCHEMA_VERSION,
        "run_id": "legacy_run_20200101_000000",
        "name": "legacy_run",
        "exp_id": None,
        "status": "completed",
        "started_at": "2020-01-01T00:00:00Z",
        "finished_at": "2020-01-01T00:00:01Z",
        "duration_sec": 1.0,
        "git": {"commit": "deadbeef", "branch": "old", "dirty": False},
        "artifacts": [],
    }
    (legacy / RUN_META_FILENAME).write_text(
        json.dumps(legacy_meta, ensure_ascii=False), encoding="utf-8"
    )

    # 另跑一个正常 run（进 jsonl）。
    with open_experiment("fresh_run", output_root=tmp_path) as run:
        pass

    text = rebuild_index_md(tmp_path, scan=True).read_text(encoding="utf-8")
    assert "legacy_run" in text  # 扫盘并入
    assert run.run_id in text  # jsonl 来源


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_rebuild_index(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    with open_experiment("cli_exp", output_root=tmp_path):
        pass
    rc = rr._cli(["--output-root", str(tmp_path), "--rebuild-index"])
    assert rc == 0
    assert index_md_path(tmp_path).is_file()
    assert "INDEX.md 已重建" in capsys.readouterr().out


def test_cli_list(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    with open_experiment("cli_list_exp", output_root=tmp_path):
        pass
    rc = rr._cli(["--output-root", str(tmp_path), "--list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cli_list_exp" in out
    assert "completed" in out


def test_cli_scan_backfills(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    # 造一个 jsonl 未登记的历史目录。
    legacy = tmp_path / "old_run_19990101_000000"
    legacy.mkdir()
    (legacy / RUN_META_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": "old_run_19990101_000000",
                "name": "old_run",
                "status": "completed",
                "started_at": "1999-01-01T00:00:00Z",
                "artifacts": [],
                "git": {"commit": None, "branch": None, "dirty": None},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rc = rr._cli(["--output-root", str(tmp_path), "--scan"])
    assert rc == 0
    rows = _read_jsonl(tmp_path)
    assert any(r["run_id"] == "old_run_19990101_000000" for r in rows)
    assert "扫盘发现" in capsys.readouterr().out


def test_cli_requires_a_mode(tmp_path: Path) -> None:
    # 互斥组 required=True：不给任何模式应报错（SystemExit）。
    with pytest.raises(SystemExit):
        rr._cli(["--output-root", str(tmp_path)])


def test_rebuild_index_dedups_duplicate_run_id(tmp_path: Path) -> None:
    """回归（Codex MED）：同一 dir 重跑会在 jsonl 留同 run_id 多行；
    rebuild_index_md 应按 run_id 去重、保留最后一条（最新状态）。"""
    d = tmp_path / "dup_run_20200101_000000"
    # 第一次（失败）→ 追加一行 status=failed
    with pytest.raises(ValueError):
        with open_experiment("dup", dir=d, output_root=tmp_path):
            raise ValueError("boom")
    # 第二次（成功，同 dir）→ 再追加一行 status=completed
    with open_experiment("dup", dir=d, output_root=tmp_path):
        pass

    rows = _read_jsonl(tmp_path)
    same = [r for r in rows if r["run_id"] == "dup_run_20200101_000000"]
    assert len(same) == 2, "jsonl 应有 2 行（追加写）"

    text = rebuild_index_md(tmp_path).read_text(encoding="utf-8")
    data_rows = [
        ln for ln in text.splitlines() if ln.startswith("| dup_run_20200101_000000 |")
    ]
    assert len(data_rows) == 1, "INDEX.md 该 run_id 应去重为 1 行"
    assert "completed" in data_rows[0], "去重应保留最后一条（completed）"
