"""evo-agent baseline KG-RAG 检索子包（spec §5 / §10）。

- fact_retriever.py —— Fact KG-RAG 检索建筑事实子图 → FactPack（spec §5.3 / §5.5）
- rule_retriever.py —— Rule KG-RAG 检索候选 rule card + 排序 → RuleSlice（spec §5.4 / §5.6）
- pack_builder.py   —— 扁平子图 → DTO 还原 + 组装 FactPack / RuleSlice（spec §5.4.3 / §5.5 / §5.6）

闭包验证器以 `FactPack + RuleSlice` 为唯一输入；这两个 DTO 在
`evo_agent_baseline.contracts` 定义，本子包只负责检索 + 装配。
"""

from typing import Callable, Tuple

from evo_agent_baseline.contracts import FactPack, RuleSlice
from evo_agent_baseline.retrieval import pack_builder
from evo_agent_baseline.retrieval.fact_retriever import retrieve_fact_pack
from evo_agent_baseline.retrieval.rule_retriever import retrieve_rule_slice


def make_retrieval_fn(
    client, rulecard_bundle_id: str
) -> Callable[[str, str, str], Tuple[FactPack, RuleSlice]]:
    """适配 AGENT 编排器期望的 RetrievalFn = (world_id, building_id, run_id) -> (FactPack, RuleSlice)。

    DATA 的 ``retrieve_fact_pack`` / ``retrieve_rule_slice`` 分别要 Neo4jClient + rulecard_bundle_id。
    本工厂用闭包捕获这两个长期依赖，返回符合 AGENT 编排器 RetrievalFn 签名的可调用对象。
    ``world_id`` 当前未使用（DATA 按 building_id 检索；world 经由 building 反查），
    参数保留以对齐 AGENT 签名、未来需要时启用。
    """

    def _retrieve(world_id: str, building_id: str, run_id: str) -> Tuple[FactPack, RuleSlice]:
        fact_pack = retrieve_fact_pack(client, run_id=run_id, building_id=building_id)
        rule_slice = retrieve_rule_slice(
            client,
            run_id=run_id,
            fact_pack=fact_pack,
            rulecard_bundle_id=rulecard_bundle_id,
        )
        return fact_pack, rule_slice

    return _retrieve


__all__ = [
    "pack_builder",
    "retrieve_fact_pack",
    "retrieve_rule_slice",
    "make_retrieval_fn",
]
