"""evo-agent baseline agent 三层控制体系子包（spec §7 / §10）。

三层控制：System Prompt / Skills / Hooks。

- system_prompt.txt  —— agent 系统提示词
- skills/            —— 4 个 baseline 手工 seed Skill 目录
- hooks.py           —— 运行期 hook（输入守卫 / 检索守卫 / 停机门 / 输出语言守卫）
- report_writer.py   —— 辅助审查报告生成
- run_orchestrator.py—— ComplianceAssessmentRun 运行编排

地基层不实现以上 .py，留给后续代理。
"""
