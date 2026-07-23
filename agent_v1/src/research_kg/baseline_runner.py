"""DualSourceBaselineRunner — Phase D 最小 baseline 运行器.

流程: 查询 -> KG 检索 -> LLM 选择/解释 -> Closure Verifier -> 输出
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from research_kg.baseline_config import LocalLLMConfig
from research_kg.kg_retriever import RetrievalResult, retrieve_from_kg
from research_kg.loader import DualSourceResearchKG, load_dual_source_kg

from workflow_engine.closure_validator import validate_closure
from workflow_engine.evidence_schema import FactItem, FactPack, RuleCard, RuleCondition
from workflow_engine.obligation_schema import ClosureValidationResult


# ---------------------------------------------------------------------------
# LLM caller (OpenAI-compatible, minimal)
# ---------------------------------------------------------------------------


def _is_ollama_endpoint(config: LocalLLMConfig) -> bool:
    parsed = urlparse(config.base_url)
    return (parsed.hostname or "") in {"127.0.0.1", "localhost", "0.0.0.0", "::1"} and parsed.port == 11434


def _ollama_url(config: LocalLLMConfig, path: str) -> str:
    parsed = urlparse(config.base_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    return f"{base}{path}"


def _wait_for_ollama_ready(config: LocalLLMConfig) -> None:
    """Wait briefly for Ollama service readiness on fresh start."""
    import httpx

    ready_url = _ollama_url(config, "/api/tags")
    last_error: Optional[Exception] = None
    for _ in range(6):
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(ready_url)
                resp.raise_for_status()
                return
        except Exception as exc:  # pragma: no cover - integration path
            last_error = exc
            time.sleep(1)
    if last_error:
        raise last_error


def _call_llm(config: LocalLLMConfig, prompt: str) -> str:
    """Call the local LLM via Ollama native API or OpenAI-compatible HTTP API."""
    import httpx

    if _is_ollama_endpoint(config):
        _wait_for_ollama_ready(config)
        payload = {
            "model": config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一个建筑检测评估助手。"
                        "你的职责是从用户的缺陷描述中提取事实数据，并选择最相关的规则。"
                        "请用 JSON 格式回复。不要输出最终 Pass/Fail 判定。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        if config.model.startswith("qwen3.5"):
            payload["think"] = False

        with httpx.Client(timeout=config.timeout) as client:
            resp = client.post(_ollama_url(config, "/api/chat"), json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]

    url = f"{config.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个建筑检测评估助手。"
                    "你的职责是从用户的缺陷描述中提取事实数据，并选择最相关的规则。"
                    "请用 JSON 格式回复。不要输出最终 Pass/Fail 判定。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
    }

    with httpx.Client(timeout=config.timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _build_extraction_prompt(query: str, retrieval: RetrievalResult) -> str:
    """Build the prompt for LLM fact extraction and rule selection."""
    rule_descriptions = []
    for rc in retrieval.rule_cards:
        props = rc.get("properties", {})
        conditions = props.get("conditions", [])
        cond_strs = [
            f"  - {c['fact_key']} {c['comparator']} {c['threshold']}"
            for c in conditions
        ]
        rule_descriptions.append(
            f"规则 {rc['node_id']} ({rc['label']}):\n"
            f"  理由: {props.get('rationale', '')}\n"
            f"  条件:\n" + "\n".join(cond_strs)
        )

    skill_descriptions = []
    for sk in retrieval.skills:
        props = sk.get("properties", {})
        steps = props.get("procedure_steps", [])
        skill_descriptions.append(
            f"技能 {sk['node_id']} ({sk['label']}, state={props.get('state', '?')}):\n"
            f"  步骤: {'; '.join(steps[:2])}..."
        )

    prompt = (
        f"缺陷描述: {query}\n\n"
        f"匹配的链路: {retrieval.matched_chain}\n\n"
        f"召回的规则:\n" + "\n".join(rule_descriptions) + "\n\n"
        f"召回的技能:\n" + "\n".join(skill_descriptions) + "\n\n"
        "请从缺陷描述中提取以下事实数据（如果描述中提到了的话），"
        "以 JSON 格式返回:\n"
        "{\n"
        '  "extracted_facts": {\n'
        '    "crack_width_mm": <数值或null>,\n'
        '    "spalling_area_m2": <数值或null>,\n'
        '    "has_rebar_exposed": <true/false或null>\n'
        "  },\n"
        '  "selected_rule_ids": ["规则ID列表，只能填写上面给出的 node_id，例如 RC-CRACK-WIDTH"],\n'
        '  "reasoning": "简短说明为什么选择这些规则"\n'
        "}\n\n"
        "注意: 只提取描述中明确提到的数据。不要猜测。"
        "selected_rule_ids 必须严格使用 node_id 原文，不要添加“规则”前缀或中文标签。"
        "不要输出 Pass/Fail。"
    )
    return prompt


def _parse_llm_response(raw: str) -> Dict[str, Any]:
    """Parse the LLM JSON response, tolerant of markdown fences."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "extracted_facts": {},
            "selected_rule_ids": [],
            "reasoning": f"LLM 返回无法解析: {raw[:200]}",
            "parse_error": True,
        }


def _normalize_selected_rule_ids(
    selected_ids: Any,
    retrieval: RetrievalResult,
) -> List[str]:
    """Normalize LLM-selected ids against the retrieved RuleCard node ids."""
    if not isinstance(selected_ids, list):
        return []

    valid_ids = [rc["node_id"] for rc in retrieval.rule_cards]
    normalized: List[str] = []
    for raw_id in selected_ids:
        if not isinstance(raw_id, str):
            continue
        matched_id = None
        if raw_id in valid_ids:
            matched_id = raw_id
        else:
            matched_id = next((rule_id for rule_id in valid_ids if rule_id in raw_id), None)
        if matched_id and matched_id not in normalized:
            normalized.append(matched_id)
    return normalized


# ---------------------------------------------------------------------------
# FactPack builder
# ---------------------------------------------------------------------------

def _build_fact_pack(
    query: str,
    extracted_facts: Dict[str, Any],
    chain: str,
) -> FactPack:
    """Build a FactPack from LLM-extracted facts."""
    now = datetime.now(timezone.utc).isoformat()
    facts: List[FactItem] = []
    idx = 0

    for key, value in extracted_facts.items():
        if value is None:
            continue
        idx += 1
        unit = None
        if "mm" in key:
            unit = "mm"
        elif "m2" in key:
            unit = "m2"
        facts.append(
            FactItem(
                fact_id=f"phaseD-fact-{idx:03d}",
                key=key,
                value=value,
                unit=unit,
                source_type="query",
                confidence=0.8,
            )
        )

    return FactPack(
        case_id=f"phaseD-baseline-{chain}",
        generated_at=now,
        facts=facts,
    )


def _build_rule_cards_for_closure(retrieval: RetrievalResult) -> List[RuleCard]:
    """Convert KG RuleCard nodes to evidence_schema.RuleCard for closure validator."""
    result: List[RuleCard] = []
    for rc_node in retrieval.rule_cards:
        props = rc_node.get("properties", {})
        conditions = [
            RuleCondition(
                fact_key=c["fact_key"],
                comparator=c["comparator"],
                threshold=c["threshold"],
            )
            for c in props.get("conditions", [])
        ]
        result.append(
            RuleCard(
                rule_id=rc_node["node_id"],
                title=rc_node["label"],
                version=props.get("version", "v1"),
                conditions=conditions,
                rationale=props.get("rationale", ""),
            )
        )
    return result


# ---------------------------------------------------------------------------
# Seed-rule bridge builder
# ---------------------------------------------------------------------------

def _build_seed_rule_bridge(
    retrieval: RetrievalResult,
) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
    """Build the seed_rule_bridge mapping for closure validator."""
    bridge: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
    trigger = retrieval.triggers[0] if retrieval.triggers else None
    if not trigger:
        return bridge

    trigger_id = trigger["node_id"]
    trigger_props = trigger.get("properties", {})
    fp_ids = trigger_props.get("required_pattern_ids", [])
    feat_ids = trigger_props.get("required_feature_ids", [])

    for rc in retrieval.rule_cards:
        rc_id = rc["node_id"]
        rc_conditions = rc.get("properties", {}).get("conditions", [])
        bridge[rc_id] = {}
        for cond in rc_conditions:
            fk = cond["fact_key"]
            bridge[rc_id][fk] = {
                "feature_ids": feat_ids,
                "pattern_ids": fp_ids,
                "trigger_ids": [trigger_id],
            }
    return bridge


# ---------------------------------------------------------------------------
# LocalBaselineReport
# ---------------------------------------------------------------------------

class LocalBaselineReport:
    """Phase D baseline 运行报告."""

    def __init__(
        self,
        query: str,
        config_summary: dict,
        retrieval_summary: dict,
        llm_response: Dict[str, Any],
        fact_pack: FactPack,
        closure_result: Optional[ClosureValidationResult],
        chain_status: Dict[str, str],
        error: Optional[str] = None,
    ) -> None:
        self.query = query
        self.config_summary = config_summary
        self.retrieval_summary = retrieval_summary
        self.llm_response = llm_response
        self.fact_pack = fact_pack
        self.closure_result = closure_result
        self.chain_status = chain_status
        self.error = error

    def to_dict(self) -> dict:
        closure_dict = None
        if self.closure_result:
            closure_dict = {
                "allow_stop": self.closure_result.allow_stop,
                "closure_summary": self.closure_result.closure_summary.model_dump(),
                "obligations": [o.model_dump() for o in self.closure_result.obligations],
                "unmet_obligations": [o.model_dump() for o in self.closure_result.unmet_obligations],
            }
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "query": self.query,
            "llm_config": self.config_summary,
            "retrieval": self.retrieval_summary,
            "llm_extraction": self.llm_response,
            "fact_pack": self.fact_pack.model_dump(),
            "closure_result": closure_dict,
            "chain_status": self.chain_status,
            "error": self.error,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class DualSourceBaselineRunner:
    """Phase D 最小 baseline 运行器."""

    def __init__(
        self,
        kg: DualSourceResearchKG,
        config: Optional[LocalLLMConfig] = None,
    ) -> None:
        self.kg = kg
        self.config = config or LocalLLMConfig()

    def run(self, query: str) -> LocalBaselineReport:
        """Run the full baseline pipeline for a single query."""
        # Step 1: Retrieve from KG
        retrieval = retrieve_from_kg(self.kg, query)

        if retrieval.matched_chain == "unknown":
            return LocalBaselineReport(
                query=query,
                config_summary=self.config.summary(),
                retrieval_summary=retrieval.summary(),
                llm_response={},
                fact_pack=FactPack(
                    case_id="phaseD-baseline-unknown",
                    generated_at=datetime.now(timezone.utc).isoformat(),
                    facts=[],
                ),
                closure_result=None,
                chain_status={"crack_chain": "not_matched", "rebar_spall_chain": "not_matched"},
                error="查询未匹配到任何已知链路",
            )

        # Step 2: Call LLM for fact extraction and rule selection
        prompt = _build_extraction_prompt(query, retrieval)
        try:
            raw_llm = _call_llm(self.config, prompt)
            llm_parsed = _parse_llm_response(raw_llm)
        except Exception as exc:
            llm_parsed = {
                "extracted_facts": {},
                "selected_rule_ids": [],
                "reasoning": f"LLM 调用失败: {exc}",
                "llm_error": True,
            }

        # Step 3: Build FactPack
        extracted = llm_parsed.get("extracted_facts", {})
        fact_pack = _build_fact_pack(query, extracted, retrieval.matched_chain)

        if llm_parsed.get("llm_error"):
            chain_status: Dict[str, str] = {}
            if retrieval.matched_chain == "crack_chain":
                chain_status["crack_chain"] = "llm_error"
                chain_status["rebar_spall_chain"] = "not_run"
            else:
                chain_status["crack_chain"] = "not_run"
                chain_status["rebar_spall_chain"] = "llm_error"
            return LocalBaselineReport(
                query=query,
                config_summary=self.config.summary(),
                retrieval_summary=retrieval.summary(),
                llm_response=llm_parsed,
                fact_pack=fact_pack,
                closure_result=None,
                chain_status=chain_status,
                error=llm_parsed.get("reasoning"),
            )

        # Step 4: Filter retrieval by LLM selected_rule_ids, then build for Closure
        raw_selected_ids = llm_parsed.get("selected_rule_ids", [])
        selected_ids = _normalize_selected_rule_ids(raw_selected_ids, retrieval)
        if raw_selected_ids != selected_ids:
            llm_parsed["_selected_rule_ids_raw"] = raw_selected_ids
        llm_parsed["selected_rule_ids"] = selected_ids

        if selected_ids:
            filtered_retrieval = retrieval.filter_rule_cards(selected_ids)
            rule_selection_mode = "llm_selected"
        else:
            filtered_retrieval = retrieval
            rule_selection_mode = "fallback_all"
            if raw_selected_ids:
                llm_parsed["_rule_selection_warning"] = (
                    "LLM 返回了 selected_rule_ids，但未匹配到任何检索到的 RuleCard，"
                    "已回退到全部规则。"
                )
        llm_parsed["_rule_selection_mode"] = rule_selection_mode

        rule_cards = _build_rule_cards_for_closure(filtered_retrieval)
        seed_bridge = _build_seed_rule_bridge(filtered_retrieval)

        closure_result: Optional[ClosureValidationResult] = None
        closure_error: Optional[str] = None
        try:
            closure_result = validate_closure(
                rule_cards=rule_cards,
                fact_pack=fact_pack,
                seed_rule_bridge=seed_bridge,
            )
        except Exception as exc:
            closure_error = f"Closure Verifier 失败: {exc}"

        # Step 5: Build chain status
        chain_status: Dict[str, str] = {}
        if retrieval.matched_chain == "crack_chain":
            if llm_parsed.get("llm_error"):
                chain_status["crack_chain"] = "llm_error"
            else:
                chain_status["crack_chain"] = "success" if closure_result else "closure_error"
            chain_status["rebar_spall_chain"] = "not_run"
        elif retrieval.matched_chain == "rebar_spall_chain":
            chain_status["crack_chain"] = "not_run"
            if llm_parsed.get("llm_error"):
                chain_status["rebar_spall_chain"] = "llm_error"
            else:
                chain_status["rebar_spall_chain"] = "success" if closure_result else "closure_error"

        return LocalBaselineReport(
            query=query,
            config_summary=self.config.summary(),
            retrieval_summary=retrieval.summary(),
            llm_response=llm_parsed,
            fact_pack=fact_pack,
            closure_result=closure_result,
            chain_status=chain_status,
            error=closure_error,
        )


def run_baseline(
    query: str,
    kg_dir: Optional[Path] = None,
    config: Optional[LocalLLMConfig] = None,
) -> LocalBaselineReport:
    """Convenience function to run a single baseline query."""
    if kg_dir is None:
        kg_dir = Path(__file__).resolve().parents[2] / "research_kg"
    kg = load_dual_source_kg(kg_dir)
    runner = DualSourceBaselineRunner(kg=kg, config=config)
    return runner.run(query)
