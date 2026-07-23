"""evo-agent v1 evolution layer（spec v1 §9）。

子模块：
- skill_package：SkillPackage 目录读写 + sha256 验证
- skill_package_loader：SkillPackage → Neo4j Skill/SkillVersion 节点

后续阶段由其它代理填充：
- feedback_broker / replay_buffer / skill_induction / skill_validation /
  policy_trainer / audits / trace_capture

v1.1 修订（2026-05-26，spec §0.6 修订 2）：
- ``release_manager`` 与 ``rollback`` 子模块已删除——实验室阶段无 canary
  rollout / rollback artifact 需求；promotion 状态机简化为 3 态（``draft`` /
  ``active`` / ``retired``），active 出问题直接 retired + git revert。
"""

from evo_agent_baseline.evo import skill_package, skill_package_loader

__all__ = [
    "skill_package",
    "skill_package_loader",
]
