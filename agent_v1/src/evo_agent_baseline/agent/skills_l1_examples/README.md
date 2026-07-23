# L1 OperationalSkill examples

## 当前内容

- `mbis-artifact-evidence-gap-v1/` — D 代理手写的示范品，**目前的真实身份是 unit test fixture**（被 `src/evo_agent_baseline/tests/test_evo_skill_package_loader.py` 当 SkillPackage 完整样本依赖）

## 这不是 runtime active Skill

按 spec v1.1 §7.3.2 + §0.6 修订 2，L1 OperationalSkill **由 evo loop 自动生成 / 验证 / 激活 / 淘汰**，不该是手写产物。当前目录里的示范品是上一版（spec v1.0 阶段）的手写"训练失败品"，原计划 v1.1 evo loop 跑通后由 LLM induction 重生新 L1 Skill 替换。

但因为 `test_evo_skill_package_loader.py` 14 个测试依赖这个目录作 fixture，所以保留——视它为 **fixture-as-code**，不是 runtime artifact。

## 后续清理

待 v1.1 evo loop 真跑通 + LLM induction 起草出新 L1 Skill 后：
1. 把 fixture-as-code 改为 test 内部构造（`pytest.fixture` 用 `tmp_path` 临时构造完整 SkillPackage），而非依赖目录里的固定文件
2. 整个 `skills_l1_examples/` 目录可以彻底清掉
3. runtime 加载的 L1 Skill 全部来自 LLM induction + Gate 0-4 通过 + active 切换

## 当前 spec 引用清理状态（2026-05-26）

`plan.yaml` 里的两条 spec 章节号引用（`§10.4` / `§5.5`）已删，对应到 `团队文档/工程规范/spec_traceability.md`。

`SKILL.md` / `skill.json` / `validation_records.jsonl` 这一轮 grep 无 spec 引用。
