# 第一波落码蓝图:validator 判定核心改造(DEBT-065)

> 基于实际代码诊断(validator.py:1237-1273 早退本体已读)+ 勘察地图 + v2.2 §3.0/§3.1/§3.2。
> 数据资产层已完成(下附),本蓝图是剩余**判定权红线核心**手术的行号级落码指令。
> 状态:待专注块落码(需 fresh context + 全量回归 + 审核门;重锚批需 GPU+数小时)。

## 已完成(分支 debt065-wave1,均验证过)

| 产物 | 位置 | 验证 |
|---|---|---|
| lattice 生成器 | `agent_v1/scripts/build_component_type_lattice.py` | 跑通 |
| lattice 资产 | `agent_v1/regulations/rulecard_v2/mbis_cop_2023/component_type_lattice_v1.json` | — |
| lattice 测试 | `agent_v1/tests/test_component_type_lattice.py` | 8/8 pass |
| 授权表生成器 | `agent_v1/scripts/build_exact_fragment_target_authorizations.py` | 跑通 |
| 授权表(保守55卡) | `agent_v1/regulations/.../exact_fragment_target_authorizations_v1.json` | — |
| 授权表测试 | `agent_v1/tests/test_exact_fragment_target_authorizations.py` | 8/8 pass |

哈希锚:vocab_snapshot `93c54df5…` / alias_snapshot `375addbd…`。授权表 55 卡(fire 29/canopy 11/drainage 10/external_wall 5),全高置信。

## 剩余落码(判定权红线,按依赖序)

### 步骤 1:运输层——lattice + 授权表加载进 RuleSlice.retrieval_policy

(即重建被撤的 overlaps 腿,但换 lattice 版语义)

- **loader** `ingest/rulecard_loader.py`:`RULECARD_FILES` 登记表加 `component_type_lattice_v1.json` + `exact_fragment_target_authorizations_v1.json`;灌成 KG 节点(嵌套结构存 JSON 字符串属性,沿 mapping 的先例)。修撤 overlaps 时的注释失真。
- **queries** `kg/queries.py`:加查询取 lattice(leaf/non_leaf/subsumption/disjoint_pairs/双快照哈希)+ 授权表 entries。
- **retriever** `retrieval/rule_retriever.py`:解析入 `retrieval_policy.component_type_lattice` + `.exact_fragment_target_authorizations`。
- **完整性校验(§1.1/§2.3/§2.5)**:加载时执行三阶段异常矩阵——ingest hard-fail(schema/重复卡/非法evidence/双快照失配/disjoint不全/两类bundle失配/违反单目标或单组件值)、条目级失效(stale_card_binding:card_content_sha256/authoring/interpretation 失配)、runtime 保守关闭(资产整体缺席)。**运行期按精确版本键查询,禁 `ORDER BY version DESC`**(queries.py:49-53/168-179 现行字典序会误选)。
- `compute_rule_slice_hash`(validator.py:785-815)对 policy 全量取哈希 → rule_slice_hash 变(预期,显式声明入锚)。

### 步骤 2:§3.0 W0 fragment 身份专用通道

- **retriever/fact_retriever**:从 `Fragment.component_id → Component.component_type → 冻结版本别名映射`一次性生成 `w0_component_identity` 事实,provenance = `{channel, derivation:"fragment_component_projection", alias_mapping_version, alias_mapping_snapshot_sha256}`,载荷 `{fragment_id, component_id, raw_component_type, canonical_component_type}`。
- **关键**:恰一条原始 `Fragment→Component` 来源关系(count==1 基数校验),**禁 last-write-wins**(不复用 fact_retriever.py:496-502 按 fragment 建字典后写覆盖;queries.py:31-36 允许多行返回,须显式 count)。
- validator 消费前校验 provenance 的 alias_snapshot == lattice 的同名哈希;不等/缺失/多来源 → 不早退。

### 步骤 3:provable_disjoint 共用纯判据 helper

`provable_disjoint(target_type, fragment_identity, lattice) -> bool`:`(target_type, fragment_identity)` 规范化对 ∈ lattice.disjoint_pairs。纯函数,卡级+触发器级共用。

### 步骤 4:替换卡级早退(validator.py:1246-1273)

现状 `_ct_na`(1246-1249)= `_card_ct and _scope_ct is not None and _card_ct <= _known_ct and not (_card_ct & _with_categories(set(_scope_ct)))`——**替换为** v2.2 §3.1 四条件:

```
_ct_na = (
    授权表有该卡有效条目(§2.5)             # 取单目标 target = entry.exact_fragment_target_types[0]
    and target in lattice.leaf_types
    and fragment 的 w0_component_identity 存在/来源唯一/规范值∈leaf/别名快照同源(§3.0)
    and provable_disjoint(target, identity, lattice)
)
```

- `_known_ct` 四路拼凑宇宙(1111-1117)不再参与互斥(仅保留卡端脏值保守回落职能)。
- `_with_categories` 类目扩张仅保留相容豁免方向,任何方向不得产 NA。
- **location 维 `_lc_na`(1250-1253)保持现状不动**(§5:location 维不在本周期)。
- 早退发 audit + continue(1261-1273)逻辑不变,reason 更新为叶×叶可证排斥措辞。

### 步骤 5:触发器级(obligation_deriver.py:463-488)+ 楼级废止

- `evaluate_trigger`(validator.py:1282-1289 传参)的 `req_ct not in scope_component_types` 隐式互斥 → 换 provable_disjoint(§3.2 六项语义:fragment-only/仅 bound=∅/measure 豁免不变/触发器值恒等于单目标/direct-or-map 限定符唯一规则/blueprint_state_eval 同源)。
- **组件维楼级结构 NA 废止**:obligation_deriver.py:463-488 以 building 集合缺值直接 NA 的路径移除;`test_trigger_structural_na.py:50-59` 钉住的旧楼级语义随规格更新。**注:仅组件维;location 维不动。**

### 步骤 6:更新钉住旧语义的测试 + 全量回归

- `closure/tests/test_card_scope_structural_na.py`、`test_trigger_structural_na.py`、`test_trigger_qualifier_conflict.py`:按新判据(叶×叶正向授权可证排斥)重写,逐条在 PR 说明列改动依据。
- 全量回归 2500+ 通过。

### 步骤 7:审核门 + 重锚批

- copilot 审核门(判定核心大改)。
- 重锚批(新 --batch-root,锚:commit+rule_slice_hash 变、池/库/模型不变;**发批前 Ollama 预热+size_vram>0**);**保守授权版硬验收值**先离线重放(比 4,532 保守,因仅 55 卡授权)再发批;实际 vs 重放对账,不可解释即作废;对照 baseline_v4_final_seed301 报预期差异账。

## 待用户可选优化(非阻塞)

1. 共享本体正典归属(倾向独立规格包,W0 rule-blind 不容纳排斥本体)。
2. 授权范围扩充:中置信 46 卡(修复周期验证卡,复核 NA 触发链是否空转)+ 存疑 3 处口径(范围定义卡该否锚 NA / canopy water ponding 两条上调否)。扩充后重跑授权表生成器(去掉"仅高置信"限制)。

---

## 进度更新(2026-07-24 续):判定逻辑模块已完成 + 15 单测

**`closure/component_lattice.py`**(纯判定逻辑,不碰判定路径、不改 rule_slice_hash):
- `ComponentLattice.provable_disjoint(target, identity)`:仅叶×叶且显式登记于 disjoint_pairs 才真;禁传递闭包、禁"未登记=互斥"。
- `Authorization.authorized_target(card_obj)`:无有效条目/stale(四字段任一失配)→ None(缺省拒绝)。
- `load_component_lattice` / `load_authorizations`:v2.2 §1.1 三阶段异常——ingest hard-fail(快照失配/disjoint 不全/二分破坏/bundle 失配/重复卡/非叶目标/非法 evidence)。
- `card_fingerprint_v1`:哈希原始单卡对象。
- 单测 `closure/tests/test_component_lattice_module.py` **15/15 过**。

判据"大脑"就绪+测透 → 原子接线步风险大降(只需正确调用已验证逻辑)。

## 接线关键设计点(原始卡指纹 vs DTO)——自决方案

`card_fingerprint.v1` 哈希**原始 rule_cards.json 单卡对象**,但 validator 拿到的 card 是 KG 重建 DTO(`pack_builder` 排序子数组+重建)——直接对 DTO 算指纹会**失配**授权表。

**方案(自决,符合 blind/分层)**:授权判定在能拿原始卡的**上游**(RuleSlice 构造 / retriever)预算 `authorized_target`,把**目标叶值预绑定**到卡(RuleSlice 携带);validator 判据读预绑定目标 + fragment 单值身份 + `provable_disjoint`。这样 validator 只吃 RuleSlice(不直读 rule_cards.json,守 blind:闭包只吃 RuleSlice+FactPack),授权判定与身份通道都归运输层。

**接线剩余(原子红线步,专注块)**:运输层(RuleSlice 携带 lattice + 预绑定授权目标 + w0_component_identity 单值身份)→ validator 卡级判据替换(1246-1254,`_ct_na` 换 `预绑定目标 and provable_disjoint(目标, 身份)`)→ 触发器级(obligation_deriver:463-488)+ 组件维楼级废止 → 更新钉死测试 → 全量回归 → 审核门 → 重锚批(保守 55 卡授权,GPU 就绪时)。

---

## 接线落码进度(2026-07-24 续续)——卡级链路已打通

- **loader** ✓:`RULECARD_FILES` 登记两资产 + `_load_component_lattice_and_authorizations`(ingest §1.1 验证 + 原始卡算指纹产出验证过 `{rule_card_id: target}` + 灌 `ComponentTypeLattice`/`ExactFragmentTargetAuthorizations` 节点)。loader 测试 **18/18**。
- **queries** ✓:`RULE_COMPONENT_TYPE_LATTICE` + `RULE_EXACT_FRAGMENT_TARGET_AUTHORIZATIONS`(v1 单版本沿 ORDER BY DESC,多版本改精确键 TODO)。
- **retriever** ✓:读两节点进 `retrieval_policy`(坏 JSON 可见化不阻断)。
- **validator 卡级判据** ✓:取 lattice+auth policy;`_w0_fragment_identity`(§3.0 保守近似:`_frag_ct` 单值叶型才认,多值/空/非叶不早退,TODO 完整 count==1 通道);`_provable_disjoint`(显式登记排斥,禁传递闭包);替换 `_ct_na`(1246-)为 `授权target and 身份 and provable_disjoint`;location 维 `_lc_na` 不动。
- **影响面(结构 NA 测试)**:2 失败(test_incompatible/test_category_nonmember,**预期**——合成测试 policy 无授权资产→保守关闭,且 external_component 非叶→不授权),5 passed(护栏不受影响)。

**剩余**:
1. **触发器级** `obligation_deriver.py:463-488`(卡级已新、触发器级仍旧"req_ct not in scope"=不一致,待换 provable_disjoint;§3.2 六项语义)+ 组件维楼级 NA 废止。
2. **重写** `test_card_scope_structural_na.py`(新语义:授权卡+叶身份+可证排斥→早退;未授权/非叶/身份未知→不早退。注意:测试所有卡共用 `RC.fire.001`,新判据只看授权表 target 不看卡限定,需分卡 rule_card_id + 分授权重构)。
3. **全量回归甄别**(后台 b4h6cx5mo):区分预期判定面变化 vs 真 bug。
4. 审核门 + 重锚批(保守 55 卡授权,GPU)。

---

## ✅ 判定核心手术完成(2024-07-24)——全链路落码 + 测试重写全过

**生产代码全接线**:loader(灌 lattice+授权表 + ingest §1.1 验证 + 原始卡算指纹产出验证过 {id:target})→ queries(两查询)→ retriever(进 retrieval_policy)→ validator 卡级判据(§3.1:授权目标叶型 × fragment 单值身份可证排斥,替换旧"词表空交=互斥")+ 触发器级(§3.2:req_ct 恒等授权目标 + 可证排斥)+ 组件维楼级 NA 废止(楼级身份 None 自然不早退)。

**happy path 端到端验证**:授权卡 + fragment 叶身份 + 可证排斥 → 确实产生 scope NA(test_card_scope test_authorized_disjoint_identity_early_exit 过)。

**5 个钉死测试重写全过**:
- test_card_scope_structural_na.py **7/7**(授权正例 + 未授权/非叶身份/身份未知/多值身份/无资产保守关闭各护栏)。
- test_trigger_structural_na.py **13/13**(触发器授权可证排斥 NA + 组件维楼级 NA 废止 + location 维不动 + 各回落护栏)。
- test_identity_shadow.py **1/1**(结构审计蓝图绑定,beam/column 合成叶型)。

**影响面证实非宽**:卡级新+触发器旧的过渡全量回归仅 **3 失败 / 2565 过**;全部为钉死旧结构 NA 语义的测试,已逐一重写。

**保守近似(TODO 后续加强,不阻塞)**:①§3.0 身份用 `_frag_ct` 单值集合近似(完整 count==1 原始来源关系通道 + provenance alias 快照校验待建;多值/空保守不早退,不错早退)②v1 单版本查询沿 ORDER BY version DESC(多版本改精确键)。

**剩余**:最终全量回归(br7kd4a9p,卡级+触发器都新+测试重写后)→ 待绿 → copilot 审核门 → 重锚批(保守 55 卡授权,离线重放硬验收值 → GPU 就绪发批)。

---

## ⚠️ copilot 审核门:不可提交——4 P1 判定核心红线漏洞(2026-07-24)

**审核门价值实证**:深夜落码的保守近似经审核证实不安全。P0:0 / P1:4 / P2:1。全量回归全绿≠正确(回归未覆盖这些边界)。

- **P1-1(判定权红线,最重)**:§3.0 身份用 `_frag_ct` 近似**会产生未证成 NA**(错早退)——普通事实的叶型值被误认作身份 + 同值多来源集合去重折叠成"单值",非真 count==1 来源关系。`validator.py:1111-1149`。**修**:实现完整 `w0_component_identity` 专用通道(count==1 原始 Fragment→Component 来源关系 + provenance alias 快照校验),不扫一般事实限定符。
- **P1-2**:运行时版本未冻结——`queries` 两查询 `ORDER BY version DESC LIMIT 1` 未绑同一 run/bundle/alias 版本;字符串序 v9>v10;新资产缺席仍读旧节点(旧授权作用于已变卡)。`queries:181-196`/`retriever:386-399`/`loader:1084-1106`。**修**:冻结三资产精确键 + 同源校验 + 缺席/不一致整体关闭组件早退。
- **P1-3**:类型格 `rulecard_bundle_id` 仅保存未比较(他卡包的叶型/排斥可能用于当前卡包)。`component_lattice.py:95-149`/`loader:1097-1098`。**修**:加载时 bundle_id 非空且精确相等否则摄入失败。
- **P1-4**:授权摄入缺强失败护栏——重复卡标识字典静默覆盖 / 未验每卡单组件值 / 授权证据引用只检非空+种类不检所引槽位或条件真实存在。`loader:981-1028,1110-1119`/`component_lattice.py:152-188`。**修**:建图前验卡标识唯一 + 每卡单组件值 + 逐项证据引用存在性。
- **P2**:类型格证明测试与生成器共用硬编码 registry,可同步漂移保持全绿。`build_component_type_lattice.py:47-50`/`test_component_type_lattice.py`。**修**:从 W0 权威常量动态派生 + 断言。

**通过项**:blind/分层 ✅(validator 仍只吃 FactPack+RuleSlice,未读真值/原始卡)、判定权红线 ✅(最终状态+allow_stop 仍由 validate_building_closure 产)、运输接线确接通并影响 rule_slice_hash(非死接线)✅。

**下个专注块**:照上五项修(P1-1 完整身份通道是判定核心深度)→ 全量回归 → 再审核门 → 提交(用户批准)→ 重锚批(GPU)。审核会话续接:`copilot --resume=266c5d85-e304-4faf-87a6-c11a012a66b2`。

---

## ✅ 审核门 4 P1 + P2 全修复(2026-07-24)——含定向测试

- **P1-1(判定权红线)**:身份从"扫所有事实 qualifier + set 去重"改为"genuine 来源(slot_id=='component_type' 事实)+ count==1(list 非 set)"——普通事实的 component_type_key 不再误认作身份、同值多来源不折叠成假单值。`validator.py` `_w0_identity_src`/`_w0_fragment_identity`。定向测试:`test_incidental_component_qualifier_not_identity`(defect 事实带 external_wall 不早退)+ `test_same_value_multi_source_not_folded`(两条同值 → count==2 不早退)。
- **P1-2**:运行时同源校验(lattice 的 alias 快照 vs 当前 mapping alias,不一致 → 整体关闭组件早退)+ 缺席整体关闭。`validator.py`。精确版本键冻结标 TODO(v1 单版本:loader ingest 校验 + 同源校验 + 缺席关闭三重兜底)。
- **P1-3**:类型格 bundle 配套校验(`load_component_lattice` expected_bundle_id 非空且精确相等)。`component_lattice.py` + loader wire。定向测试 `test_lattice_bundle_match_ok`/`test_lattice_bundle_mismatch_hardfail`。
- **P1-4**:授权摄入强失败护栏(重复卡 hard-fail + 每卡单组件值 + evidence 引用卡内存在性)。`component_lattice.load_authorizations` + loader 重复卡检查。定向测试 `test_auth_evidence_ref_not_in_card_hardfail`/`test_auth_multi_component_value_hardfail`。
- **P2**:测试动态读 W0 `component_type_registry`(防生成器/测试硬编码同步漂移)。`test_component_type_lattice.py::_registry_component_types`。

定向测试全过(36 passed)。**剩余**:全量回归(b8fb8hw4d 验证 P1 修复不破坏)→ 最终全量回归(含新测试)→ copilot 复审(`--resume=266c5d85-e304-4faf-87a6-c11a012a66b2`)→ 提交(用户批准)→ 重锚批(GPU)。

---

## ⚠️ copilot 复审(41 分钟深审):仍不可提交——4 P1 未彻底关闭(2026-07-24)

修复方向对但不彻底;P2 已修。**审核门两轮守住判定核心正确性(避免两次错误提交),但也实证:在极长疲劳 session 反复修判定核心红线不奏效**(第一轮 4 P1 → 修 → 复审 4 P1 仍未彻底)。

- **P1-1 未修(判定权红线)**:身份仍可伪造——任意 slot_id=="component_type" 的关联事实被当身份,未验证专用 w0_component_identity/原始 Fragment→Component 关系/component_id/别名快照。**关键:真实生产事实没有 fragment_id,我的 slot_id 方案在真实数据下取不到身份**(近似两轮均不工作)。`validator.py:1137-1149`。**完整修**:检索器(fact_retriever/retriever)从原始 Fragment→Component 关系生成专用 w0_component_identity 原子(带 component_id + 别名快照来源证明),validator 只消费该通道、按原始关系行计数。
- **P1-2 未修**:精确键冻结不能留 TODO——旧 KG 节点不消失,重摄改后同名卡会复用旧授权,"缺席整体关闭"不成立。`queries:184-195`/`loader:1108-1137`/`retriever:386-399`。**修**:run 级冻结三资产共同精确键(卡包+版本+卡指纹+类型格版本+别名哈希),授权运输保留卡指纹复核(不只 {id:target}),三节点绑同一卡包+版本。
- **P1-3 仅正常路径修**:expected_bundle_id 仍可选,清单缺失时 loader 传 None → 绕过校验,错误卡包类型格仍入图。`component_lattice.py:95-109`。**修**:改必填非空,缺失强失败,加经完整建图入口的测试。
- **P1-4 部分修**:证据定位符合并检查(kind 不需对应真实区段)/引用项不需承载授权目标/单组件仅覆盖授权卡(非全卡包)/重复卡检查资产缺席时跳过。`component_lattice.py:184-237`。**修**:无条件先验全卡包 ID 唯一+每卡单组件,按 evidence kind 检查对应区段,引用项组件类型 == 授权目标。
- **P2 已修** ✅(测试动态读真实 registry;非阻断补测:从 `_BASE_COMPONENT_PLAN + _ARCHETYPE_EXTRA_COMPONENTS` 推导而非 alias keys)。

**下个专注块(fresh 清醒)**:P1-1 检索器专用身份通道(读 fact_retriever 投影 + KG Fragment→Component count==1,判定核心深度)+ P1-2 版本冻结机制 + P1-3 必填 + P1-4 全卡包/kind/target 校验 → 全量回归 → 三审 copilot(`--resume=266c5d85-e304-4faf-87a6-c11a012a66b2`)→ 提交(用户批准)→ 重锚批(GPU)。

---

## P1-1 诊断突破(读通真实身份路径)+ P1-3 部分修(2026-07-24)

**P1-1 正解诊断突破**:读通 `fact_retriever.enrich_qualifiers_from_structure`(474-552)——genuine 身份权威 = `raw.fragments` 的 **Fragment→Component 关系**(`frag_info[fragment_id]=(component_type, location_class)`,497-502)。复审所指"真实事实无 fragment_id"根因:原始 atom 无 fragment_id qualifier,enrich 才从 frag_info 反查盖上(521-530)。**前两轮近似(`_frag_ct` / `slot_id=="component_type"`)失败的根因 = 扫事实 qualifier 而非原始 Fragment→Component 关系,没读通 frag_info。**

**P1-1 完整修复正解(行号级 turnkey)**:
1. `fact_retriever` enrich 末尾从 `frag_info` 生成专用 `w0_component_identity` 原子(每 fragment 一个,count==1 天然——frag_info 每 fragment 单 component_id;需 frag_info 加存 component_id 作来源证明;`slot_id="w0_component_identity"` + provenance channel + alias 快照)。
2. `validator._w0_identity_src` 改读 `slot_id=="w0_component_identity"` 通道(非 "component_type"),按 fragment_id 索引,多来源标 dup→None。`validator.py:1130-1149`。
3. 测试 `_frag_fact` 改生成该专用原子(需 make_fact 支持 provenance)。
→ 真实数据有效(enrich 有 raw.fragments)+ 不可伪造(专用 slot_id+channel)+ count==1 天然。

**P1-3 部分修**:loader 类型格资产在场但 bundle_id 缺失 → 强失败(堵 None 绕过);loader/component_lattice 测试 37 passed 不破坏。收尾:component_lattice `expected_bundle_id` 改必填(去 Optional 默认)+ 更新 module 测试传 bundle。

**完整修复仍待 fresh 专注块**(判定核心多文件轮:P1-1 enrich 专用原子跨 fact_retriever/validator/测试 + P1-2 版本冻结机制 + P1-4 全卡包检查 + P1-3 必填收尾)。理由:上下文饱和,中途 compaction 打断判定核心多文件手术风险具体;两轮实证判定核心近似反复不彻底。turnkey 清单如上,三审 `copilot --resume=266c5d85-e304-4faf-87a6-c11a012a66b2`。

---

## P1-1 完整版落地全绿 + P1-3/P1-4 核心修 + agy 派 P1-2/P1-4 收尾(2026-07-24)

- **P1-1 完整修复(检索器专用身份通道,全绿)**:fact_retriever.enrich 从 frag_info(原始 Fragment→Component 关系)生成专用 `w0_component_identity` 原子(每 fragment 一个,count==1 天然,provenance channel);validator `_w0_identity_src` 只认该通道(slot_id=="w0_component_identity"+channel),多来源标 dup→None。测试 `_frag_fact`/`_fact` 改生成该原子(fixtures/test `_fact` 加 provenance 参数)。**全量回归 2574 passed 全绿**——新身份原子不匹配任何卡槽、不产义务、下游安全。彻底解决前两轮近似的伪造/多来源/真实数据失效三问题。
- **P1-3 完整**:loader 缺失强失败 + `component_lattice.load_component_lattice` expected_bundle_id 改必填 + module 测试更新。
- **P1-4 核心**:loader 无条件全卡包 rule_card_id 唯一。
- **P1-2 + P1-4 收尾派 agy Opus 4.6**(自足运输层活,提示词 `scratchpad/agy_p1_2_p1_4_prompt.txt`,后台 bfx6vmke6):P1-2 版本冻结(三节点绑 bundle+版本 / retriever 校验同源 / 授权运输保留卡指纹)+ P1-4 每卡单组件无条件。我审 + 含所有的最终回归 + copilot 三审(--resume=266c5d85)。

---

## ⚠️ codex 独立三审(第三轮):仍不可提交——4 P1 深层未闭合 + 致命断路(2026-07-24)

codex(独立第三方,未参与实现)三审:4 组 P1 仍在,P1-1/P1-4 可产未证成 NA,**P1-2 真实链路反而恒关闭功能**。三轮审核(copilot×2 + codex×1)逐层挖出更深漏洞。相关测试 104 passed 但未覆盖这些反例。

- **P1-1 身份仍可伪造**:`frag_info` 覆盖写非 count==1(多关系行取最后,queries:31 允许多行,无保守关闭);生成端缺 raw_component_type/alias_mapping_version/alias_snapshot(规格要的来源证明,fact_retriever:567);消费端只验 slot_id+channel,不验别名哈希/component_id/carrier/载荷一致(validator:1147)。→ **普通 FactAtom 自填专用 slot/channel+fragment_id+叶值即可伪造身份产 NA;专用字符串标记≠来源证明**。修:身份原子带别名快照+component_id+raw_ct;validator 验之+载荷一致;frag_info 真 count==1(多行→保守关闭)。
- **P1-2 致命断路(我审 agy 时漏了)**:loader 的 ComponentTypeLattice 节点只有 lattice_json、**无顶层 rulecard_bundle_id**(rulecard_loader:1125),但查询读 l.rulecard_bundle_id(queries:184)→ 真实 loader→KG→retriever 下 lattice bundle=None → 三方同源检查删两资产 → **恒保守关闭功能**。我补的定向测试伪造了 loader 实际不产生的属性(test_retrievers:246)→ 掩盖断路。+ 仍字典序 latest 非精确版本;validator 只读 target 不验指纹。修:loader 给 lattice 节点加顶层 bundle;精确版本键(**不可 TODO**);validator 验指纹。
- **P1-3 loader 仍绕过**:manifest 存在但 bundle_id 缺失时 loader 自动补默认值(rulecard_loader:918)→ `if not result.bundle_id` 永不触发(1107)→ 端到端未闭合。修:别自动补默认。
- **P1-4 卡值 A 授权目标 B 仍允许**:只拒 len(cvals)>1,不要求 cvals=={target}(component_lattice:226)。反例:外墙卡+外墙 evidence+正确指纹却授权 fire_safety_component→validator 按目标判 disjoint(validator:1324)→外墙 fragment 判 NA(未证成)。修:cvals=={target};evidence kind 按对应容器核对。
- **P2**:共用 helper 三份实现(模块/validator/trigger,trigger 缺叶型检查);断言 B 循环自证(未读 _BASE_COMPONENT_PLAN)。

**深刻教训(全项目级)**:①**单测伪造真实链路不产生的属性 → 掩盖断路**(P1-2 就是这样躲过 104 测试);判定核心正确性需**真实端到端验证**(重锚批 / 真实 loader→KG→retriever),不能只靠伪造属性的单测。②审核门三轮(不同视角)守住正确性——避免了三次错误提交(P1-1 伪造/P1-2 恒关闭/P1-4 卡值≠目标 若提交都会成未证成 NA 或功能失效)。

**第四轮修复 turnkey 方向如上(codex 行号级);必须配真实链路测试(不伪造属性);后续审核转 PlusAI(codex/copilot 额度紧)。** codex 三审续接 codex resume 019f92a4-c954-74e3-ba80-1ef870a895b9。
