"""P8：预注册台账（人群契约）的结构契约（2026-08-06，换池前置第八项）。

## 这份文件锁什么

`决议_换池前置_20260805.md` §二 P8 把预注册收缩为核心字段人群契约：
expectation_id / table_kind / assertion_kind / 单位 / **可执行人群查询＋成员 digest** /
三池角色 / producer / expected 与 mismatch_action；性质断言配四类桥接
（非空性 / 成员摘要 / 分区守恒 / 结构基数）。

台账本体在 `agent_v1/experiments/prereg/预注册台账_换池批_v1.json`，
执行器是 `agent_v1/scripts/preregistration_dry_run.py`。**分工与 P4 契约测试同构**：
测试锁口径与结构，台账锁数字并承担沿革。数字漂移 ⇒ 干跑标
`INVALIDATED_BEFORE_RUN`（不进这里）；**结构塌掉 ⇒ 这里红**（比如有人把
SUPERSEDED 链解开、把 WAITING 条目的所等产物删了、把四桥拆了）。

## 判据单一真源

一律走执行器的装载函数（`load_ledger` / `_expectation_from_entry` /
`run_expectation`），不在测试里复制枚举或判据——本仓成例：
内联逻辑 + 复制式测试 = 假的变异验证。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import preregistration_dry_run as dry_run  # noqa: E402

DIGEST_RE = re.compile(r"^[0-9a-f]{16}$")
BRIDGE_KEYS = ("non_emptiness", "membership_digest",
               "partition_conservation", "structural_cardinality")


@pytest.fixture(scope="module")
def ledger() -> dict:
    return dry_run.load_ledger()


@pytest.fixture(scope="module")
def entries(ledger) -> list[dict]:
    return ledger["entries"]


@pytest.fixture(scope="module")
def by_id(entries) -> dict[str, dict]:
    return {e["expectation_id"]: e for e in entries}


def _chain_head_id(by_id: dict[str, dict], start_id: str) -> str:
    """走 ``superseded_by`` 链取 ACTIVE 链头（DEBT-100：不写死后缀）。

    P8 纪律要求「换锚只能新增带沿革条目、不许原位改值」⇒ 链头必然随每次换锚前移。
    测试把链头写死成常量（``-R2``）与它要保护的纪律互相矛盾--故改为逐条走链。
    """
    cur = start_id
    while by_id[cur].get("superseded_by"):
        cur = by_id[cur]["superseded_by"]
    return cur


# ── 台账整体形状 ────────────────────────────────────────────────────────


def test_ledger_migrated_26_plus_4_replacements(entries):
    """26 条迁移 ＋ 4 条替代 ＋ 1 条期限锚补立 ＝ 31 条；id 唯一。

    P4 干跑首跑的底片是 26 条（OK 12 / INVALIDATED 4 / BLOCKED 9 / 缺 1）；
    P8 迁移全量保留并为 4 条失效者各立一条 `-R2` 替代。
    2026-08-06（#23L2L3+37 单）：期限锚案补立 `DEADLINE-C-EMISSION`
    （清 P4 尾巴 3 的欠账），旧欠账标记 `DEADLINE-NO-PREREG` 转 SUPERSEDED
    双向链接。缩水 ⇒ 有条目被删（P8 禁止：沿革必须留在台账里）。
    """
    ids = [e["expectation_id"] for e in entries]
    # 2026-08-06 换池批步 A2.1：REGENERATED_POOL 六条以「同查询重算重立」形态
    # 立池 v2 新条目（-POOLV2 后缀，WAITING 等池 v2 批产物；旧六条原地标沿革
    # 不改值），31 → 37。缩水仍禁止（沿革必须留在台账里）。
    # 2026-08-07 真值 v2 单次解封事务 §二.5：新增三条 `TRUTHV2-*` 登记
    # （生成器身份 / 真值文件身份 / 人工裁定记录指针），37 → 40。
    # ⚠️ 这三条是**新增**不是替代——`P4-TRUTH-3STATE` 锚 v1 真值、仍然有效，
    # 两份真值锚不同的池（building_id 互不相交），同时 ACTIVE 是对的。
    # 2026-08-07 官方审核门 MF-1 清偿：生成器源码改动 ⇒ `TRUTHV2-PRODUCER` 的脚本
    # 哈希失配（**该闸当天就咬住了自己单子的落码**），按沿革协议立
    # `TRUTHV2-PRODUCER-R2` 替代、旧行转 SUPERSEDED，40 → 41。
    # 2026-08-07 D9 正单清 SF-1／O-2：生成器源码**第二次**改动 ⇒ R2 的脚本哈希
    # 失配（同一道闸，同一天，第二次咬住落码），立 `TRUTHV2-PRODUCER-R3`
    # 替代、R2 转 SUPERSEDED，41 -> 42。⇒ 生成器重锚链现为三环。
    # 2026-08-07 E 簇决策门落改：apply 脚本修改真值文件 9 行（零散2 ＋ 装配缺陷族
    # 8 行，含尾巴#4），生成器本身未改但真值文件已变 ⇒ `TRUTHV2-SHA256` 重立 R2
    # （旧 sha 606b03c2… 转 SUPERSEDED）、`TRUTHV2-PRODUCER` 重立 R4
    # （生成器 sha 不变但生产者链变更），42 -> 44。
    # 2026-08-07 行尾事故修复：上一条里那个 apply 脚本用文本模式写盘
    # （`io.open(..., 'w')`，Windows 换行翻译），把真值 2,780 行全变成 CRLF ——
    # 内容层一格没动，但文件哈希已非生成器原生写盘形。整文件 CRLF→LF 归一 ⇒
    # `TRUTHV2-SHA256-R2`（9cfff2a4…）转 SUPERSEDED、立 `-R3`（7cbda756…），
    # 44 -> 45。⚠️ R2→R3 **内容层零改动**，2,780 行逐行 JSON 对象完全相同。
    # 2026-08-07 E 簇回灌单：把那 9 行改判**回灌进生成器输入**
    # （`final_grid.json` 新段 E_CLUSTER_RULINGS），清掉 `--check` 的最后一条红。
    # 两处权威随之换哈希 ⇒ 两条沿革替代：`TRUTHV2-ADJUDICATION-RECORDS` 重立 -R2
    # （final_grid a1c39697… → 643dafe2…，叙述记录指针 5 → 7 份）、
    # `TRUTHV2-PRODUCER` 重立 -R5（生成器加了「沿革注记排末尾」渲染），45 -> 47。
    # ⚠️ `TRUTHV2-SHA256` **不加环**：真值文件逐字节未变（仍 7cbda756…），
    # 本单改的是它的上游与生产者，产物没动。
    # 🔴 DEBT-100（2026-08-08）：计数改「不减少」--P8 纪律只增不删，链头随换锚前移，
    # 写死字面量会随下次换锚失效。floor 取最后一次绿时的计数。
    assert len(ids) >= 47
    assert len(set(ids)) == len(ids)
    assert sum(1 for i in ids if i.endswith("-R2")) >= 7
    assert sum(1 for i in ids if i.endswith("-R3")) >= 2
    assert sum(1 for i in ids if i.endswith("-R4")) >= 1
    assert sum(1 for i in ids if i.endswith("-R5")) >= 1
    assert sum(1 for i in ids if i.endswith("-POOLV2")) >= 6
    assert sum(1 for i in ids if i.startswith("TRUTHV2-")) >= 10


def test_every_entry_loads_through_the_executor(entries):
    """每条都能被执行器装载：枚举合法、query_key 可分派。

    判据不在测试里复制——`_expectation_from_entry` 本身就会对
    table_kind / assertion_kind / entry_status / query_key 逐一拒绝非法值。
    """
    for entry in entries:
        exp = dry_run._expectation_from_entry(entry)
        assert exp.expectation_id == entry["expectation_id"]


def test_executor_expectations_come_from_the_ledger(entries):
    """执行器的 EXPECTATIONS 就是台账（数量与 id 序一致）——不存在第二份条目表。"""
    assert [x.expectation_id for x in dry_run.EXPECTATIONS] == [
        e["expectation_id"] for e in entries]


def test_invalid_enum_is_rejected_loudly(by_id):
    """变异验证的执行体：枚举外取值必须被装载器当场拒绝，不许静默收下。"""
    bad = dict(by_id["P4-TRUTH-3STATE"])
    bad["table_kind"] = "TRUTH_SIDE"  # 旧三分类的第三值——P8 收缩后不再合法
    with pytest.raises(ValueError, match="table_kind"):
        dry_run._expectation_from_entry(bad)
    bad2 = dict(by_id["P4-TRUTH-3STATE"])
    bad2["assertion_kind"] = "RATIO"  # 旧枚举——已映射进 POINT_COUNT
    with pytest.raises(ValueError, match="assertion_kind"):
        dry_run._expectation_from_entry(bad2)


# ── P8 核心字段：人群查询 / digest / 三池角色 / producer / mismatch_action ──


def test_core_fields_present_on_every_entry(entries):
    for entry in entries:
        eid = entry["expectation_id"]
        assert entry.get("unit"), eid
        assert entry.get("mismatch_action"), eid
        query = entry.get("population_query") or {}
        assert query.get("status") in {"EXECUTABLE", "PENDING_QUERY"}, eid
        assert query.get("definition"), eid
        producer = entry.get("producer") or {}
        assert producer.get("record"), eid
        roles = entry.get("pool_roles") or {}
        assert set(roles) == {"world", "truth", "evaluation"}, eid
        assert all(roles.values()), eid
        assert "population_membership_digest" in entry, eid


def test_active_entries_have_executable_queries(entries):
    """ACTIVE ⇒ 查询必须是 EXECUTABLE 且 query_key 真的可分派。

    『把 entry_status 扳成 ACTIVE 而不接查询』由执行器的 `pending` 安全网
    兜底（照样 BLOCKED），这里把它挡在更早的一层：台账里就不许这么写。
    """
    for entry in entries:
        if entry["entry_status"] != "ACTIVE":
            continue
        query = entry["population_query"]
        assert query["status"] == "EXECUTABLE", entry["expectation_id"]
        assert query["query_key"] != "pending", entry["expectation_id"]


def test_digest_is_hex_or_declared_absence(entries):
    """digest 三态：16 位十六进制（已冻结）/ PENDING_QUERY（待接）/ N/A（说明理由）。

    ACTIVE 条目不许挂 PENDING_QUERY——能执行就必须当场算（P8：
    『成员 digest 能算的当场算，不能算的标 PENDING_QUERY』）；
    N/A 必须带括号理由，裸 N/A 不算说明。
    """
    for entry in entries:
        eid = entry["expectation_id"]
        digest = entry["population_membership_digest"]
        assert isinstance(digest, str) and digest, eid
        if DIGEST_RE.match(digest):
            continue
        if digest == "PENDING_QUERY":
            assert entry["entry_status"] == "WAITING", (
                f"{eid}：ACTIVE/SUPERSEDED 条目不许把 digest 留成 PENDING_QUERY")
            continue
        assert digest.startswith("N/A（") and digest.endswith("）"), (
            f"{eid}：digest 既不是 16 位十六进制也不是 PENDING_QUERY，"
            f"那就必须是带理由的 N/A（…）——现在是 {digest!r}")


# ── 沿革链：4 条 INVALIDATED 的替代 ─────────────────────────────────────


#: 原始条目的 expected（不随换锚变--P8 纪律：旧行留旧值）。键＝链首 id，
#: 值＝该条目创建时冻的 expected。链头走 ``_chain_head_id`` 取，不写死后缀。
REANCHORED = {
    "P4-COV-COVERED": 1816,
    "P4-COV-MISSED": 524,
    "P4-COV-RECALL": 0.7761,
    "P4-PRECISION-ANOMALY": 134,
}


def test_superseded_chain_is_bidirectional_and_values_preserved(by_id):
    """旧条目 superseded_by -> 新条目；新条目 supersedes -> 旧条目；新旧值各归各位。

    这就是『不许原位改值』的机器形状：旧行 expected 必须还是旧值（1816/524/
    0.7761/134），新值只许出现在新条目上。有人把旧行的数字改成新值 ⇒ 这里红。

    🔴 DEBT-100（2026-08-08）：断言对象从写死的 ``-R2`` 改为走 ``supersedes``/
    ``superseded_by`` 链取 ACTIVE 链头--P8 纪律要求链头随换锚前移，写死后缀
    会随下次换锚失效。链上每一环都验双向链接与 provenance.old_expected。
    """
    for old_id, old_val in REANCHORED.items():
        # 原始条目：SUPERSEDED、留旧值
        old = by_id[old_id]
        assert old["entry_status"] == "SUPERSEDED", old_id
        assert old["expected"] == old_val, (
            f"{old_id}：沿革条目的旧值被人改了（应为 {old_val}）")
        # 走整条链：每环双向链接、新行 provenance.old_expected 记上一环的 expected
        cur_id = old_id
        while by_id[cur_id].get("superseded_by"):
            nxt_id = by_id[cur_id]["superseded_by"]
            cur, nxt = by_id[cur_id], by_id[nxt_id]
            assert cur["superseded_by"] == nxt_id, cur_id
            assert nxt["supersedes"] == cur_id, nxt_id
            assert (nxt.get("provenance") or {}).get("old_expected") == cur["expected"], (
                f"{nxt_id}：provenance.old_expected 与上一环 expected 不符")
            cur_id = nxt_id
        # 链头恰一条 ACTIVE
        head_id = cur_id
        assert by_id[head_id]["entry_status"] == "ACTIVE", head_id
        assert not by_id[head_id].get("superseded_by"), head_id
        # 首环替代条目（-R2）必须注明新锚出处 #23 L1
        first_replacement = by_id[old_id]["superseded_by"]
        assert "#23 L1" in by_id[first_replacement]["evidence_tree"], (
            f"{first_replacement}：替代条目必须注明新锚出处（#23 L1 改阅卷器后）")


def test_superseded_entries_never_execute(by_id):
    """沿革条目不执行：run_expectation 直接给 SUPERSEDED，连查询都不进。

    走生产函数验证（不是读字段自嗨）：旧条目即使带着可执行查询，
    执行器也必须在查询之前短路——否则『旧值 1816 ≠ 当期 1809』会被
    误报成一条新的 INVALIDATED，账就重复记了。
    """
    exp = dry_run._expectation_from_entry(by_id["P4-COV-COVERED"])
    outcome = dry_run.run_expectation(exp, skip_slow=False)
    assert outcome.status == dry_run.SUPERSEDED
    assert outcome.actual is None


# ── WAITING：9 条阻断的处置形状（2026-08-06 收口后 WAITING 归零） ────────

#: 2026-08-06 台账收口单（`实施记录_台账收口_20260806.md`）把 P8 时的 7 条
#: WAITING 全部转 ACTIVE：三条 SWAP-*（kimi 重建重放脚本评审扶正为
#: `scripts/replay_yi12_building_granularity.py`）、D33-YI11（#33 §四订正后
#: 口径 12 条 (q) 腿）、两条 SWAP-YI-*（#33 三线审核关案后金丝雀内存回退重放）、
#: D29-BA-GRID（注册表释放＋R1 收口后台账直读）。
FORMERLY_WAITING = (
    "D33-YI11-SHARED-READING",
    "SWAP-YI12-AMBIGUOUS",
    "SWAP-D8-INTRA-BUILDING",
    "SWAP-BING-THREE-ANCHORS",
    "SWAP-YI-APPLICABLE",
    "SWAP-YI-EVIDENCE",
    "D29-BA-GRID-ZERO-ROWS",
)


def test_waiting_entries_name_their_awaited_artifact(entries):
    """WAITING 条目必须指认所等产物——『在等』而不说等什么，等于没处置。

    P4 干跑的 9 条 BLOCKED 在 P8 台账里的去向：2 条接上可执行查询转 ACTIVE
    （D33-FLIP-SET / D33-ARTIFACT-VIOLATED），7 条标 WAITING 并逐条指认；
    2026-08-06 收口单把那 7 条全部转 ACTIVE（见 FORMERLY_WAITING）⇒
    当前 WAITING 应为 0。本断言对**将来新增**的 WAITING 条目仍然生效。
    """
    waiting = [e for e in entries if e["entry_status"] == "WAITING"]
    # 2026-08-06 换池批步 A2.1：六条 -POOLV2 以 WAITING 立账（所等产物＝池 v2
    # 批产物）。**同日破封批 D10 回填后全部转 ACTIVE ⇒ 当前 WAITING 归零**：
    # 池 v2 两个 50 栋批已产出，六条按同查询在批产物上重算、补实测值与 digest，
    # 六条冻结批旧条目随之转 SUPERSEDED（沿革协议，见 POOLV2_REANCHORED）。
    # 本断言对**将来新增**的 WAITING 条目仍然生效。
    assert [e["expectation_id"] for e in waiting] == []
    for entry in waiting:  # WAITING 的形状约束：必须指认所等产物
        assert len(entry.get("waiting_on") or "") >= 20, entry["expectation_id"]


def test_waiting_entries_still_block_the_swap(by_id):
    """WAITING 不是放行——执行器给 WAITING_ON_NAMED_ARTIFACT，退出码归 1 那边。

    收口后台账里没有活的 WAITING 条目，改用合成条目走生产装载/执行路径
    （行为契约不许随收口消失：谁再立 WAITING，执行器必须照样阻断）。
    """
    entry = dict(by_id["D29-BA-GRID-ZERO-ROWS"])
    entry["expectation_id"] = "SYNTHETIC-WAITING"
    entry["entry_status"] = "WAITING"
    entry["waiting_on"] = "所等产物＝合成测试指认的一件尚未落地的产物（形状约束用）"
    exp = dry_run._expectation_from_entry(entry)
    outcome = dry_run.run_expectation(exp, skip_slow=False)
    assert outcome.status == dry_run.WAITING
    assert outcome.reason == exp.waiting_on


#: 2026-08-06 破封批 D10：六条 REGENERATED_POOL 在池 v2 上重算重立，
#: 旧条目按台账沿革协议转 SUPERSEDED（各自 note 里早就写死「D10 回填后按总工单
#: §三对接表转 SUPERSEDED」）。旧值留在旧行、新值只出现在新行——与 4 条 `-R2`
#: 同一形状，只是这次的理由是换池而不是改阅卷器。
POOLV2_REANCHORED = {
    "SWAP-YI12-AMBIGUOUS": "SWAP-YI12-POOLV2",
    "SWAP-D8-INTRA-BUILDING": "SWAP-D8-POOLV2",
    "SWAP-BING-THREE-ANCHORS": "SWAP-BING-POOLV2",
    "SWAP-YI-APPLICABLE": "SWAP-YI-APPLICABLE-POOLV2",
    "SWAP-YI-EVIDENCE": "SWAP-YI-EVIDENCE-POOLV2",
    "DEADLINE-C-EMISSION": "DEADLINE-C-EMISSION-POOLV2",
}


def test_unblocked_entries_carry_their_provenance(by_id):
    """从 BLOCKED/WAITING 解锁过的条目必须留下解锁沿革（凭什么转的）。

    ⚠️ 2026-08-06 破封批后，`FORMERLY_WAITING` 里的五条已随换池转 SUPERSEDED
    （它们的池 v2 重立条目接班）——**解锁沿革不因转沿革而消失**，故这里断的是
    「provenance 还在、digest 还在」，状态则允许 ACTIVE 或 SUPERSEDED。

    digest 规矩：全部 16 位十六进制，唯 SWAP-YI-EVIDENCE 例外——期望人群是
    空集（evidence satisfied 0 条），digest 必须是带理由的 N/A（…）。
    """
    for eid in ("D33-FLIP-SET", "D33-ARTIFACT-VIOLATED") + FORMERLY_WAITING:
        entry = by_id[eid]
        expected_status = (
            "SUPERSEDED" if eid in POOLV2_REANCHORED else "ACTIVE")
        assert entry["entry_status"] == expected_status, eid
        assert "unblocked" in (entry.get("provenance") or {}), eid
        digest = entry["population_membership_digest"]
        if eid == "SWAP-YI-EVIDENCE":
            assert digest.startswith("N/A（"), eid
        else:
            assert DIGEST_RE.match(digest), eid


def test_poolv2_reanchor_chain_is_bidirectional_and_old_values_preserved(by_id):
    """换池重立的沿革链：旧行转 SUPERSEDED 且**旧值原封不动**，新行锚池 v2 批。

    这是「不许原位改值」在换池这一幕的机器形状。特别防两件事：
    ① 有人图省事把旧行的 `expected` 直接改成新池数字（沿革就没了）；
    ② 新行没写 `anchor_batch`（那它就没有池身份，数字离开池无法解释）。

    🔴 DEBT-100（2026-08-08）：断言对象从写死的 ``-POOLV2`` 改为走链取 ACTIVE 链头。
    """
    for old_id in POOLV2_REANCHORED:
        # 走整条链：每环双向链接
        cur_id = old_id
        while by_id[cur_id].get("superseded_by"):
            nxt_id = by_id[cur_id]["superseded_by"]
            cur, nxt = by_id[cur_id], by_id[nxt_id]
            assert cur["entry_status"] == "SUPERSEDED", cur_id
            assert cur["superseded_by"] == nxt_id, cur_id
            assert nxt["supersedes"] == cur_id, nxt_id
            cur_id = nxt_id
        # 链头 ACTIVE
        head_id = cur_id
        head = by_id[head_id]
        assert head["entry_status"] == "ACTIVE", head_id
        assert not head.get("superseded_by"), head_id
        old = by_id[old_id]
        assert old["expected"] != head["expected"] or old_id in (
            "SWAP-YI-EVIDENCE", "SWAP-BING-THREE-ANCHORS",
            "DEADLINE-C-EMISSION"), (
            f"{old_id}：新旧 expected 完全相同--要么没回填，要么原位改了值")
        assert head.get("anchor_batch"), f"{head_id}：池 v2 条目必须写明锚批"
        assert "poolv2" in head["anchor_batch"], head_id
        # 新行的实测值不许留 PENDING 占位（那等于「转 ACTIVE 但没回填」）。
        assert "PENDING" not in json.dumps(head["expected"], ensure_ascii=False), (
            f"{head_id}：expected 里还留着 PENDING 占位")


# ── 生成器重锚链（08-07 MF-1 清偿 → 08-07 D9 清 SF-1/O-2） ─────────────

#: 生成器重锚链，**按发生顺序**。每加一环就往后追加一条，别改前面的。
#: 每环写死当时冻的哈希 —— 沿革值一旦被人「顺手更新」，链条就失去证据力。
TRUTHV2_PRODUCER_CHAIN = (
    ("TRUTHV2-PRODUCER", "6102109ad02a397e", None),
    ("TRUTHV2-PRODUCER-R2", "bff281858a1552e0", "MF-1"),
    ("TRUTHV2-PRODUCER-R3", "873e10f3be1483ed", "SF-1"),
    ("TRUTHV2-PRODUCER-R4", "873e10f3be1483ed", "E 簇"),
    ("TRUTHV2-PRODUCER-R5", "e0a5b6ae53fa9bbe", "E 簇回灌"),
)

#: 真值**本体**重锚链，同样按发生顺序、同样每环写死当时冻的哈希。
#: 它与生成器链是两条独立的链：生成器改了不必然改产物（MF-1／D9 两环就没改），
#: 产物改了也不必然改生成器（E 簇是 apply 脚本改的，行尾修复是归一改的）。
#: 第三个元素＝该环 `reanchor_reason` 里必须出现的口令，防「理由被改成别的事」。
TRUTHV2_SHA256_CHAIN = (
    ("TRUTHV2-SHA256", "606b03c2b59d3aee", None),
    ("TRUTHV2-SHA256-R2", "9cfff2a4e88eb347", "E 簇"),
    ("TRUTHV2-SHA256-R3", "7cbda756391f4238", "行尾"),
)


def test_truth_v2_producer_reanchor_chain(by_id):
    """生成器改了 ⇒ 旧行转 SUPERSEDED 留旧哈希、新行带新哈希，双向链接。

    这条闸的价值已经兑现**两次**：MF-1 的落码、D9 的 SF-1/O-2 落码，
    各自在当天把上一环标成 INVALIDATED —— 它不是坏了，是在干活。

    🔴 同时锁一件容易被「顺手补上」的事：**生成器链**那两环的真值产物都逐字节未变
    （只动 CLI 外壳的 blind 护栏时点 / 报错串与路径格式化），故那两次
    `TRUTHV2-SHA256` **不重立**、值不变。重立一个没变的值只会制造与口径无关的
    沿革噪声，而噪声多了就会有人把整条闸关掉。
    ⚠️ 后来真值本体确实重锚了两次（E 簇 9 行改判 / 行尾 CRLF→LF 归一），
    但那两次的触发源都不是生成器 —— 两条链各走各的，见 `TRUTHV2_SHA256_CHAIN`。
    """
    for (old_id, old_sha, _), (new_id, new_sha, reason_token) in zip(
            TRUTHV2_PRODUCER_CHAIN, TRUTHV2_PRODUCER_CHAIN[1:]):
        old, new = by_id[old_id], by_id[new_id]
        assert old["entry_status"] == "SUPERSEDED", old_id
        assert old["superseded_by"] == new_id, old_id
        assert old["expected"]["script_sha256_16"] == old_sha, (
            f"{old_id}：沿革条目的旧哈希被人改了")
        assert new["expected"]["script_sha256_16"] == new_sha, new_id
        assert new["supersedes"] == old_id, new_id
        provenance = new.get("provenance") or {}
        assert provenance.get("old_expected") == old["expected"], new_id
        assert reason_token in provenance.get("reanchor_reason", ""), new_id
        assert "逐字节未变" in provenance.get("product_unchanged", ""), new_id

    # 链尾恰好一条 ACTIVE：多于一条＝有人漏了转 SUPERSEDED，那时两个值同时"有效"。
    active = [eid for eid, _, _ in TRUTHV2_PRODUCER_CHAIN
              if by_id[eid]["entry_status"] == "ACTIVE"]
    assert active == [TRUTHV2_PRODUCER_CHAIN[-1][0]], active
    assert "superseded_by" not in by_id[active[0]]

    # 生产者哈希须与盘上文件当期实测相符——链条不能只是自洽的一串字符串。
    import hashlib  # noqa: PLC0415
    generator = (Path(__file__).resolve().parents[1]
                 / "scripts" / "generate_truth_v2.py")
    assert hashlib.sha256(
        generator.read_bytes()).hexdigest()[:16] == active_expected_sha(by_id)

    # 真值本体重锚链：R1 → R2（E 簇 9 行改判）→ R3（行尾 CRLF→LF 归一）
    for (old_id, old_sha, _), (new_id, new_sha, reason_token) in zip(
            TRUTHV2_SHA256_CHAIN, TRUTHV2_SHA256_CHAIN[1:]):
        old, new = by_id[old_id], by_id[new_id]
        assert old["entry_status"] == "SUPERSEDED", old_id
        assert old["superseded_by"] == new_id, old_id
        assert old["expected"]["truth_sha256"].startswith(old_sha), (
            f"{old_id}：沿革条目的旧哈希被人改了")
        assert new["expected"]["truth_sha256"].startswith(new_sha), new_id
        assert new["supersedes"] == old_id, new_id
        provenance = new.get("provenance") or {}
        assert provenance.get("old_expected") == old["expected"], new_id
        assert reason_token in provenance.get("reanchor_reason", ""), new_id

    # 链尾恰一条 ACTIVE（同生成器链的理由：两个值同时"有效"＝没人知道该引哪个）
    sha_active = [eid for eid, _, _ in TRUTHV2_SHA256_CHAIN
                  if by_id[eid]["entry_status"] == "ACTIVE"]
    assert sha_active == [TRUTHV2_SHA256_CHAIN[-1][0]], sha_active
    assert "superseded_by" not in by_id[sha_active[0]]

    # 🔴 E 簇的取值必须**穿过**行尾修复原样活下来：行尾归一不许顺手动分母。
    # 这三个数从 R2 到 R3 逐位相同，正是「本次只换文件哈希、不换取值」的机器判据。
    sha_entry = by_id["TRUTHV2-SHA256-R3"]
    assert sha_entry["expected"]["applicable"] == 2040
    assert sha_entry["expected"]["not_applicable"] == 548
    assert sha_entry["expected"]["pending"] == 192
    assert (sha_entry["population_membership_digest"]
            == by_id["TRUTHV2-SHA256-R2"]["population_membership_digest"]), (
        "行尾归一改了人群 digest —— 那就不是行尾问题了")

    # 真值哈希须与盘上文件当期实测相符——链条不能只是自洽的一串字符串。
    truth_file = (Path(__file__).resolve().parents[1] / "src"
                  / "evo_agent_baseline" / "eval"
                  / "applicable_normative_item_truth_v2.jsonl")
    raw = truth_file.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sha_entry["expected"]["truth_sha256"]
    # 行尾不变量：原生形＝生成器 render_truth 的纯 LF（CRLF 会静默改哈希）
    assert raw.count(b"\r") == 0, "真值 v2 出现 CR —— 又被文本模式写盘污染了"
    assert raw.count(b"\n") == sha_entry["expected"]["rows"]


def active_expected_sha(by_id) -> str:
    return by_id[
        TRUTHV2_PRODUCER_CHAIN[-1][0]]["expected"]["script_sha256_16"]


#: 裁定记录指针重锚链（冻的是 `final_grid.json` 这份机器权威的哈希）。
#: 第二元素＝该环冻的 final_grid sha16，第三元素＝`reanchor_reason` 里必须出现的口令。
TRUTHV2_ADJUDICATION_CHAIN = (
    ("TRUTHV2-ADJUDICATION-RECORDS", "a1c396976989e4c1", None),
    ("TRUTHV2-ADJUDICATION-RECORDS-R2", "643dafe29ea4a46c", "E 簇回灌"),
)

_FINAL_GRID_REL = (
    "agent_v1/experiments/truth_v2_prep/varying_adjudication/final_grid.json")


def test_truth_v2_adjudication_records_reanchor_chain(by_id):
    """裁定权威产物改哈希 ⇒ 沿革重立，且新环的值必须与盘上文件当期实测相符。

    🔴 这条闸补的是一个具体缺口：E 簇的 9 格改判 2026-08-07 先被 apply 脚本
    直接打在**真值产物**上、没回灌 `final_grid.json`，于是台账里冻的裁定权威
    哈希与真值取值来自两套东西 —— `TRUTHV2-SHA256` 全绿，而
    `generate_truth_v2.py --check` 红了一整天。**冻上游哈希的条目必须自己
    与盘上对账**，否则它只证明「我记下的那个字符串没被人改」。
    """
    import hashlib  # noqa: PLC0415
    for (old_id, old_sha, _), (new_id, new_sha, token) in zip(
            TRUTHV2_ADJUDICATION_CHAIN, TRUTHV2_ADJUDICATION_CHAIN[1:]):
        old, new = by_id[old_id], by_id[new_id]
        assert old["entry_status"] == "SUPERSEDED", old_id
        assert old["superseded_by"] == new_id, old_id
        assert old["expected"]["machine_authority_sha16"][_FINAL_GRID_REL] == old_sha, (
            f"{old_id}：沿革条目的旧哈希被人改了")
        assert new["expected"]["machine_authority_sha16"][_FINAL_GRID_REL] == new_sha, new_id
        assert new["supersedes"] == old_id, new_id
        provenance = new.get("provenance") or {}
        assert provenance.get("old_expected") == old["expected"], new_id
        assert token in provenance.get("reanchor_reason", ""), new_id

    active = [eid for eid, _, _ in TRUTHV2_ADJUDICATION_CHAIN
              if by_id[eid]["entry_status"] == "ACTIVE"]
    assert active == [TRUTHV2_ADJUDICATION_CHAIN[-1][0]], active
    assert "superseded_by" not in by_id[active[0]]

    # 与盘上逐份对账：5 份机器权威一份都不许只活在字符串里
    repo = Path(__file__).resolve().parents[2]
    frozen = by_id[active[0]]["expected"]["machine_authority_sha16"]
    assert set(frozen) == set(dry_run.TRUTH_V2_MACHINE_AUTHORITY), "机器权威清单漂移"
    for rel, sha16 in frozen.items():
        actual = hashlib.sha256((repo / rel).read_bytes()).hexdigest()[:16]
        assert actual == sha16, f"{rel}：盘上 {actual} 与台账 {sha16} 不符"

    # 叙述记录只验在场性（不冻哈希），但「在场」这件事得真成立
    present = by_id[active[0]]["expected"]["narrative_records_present"]
    assert present == sorted(dry_run.TRUTH_V2_NARRATIVE_RECORDS), "叙述记录清单与执行器不符"
    for rel in present:
        assert (repo / rel).is_file(), f"叙述记录不在盘上：{rel}"


# ── 性质断言四桥 ────────────────────────────────────────────────────────


def test_structural_invariants_carry_four_bridges(entries):
    """每条 STRUCTURAL_INVARIANT 都带四桥；桥要么有内容要么 N/A＋理由。"""
    invariants = [e for e in entries
                  if e["assertion_kind"] == "STRUCTURAL_INVARIANT"]
    # D33-ALLOW-STOP / SWAP-BING / D29-BA / DEADLINE-C-EMISSION（2026-08-06 补立）。
    # DEADLINE-NO-PREREG（沿革）2026-08-06 G6 必清 C5 口径整改后改标 UPPER_BOUND
    # （其承载的期限锚位移量化本体是上界口径，原 STRUCTURAL_INVARIANT 系误标），
    # 故从本集合退出：5 → 4。
    # 2026-08-06 换池批步 A2.1：SWAP-BING-POOLV2 / DEADLINE-C-EMISSION-POOLV2
    # 两条池 v2 重立不变量条目入集（桥以 PENDING/预测形先立，D10 回填）：4 → 6。
    # 2026-08-07 真值 v2 落地：TRUTHV2-PRODUCER / TRUTHV2-SHA256 /
    # TRUTHV2-ADJUDICATION-RECORDS 三条同为不变量（身份/哈希断言），6 → 9。
    # 2026-08-07 MF-1 清偿：TRUTHV2-PRODUCER-R2 重锚条目同形入集（沿革旧行仍在），9 → 10。
    # 2026-08-07 D9 正单：TRUTHV2-PRODUCER-R3 同形入集（R2 转沿革但仍在集合里），10 → 11。
    # 2026-08-07 E 簇落改：TRUTHV2-SHA256-R2 ＋ TRUTHV2-PRODUCER-R4，11 → 13。
    # 2026-08-07 行尾修复：TRUTHV2-SHA256-R3 同形入集（R2 转沿革仍在集合里），13 → 14。
    # 2026-08-07 E 簇回灌：TRUTHV2-ADJUDICATION-RECORDS-R2 ＋ TRUTHV2-PRODUCER-R5
    # 两条同形入集（被替代的旧行仍在集合里），14 -> 16。
    # 🔴 DEBT-100（2026-08-08）：改「不减少」--换锚只增不删，写死字面量会失效。
    assert len(invariants) >= 16
    for entry in invariants:
        bridges = entry.get("bridges") or {}
        assert set(bridges) == set(BRIDGE_KEYS), entry["expectation_id"]
        for key, value in bridges.items():
            assert isinstance(value, str) and len(value) >= 8, (
                f"{entry['expectation_id']}.{key}：桥不能是空话")
            if value.startswith("N/A"):
                assert "（" in value, (
                    f"{entry['expectation_id']}.{key}：N/A 必须给理由")


def test_allow_stop_bridges_are_filled_not_na(by_id):
    """唯一当前可全量实测的性质断言（D33-ALLOW-STOP）四桥必须是实的。"""
    bridges = by_id["D33-ALLOW-STOP"]["bridges"]
    assert not any(v.startswith("N/A") for v in bridges.values())
    assert "1243e4c0629e532e" in bridges["membership_digest"]
    assert "0 + 30 == 30" in bridges["partition_conservation"]


# ── digest 参与判定（P8 的机器理由，走生产函数） ─────────────────────────


def test_digest_mismatch_invalidates_even_when_counts_match(monkeypatch, by_id):
    """计数相等而人群换掉 ⇒ INVALIDATED。只登记分母数字挡不住这种失效。

    变异形状：给 D33-VIOLATED 喂一个计数相同、成员不同的假查询。
    """
    entry = by_id["D33-VIOLATED"]
    exp = dry_run._expectation_from_entry(entry)
    assert exp.expected_member_digest  # 台账确实冻结了 digest

    def fake_query(_exp):
        return entry["expected"], ["BLD-SWAPPED-1", "BLD-SWAPPED-2"], {}

    monkeypatch.setitem(dry_run.QUERIES, exp.query, fake_query)
    outcome = dry_run.run_expectation(exp, skip_slow=False)
    assert outcome.status == dry_run.INVALIDATED
    assert "digest 失配" in outcome.reason


# ── `--only` 子集跑（2026-08-07 官方审核门给 D10 的处置建议） ─────────────
#
# 为什么要这个参数：`slow=true` 的 23 条成本极不均匀 —— 8 条 `coverage` 合计约 4 秒
# （按批缓存，只有第一条真跑），5 条 `SWAP-*` 单条 > 9 分钟。没有筛选参数时，
# 想复验那 8 条就得陪跑 35 分钟，结果是**唯一需要复验的那 8 条**被整体跳过。


def test_only_filter_selects_by_prefix(entries):
    """正例：前缀清单选出对应子集，且不多不少。"""
    expectations = [dry_run._expectation_from_entry(e) for e in entries]
    selected, prefixes = dry_run.select_expectations(
        expectations, "P4-COV-,P4-PRECISION-")
    assert prefixes == ["P4-COV-", "P4-PRECISION-"]
    ids = {e.expectation_id for e in selected}
    assert ids == {e.expectation_id for e in expectations
                   if e.expectation_id.startswith(("P4-COV-", "P4-PRECISION-"))}
    # 该族计数从台账派生（DEBT-100：换锚只增不删，链头前移，写死字面量会失效）
    family = [e for e in expectations
              if e.expectation_id.startswith(("P4-COV-", "P4-PRECISION-"))]
    assert len(selected) == len(family)
    active = [e for e in selected if e.entry_status == "ACTIVE"]
    assert len(active) == sum(
        1 for e in family if e.entry_status == "ACTIVE")
    # 不许把同前缀家族外的条目捎进来（`P4-TRUTH-3STATE` 也是 `P4-` 开头）
    assert "P4-TRUTH-3STATE" not in ids


def test_only_filter_without_value_returns_everything(entries):
    """缺省（不给 `--only`）＝全量，且前缀清单为空 ⇒ 打印面不会误标「子集」。"""
    expectations = [dry_run._expectation_from_entry(e) for e in entries]
    selected, prefixes = dry_run.select_expectations(expectations, None)
    assert prefixes == []
    assert len(selected) == len(expectations)


def test_only_filter_raises_on_zero_hit(entries):
    """反例：前缀零命中 ⇒ 抛（exit 2），**不许静默跑一个空集合然后报绿**。

    空人群上的「全部通过」没有意义，而拼错前缀是最容易发生的事
    —— 这正是本仓「判据必须在被筛人群上有意义」反复栽过的形状。
    """
    expectations = [dry_run._expectation_from_entry(e) for e in entries]
    with pytest.raises(dry_run.OnlyFilterError, match="零命中"):
        dry_run.select_expectations(expectations, "P4-CVO-")
    # 多前缀里只要有一个零命中就抛（不许「命中了几条就算数」）
    with pytest.raises(dry_run.OnlyFilterError, match="零命中"):
        dry_run.select_expectations(expectations, "P4-COV-,NO-SUCH-PREFIX")
    with pytest.raises(dry_run.OnlyFilterError):
        dry_run.select_expectations(expectations, " , ")


def test_only_filter_marks_the_run_as_subset_in_json(tmp_path, capsys):
    """子集跑必须在**产物**里自述是子集 —— 只看 outcomes 全 OK 会把子集读成全量。"""
    out = tmp_path / "only.json"
    code = dry_run.main(["--only", "TRUTHV2-", "--json", str(out)])
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    # 10 ＝ 三条落地登记 ＋ 生成器重锚链的 `-R2`／`-R3`／`-R4`／`-R5`
    #      ＋ 真值哈希重锚链的 `-R2`（E 簇 9 行）／`-R3`（行尾 CRLF→LF 归一）
    #      ＋ 裁定记录指针重锚链的 `-R2`（E 簇回灌，final_grid 换哈希）
    #      （沿革旧行不删、仍在集合内 -- P8「沿革必须留在台账里」的直接后果）
    assert payload["selection"] == {
        "only": "TRUTHV2-", "prefixes": ["TRUTHV2-"],
        "selected_count": 10, "is_subset": True, "skip_slow": False}
    assert len(payload["outcomes"]) == 10
    printed = capsys.readouterr().out
    assert "不构成「全量 exit 0」" in printed


def test_only_filter_zero_hit_exits_two_from_main(capsys):
    """端到端：零命中从 `main()` 返回 2（前提不成立），不是 0 也不是 1。"""
    assert dry_run.main(["--only", "P4-CVO-"]) == 2
    assert "前提不成立" in capsys.readouterr().err
