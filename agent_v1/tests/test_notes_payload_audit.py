"""`notes` 结构化载荷审计器的行为锁定。

为什么有这个审计器(2026-07-25):义务 `notes` 是自由文本，却承载 10 种 `key=value`
(`bucket=` / `sources=` / `slot_id=` …)。**8,426 条义务的 notes 里有两个以上
`bucket=`**，形如 `bucket=obligation_graph.node | bucket=workflow_operands.artifacts`。
同一天我因此三次得出错误结论——按分隔符切会切出带 ` |` 的怪串归错桶，把
"节点派生义务 83% 闭合"读成"0% 闭合"。

审计器本身不改判定层，它的价值是**在任何人写 notes 解析之前先量出风险**。
"""
from __future__ import annotations

import inspect
import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import audit_notes_structured_payload as audit  # noqa: E402


@pytest.fixture
def work_path():
    root = Path(__file__).parent / ".notes_audit_tmp"
    root.mkdir(exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            root.rmdir()
        except OSError:
            pass


def _batch(root: Path, notes_list: list[str]) -> Path:
    batch = root / "batch"
    run = batch / "buildings" / "BLD-X" / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "obligation_set.json").write_text(json.dumps({
        "obligations": [{"notes": n} for n in notes_list]
    }, ensure_ascii=False), encoding="utf-8")
    return batch


def test_detects_duplicate_key_in_one_notes(work_path, capsys):
    """核心能力:必须报出「同一条 notes 里重复出现的键」。

    这是真实数据的形状——双 bucket 就是这么写的。审计器若漏报这一项，
    下游就会继续用 split 取第一个值，重演今天那三次误判。
    """
    batch = _batch(work_path, [
        "bucket=obligation_graph.node | bucket=workflow_operands.artifacts",
        "bucket=for_completion",
        "sources=[obligation_graph]; slot_id=defect.class.present",
    ])
    rc = audit.main(["--batch-root", str(batch)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "重复出现" in out and "bucket" in out
    # 必须给出安全解析指引，而不是只报数
    assert "不要" in out and "split" in out


def test_reports_no_duplicates_when_clean(work_path, capsys):
    batch = _batch(work_path, ["bucket=a", "sources=[x]"])
    audit.main(["--batch-root", str(batch)])
    assert "无重复键" in capsys.readouterr().out


def test_audit_itself_does_not_use_naive_split():
    """审计器不能自己踩它要检测的坑——必须用 findall 取全部值，不是 split 取第一个。"""
    src = inspect.getsource(audit)
    assert "findall" in src, "须用 findall 枚举全部键出现"
    assert "split('bucket=')" not in src and 'split("bucket=")' not in src, \
        "审计器自己用 split 取第一个值，等于重演被审计的 bug"
