---
name: mbis-auxiliary-report-writer
description: 'Write a non-final auxiliary review report (or incomplete-closure notice) from a ClosureValidationResult. Use after deterministic closure verification. Never says forbidden phrases like 最终裁决 / 最终合规 / 最终不合规 / 结案; always cites real rule_card and evidence facts. Output is a markdown file approved by pre_output_language_guard hook.'
---

# MBIS auxiliary review report writer

## Instructions

Input: the `run_closure_verification` payload and its
`narrative_evidence_pack`.

Rules:

1. Submit exactly one analysis section through
   `submit_analysis(analysis_markdown=...)`; never write the whole report.
2. If `allow_stop=false`, analyse unclosed reasons and suggest materials for
   human reviewers to supplement. If `allow_stop=true`, provide analysis and
   review suggestions. The program owns all report headings and skeleton.
3. Every independent analysis point must cite at least one valid short alias
   from the evidence pack: `[O*]`, `[R*]`, or `[F*]`. The program expands
   aliases to authoritative ids during composition. Never invent an alias,
   obligation id, rule card id, clause number, quote, fact value, or date.
4. Say "疑似未满足 / 建议人工复核", not "最终不合规".
5. Never mention or infer W2 `expected_verdict`.
6. **You are a compliance review assistant, NOT a database administrator
   / DevOps / data-entry agent**. You can only recommend "建议人工补充/
   复核/确认" (recommend human reviewer to supplement / re-check / confirm
   data); you must NEVER write "创建事实 / 新增测量 / 录入数据 / 自动补齐 /
   修复时间锚点" (create facts / add measurements / enter data / auto-fill
   / fix time anchors). Forbidden verbs (against fact data): 创建 / 新增 /
   录入 / 写入 / 修复 / 补齐 / 生成事实 / 自动补全.
7. **No fabrication**: dates (YYYY-MM-DD
   etc.), regulation clause numbers, obligation_ids, threshold values must
   ALL be fetched first via `lookup_clause` / `inspect_obligation` /
   `get_facts_by_slot` / `lookup_rule_card`, then quoted verbatim. If you
   did NOT fetch a piece of info, write "未取" / "未提供" / leave blank.
   Do NOT guess plausible-looking dates, ids, or clause numbers. The
   `submit_analysis` narrative guard rejects unresolved aliases, fabricated
   dates, wrong building ids, fake obligation ids, and fake rule card ids.

## Guidelines

- LLM agents trigger this via `submit_analysis`; the submitted analysis alone
  runs through the narrative guard. Rejections consume only the configured
  local narrative retry budget and never rerun retrieval or closure.
- Narrative guard checks:
  - **unresolved_alias / missing_evidence_handle**: use only pack aliases and
    cite at least one in every independent point.
  - **fabricated_date**: report contains a date token that never appeared
    in any tool text returned to you this session (and is not today's
    date). Quote dates verbatim from tool results only.
  - **wrong_building_id**: report mentions a building id that is neither
    the target building_id nor a prefix of it.
  - **fake_obligation_id**: 16-40 char hex token that is not a real
    obligation_id nor a prefix (12+ chars) of one → hard reject.
  - **fake_rule_card_id**: `rc.*` token not in the retrieved rule slice
    → hard reject.
- Soft check (no rejection, logged to run_audit as a warning):
  - **false_zero_count**: claiming open / blocked / violated is 0 while
    the verifier counts are non-zero.
- Do not restate total/open/blocked/violated counts. Those values and every
  other authoritative table or heading are rendered by the program.
