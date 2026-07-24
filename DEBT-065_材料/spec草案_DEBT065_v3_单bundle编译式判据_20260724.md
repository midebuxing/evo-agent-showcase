# spec 草案 v3:单 bundle 编译式适用性判据(DEBT-065 第四轮设计定稿)

- 版本:草案 v3(2026-07-24)。**取代 v2.2 的运行时组装式设计**。
- 状态:设计商议后定稿候选(商议:PlusAI 深度研究 + codex 三轮审核根因 + 主会话实现视角)
- 决策依据:用户 2026-07-24 定"先商议设计再修";商议结论=**v2.2 过重,漏洞面来自 runtime 复杂性叠加而非 leaf×leaf 排斥想法本身**

## 0. 为什么换设计(不是打第四个补丁)

v2.2 用四层活动部件(runtime 授权表 + 专用身份通道 + 三方版本冻结 + 卡指纹匹配)去实现一个**其实很窄**的判据。三轮独立审核(copilot×2 + codex×1)挖出的全部 P1 **都在这些间接层里**,不在排斥关系本身:身份可伪造、真实链路断路、版本字典序、卡值≠授权目标、单测伪造掩盖断路。

PlusAI 商议的核心批评一针见血:**当前设计花大量机制预算去"证明"运行时的值真的来自 W0、真的是对的卡绑定,而不是让这些属性结构上不可能出错**。按来源证明标准(W3C PROV / SLSA),可信性是"产出与绑定方式"的属性,不是任意方断言的字符串标签——**普通事实只要能在语法上模仿可信通道,该通道在保障意义上就不是来源证明通道**。这解释了三轮为什么反复。

v3 的思路:**把证明责任从 runtime 判据挪到离线产出与绑定**,runtime 只剩一个微小、确定、不可绕过的谓词。

## 1. 设计(三个可信输入 + 一个微小判据)

**一句话**:早退 NA 当且仅当——已发布卡携带一个已授权义务目标叶 ∧ 该 fragment 的 W0 产物携带一个可信物理叶身份 ∧ 二者在显式叶×叶排斥矩阵中;否则继续正常求值。

### 1.1 三个可信输入(全部离线产出、精确钉住)

1. **叶排斥规格**(固定,不随卡/世界变):5 物理叶(external_wall / fire_safety_component / drainage_component / cantilevered_canopy / wall_tiles)+ C(5,2)=10 显式排斥对 + 涵盖关系。
2. **已发布卡适用性 manifest**(离线生成):`{rule_card_id: {authorized_target_leaf: <五叶之一> | null}}`。由卡包 + 授权裁定在**离线合并 + 规范化**时产出;生成时校验"该卡唯一组件值 == 授权目标"(结构性消除 v2.2 的 P1-4),runtime 只消费规范叶 ID、**永不接触 authoring 标签/别名/法律属性词表值**。
3. **W0 fragment 身份 manifest**(离线生成):`{fragment_id: {physical_leaf_identity: <五叶之一> | "unknown"}}`。直接从 W0 自己的产物(worldgen 输出的 Fragment→Component→component_type)离线提取 + 规范化;**runtime 不再从任何"事实"重建身份**(结构性消除 P1-1 伪造面)。

### 1.2 单 bundle manifest(取代三方版本冻结)

一份 bundle manifest 用**精确版本 + digest** 钉住上述三个产物。validator **不问"最新是什么"**、不做任何字典序/包新近度选择;只加载被指向的那一个 bundle。bundle 缺失 / digest 不符 / 未验证 → **该路径禁用早退**(保守回落)。

### 1.3 runtime 判据(全部逻辑)

```
早退 = bundle 已验证
     ∧ card_manifest[card].authorized_target_leaf 非 null
     ∧ fragment_manifest[fragment].physical_leaf_identity 非 unknown
     ∧ (authorized_target_leaf, physical_leaf_identity) ∈ 排斥对
```
其余一切情形(未授权 / 身份 unknown / 不在排斥对 / bundle 异常)→ **不早退**(fail-safe default)。

**由此消除**:runtime 授权表查询、专用身份通道、runtime 卡指纹匹配器、三资产同源冻结、KG 运输耦合——即三轮审核全部 P1 的滋生地。

## 2. 结构性消除三轮审核的 4 组 P1

| codex 三审 P1 | v2.2 为何反复修不好 | v3 如何结构性消除 |
|---|---|---|
| P1-1 身份可伪造(专用标记≠来源证明) | runtime 试图从事实流里"认出"可信身份,而标记可被模仿 | 身份只来自离线 W0 产物 manifest;runtime **没有**"从事实重建身份"这条路径,无从伪造 |
| P1-2 真实链路断路 + 版本非精确 | 多资产跨 KG 运输、各自选"最新",字段错配即断路且被伪造单测掩盖 | 单 bundle 精确版本+digest;无 KG 运输耦合;发布门禁在**真实 bundle** 上比对(见 §3) |
| P1-3 bundle 校验可绕过(自动补默认值) | 校验散落在 loader 多处,有旁路 | bundle manifest 是**唯一入口**,无默认值路径;未验证即禁用 |
| P1-4 卡值 ≠ 授权目标 | runtime 无从核对卡值与授权目标 | 授权 manifest **离线生成时**即强制 `卡唯一组件值 == 授权目标`,不合规不出包 |

## 3. 发布门禁五道(专治"单测伪造掩盖")

1. **微小域穷尽真值表**:判据只依赖 5 叶 + null/unknown + 10 排斥对,可穷举抽象函数全部输入,证明所有非授权/未知输入回落"不早退"。
2. **真实发布数据端到端 oracle 比对**:对精确 bundle,用真实卡 manifest + 真实 W0 身份 manifest 离线生成**全 card × fragment 答案表**,与生产 validator 输出**精确相等**,否则发布失败。(这才是离线全表的正确用法——发布 oracle,不是服务路径。)
3. **负向来源证明测试**:注入携带相同字符串值的普通事实 → 必须被忽略;改字段名 / 删 bundle 成员 / 坏 digest / 换 manifest → 唯一允许结果是保守回落。
4. **精确版本测试**(非"最新可用"):验证只加载被指向的 bundle;无任何字典序/新近度选择路径。
5. **shadow 模式度量**(启用前):并行计算新判据、与当前保守路径比对,在真实 bundle 上记录与 oracle 的分歧,确认保住 NA 回收率而不扩大假 NA 面。

## 4. 迁移路径(不动卡包本体、不动 W0 本体)

关键:**两份 manifest 都是离线派生产物,不要求改卡包 JSON 结构、也不要求改 worldgen 代码**。
- 卡适用性 manifest:由现有卡包 + 授权裁定(118 卡工作面已枚举、55 卡高置信初裁已备)离线合并生成。
- W0 身份 manifest:从现有 worldgen 产物离线提取(Fragment→Component→component_type 经固定别名映射规范化)。
- 二者 + 叶排斥规格 → bundle manifest(精确版本 + digest)。
- validator 改为只读 bundle,删除 v2.2 的授权表查询 / 身份通道 / 三方校验代码路径。

v2.2 已落码的部分:类型格资产(叶集/排斥对/涵盖)**可直接复用**为叶排斥规格;授权裁定数据可复用为卡 manifest 的输入;其余 runtime 组装代码按 §1.3 简化(净删多于净增)。

## 5. 数字口径

v2.2 的 4,532 / 91,972 是**旧口径条件预测**。v3 下 NA 回收包络理论上相近(同样的授权卡 + 同样的 W0 叶身份),但**必须在新发布 oracle 下重新测量**再引用(PlusAI 明确保留了这一点:37.7% 是我方估计,它不独立验证)。

## 6. 待办(第四轮实现)

1. 离线生成器:卡适用性 manifest(含"卡唯一组件值==授权目标"强校验)+ W0 fragment 身份 manifest + bundle manifest(版本+digest)。
2. validator 判据替换为 §1.3(删 v2.2 授权表/身份通道/三方冻结路径);触发器级共用同一纯 helper(消除 codex 三审 P2 的三份实现)。
3. 发布门禁五道(§3),其中第 2、3 道是重点(闭合"单测伪造掩盖"缺口)。
4. shadow 度量 → 重锚批 → 数字重出。
