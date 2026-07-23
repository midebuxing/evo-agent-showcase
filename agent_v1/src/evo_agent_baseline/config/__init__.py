"""evo-agent baseline 运行配置子包。

存放 spec 附录 B 的最小配置样例：
- kg.yaml         —— Neo4j 连接、库名、约束 / 索引相关配置
- guard.yaml      —— agent loader 白名单 / 黑名单、禁止属性、闭包验证器与 agent 守卫配置
- evaluator.yaml  —— evaluator-only 配置（agent 不可读）

config 子包不含逻辑代码；yaml 由 ingest / closure / agent / eval 各模块按需读取。
"""
