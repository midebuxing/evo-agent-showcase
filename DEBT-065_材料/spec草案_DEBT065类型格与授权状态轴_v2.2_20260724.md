# spec 草案 v2.2:组件类型格与授权状态轴(DEBT-065 修复周期)

- 版本:草案 v2.2(2026-07-24;v2.1 经 copilot gpt-5.6-sol 终确认后契约细节补全,复核全文 `杂物箱/文件包/DEBT-065_修复周期材料_20260724/copilot_决策门终确认_规格草案v2.1_20260724.md`)
- 状态:**定稿候选**(三轮外部审核后契约收敛;主会话逐条自核落实后进入第一波落码,落码阶段审核门为下一道防线)
- 适用范围:闭包验证器"组件结构不相容早退 NA"机制的判据重设计 + ubw 迁出组件类型轴
- 权威方向:定稿后代码以本规格为准,代码不得反向改写本规格
- **v2.1→v2.2 修订摘要**(copilot 终确认三阻断+三歧义全部收敛,不改路线):
  - **阻断 1(异常矩阵不完备)**:§1.1 矩阵三档逐项补全——ingest 加"卡包内重复 rule_card_id"+"授权表非法 evidence 格式"+"两类顶层 rulecard_bundle_id 失配(类型格+授权表,均属配套校验)";条目级只列逐条 card_version_binding 四类失配(rule_card_id 不存在 / card_content_sha256 / authoring_revision / interpretation_revision);runtime 缺席补第三项别名资产。与 §2.5 覆盖范围对齐(自核修正:bundle_id 是顶层字段,归 ingest 配套级,不混入逐条失效)。
  - **阻断 2(重复卡致指纹不唯一)**:§2.5 明确卡包内 `rule_card_id` 唯一性为**卡包完整性前提**,重复→ingest hard-fail,保证 card_fingerprint 的"该单卡对象"良定义。
  - **阻断 3(二分测试只写数量)**:§2.3-⑥ 断言 B 写死 11 可生成 + 8 休眠成员清单(资产内 `w0_generation_plan_types`/`w0_dormant_types` 字段),加"可生成清单 == generator 实际计划类型集合"相等断言,不只并集==registry。
  - **歧义 1**:§3.0 `alias_mapping_version` 澄清=别名映射资产的精确版本键(取自 lattice 同名字段),非类型格自身版本。
  - **歧义 2**:§2.2 类型格 `rulecard_bundle_id` 定为"配套强校验"(与当前卡包 bundle_id 失配→ingest hard-fail),校验的是"资产与卡包语料配套",非随每张卡升版。
  - **歧义 3**:§2.5 evidence 定必填字段契约(slot_ref_id/condition_id 至少一非空 + kind 枚举 + 卡内引用存在性),违反→ingest hard-fail。

## 0. 背景与证据锚

**病灶(DEBT-065)**:现行早退判据="卡组件类型词表值集合 与 fragment 作用域观测集(含类目扩张)交集为空 ⇒ 结构不相容整卡 NA"(`closure/validator.py:1237-1273`)。词表 10 值混装父类/子类/状态/法律属性四条轴,codex 穷尽裁定 **45/45 值对无法从规则文本证明互斥**——"词表空交=互斥"是验证器自造公理,无证明责任基础。收官批 10,602 条组件维 scope NA(含 480 条 ubw×物理组件)判据均属未证成。

**架构纲领(grok 乙案裁决,多方收敛)**:**正类型归生成(W0);排斥关系归共享本体(单一有出处的类型格,规格授权的上游产物);验证器只执行、不立法。**

**定价(codex 路线二量化 + 决策门修正)**:W0 单类型链代码级成立(`ComponentNode.component_type` 单标量,链上无例外;收官批 120/120 fragment 恰一非类目规范身份)。限缩早退为"可证叶型分区两侧+正向授权",全授权条件下预测口径见 §6。

**首次正典化声明**:现行机制在 v0.4 正文零落点,唯一 spec 来源是**从未合入**的草案 `spec草案_触发器限定符结构不可满足NA_20260708.md`;本规格定稿即**显式废止**该草案"值不同即不相容"判据段(含其楼级触发器 NA 语义,见 §3.2-①)。

**输入材料台账**:冻结档 `杂物箱/文件包/DEBT-050_词表互斥修复冻结档_20260723/`;四路勘察 + 三轮决策门裁决/复核/终确认 + 118 卡授权裁定工作面枚举(`杂物箱/文件包/DEBT-065_修复周期材料_20260724/`)。

## 1. 红线(写入红线,全程有效)

1. **排斥只认显式声明**:两类型互斥当且仅当类型格资产**逐对显式声明**;未声明=未知=不早退。禁止任何"未登记对视为互斥"的缺省反转。
2. **禁运行时推导叶集**:叶型集是版本化资产的字面内容,禁止运行时用"词表剩余值"等规则推导。
3. **fragment 身份只认专用通道**:排斥判定的 fragment 侧输入=§3.0 的 `w0_component_identity` 专用通道(带专属 provenance),**禁止扫描一般事实限定符充当身份**;类目扩张/overlap 闭包等加工集合禁用于互斥证明,仅可用于相容豁免方向。
4. **禁传递闭包**:排斥与重叠均为逐对关系,禁止不动点/传递闭包扩张。
5. **措辞边界**:类型格证明的是"W0 生成模型内"的互斥,**不外推**为现实世界本体互斥;对外宣称一律带此限定。
6. **判定权红线不动**:类型格与授权表是判据的数据来源,合规判定仍唯一由 `validate_building_closure` 产出;blind 红线不碰(两资产均属法规/本体侧 agent 可见知识,非 W2 真值)。
7. **正向授权、缺省拒绝**:卡级早退**只**对授权表中有**有效**条目(定义见 §2.5)的卡开放;未授权/条目失效=不早退。新卡/改卡自动失去授权(指纹失配→条目失效),须重新裁定。

### 1.1 资产异常三阶段矩阵(v2.2 逐项补全,与 §2.5 对齐)

异常按发生阶段分三档,语义互斥不得混写:

| 阶段 | 触发条件(逐项列全) | 处置 |
|---|---|---|
| **Ingest hard-fail**(灌库/加载即炸) | (a) 任一资产 schema 结构损坏;(b) **卡包内 `rule_card_id` 重复**(卡包完整性前提,§2.5);(c) 同 `rule_card_id` 出现多个授权条目;(d) 授权条目**非法 evidence 格式**(§2.5 契约:slot_ref_id/condition_id 全空、kind 非枚举、卡内引用不存在);(e) 非法目标类型(非叶/多目标)/非法哈希格式;(f) lattice 的**词表快照 / 别名快照失配**;(g) `disjoint_pairs` 未覆盖叶集 C(n,2) / 非对称 / 含自反;(h) 违反"每卡单组件值"不变量;(i) 类型格顶层 `rulecard_bundle_id` 与当前卡包 bundle_id 失配(§2.2);(j) 授权表顶层 `rulecard_bundle_id` 与当前卡包 bundle_id 失配(整表配套错误,§2.5) | 整包拒绝,批不启动 |
| **条目级失效**(标记 `stale_card_binding`,仅该条目失效,不 fail 整包) | 授权条目结构合法、顶层 bundle 已过 ingest 校验,但下列**任一失配**(均为逐条 `card_version_binding` 字段):(a) `rule_card_id` 不存在于卡包;(b) 独立重算 `card_content_sha256` 失配;(c) `authoring_revision` 失配;(d) `interpretation_revision` 失配 | 该卡退化为不早退(安全的保守退化,只减 NA 不产未证成 NA) |
| **Runtime 保守关闭** | 选定的 **lattice / 授权表 / 别名映射**三资产**任一整体缺席**(run 起始版本冻结后取不到) | 组件结构早退**整体关闭**(全部不早退),不回退旧词表空交判据 |

## 2. 类型格本体资产(锁 1 落地)

### 2.1 内容三件套

- **叶型集**(v1 恰 5 值):`external_wall` / `fire_safety_component` / `drainage_component` / `cantilevered_canopy` / `wall_tiles`。
- **涵盖关系(subsumption,有方向)**:v1 = `external_component ⊇ {external_wall, cantilevered_canopy, wall_tiles}`(**收编** `projection_runtime_mapping_v1.json:104-110` 的 `component_category_members`——lattice 成为**唯一涵盖权威**;旧表删除,或降级为由 lattice 机械生成的缓存并加逐字一致断言 §2.3-⑦。禁双源)。`structural_component ⊇ cantilevered_canopy` 多父裁定**显式延期**(资产不留"待裁"条目;结构保留多父能力,v1 数据不启用)。
- **排斥关系(disjointness,对称,逐对显式)**:v1 = 5 叶两两互斥,C(5,2)=10 对全部显式列出。证明出处逐对锚 W0 代码单类型链。

### 2.2 数据形状(草案)

```json
{
  "version": "component_type_lattice.v1",
  "rulecard_bundle_id": "<绑定的卡包 bundle_id;加载时与当前卡包 bundle_id 校验,失配→ingest hard-fail>",
  "leaf_types": ["external_wall", "fire_safety_component", "drainage_component", "cantilevered_canopy", "wall_tiles"],
  "non_leaf_types": ["structural_component", "external_component", "ubw", "covered_component", "transfer_structure"],
  "subsumption": { "external_component": ["external_wall", "cantilevered_canopy", "wall_tiles"] },
  "disjoint_pairs": [["external_wall", "fire_safety_component"], "...(10 对全列)"],
  "w0_generation_plan_types": ["external_wall","structural_member","drainage_stack","drainage_branch","fire_door","signboard","wall_tile_finish","canopy","unauthorized_structure","balcony_slab","parapet_wall"],
  "w0_dormant_types": ["access_panel","floor_trap","fire_resisting_wall","escape_route","smoke_vent","fire_service_installation","unknown_fire_component","protective_render"],
  "vocabulary_snapshot_sha256": "<controlled_vocabularies_v1.json 之 component_type_key 值域,canonical_hash>",
  "alias_mapping_version": "<别名映射资产精确版本键>",
  "alias_mapping_snapshot_sha256": "<projection_runtime_mapping_v1.json 之 qualifier_value_aliases.component_type_key,canonical_hash>",
  "canonical_hash_algorithm": "component_lattice_hash.v1 = sha256( UTF-8( JSON(排序键, 分隔符(',',':'), ensure_ascii=False) ) )",
  "provenance": {
    "authority": "W0 component_type_registry + 组件计划(单类型链)",
    "proof_anchors": ["models.py:447", "generator.py:502", "registry.py:1460", "fact_retriever.py:490"],
    "scope_statement": "互斥仅在 W0 生成模型内成立,不外推现实本体"
  }
}
```

注:①`leaf_types ∪ non_leaf_types` 必须**穷尽且不交地二分**词表全值域(§2.3-⑥);②`rulecard_bundle_id` 是**配套强校验**——叶集/涵盖是相对某卡包语料裁定的,故资产必须声明其配套 bundle,加载时失配即 hard-fail;但类型本体语义(叶集/排斥)不随卡内容小改升版,只在卡包换代复核时同步升版;③"精确目标授权"**不入本资产**(类型本体不得随卡片修订升版,另立 §2.5)。

### 2.3 完整性自校验(裁定 C 全套 + 三轮决策门补强,落测试)

① 双快照哈希(vocabulary + alias_mapping)在场且与当前资产一致(任一漂移 → **ingest hard-fail**);② `disjoint_pairs` 恰为叶集 C(n,2) 全覆盖 + 对称 + 无自反(违反 → ingest hard-fail);③(并入②);④ 词表/别名突变测试(加值/改桥而资产未升版必炸);⑤ 灌库往返测试(源 JSON→Neo4j→查询→`retrieval_policy` 逐字段一致,含 version 与双哈希);⑥ **穷尽二分对齐测试拆两断言**:
  - **断言 A(词表二分)**:`leaf_types ∪ non_leaf_types == controlled_vocabularies_v1.json 的 component_type_key 值域`(逐字相等),且 `leaf_types ∩ non_leaf_types == ∅`;
  - **断言 B(生成计划映射全覆盖,成员写死)**:
    - `w0_generation_plan_types`(资产字段,11 成员)**逐字等于** `generator.py` 实际生成计划(`_BASE_COMPONENT_PLAN` + `_ARCHETYPE_EXTRA_COMPONENTS`,当前 303-359)派生的原始类型集合(相等断言,非子集);
    - `w0_generation_plan_types` 每个成员经 `qualifier_value_aliases.component_type_key` 有别名,且映射结果全部落入断言 A 的二分;
    - `w0_generation_plan_types ∪ w0_dormant_types` **逐字等于** `component_type_registry` 全 19 成员(禁静默丢弃;休眠 8 类不参与别名断言但必须显式在册);
    - 三清单交集两两为空;
⑦ 涵盖单源断言(若旧类目表保留为缓存:与 lattice.subsumption 逐字一致)。

### 2.4 落点、版本纪律与运行期版本选择

- **单一版本化 JSON** 落 `agent_v1/regulations/rulecard_v2/mbis_cop_2023/component_type_lattice_v1.json`;运输走既有 loader→KG→retriever 通道(取代 `component_type_overlaps` 腿,该腿裁撤并修 loader 注释失真);词表腿(`RULE_QUALIFIER_VOCABULARY`)保留。
- **版本纪律从严**:语义变更必升 `_vN` 新文件 + 文件内 `version` 字段 + 变更记录;消费端校验 version 与双快照哈希。W0 侧不新增 RegistryTable(权威性由 proof_anchors + ⑥ 对齐测试保证)。
- **运行期版本选择(消除 bundle/version 歧义)**:一次 run 开始时**冻结**三资产(lattice / 授权表 / 别名映射)的精确版本键,validator 与 retriever 按**精确键**查询(**禁止** `ORDER BY version DESC LIMIT 1` 式字典序回落——`queries.py:49-53/168-179` 现行写法在 v10/v9 时会误选);冻结版本取不到 → §1.1 runtime 保守关闭。冻结版本键写入 run_meta,纳入锚可比性声明。

### 2.5 精确目标授权资产(锁 3 落地;独立于类型格)

**新建** `exact_fragment_target_authorizations_v1.json`(同目录,独立版本化——规则解释资产,随卡片修订升版,与类型本体解耦):

```json
{
  "version": "exact_fragment_target_authorizations.v1",
  "rulecard_bundle_id": "<绑定的卡包 bundle_id>",
  "card_fingerprint_profile": "card_fingerprint.v1",
  "entries": [
    {
      "rule_card_id": "rc.mbis....c01",
      "card_version_binding": { "authoring_revision": "...", "interpretation_revision": "...", "card_content_sha256": "..." },
      "exact_fragment_target_types": ["drainage_component"],
      "evidence": [{ "slot_ref_id": "...sr01", "condition_id": null, "kind": "slot_role_map" }],
      "adjudication_note": "引文行号+一句话依据(限定符系义务作用组件,非跨组件证据宿主)"
    }
  ]
}
```

- **卡包完整性前提**:卡包内 `rule_card_id` 必须唯一(重复→ingest hard-fail,§1.1-b),否则 card_fingerprint 的"该单卡对象"不良定义。
- **卡指纹定义**:`card_fingerprint.v1` = `sha256( UTF-8( JSON( 原始 rule_cards.json 的**该单卡对象**, 排序键, 分隔符(',',':'), ensure_ascii=False ) ) )`——**哈希原始卡对象,不哈希 KG 重建后的 DTO**(避免 `pack_builder.py:500/663` 子数组排序+重建带来的口径分歧)。加载时对卡包内该卡独立重算并比对。
- **顶层 bundle 前提**:授权表顶层 `rulecard_bundle_id` 必须与当前卡包 bundle_id 一致,否则整表配套错误 → ingest hard-fail(§1.1-j);此为条目有效性判定的**前提**,bundle 校验通过后才逐条判有效性。
- **有效条目判定(四字段全等)**:顶层 bundle 通过后,条目"有效" ⟺ `rule_card_id` 存在于卡包 ∧ `authoring_revision` ∧ `interpretation_revision` ∧ 独立重算 `card_content_sha256` **四者全部相等**;任一不符 → `stale_card_binding` 条目失效(§1.1 条目级)。
- **evidence 格式契约(必填,违反→ingest hard-fail)**:每个 evidence 项 = `{ slot_ref_id?, condition_id?, kind }`;约束:(a) `slot_ref_id` 与 `condition_id` **至少一个非空**;(b) `kind ∈ {slot_role_map, threshold_regimes, trigger_conditions}`;(c) 所引 `slot_ref_id`/`condition_id` 必须能在该卡对象内定位到(引用存在性)。
- **v1 加载不变量(封死多目标漏洞,阻断 4 最小案)**:①每个有效条目 `len(exact_fragment_target_types) == 1`(违反→ingest hard-fail);②该单目标 ∈ `lattice.leaf_types`(非仅词表值域);③**每卡单组件值不变量**——卡包内每张卡的所有 `component_type_key` 出现值必须一致(违反→ingest hard-fail),使"卡目标"良定义。多目标/逐源项授权留 v2 另升版。
- **唯一性**:同 `rule_card_id` 多个授权条目 → ingest hard-fail(§1.1-c)。
- **缺省拒绝**(红线 7):无有效条目的卡永不早退。signboard 反例(`rule_cards.json:230-313`:measure 限定 `external_wall` 系证据宿主;118 卡枚举实证该 `area.signboard.display` 为 measure 谓词项)已由 measure 触发器在结构检查前返回(§3.2-③)+ 单目标不变量双重封住。
- **裁定工作面**:118 卡 / 169 个叶值限定来源项(枚举台账 `杂物箱/文件包/DEBT-065_修复周期材料_20260724/授权裁定工作面_118卡枚举_20260724.md`),法规卡专员按引文逐项裁定"目标类型/证据宿主/存疑"(转述法规,不发明);measure 谓词 3 项已标"疑似证据宿主"线索。

## 3. 验证器消费语义(锁 2/锁 3 落地;第一波)

### 3.0 W0 fragment 身份专用通道(定死 schema)

retriever 从 `Fragment.component_id → Component.component_type → 冻结版本别名映射` **一次性生成**专用身份事实 `w0_component_identity`,validator 互斥判定**只读**该通道:

- **保留 channel/schema**:事实原子 `slot_id == "w0_component_identity"`,provenance =
  ```json
  { "channel": "w0_component_identity",
    "derivation": "fragment_component_projection",
    "alias_mapping_version": "<别名映射资产的精确版本键;取值等于 lattice.alias_mapping_version 字段,非类型格自身 version>",
    "alias_mapping_snapshot_sha256": "<等于 lattice.alias_mapping_snapshot_sha256>" }
  ```
  载荷字段:`fragment_id` / `component_id` / `raw_component_type` / `canonical_component_type`。
- **消费前提(同源绑定)**:validator 使用前必须校验该事实 provenance 的 `alias_mapping_snapshot_sha256` **等于** lattice 引用的同名哈希;不等 → 拒用该身份 → 不早退。
- **"唯一"= 来源关系基数**:恰**一条**原始 `Fragment→Component` 来源关系(基数校验),**非**规范值去重后剩一个;来源关系 >1 或缺失 → 不早退。**禁 last-write-wins**——新通道不得复用 `fact_retriever.py:496-502` 按 fragment 建字典后写覆盖的形态(`queries.py:31-36` 允许多行返回),须显式 count==1 校验。
- **回归矩阵(必测)**:①兜底任选组件(模板类型 A、实选组件 B → 身份必须=B,`generator.py:686-698,735-739` 证模板非权威);②类目行并存(41/120 fragment 叶值+`external_component` 并存,身份仍唯一);③身份缺失→不早退;④多来源关系→不早退。

### 3.1 卡级早退新判据(替换 validator.py:1246-1249)

早退当且仅当**全部**成立:

1. 卡在授权表有**有效**条目(§2.5),取其单一 `exact_fragment_target_type`(v1 恰一);
2. 该目标类型 ∈ 叶集;
3. fragment 的 `w0_component_identity` 存在、来源关系唯一、规范值 ∈ 叶集、别名快照同源(§3.0);
4. (目标类型, fragment 身份) 对 ∈ `disjoint_pairs`。

现有护栏全部保留(身份未知不早退/卡端脏值回落 missing/合并保守序等);`_known_ct` 四路拼凑宇宙不再参与互斥判定(仅保留"卡端脏值保守回落"职能);类目扩张仅保留相容豁免方向。

### 3.2 卡级/触发器级共用纯判据 helper

抽出共用纯函数 `provable_disjoint(target_type, fragment_identity, lattice)`,两级消费,语义**显式定死**:

1. **fragment-only**:`scope_fid` 必须非空且身份来自 §3.0 通道;**组件维楼级结构 NA 一律废止**(现行触发器代码以 building component 集合缺值直接 NA 的路径 `obligation_deriver.py:463-488`、`test_trigger_structural_na.py:50-59` 钉住的旧语义,按本规格移除,测试随规格更新)。**注:此处仅指组件维楼级结构 NA;location 维 NA 不在本周期范围(§5),不受影响。**
2. **仅 `bound=∅`**:该 trigger 无任何事实绑定时才判;已绑定事实绝不覆盖;
3. **measure 触发器不参与**(现行代码在结构检查前已返回,`obligation_deriver.py:413-418`;本规格显式承认该豁免,不扩);
4. **触发器授权=恒等而非子集**(封死 A⊆{A,B} 漏洞):触发器的组件限定值必须**恒等于**该卡的单一授权目标类型(v1 单目标不变量下"子集"退化为"相等"),否则不早退;
5. **限定符合并规则唯一化**:触发器级取 `trigger.qualifiers`,缺失则回落 `map_qualifiers`(`obligation_deriver.py:390-404` 现行两分支的显式化,禁并集);
6. **同源参数**:`blueprint_state_eval.py` 的 `trigger_eval_kwargs` 与主路径同一构造点,落码时断言同源;
7. 卡级与触发器级差异**只允许**存在于上述显式声明处,其余逐字共用 helper。

## 4. ubw 迁授权状态轴(第二波;按决策门改向)

- **表示法(主案改向)**:授权状态建成**独立 slot/value 条件**(如 `slot_id: authorization.status`,值域对齐 W0 `authorization_status_proxy` 三值),**不走 qualifier 方案**——严格身份 DTO 只准八个限定符键、第九键 hard-fail(`closure/source_dtos.py:58-90`);`authorization_status_proxy` 是事实值非限定符(`fact_retriever.py:105-108`);UBWState 挂 Component 不带 fragment_id(`kg/queries.py:105-115`),投影须另规格化 `UBWState.component_id → fragment` 唯一映射与盖章规则。若届时仍议 qualifier 方案,须先升级严格 DTO + 覆盖矩阵全部"八键"假设。
- **卡面迁移**:20 卡 21 处**逐项裁定**目标语义(§39C validated/报告记录/紧急通报等语义异质,禁机械映射为 `unauthorized_like`);词表与卡同一提交原子迁移;法规卡专员工单。
- **清理清单(四处)**:①组件轴 `ubw` 值+别名桥 `unauthorized_structure → ubw`;②defect 轴 `ubw` 值+`DC_UBW_PRESENT → ubw` 桥归宿裁定;③`is_ubw` 硬编码(`fact_loader.py:167-168`);④`subject_component_crosswalk` 的 ubw 桥。
- **连带断裂**:卡侧变更 → 结构审计身份哈希全变 → catalog 重建+双读径闸重过;派生索引必重跑(`rebuild_derived_indexes`,DEBT-056 教训);第二波单独重锚批。
- **悬空值**:`transfer_structure`/`covered_component` 迁移方向第二波裁定;v1 阶段二者列 `non_leaf_types`、不早退、诚实注记不变。

## 5. 波及面与工程迁移清单(第一波)

- **主改**:validator.py(判据+§3.0 通道消费)/obligation_deriver.py(触发器级+组件维楼级路径移除)/fact_retriever.py 或 retriever(身份通道生成)/两份资产 JSON 新建/完整性测试套/共用 helper。
- **锚影响**:资产数据进 `retrieval_policy` → `rule_slice_hash` 变(显式声明);卡侧 qualifiers 不动 → 结构审计身份哈希不变、无需 catalog 重建;池目录不放任何新资产。
- **不碰**:location 维(含 location 维楼级/fragment NA);applicability.py 规则 3 词桥(显式授权 crosswalk,第二波随 ubw 桥核);缺叶上塌卡(columns/curtain_wall/rendering/finishes)不下沉。

## 6. 验收与重锚(第一波)

1. **定向冻结用例**:授权叶×叶可证对 NA 保留;未授权卡/非叶/身份异常/资产缺席全部保守显现;§3.0 回归矩阵四场景;组件维楼级 NA 移除语义;measure 豁免不变;§1.1 三阶段异常各典型例(重复卡/非法 evidence/指纹失配/别名资产缺席)。
2. **全量回归** 2500+ 通过(含按新语义更新的旧钉死测试,逐条在 PR 说明列明改动依据)。
3. **重锚批预测对账(硬验收,两段式)**:`4,532 / 91,972`(+8.32%,重放口径基准 84,911)是"**118 卡全授权**"条件下的**条件预测**(535 条恢复的 scope 早退替换 2,541 条下游义务,总义务净减 2,006);**授权表定稿后先离线重放生成硬验收值**,再发批;实际 vs 硬验收值差异逐项归因,不可解释即批作废。三个移动量口径(6,605/15,672/4,319)禁混用;磁盘锚 83,831 与重放基准差 +1,080 已定案。
4. **门禁**:A/B 门批尾自动执行(A 门 180 行线须实测);每栋 `tool_call>0`。
5. **对照迁移**:对照对象 `baseline_v4_final_seed301`(整批留档),报预期差异账;跟踪表/收官宣告/债文件口径注记同步;新开 EXP 编号;行号级引用在落码 PR 补 commit/符号级 provenance(防行号漂移)。

## 7. 范围边界(本周期不做)

词表 `_v2` 全面重构;location 维互斥;缺叶上塌下沉;structural_member 叶化(延期,资产 non_leaf 已覆盖);canopy 多父裁定(延期);多目标/逐源项授权(v2 升版);现实本体外推宣称;evo 探索版机制。

## 8. 决策门收敛落账(三轮)

| 轮 | 载体 | 结论 |
|---|---|---|
| 裁决(codex) | v1 | D4 否决→正向授权;D2/D6 有条件;D1/D3/D5 同意 |
| 复核(codex) | v2 | 路线闭合;五项契约阻断待补,出 v2.1 |
| 终确认(copilot) | v2.1 | 身份通道/触发器漏洞/楼级位置维三项闭合;异常矩阵/二分测试/几处措辞待补,出 v2.2 |
| 自核定稿 | v2.2 | 三阻断+三歧义逐条落实(见 v2.1→v2.2 摘要);进入第一波落码,审核门为下一道防线 |

## 9. 定稿后合入路线(双落点)

- **(a) 类型格资产 + 授权表 + ubw 授权状态轴**:**落点待定(2026-07-24 合入准备时发现,原拟落 W0 规格包不成立)**——W0 规格包 README 明确 W0 是 rule-blind 静态资源层「不消费 rule_card v2、不承接判定逻辑」;类型格(排斥关系本体)是给闭包验证器用的**判据本体**,消费在闭包侧,叶集虽源于 W0 单类型链但「排斥关系」是从正类型事实推出的本体断言,不属 W0(grok 裁决即「正类型归生成 W0/ 排斥关系归**共享本体**」,共享本体≠W0 独权)。候选落点:①蓝图汇总/ 下新建独立「共享本体规格包」②v0.4 新增本体章。**属架构分层归属决策,待 codex 商议+用户定**;落码阶段资产可先作独立文件生成+自校验(不接主链),正典化与消费接线待落点定后再做。
- **(b) 验证器只读消费语义**:合入 v0.4 §6.3 新增小节,打 `[v0.4-F-1]` 标记;显式废止 `spec草案_触发器限定符结构不可满足NA_20260708.md` 判据段(含楼级触发器 NA 语义)。
- 本草案 v1/v2/v2.1/v2.2 文件按家惯例留档不删。
