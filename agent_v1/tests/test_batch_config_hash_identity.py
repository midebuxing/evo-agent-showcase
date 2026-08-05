

def test_fragment_count_enters_identity_when_non_default() -> None:
    """🔴 `fragment_count_per_building` 必须进身份键（codex 审核门 2026-07-30）。

    它是函数签名上公开、且真被消费的旋钮（`validation.py:267` 形参、`:347` 传递），
    却一直不在哈希载荷里 ⇒ `=4` 与 `=8` 生成**不同世界内容**却拿到**同一个
    `deterministic_key`**。这是当前可调参数造成的确定性同键，不是未来风险。

    同时锁**缺省等价**：等于默认值 4 时不进载荷 ⇒ 既有池的键逐位不变。
    """
    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "wg_validation", root / "src/workflow_engine/worldgen/validation.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    src = (root / "src/workflow_engine/worldgen/validation.py").read_text(encoding="utf-8")
    # 载荷构造段必须出现该键的条件登记
    assert 'fragment_count_per_building' in src.split("_batch_hash_payload = {")[1][:1200], \
        "fragment_count_per_building 没有登记进 _batch_hash_payload ⇒ 不同世界会同键"
    # 且必须是「偏离默认才进」的缺省等价写法，不许无条件入载荷（那会改掉既有池的键）
    assert "if fragment_count_per_building != 4:" in src, \
        "必须写成偏离默认才进载荷，否则既有池的 deterministic_key 会变、旧批不可复现"


def test_different_fragment_count_yields_different_deterministic_key(tmp_path) -> None:
    """🔴 行为级断言：`=4` 与 `=8` 必须得到**不同**的 `deterministic_key`。

    上一条测试是**源码级字符串检查**，它证明不了真实哈希路径的行为——
    codex 审核门 2026-07-30 正好抓过同形状的问题：
    「哈希测试复制了一份本地载荷构造，没有调用生产哈希路径；
      即使生产代码漏掉新开关，测试仍可能通过」。
    ⇒ 这条走**真生产入口** `run_worldgenerator_fullcoverage_framework_v2`，
      只跑 2 栋（够快），比两次的 `deterministic_key`。

    同时反向锁**缺省等价**：两次都用默认 4 ⇒ 键必须**逐位相同**。
    """
    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "wg_validation2", root / "src/workflow_engine/worldgen/validation.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    def key(frag_n: int, tag: str) -> str:
        res = m.run_worldgenerator_fullcoverage_framework_v2(
            output_dir=tmp_path / tag, count=2, seed=7,
            fragment_count_per_building=frag_n)
        return res["deterministic_key"]

    k4a, k4b, k8 = key(4, "a"), key(4, "b"), key(8, "c")
    assert k4a == k4b, "同参数两次跑出不同键 ⇒ 生成不确定，比对无意义"
    assert k4a != k8, (
        "fragment_count_per_building=4 与 =8 生成不同世界内容，"
        f"却拿到同一个 deterministic_key（{k4a}）⇒ 静默同键")
