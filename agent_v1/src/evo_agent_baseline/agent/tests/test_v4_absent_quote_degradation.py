"""v4 引文缺席诚实降级（2026-08-04）。"""
from evo_agent_baseline.agent import report_contract_v4 as v4


# ===== 显式缺席引文的诚实降级（2026-08-04；15/30 栋叙述被 11 张缺席卡黑洞的修复）=====

def _mk_pack_and_points(quote):
    class P: pass
    pack=P()
    pack.key_items=[{"alias":"O1","category":"open","reason_code":"missing_fact",
                     "rule_card_alias":"R1","fact_aliases":[],"evidence_aliases":[],
                     "kind":"evidence","satisfaction_status":"unknown","closure_status":"open"}]
    pack.rule_cards=[{"alias":"R1","rule_card_id":"rc.test.s9_9_9.c01","quote":quote}]
    pack.facts=[]
    pts=[{"obligation_alias":"O1","analysis_code":"EVIDENCE_GAP",
          "review_action_code":"MANUAL_VERIFY","selected_fact_aliases":[]}]
    norm,errs=v4.validate_submission_payload_v4({"contract":"report_contract_v4","points":pts},pack.key_items)
    assert not errs and norm is not None, errs
    return pack,norm


def test_absent_quote_degrades_honestly_instead_of_killing_render():
    """占位引文 ⇒ 渲染成功＋条款号引用行，**绝不**出现引号包着的占位符。"""
    pack,norm=_mk_pack_and_points("（未取得引文）")
    out=v4.render_v4_points(pack,norm)
    assert out is not None, "缺席卡把整篇拉黑洞——降级失效"
    joined=chr(10).join(out)
    assert "显式缺席" in joined and "rc.test.s9_9_9.c01" in joined
    assert "「（未取得引文）」" not in joined, "占位符被当引文渲出＝2026-07-23 那个洞复活"


def test_normal_quote_renders_verbatim_unchanged():
    pack,norm=_mk_pack_and_points("條文原文逐字。")
    out=v4.render_v4_points(pack,norm)
    assert out is not None and any("「條文原文逐字。」" in l for l in out)


def test_missing_card_still_fails_whole_render():
    """卡整个缺失（非引文缺席）仍整篇 fallback——降级只放宽引文档，不放宽卡档。"""
    pack,norm=_mk_pack_and_points("x")
    pack.rule_cards=[]
    assert v4.render_v4_points(pack,norm) is None
