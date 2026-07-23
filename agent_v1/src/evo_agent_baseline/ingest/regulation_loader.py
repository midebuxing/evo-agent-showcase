"""regulation loader：法规原文 markdown → RegulationClause（spec §4.4 + §3.4.1）。

把 4 份法规 markdown 按标题层级切分为 `(:RegulationClause)`，灌入法规-Skills 侧 KG。

实现的 spec 章节：
- §3.4.1 RegulationDocument / RegulationClause 节点 + PARENT_OF / NEXT_CLAUSE 关系；
- §4.4.1 markdown clause 切分（按 markdown 标题正则，clause text 到下一同级/更高级标题前）；
- §4.4.2 4 份文件的 document_id 映射；
- §4.4.3 text_hash = sha256(canonical_text)；baseline 无 embedding 仍可用全文索引。

rule-blind 红线只属 W0/W1（见 memory）；法规原文是 agent-visible 事实源（spec §2.1），
regulation loader 正常加载，不受 blind 约束。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from evo_agent_baseline.ingest._graphspec import EdgeSpec, GraphBatch, NodeSpec
from evo_agent_baseline.ingest.guard import AuditLog

# §4.4.2 文件名 → document_id 映射。
DOCUMENT_ID_MAP: Dict[str, str] = {
    "MBIS_CoP_2023.md": "MBIS_CoP_2023",
    "MBIS_MWIS_CoP_2012_Legacy.md": "MBIS_MWIS_CoP_2012_Legacy",
    "MBIS_MWIS_Operation_Note.md": "MBIS_MWIS_Operation_Note",
    "PNBI10_CoP_2023.md": "PNBI10_CoP_2023",
}

# §4.4.1 标题正则：1~6 个 # + 空格 + 标题文本。
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# 从标题里抽前导章节号 / slug 的正则（§4.4.1 extract_leading_section_number_or_slug）。
# 优先匹配：数字点号链（2.1.3）、可带括号字母后缀（(o)）、附录 / 表号等。
_SECTION_NUMBER_RE = re.compile(r"^\s*((?:\d+\.)*\d+(?:\([a-zA-Z0-9]+\))?)")
_SECTION_PAREN_RE = re.compile(r"^\s*(\([a-zA-Z0-9]+\))")


def sha256_text(text: str) -> str:
    """对文本算 sha256（spec §4.4.3 text_hash）。

    Args:
        text: 输入文本。

    Returns:
        十六进制 sha256 摘要。
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify_heading(heading: str) -> str:
    """把标题文本压成 slug（无章节号时的 section_id 兜底）。

    Args:
        heading: 标题文本。

    Returns:
        小写、非字母数字转下划线、截断的 slug。
    """
    slug = re.sub(r"[^0-9a-zA-Z一-鿿]+", "_", heading.strip().lower())
    slug = slug.strip("_")
    return slug[:64] if slug else "section"


def extract_section_id(heading: str, ordinal: int) -> str:
    """从标题抽 section_id（spec §4.4.1）。

    优先抽前导数字章节号（含括号字母后缀），其次抽纯括号编号，
    再不行用 slug + 序号兜底保证唯一。

    Args:
        heading: 标题文本（不含 # 前缀）。
        ordinal: 该 clause 在文档内的 0-based 序号（兜底唯一性用）。

    Returns:
        section_id 字符串。
    """
    num_match = _SECTION_NUMBER_RE.match(heading)
    if num_match:
        return num_match.group(1)
    paren_match = _SECTION_PAREN_RE.match(heading)
    if paren_match:
        return f"{paren_match.group(1)}#{ordinal}"
    return f"{slugify_heading(heading)}#{ordinal}"


@dataclass
class ClauseRecord:
    """切分出的一条 clause 中间结构（写图前）。"""

    clause_id: str
    section_id: str
    document_id: str
    heading: str
    level: int
    text: str
    text_hash: str
    parent_clause_id: Optional[str] = None
    ordinal: int = 0


@dataclass
class RegulationLoadResult:
    """regulation loader 灌库结果。"""

    batch: GraphBatch
    document_ids: List[str] = field(default_factory=list)
    clause_count: int = 0
    audit: AuditLog = field(default_factory=AuditLog)


def split_markdown_clauses(
    markdown_text: str,
    document_id: str,
) -> List[ClauseRecord]:
    """把一份法规 markdown 切分为 ClauseRecord 列表（spec §4.4.1）。

    切分规则：每个 `#`~`######` 标题起一个 clause，其 text 为该标题到
    下一个 **同级或更高级** 标题前的全部正文（不含子标题正文，子标题另成 clause）。
    parent_clause_id 由标题层级栈推出。

    非标题前导文本（首个标题之前的内容）不单独成 clause，被丢弃 + warning
    由调用方决定；本函数只切标题。

    Args:
        markdown_text: 法规 markdown 全文。
        document_id: 文档 id。

    Returns:
        ClauseRecord 列表，按出现顺序。
    """
    lines = markdown_text.splitlines()
    # 第一遍：定位所有标题行。
    headings: List[Dict[str, Any]] = []
    for line_no, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            headings.append({
                "line_no": line_no,
                "level": len(m.group(1)),
                "heading": m.group(2).strip(),
            })

    clauses: List[ClauseRecord] = []
    # 标题层级栈：保存 (level, clause_id)，用于推 parent。
    level_stack: List[tuple[int, str]] = []
    seen_section_ids: Dict[str, int] = {}

    for idx, head in enumerate(headings):
        level = head["level"]
        heading_text = head["heading"]
        # clause 正文：本标题行后一行 ~ 下一个标题行前一行。
        body_start = head["line_no"] + 1
        body_end = headings[idx + 1]["line_no"] if idx + 1 < len(headings) else len(lines)
        body = "\n".join(lines[body_start:body_end]).strip()

        # section_id 抽取 + 文档内去重。
        raw_section_id = extract_section_id(heading_text, idx)
        if raw_section_id in seen_section_ids:
            seen_section_ids[raw_section_id] += 1
            section_id = f"{raw_section_id}#dup{seen_section_ids[raw_section_id]}"
        else:
            seen_section_ids[raw_section_id] = 0
            section_id = raw_section_id

        clause_id = f"{document_id}::{section_id}"

        # parent：栈中第一个 level 严格更小的标题。
        while level_stack and level_stack[-1][0] >= level:
            level_stack.pop()
        parent_clause_id = level_stack[-1][1] if level_stack else None
        level_stack.append((level, clause_id))

        clauses.append(ClauseRecord(
            clause_id=clause_id,
            section_id=section_id,
            document_id=document_id,
            heading=heading_text,
            level=level,
            text=body,
            text_hash=sha256_text(body),
            parent_clause_id=parent_clause_id,
            ordinal=idx,
        ))

    return clauses


def build_regulation_document_node(
    document_id: str,
    title: str,
    source_path: str,
    full_text: str,
    loaded_at: str,
    version: Optional[str] = None,
) -> NodeSpec:
    """构造 (:RegulationDocument) 节点（spec §3.4.1）。

    Args:
        document_id: 文档 id。
        title: 文档标题。
        source_path: markdown 文件路径。
        full_text: 文档全文（算 text_hash 用）。
        loaded_at: ISO 时间戳。
        version: 文档版本，可空。

    Returns:
        RegulationDocument NodeSpec。
    """
    props = {
        "title": title,
        "version": version,
        "source_path": source_path,
        "loaded_at": loaded_at,
        "text_hash": sha256_text(full_text),
    }
    return NodeSpec("RegulationDocument", "document_id", document_id, props)


def build_clause_node(clause: ClauseRecord) -> NodeSpec:
    """ClauseRecord → (:RegulationClause) 节点（spec §3.4.1）。

    spec §3.4.1 给的字段：section_id, document_id, heading, level, text,
    text_hash, page_start, page_end。markdown 切分无页码信息，page_* 填 None。
    """
    props = {
        "section_id": clause.section_id,
        "document_id": clause.document_id,
        "heading": clause.heading,
        "level": clause.level,
        "text": clause.text,
        "text_hash": clause.text_hash,
        "page_start": None,   # markdown 切分无页码
        "page_end": None,
    }
    return NodeSpec("RegulationClause", "clause_id", clause.clause_id, props)


def build_regulation_graph(
    markdown_path: Path,
    loaded_at: str,
    document_id: Optional[str] = None,
    title: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> RegulationLoadResult:
    """把一份法规 markdown 转换为 GraphBatch（纯转换，不写 Neo4j）。

    Args:
        markdown_path: markdown 文件路径。
        loaded_at: ISO 时间戳。
        document_id: 文档 id；None 时按文件名查 `DOCUMENT_ID_MAP`。
        title: 文档标题；None 时用第一个 H1 标题或文件名。
        audit: 审计记录器。

    Returns:
        RegulationLoadResult。
    """
    audit = audit or AuditLog()
    result = RegulationLoadResult(batch=GraphBatch(), audit=audit)

    filename = markdown_path.name
    doc_id = document_id or DOCUMENT_ID_MAP.get(filename)
    if doc_id is None:
        audit.warn(f"regulation: unknown markdown file {filename}, using filename stem as id")
        doc_id = markdown_path.stem

    full_text = markdown_path.read_text(encoding="utf-8")
    clauses = split_markdown_clauses(full_text, doc_id)

    # 文档标题：优先第一个 H1。
    doc_title = title
    if doc_title is None:
        for clause in clauses:
            if clause.level == 1:
                doc_title = clause.heading
                break
    doc_title = doc_title or doc_id

    result.batch.add_node(build_regulation_document_node(
        doc_id, doc_title, str(markdown_path), full_text, loaded_at
    ))
    result.document_ids.append(doc_id)
    audit.record_source(filename)

    prev_clause_id: Optional[str] = None
    for clause in clauses:
        result.batch.add_node(build_clause_node(clause))
        result.clause_count += 1
        # RegulationDocument-HAS_CLAUSE->RegulationClause。
        result.batch.add_edge(EdgeSpec(
            "RegulationDocument", "document_id", doc_id,
            "HAS_CLAUSE",
            "RegulationClause", "clause_id", clause.clause_id,
        ))
        # RegulationClause-PARENT_OF->RegulationClause。
        if clause.parent_clause_id:
            result.batch.add_edge(EdgeSpec(
                "RegulationClause", "clause_id", clause.parent_clause_id,
                "PARENT_OF",
                "RegulationClause", "clause_id", clause.clause_id,
            ))
        # RegulationClause-NEXT_CLAUSE->RegulationClause（文档内顺序链）。
        if prev_clause_id:
            result.batch.add_edge(EdgeSpec(
                "RegulationClause", "clause_id", prev_clause_id,
                "NEXT_CLAUSE",
                "RegulationClause", "clause_id", clause.clause_id,
            ))
        prev_clause_id = clause.clause_id

    return result


def build_regulation_graph_dir(
    markdown_dir: Path,
    loaded_at: str,
    audit: Optional[AuditLog] = None,
) -> RegulationLoadResult:
    """把法规 markdown 目录下 4 份已知法规全部转换为单一 GraphBatch。

    只加载 `DOCUMENT_ID_MAP` 中的 4 份；目录里其它 .md 跳过 + warning。

    Args:
        markdown_dir: 法规 markdown 目录。
        loaded_at: ISO 时间戳。
        audit: 审计记录器。

    Returns:
        合并后的 RegulationLoadResult。
    """
    audit = audit or AuditLog()
    result = RegulationLoadResult(batch=GraphBatch(), audit=audit)
    for filename in sorted(DOCUMENT_ID_MAP):
        path = markdown_dir / filename
        if not path.is_file():
            audit.warn(f"regulation: expected markdown {filename} not found in {markdown_dir}")
            continue
        sub = build_regulation_graph(path, loaded_at, audit=audit)
        result.batch.extend(sub.batch)
        result.document_ids.extend(sub.document_ids)
        result.clause_count += sub.clause_count
    return result


def load_regulation_kg(
    markdown_dir: Path,
    client: Any,
    loaded_at: str,
    audit: Optional[AuditLog] = None,
) -> RegulationLoadResult:
    """把法规 KG 写入 Neo4j（spec §4.4）。

    Args:
        markdown_dir: 法规 markdown 目录。
        client: `Neo4jClient` 实例。
        loaded_at: ISO 时间戳。
        audit: 审计记录器。

    Returns:
        RegulationLoadResult（已写入）。
    """
    from evo_agent_baseline.ingest._graphspec import compile_batch

    result = build_regulation_graph_dir(markdown_dir, loaded_at, audit)
    client.write_many(compile_batch(result.batch))
    return result


__all__ = [
    "DOCUMENT_ID_MAP",
    "sha256_text",
    "slugify_heading",
    "extract_section_id",
    "ClauseRecord",
    "RegulationLoadResult",
    "split_markdown_clauses",
    "build_regulation_document_node",
    "build_clause_node",
    "build_regulation_graph",
    "build_regulation_graph_dir",
    "load_regulation_kg",
]
