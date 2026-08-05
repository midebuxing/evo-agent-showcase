"""中文权威源旁路附件与对账闸的行为锁定(DEBT-071 丙′)。

核心约束有三条，每条都对应一个已实证的事故形状：
  ① **不许碰 `rule_cards.json`**——`card_fingerprint_v1` 哈希整张卡对象，加任何字段都会
     让授权条目全部 stale，而失配是**静默降级**（`return None  # stale_card_binding`）。
     2026-07-26 早上刚因同形 bug（bundle 世界目录格式）导致早退全关、2588 测试全绿。
  ② **缺席语义**：定位不到必须显式 `null` + 原因，**禁止空串伪装**——否则下游静默拿到
     `""` 当正文。
  ③ **附件过期即 fail-closed**：法规原文改了而附件没重建，对账结果一律不作数。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import audit_rulecard_modality_drift as drift  # noqa: E402
import build_rulecard_zh_sidecar as sidecar  # noqa: E402

SIDECAR = (drift.REG / "rulecard_v2" / "mbis_cop_2023" / "rulecard_zh_sidecar_v1.json")


def _load():
    if not SIDECAR.is_file():
        import pytest
        pytest.skip("附件未生成(派生物，可用 build_rulecard_zh_sidecar.py 重建)")
    return json.loads(SIDECAR.read_text(encoding="utf-8"))


def test_sidecar_never_fakes_absence_with_empty_string():
    """🔴 缺席语义:定位不到必须 `cn_text: null` + `absent_reason`，**不许空串**。

    空串会让下游静默拿到 "" 当正文——分不清「没有中文」与「中文是空的」。
    """
    doc = _load()
    fake = [k for k, e in doc["cards"].items() if e.get("cn_text") == ""]
    assert not fake, f"{len(fake)} 条用空串伪装了正文"
    for k, e in doc["cards"].items():
        if e.get("cn_text") is None:
            assert e.get("absent_reason"), f"{k} 缺席但没写原因(禁静默丢弃)"


def test_sidecar_pins_regulation_hash():
    """附件必须钉住法规原文哈希——法规一改就能发现附件过期。"""
    doc = _load()
    cn = (drift.REG / "markdown" / "MBIS_CoP_2023.md").read_text(encoding="utf-8")
    assert doc["regulation_sha256"] == hashlib.sha256(cn.encode("utf-8")).hexdigest()


def test_sidecar_declares_chinese_is_authoritative():
    """附件必须写明「中文权威、英文是无效力证据力的译文」——这是本路线的全部理由。"""
    doc = _load()
    note = doc.get("authority_note") or ""
    assert "權威" in note or "权威" in note
    assert "译文" in note and "无效力证据力" in note


def test_builder_does_not_touch_rule_cards():
    """🔴 接线闸:构建器**不得写 `rule_cards.json`**。

    `card_fingerprint_v1` 哈希整张卡对象，动一个字节就让授权全部 stale，而且是**静默**的
    （`component_lattice.py` 失配返回 None、`applicability_v3.py` 失配 continue）。
    本测试锁住"只读卡包"这条边界。
    """
    import inspect
    src = inspect.getsource(sidecar)
    assert "read_text" in src
    for forbidden in ("rule_cards.json\").write_text",
                      "rule_cards.json').write_text"):
        assert forbidden not in src
    # 构建器必须在文档里写明为什么不能碰卡
    assert "字节" in sidecar.__doc__ and "静默" in sidecar.__doc__


def test_sidecar_covers_the_bulk_of_cards():
    """覆盖不得悄悄退化:有中文的卡数必须占绝大多数(当前 386/397)。"""
    doc = _load()
    total = len(doc["cards"])
    present = sum(1 for e in doc["cards"].values() if e.get("cn_text"))
    assert present >= total * 0.9, f"覆盖退化到 {present}/{total}"


# ===== 消费面改指:默认关闭 + fail-closed(DEBT-071 丙′) =====


def test_zh_authority_is_off_by_default():
    """🔴 默认必须关闭——不设环境变量时行为与改动前**逐字节相同**。

    改「报告引什么文本」「大模型看什么文本」是运行时行为变更，必须跑批对照后才翻开关。
    本项目栽过同形的跟头:bundle 世界目录格式写错 → 早退全关 → **2,588 测试与 12 项
    发布门禁全绿**、跑了 8 栋才被跨批对账抓出来。
    """
    import os
    from evo_agent_baseline.ingest import zh_authority
    old = os.environ.pop("EVO_ZH_AUTHORITY", None)
    try:
        zh_authority.reset_cache()
        assert zh_authority.enabled() is False
        assert zh_authority.zh_text_for_card("任意卡") is None
    finally:
        if old is not None:
            os.environ["EVO_ZH_AUTHORITY"] = old
        zh_authority.reset_cache()


def test_zh_authority_fails_closed_on_stale_sidecar(tmp_path, monkeypatch):
    """🔴 变异测试:开关打开但附件**过期**必须抛错拒跑，**绝不静默回退到英文**。

    静默回退正是「关键配置静默退化」那一族——配置没生效、行为退回旧路径、无人报错。
    """
    import json
    import os
    import pytest
    from evo_agent_baseline.ingest import zh_authority

    fake_root = tmp_path
    side = fake_root / zh_authority._SIDECAR_REL
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({"regulation_sha256": "0" * 64, "cards": {}}),
                    encoding="utf-8")
    reg = fake_root / zh_authority._REGULATION_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text("法規原文已改，附件没重建", encoding="utf-8")

    monkeypatch.setenv("EVO_ZH_AUTHORITY", "1")
    monkeypatch.setattr(zh_authority, "_repo_root", lambda: fake_root)
    zh_authority.reset_cache()
    with pytest.raises(RuntimeError, match="过期|不符"):
        zh_authority.zh_text_for_card("任意卡")
    zh_authority.reset_cache()


def test_zh_authority_fails_closed_when_sidecar_missing(tmp_path, monkeypatch):
    """开关打开但附件**不存在**同样必须抛错，不得当成"没有中文"悄悄用英文。"""
    import pytest
    from evo_agent_baseline.ingest import zh_authority
    monkeypatch.setenv("EVO_ZH_AUTHORITY", "1")
    monkeypatch.setattr(zh_authority, "_repo_root", lambda: tmp_path)
    zh_authority.reset_cache()
    with pytest.raises(RuntimeError, match="不存在"):
        zh_authority.zh_text_for_card("任意卡")
    zh_authority.reset_cache()


def test_report_writer_uses_chinese_and_never_falls_back_to_translation(monkeypatch):
    """接线闸：消费者文本只可取中文权威源，缺失时不得使用派生译文。"""
    import inspect
    from evo_agent_baseline.agent import report_writer
    src = inspect.getsource(report_writer._first_quote_for_card)
    assert "zh_authority.zh_text_for_card" in src, "报告引文没接中文权威源"

    calls = []
    monkeypatch.setattr(report_writer.zh_authority, "zh_text_for_card",
                        lambda cid: (calls.append(cid), "中文正文")[1])

    class _C:
        rule_card_id = "rc.x"
        source_quote = [{"text": "English translation"}]
        normalized_rule_text = "normalized"
    assert report_writer._first_quote_for_card(None, _C()) == "中文正文"
    assert calls == ["rc.x"]

    # 中文缺席时宁可不附规则文本，也绝不能把不忠实译文交给消费者。
    monkeypatch.setattr(report_writer.zh_authority, "zh_text_for_card",
                        lambda cid: None)
    assert report_writer._first_quote_for_card(None, _C()) is None


def test_empty_string_never_passes_as_chinese(monkeypatch):
    """空串伪装第二道防线:附件里若混进 `""`，读取层也要当成缺席。"""
    import os
    from evo_agent_baseline.ingest import zh_authority
    monkeypatch.setenv("EVO_ZH_AUTHORITY", "1")
    monkeypatch.setattr(zh_authority, "_load",
                        lambda: {"cards": {"rc.x": {"cn_text": "   "}}})
    assert zh_authority.zh_text_for_card("rc.x") is None


# ===== 阈值回填旁路附件(DEBT-071 第一刀的交付形态) =====

THRESH = (drift.REG / "rulecard_v2" / "mbis_cop_2023"
          / "rulecard_threshold_sidecar_v1.json")


def _load_thresholds():
    if not THRESH.is_file():
        import pytest
        pytest.skip("阈值附件未生成(派生物)")
    return json.loads(THRESH.read_text(encoding="utf-8"))


def test_every_threshold_carries_verbatim_chinese():
    """🔴 每条阈值必须带中文原句逐字——没有它就**无从复核**。

    "无从复核的阈值"正是本项目要根治的东西（卡里 41 条阈值、来源不可查），
    不能在修复过程里再造一批。
    """
    doc = _load_thresholds()
    assert doc["thresholds"], "附件是空的"
    for t in doc["thresholds"]:
        assert (t.get("source_zh") or "").strip(), f"{t['section_id']} 缺中文原句"
        assert t.get("operator"), f"{t['section_id']} 缺比较算子"
        assert t.get("provenance") == "zh_backfill_v1", "缺来源标记，进图后无法审计"


def test_flagship_threshold_is_present_and_correct():
    """今天追了一整天的那条:「嚴重銹蝕」的操作性定义回来了。"""
    doc = _load_thresholds()
    hit = [t for t in doc["thresholds"]
           if "App5 1.1(d)" in t["section_id"] and t["number"] == 15]
    assert hit, "§App5 1.1(d) 的 >15% 没入册"
    t = hit[0]
    assert t["operator"] == ">" and t["unit"] == "%"
    assert "損失的截面面積大於 15%" in t["source_zh"]


def test_threshold_adjudications_declare_no_runtime_effect():
    """裁定记录必须明确停用，禁止重新长出运行时注入契约。"""
    doc = _load_thresholds()
    assert doc.get("status") == "deferred"
    assert doc.get("runtime_effect") == "none"
    assert (doc.get("injection_policy") or {}).get("injectable_roles") == []
    assert "injection_contract" not in doc, "停用记录仍声明注入契约，会诱导死路径复活"

def test_threshold_builder_never_writes_rule_cards():
    """🔴 接线闸:构建器不得写 `rule_cards.json`——写了就静默炸授权链。"""
    import inspect
    import build_threshold_sidecar as bt
    src = inspect.getsource(bt)
    assert "rule_cards.json\").write_text" not in src
    assert "rule_cards.json').write_text" not in src
    assert "指纹" in bt.__doc__ and "静默" in bt.__doc__


def test_zh_sidecar_is_in_sync_with_card_pack():
    """🔴 派生物必须与卡包同步——改卡后忘了重跑 sidecar 会静默留下旧快照。

    2026-07-26 整理改动面时撞到:补了 canary 卡后 sidecar 仍是 397 张，
    唯一差异就是漏了新卡。**内容变了的 0 张**——证明它确实是纯派生物，
    但也证明"派生物不会自己跟上"。
    """
    import json as _j
    cards = _j.loads((drift.REG / "rulecard_v2" / "mbis_cop_2023"
                      / "rule_cards.json").read_text(encoding="utf-8"))["cards"]
    side_p = (drift.REG / "rulecard_v2" / "mbis_cop_2023"
              / "rulecard_zh_sidecar_v1.json")
    if not side_p.is_file():
        import pytest as _p
        _p.skip("中文权威源附件未生成（派生物）")
    side = _j.loads(side_p.read_text(encoding="utf-8"))["cards"]
    missing = {c["rule_card_id"] for c in cards} - set(side)
    assert not missing, (
        f"{len(missing)} 张卡不在中文权威源附件里——改卡后须重跑 "
        f"build_rulecard_zh_sidecar.py：{sorted(missing)[:3]}")
