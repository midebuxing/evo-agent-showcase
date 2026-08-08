"""新池（池 v2）真值面**生成期**规则内核 —— M14 ／ 步 A1.5 落码件。

地位
----
本模块是「适用规范项独立真值」在**新池上按机械规则生成**时的唯一判据实现，
外加一个生成完就地自检的断言入口。设立它的理由只有一条：
**生成完自检，不靠人记得**——旧池那 29 行是人工逐行落改的，规则只活在裁定文档里；
换池后真值面整面重生成，如果规则仍只活在文档里，第一次漂移不会有任何东西报警。

- 消费点：步 B3（新池真值面生成脚本）——调 :func:`q2_applicable` ／ :func:`q3_applicable`
  产值与 reason，落盘后立刻调 :func:`verify_truth_face_invariants` 自检，非空即中止。
- 本模块**不写盘、不读盘、不认识任何具体的池**：它是纯函数内核，
  行数／栋数／池 seed／世界计数一个都不出现（见下「池无关」）。

出处指针（带行号；改动这些文档时请回来核这里）
----
- 工单：``团队文档/我的笔记/换池批总工单_v1_20260806.md:111-116``（步 A1.5）、
  同文件 :49（M14 收编行）。
- 规则原文（§2.1 Q2／Q3 机械规则、两个必须显式声明的点）：
  ``团队文档/我的笔记/底稿_真值落改_20260805.md:143-177``。
- P1／P2／P3 三段切分与「换池后 `.intended` 重述」的前提：同底稿 :374-401。
- 裁决：``团队文档/我的笔记/决议_真值落改_20260805.md``
  §二（**删** ``ELIF NOTIFIED is true -> applicable=true`` 分支）、
  §三.1（``artifact.notice.investigation_intention`` **不得**作「通知已作出」证据，
  且该排除须在 Q3 规则注释里**显式**写出——即本模块 :data:`RULE_Q3` 的「显式排除」段）。
- ``.intended`` 重述依据：``团队文档/我的笔记/商议结果_official_乙路_20260805.md:52-56``
  （方案 A 落地后，真值侧触发谓词由 ``intention_notified`` 换成
  ``procedure.investigation.detailed.intended``，真值判适用的栋数由 3 → 10）。
- 旧池参照实现（**只参照口径，不复用其任何池锚常数**）：
  ``agent_v1/scripts/apply_truth_landing_25_20260805.py`` 的 ``RULE_Q2`` ／ ``RULE_Q3``
  两个文档常量与 ``_Q3_EXCLUSION`` reason 模板。该脚本内含 ``WORLD_Q3`` 世界计数表与
  29 行行号白名单，**全部锚死在批 `baseline_batch_final_seed301`，换池即作废**；
  本模块一个字节都不继承它们。

池无关（这是硬约束，不是风格偏好）
----
本模块内**不得**出现：栋数、真值行数、池 seed 标签、任何 ``t/n`` 世界计数、任何批名。
理由：旧池那九行 reason 把世界计数写进了数据自述，于是「拿另一个同标签池复核会误得
『真值错了』」——本仓已记的「加一个世界槽就换掉整池种子」形状。生成期内核只表达
**规则**；世界数字由调用方（步 B3 生成脚本）从当批 fact_pack 现取现填。

blind 红线
----
本模块属 ``eval/`` 旁路，**零 import agent 运行时**（``closure`` ／ ``agent`` ／
``retrieval`` 一律不进）。真值面只服务阅卷侧，不得被 agent runtime 消费。
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping

__all__ = [
    "APPLICABLE_TRUE",
    "APPLICABLE_FALSE",
    "APPLICABLE_PENDING",
    "APPLICABLE_STATES",
    "RULE_Q2",
    "RULE_Q3",
    "Q2_ITEM_PREFIX",
    "Q2_CIRCUMSTANCE",
    "Q3_ITEM_ID",
    "Q3_CIRCUMSTANCE",
    "Q3_ANTECEDENT_SLOT",
    "Q3_PROXY_SLOT",
    "Q3_FORBIDDEN_EVIDENCE_SLOTS",
    "FORBIDDEN_REASON_PHRASE",
    "FORBIDDEN_REASON_PREFIX",
    "decode_applicable",
    "encode_applicable",
    "q2_applicable",
    "q2_reason",
    "q3_applicable",
    "verify_truth_face_invariants",
]


# ── applicable 三态编码 ────────────────────────────────────────────────────
#
# schema（``applicable_normative_item_truth_v1.schema.json`` 的 ``applicable``）
# 定的是 ``boolean ∪ const "unknown_pending"``，**不是**三值字符串枚举：
# 既有布尔行必须逐字节不变。故内核内部用三个字符串态表达判定，
# 落盘前经 :func:`encode_applicable` 转回 schema 形态。
# 🔴 读盘一律走 :func:`decode_applicable`（``is True`` / ``is False``），
#    不许用 Python 真值判断——非空字符串 "unknown_pending" 会被当成适用，
#    那正是本仓已实测过的静默退化形状。

APPLICABLE_TRUE = "true"
APPLICABLE_FALSE = "false"
APPLICABLE_PENDING = "unknown_pending"
APPLICABLE_STATES = (APPLICABLE_TRUE, APPLICABLE_FALSE, APPLICABLE_PENDING)


# ── 规则文档常量（照 §2.1 机械规则写；生成脚本应把它们打印进运行记录） ──────

RULE_Q2 = """\
Q2（§3.1.1 族）机械规则：
  IF  normative_item_id 前缀 == "mbis.cop2023.s3_1_1."      # 🔴 硬边界，不许放宽
      # 等价判据：source_clause_id == "3.1.1"（底稿 §2.1 实测两套判据差集为空，可互换）
  THEN applicable MUST BE true
       AND reason 的「情形」标记 MUST BE 1
       AND reason 不得以「排除依据」开头、不得含「判不适用」

  理由：条款唯一写出的前件是「如樓宇被選定為強制驗樓計劃的目標樓宇」——
       换池后每一栋受检楼宇仍恒真（这是「被选定为目标楼宇」的定义，与池无关）。
       「公用部分／外牆／訂明的伸出物／豎設在樓宇上的招牌」是**被涵蓋範圍的列举项**，
       不是适用前件——正文没有写「如該樓存在該對象則……」。
       故「本樓有沒有該對象」不进适用性判定，下沉到满足层，以「查明無此對象」处理。
       （原判据把「对象存在」当前件，属给条款加了正文里没有的前件，2026-08-05 已撤回。）"""

RULE_Q3 = """\
Q3（§2.1.3(n)）机械规则 —— **新池口径（前件槽直采）**：
  IF  normative_item_id == "mbis.cop2023.s2_1_3_n.notify_ba_investigation_intention"
  THEN 令 INTENDED := 该楼 `procedure.investigation.detailed.intended`
                      （乙路方案 A 判定侧已随捆绑批落地；世界侧直接采样的意图谓词）
       令 PROPOSAL := 该楼 `artifact.proposal.detailed_investigation` 的 **any_true** 聚合

       IF   INTENDED is True    -> applicable = true              # 前件槽直读，正判
       ELIF INTENDED is False   -> applicable = false             # 前件槽直读，负判
       ELIF PROPOSAL is True    -> applicable = true              # 唯一正向证据代理
       ELSE                     -> applicable = "unknown_pending" # 双缺，不可判

       AND reason 不得含「判不适用」
       AND reason 不得引用下列两槽**作依据**（见「显式排除」段）

  🔴 `ELIF NOTIFIED is true -> applicable = true` 分支**已按
     `决议_真值落改_20260805.md` §二裁删**，本内核结构上不存在该分支——
     :func:`q3_applicable` 的签名里**没有 notified 形参**，故「反推」在这里不是
     被规则禁止，而是**没有入口**。
     裁删依据：`procedure.investigation.intention_notified` 是**独立采样布尔**，
     本世界里「已通知」**不蕴含**「有意」（乙路案实测存在 `intended=false ∧
     notified=true` 的栋）；该分支会对这类栋造假 true。正负两向反推**均**非法：
     正向（通知在 ⇒ 有意）被上述交叉表证伪；负向（未通知 ⇒ 无意）是缺省真负，
     更不构成前件取假的证据。
     ⇒ notified=true ∧ 前件证据缺席的栋，落 `unknown_pending`
       （诚实：通知在场但意图证据缺席，且世界不保证蕴含）。

  🔴 显式排除（`决议_真值落改_20260805.md` §三.1，两线＋主线三方一致）：
     `artifact.notice.investigation_intention` **不得**作「通知已作出」的证据。
     ① registry 对该槽声明的同步 `conditional_formula` 为 None——notes 写的
        「与 intention_notified 同步」是意图声明、**未执行**；round6 只有软关联，
        不是硬闸。
     ② 实测存在 `intention_notified=false` 而该槽仍取真的栋 ⇒ 用它会造假阳。
     ③ Q3 只授权了**一个**正向证据代理（`artifact.proposal.detailed_investigation`）。
     ④ 方向也不对：它是通知的物理载体，用它代理通知＝用效果反推原因，
        与被禁的反向推理同形。
     ⇒ 该槽既不能证「通知已作出」，而「通知已作出」本身又不能推前件（上一条），
       故它在 Q3 里**双重无效**。

  ⚠️ 两个必须显式声明、否则口径不完整的点（底稿 §2.1 注 1／注 2）：
     1. `artifact.proposal.detailed_investigation` **没有楼级事实**（实测每栋均为
        sidecar／片段条目，`granularity != building`）⇒ 用它作代理**必须声明聚合量词**，
        本内核取 **any_true**，且 reason 里须写出该量词。
     2. 前件槽 `procedure.investigation.detailed.intended` 在**旧池**零事实
        （它是新池世界侧才产的）⇒ 旧池 reason 只能写建议书代理。本内核是**新池**口径，
        以前件槽为主、建议书代理降为前件槽缺席时的回退。"""


# ── 判据身份常量 ──────────────────────────────────────────────────────────

#: Q2 射程判据（前缀匹配 ``normative_item_id``）。
Q2_ITEM_PREFIX = "mbis.cop2023.s3_1_1."
#: Q2 唯一情形号：唯一前件＝被选定为目标楼宇，恒真 ⇒ 情形 1。
Q2_CIRCUMSTANCE = 1

#: Q3 射程判据（全等匹配 ``normative_item_id``）。
Q3_ITEM_ID = "mbis.cop2023.s2_1_3_n.notify_ba_investigation_intention"
#: Q3 情形号：条件句·前件须由世界事实定夺 ⇒ 情形 2。
Q3_CIRCUMSTANCE = 2

#: Q3 真前件槽（新池由世界侧直接采样）。
Q3_ANTECEDENT_SLOT = "procedure.investigation.detailed.intended"
#: Q3 唯一被授权的正向证据代理（前件槽缺席时的回退；须声明 any_true 量词）。
Q3_PROXY_SLOT = "artifact.proposal.detailed_investigation"

#: 🔴 Q3 reason 里**不得作依据**的两槽（决议 §二 ＋ §三.1）。
#:   第一项写成裸 token，是为了同时罩住 ``procedure.investigation.intention_notified``
#:   与任何简写形态。
Q3_FORBIDDEN_EVIDENCE_SLOTS = (
    "intention_notified",
    "artifact.notice.investigation_intention",
)

#: reason 全域禁语：出现即说明该行在「值判适用／理由自述不适用」之间自相矛盾。
FORBIDDEN_REASON_PHRASE = "判不适用"
#: Q2 reason 禁开头（同上，旧模板的排除句式）。
FORBIDDEN_REASON_PREFIX = "排除依据"


# ── 内部工具 ──────────────────────────────────────────────────────────────

#: 情形标记抽取。两种承载形态都要认（实测旧真值文件两形态并存）：
#:   ①「（判据情形 1）」括号后缀形；②「适用依据＝判据情形 1。」前置形。
_CIRCUMSTANCE_RE = re.compile(r"(?:判据)?情形\s*([123])")

#: 句读切分。用于判别「引用某槽」是**作依据**还是**在显式排除句里点名**。
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。；;！!])")

#: 排除句标志词。一个句子里同时出现被禁槽名与其中任一词 ⇒ 该处属「点名排除」，
#: 不算「作依据」。
_PROHIBITION_MARKERS = ("禁止", "不得", "非法", "不許", "不构成", "排除")


def _cited_as_evidence(reason: str) -> list[str]:
    """返回 reason 里**把被禁槽当依据用**的句子清单（空＝合规）。

    为什么不是裸子串禁令
    ------------------
    决议 §三.1 **要求**把「不得用 `artifact.notice.investigation_intention`」这条
    排除**显式写出来**。若采「reason 里出现该槽名即违例」的裸子串判据，那么每一行
    照决议写了排除句的合规行都会被判违例——判据会在被筛人群上命中 100%，
    等于什么都没判（本仓已记：判据必须在被筛人群上有意义）。

    故判据下沉到**句**这一级：句子里出现被禁槽名，且该句**没有**排除标志词
    （禁止／不得／非法／不許／不构成／排除），才算「作依据」。

    诚实边界
    --------
    这是对自然语言 reason 的**启发式**，不是证明。硬保证在另一侧：本内核自己产的
    reason **一个被禁槽名都不含**（:func:`q3_applicable` 的文案里零出现），
    该性质由单测逐分支钉死。本函数是给**手写／历史**行兜底的。
    """
    hits: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(reason or ""):
        if not sentence.strip():
            continue
        if not any(tok in sentence for tok in Q3_FORBIDDEN_EVIDENCE_SLOTS):
            continue
        if any(marker in sentence for marker in _PROHIBITION_MARKERS):
            continue
        hits.append(sentence.strip())
    return hits


def _circumstances(reason: str) -> set[str]:
    """抽出 reason 里出现过的全部情形号（取全部而非首个，防同行两个标记互相打架）。"""
    return set(_CIRCUMSTANCE_RE.findall(reason or ""))


# ── 编解码 ────────────────────────────────────────────────────────────────


def decode_applicable(raw: object) -> str | None:
    """把 schema 形态的 ``applicable`` 解成内核三态字符串；非法值返回 ``None``。

    🔴 只认 ``is True`` ／ ``is False`` ／ 字符串常量 ``"unknown_pending"``。
    整数 1／0、字符串 "true"／"false" 一律判非法——它们进真值文件就是静默换语义。
    """
    if raw is True:
        return APPLICABLE_TRUE
    if raw is False:
        return APPLICABLE_FALSE
    if isinstance(raw, str) and raw == APPLICABLE_PENDING:
        return APPLICABLE_PENDING
    return None


def encode_applicable(state: str) -> bool | str:
    """把内核三态字符串编回 schema 形态（``bool`` ∪ ``"unknown_pending"``）。"""
    if state == APPLICABLE_TRUE:
        return True
    if state == APPLICABLE_FALSE:
        return False
    if state == APPLICABLE_PENDING:
        return APPLICABLE_PENDING
    raise ValueError(f"applicable 三态取值非法: {state!r}")


# ── Q2 ────────────────────────────────────────────────────────────────────


def q2_applicable() -> tuple[str, int]:
    """§3.1.1 族的适用性：**恒** ``("true", 1)``。

    没有形参，是因为该族在规则上**没有任何可变前件**：条款唯一写出的前件是
    「如樓宇被選定為強制驗樓計劃的目標樓宇」，而真值面覆盖的每一栋按定义都已被选定
    ⇒ 前件恒真 ⇒ 情形 1、无条件适用。把它写成无参函数，是让「拿片段清单当前件」
    这种回归**在类型层就写不出来**。

    返回 ``(applicable 三态, 情形号)``。
    """
    return APPLICABLE_TRUE, Q2_CIRCUMSTANCE


def q2_reason(coverage_item_zh: str) -> str:
    """产 §3.1.1 族的 reason（情形 1 口径）。

    ``coverage_item_zh``＝该规范项对应的**被涵蓋範圍列举项**中文名
    （如「訂明的伸出物」／「豎設在樓宇上的招牌」／「公用部分（位於私人處所範圍內的除外）」
    ／「外牆」）。它只进文案，**不进判定**——这正是本口径要说清的那件事。
    """
    return (
        "适用依据＝§3.1.1 自己写出的**唯一**前件：樓宇被選定為強制驗樓計劃的目標樓宇"
        "（真值面覆盖的每一栋按定义恒真）。条款把"
        f"「{coverage_item_zh}」列为**被涵蓋範圍的列举项**，不是适用前件"
        f"——正文没有写「如該樓存在{coverage_item_zh}則……」。"
        f"故「本樓有沒有{coverage_item_zh}」不进适用性判定，下沉到满足层，"
        "以「查明無此對象」处理。（判据情形 1）（片段清单是抽样产物，不作判据。）"
    )


# ── Q3 ────────────────────────────────────────────────────────────────────


def _q3_reason_true_by_intended() -> str:
    return (
        "适用依据＝§2.1.3(n) 自己写出的前件 P：有意進行詳細調查。"
        f"前件槽 `{Q3_ANTECEDENT_SLOT}` 于本楼取真——该槽是世界侧**直接采样**的意图谓词，"
        "读到的就是世界态本身，直接见证 P ⇒ P 取真，判适用。"
        "（前件只看该槽；「通知是否已作出」不得用来反推 P，正负两向反推均非法，"
        "详见 Q3 规则的显式排除段。）"
        "（判据情形 2）（片段清单是抽样产物，不作判据。）"
    )


def _q3_reason_true_by_proposal() -> str:
    return (
        "适用依据＝§2.1.3(n) 自己写出的前件 P：有意進行詳細調查。"
        f"前件槽 `{Q3_ANTECEDENT_SLOT}` 在本楼**缺席**（世界未产出该槽事实），"
        f"故回退到裁定保留的**唯一**正向证据代理＝`{Q3_PROXY_SLOT}`。"
        "该槽没有楼级事实（实测均为 sidecar／片段条目），故聚合量词必须显式声明："
        "本内核取 **any_true**，本楼 any_true 取真 ⇒ 詳細調查建議書已在场，"
        "直接见证「有意進行詳細調查」⇒ P 取真，判适用。"
        "（前件只看上述两项；「通知是否已作出」不得用来反推 P，正负两向反推均非法，"
        "详见 Q3 规则的显式排除段。）"
        "（判据情形 2）（片段清单是抽样产物，不作判据。）"
    )


def _q3_reason_false() -> str:
    return (
        "§2.1.3(n) 的前件 P：有意進行詳細調查。"
        f"前件槽 `{Q3_ANTECEDENT_SLOT}` 于本楼取假——新池该槽由世界侧**直接采样**，"
        "负判读的是世界态本身，**不是**从「通知是否已作出」反推得来，故负判合法。"
        "（旧池没有该槽、只有建议书代理，那时任何负判都非法；限制随前件槽落地解除，"
        "不是放宽标准，是证据换了一等。）"
        "⇒ P 取假 ⇒ 该条款于本楼不适用（结构不适用：不进召回分母，走精确率侧反向闸）。"
        "（判据情形 2）（片段清单是抽样产物，不作判据。）"
    )


def _q3_reason_pending() -> str:
    return (
        "§2.1.3(n) 的前件 P：有意進行詳細調查。"
        f"前件槽 `{Q3_ANTECEDENT_SLOT}` 在本楼**缺席**（世界未产出该槽事实）；"
        f"裁定保留的唯一正向证据代理 `{Q3_PROXY_SLOT}`（聚合量词＝ any_true）**亦缺席**。"
        "⇒ 正向证据双缺；而以「通知是否已作出」反推 P 属非法推理（正负两向均非法，"
        "详见 Q3 规则的显式排除段）⇒ **阅卷者判不了**，记 unknown_pending："
        "既不进召回分母、也不进精确率侧分母，单独计数出报表。"
        "🔴 这是**真值侧不可判**，不是系统缺陷，不得据此给系统记分或扣分。"
        "（判据情形 2）（片段清单是抽样产物，不作判据。）"
    )


def q3_applicable(
    intended: bool | None,
    proposal_any_true: bool | None,
) -> tuple[str, str]:
    """§2.1.3(n) 的适用性判定。返回 ``(applicable 三态, reason)``。

    参数
    ----
    intended
        该楼 ``procedure.investigation.detailed.intended`` 的取值；
        ``None``＝世界未产出该槽事实（缺席），**不是** False。
    proposal_any_true
        该楼 ``artifact.proposal.detailed_investigation`` 的 **any_true** 聚合；
        ``None``＝该槽在本楼无任何条目。

    🔴 签名里**没有 notified 形参**，这不是省略，是本函数的核心性质：
       被裁删的 ``ELIF NOTIFIED is true`` 分支在这里**不可能被写回来**——
       没有入口就没有反推。单测用 :func:`inspect.signature` 把这条钉死。
    """
    for name, value in (("intended", intended), ("proposal_any_true", proposal_any_true)):
        if value is not True and value is not False and value is not None:
            # 只认 True/False/None。挡的是「非空字符串被 Python 真值判断当成真」
            # 这一类静默退化——本仓已实测过的形状。
            raise TypeError(f"{name} 只接受 True / False / None，收到 {value!r}")

    if intended is True:
        return APPLICABLE_TRUE, _q3_reason_true_by_intended()
    if intended is False:
        return APPLICABLE_FALSE, _q3_reason_false()
    if proposal_any_true is True:
        return APPLICABLE_TRUE, _q3_reason_true_by_proposal()
    return APPLICABLE_PENDING, _q3_reason_pending()


# ── 生成完自检 ────────────────────────────────────────────────────────────


def verify_truth_face_invariants(
    rows: Iterable[dict],
    world_q3_inputs: Mapping[str, tuple] | None = None,
) -> list[str]:
    """把 §2.1 两条规则跑成断言，返回**违例清单**（空 list ＝ 过）。

    这是步 B3 的自检入口：真值面生成完立刻喂全部行，非空即中止落盘。
    也可只喂 Q2／Q3 射程行（既有真值文件复核就该这么用——其余行归别的裁定，
    不在本规则射程内）。

    参数
    ----
    rows
        真值行 dict 序列（schema ``applicable_normative_item_truth_v1``）。
    world_q3_inputs
        可选。``building_id -> (intended, proposal_any_true)``。给了就对每一条 Q3 行
        **复算** :func:`q3_applicable` 并断言值一致——这是把「规则」与「落盘结果」
        对上的那一刀；不给则只做与世界无关的结构断言。

    检查项
    ------
    Q2（``normative_item_id`` 前缀命中 :data:`Q2_ITEM_PREFIX`）：
      applicable 恒 true ／ 情形标记恒 1（两种承载形态都认）／
      reason 不以「排除依据」开头 ／ reason 不含「判不适用」。
    Q3（``normative_item_id`` == :data:`Q3_ITEM_ID`）：
      applicable ∈ 三态 ／ reason 不含「判不适用」／
      reason 不把被禁两槽**当依据**用 ／（给了世界输入则）与复算值一致。

    射程说明（有意为之，不是漏检）
    ----------------------------
    「不得引用被禁槽作依据」这条只对 **Q3 行**生效。它的规范效力来自
    「禁止反推 §2.1.3(n) 的前件 P」——**别的规范项引用这两槽不受该裁定约束**。
    实测反例：``mbis.cop2023.s4_2_3.no_di_before_ba_endorsement`` 族的行在
    「世界确实产出意向谓词」一句里点名这两槽，用途是**订正世界供给的事实陈述**，
    且该行同时明写「禁止性规范没有这个前件」——把它判违例是拿一条没授权的规则去管
    别人的地界。故本函数按 Q3 射程判，并把这个边界写在这里，防后来者「顺手扩大」。
    """
    violations: list[str] = []
    world = world_q3_inputs or {}

    for index, row in enumerate(rows, start=1):
        item_id = row.get("normative_item_id")
        building_id = row.get("building_id")
        reason = row.get("reason") or ""
        where = f"#{index} {building_id}／{item_id}"
        state = decode_applicable(row.get("applicable"))

        is_q2 = isinstance(item_id, str) and item_id.startswith(Q2_ITEM_PREFIX)
        is_q3 = item_id == Q3_ITEM_ID
        if not (is_q2 or is_q3):
            continue

        if state is None:
            violations.append(
                f"{where}：applicable 取值非法 {row.get('applicable')!r}"
                f"（只许 True／False／{APPLICABLE_PENDING!r}）"
            )

        if FORBIDDEN_REASON_PHRASE in reason:
            violations.append(f"{where}：reason 含禁语「{FORBIDDEN_REASON_PHRASE}」")

        if is_q2:
            if state is not None and state != APPLICABLE_TRUE:
                violations.append(
                    f"{where}：Q2 族 applicable 必须为 true，实得 {state}"
                    "（§3.1.1 唯一前件恒真，列举项不是前件）"
                )
            circumstances = _circumstances(reason)
            if circumstances != {str(Q2_CIRCUMSTANCE)}:
                violations.append(
                    f"{where}：Q2 族情形标记必须恒为 {Q2_CIRCUMSTANCE}，"
                    f"reason 实得 {sorted(circumstances) or '（无标记）'}"
                )
            if reason.startswith(FORBIDDEN_REASON_PREFIX):
                violations.append(
                    f"{where}：Q2 族 reason 不得以「{FORBIDDEN_REASON_PREFIX}」开头"
                )

        if is_q3:
            for sentence in _cited_as_evidence(reason):
                violations.append(
                    f"{where}：reason 把被禁槽当依据用（决议 §二／§三.1）——"
                    f"涉事句「{sentence}」"
                )
            if building_id in world:
                supplied = world[building_id]
                if not isinstance(supplied, tuple) or len(supplied) != 2:
                    violations.append(
                        f"{where}：world_q3_inputs 形态非法 {supplied!r}"
                        "（须为 (intended, proposal_any_true) 二元组）"
                    )
                    continue
                expected, _ = q3_applicable(*supplied)
                if state != expected:
                    violations.append(
                        f"{where}：Q3 复算不一致——世界输入 {supplied!r} 应得 {expected}，"
                        f"落盘为 {state}"
                    )

    return violations
