"""evo-agent baseline 包。

香港 MBIS 场景下、不带 evo 的合规助手代理系统 baseline。
本包严格按《evo-agent baseline 全量实现级设计规格包》v0.4 实现，
spec→code 单向：规格是代码唯一权威。

模块划分（spec §10）：
- config/     —— 运行配置（kg / guard / evaluator yaml）
- ingest/     —— 各路灌库器（fact / sidecar / regulation / rulecard / skill）
- kg/         —— Neo4j 客户端、查询、DTO 构造
- retrieval/  —— 事实 / 规则 KG-RAG 检索与 pack 构造
- closure/    —— 确定性闭包验证器
- agent/      —— agent 三层控制体系（System Prompt / Skills / Hooks）
- eval/       —— 评测闭环（读 W2 参考真值独立阅卷）
- tests/      —— 测试

地基层只交付：包骨架 + contracts.py（跨模块共享契约）+ config/。
loader / verifier / retriever / agent / eval 的实际逻辑由后续代理实现。
"""

__all__ = ["contracts"]
