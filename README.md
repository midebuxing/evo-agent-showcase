# evo-agent Showcase

Research snapshot of **evo-agent** — a compliance-assistant agent system for Hong Kong
MBIS (Mandatory Building Inspection Scheme) building-inspection auditing, built as a
master's-thesis research project exploring **runtime scaling laws and self-evolving
agent skills** on top of a deterministic compliance-verification backbone.

> This is a curated read-only snapshot (code + design specs + experiment reports),
> synced from a private research repository. Regulatory source texts and experiment
> data artifacts are intentionally excluded.

## Layout

| Path | What it is |
|---|---|
| `agent_v1/src/workflow_engine/` | Perception layer: synthetic world generation (W0/W1) + normative projection (W2, reference truth) |
| `agent_v1/src/evo_agent_baseline/` | Cognition/baseline agent: KG-RAG retrieval, deterministic closure verifier (sole authority on compliance verdicts), LLM orchestration, report contract v4 (zero model free-text) |
| `agent_v1/docs/` | Architecture overviews, glossary, quickstart |
| `agent_v1/tests/` + `src/**/tests/` | Test suites (~2.5k tests) |
| `团队文档/我的笔记/蓝图汇总/` | Design specifications (authoritative, Chinese) |
| `实验记录/` | Experiment reports EXP-001…015 (runtime scaling law, skills-evo ablations, baseline acceptance, narrative-layer contract v4) |

## Key ideas

- **Judgment-authority red line**: compliance verdicts come only from a deterministic
  closure verifier; the LLM orchestrates tool calls and evidence selection but never
  decides outcomes.
- **Report contract v4**: the model submits only structured selections
  (obligation / analysis code / evidence aliases / review action); every sentence in
  the final report is deterministically rendered from authoritative objects — rule
  misparaphrase is impossible by construction.
- **Runtime scaling law (EXP-009)**: M(K) = M∞ + a·K^(−α) fitted over cumulative
  experience K across seeded world pools.

Most documentation and specs are written in Chinese.
