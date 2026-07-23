"""Build and load the regulation corpus used by the research KG.

This module provides two minimal capabilities:
1. Build canonical regulation assets from local PDF sources.
2. Load the generated manifests/chunks for downstream research usage.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import fitz


MANIFEST_VERSION = "2026-04-05"
LOW_TEXT_THRESHOLD = 80
CHUNK_TARGET_CHARS = 1200
CHUNK_MIN_CHARS = 350
PAGE_ANCHOR_RE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
TABLE_HEADER_KEYWORDS = (
    "項目",
    "條款",
    "備註",
    "檢查",
    "日期",
    "簽署",
    "編號",
    "監督數量",
    "巡查地盤",
    "姓名",
    "香港身份證",
    "聯絡地址",
    "電話號碼",
    "電郵地址",
    "建築工程",
    "測試樣本",
    "大廈名稱及地址",
    "通知編號",
    "驗證測試",
    "結果",
)


@dataclass(frozen=True)
class RegulationSpec:
    document_id: str
    title: str
    publisher: str
    canonical_pdf_name: str
    source_candidates: Sequence[Path]
    source_kind: str = "pdf"
    alias_of_document_id: str | None = None
    counts_as_independent_source: bool = True
    preferred_markdown_candidates: Sequence[Path] = ()
    preferred_markdown_starts_at_page: int | None = None

    @property
    def extract_dir_name(self) -> str:
        return self.document_id


@dataclass
class BuiltRegulation:
    spec: RegulationSpec
    canonical_pdf_path: Path
    markdown_path: Path
    extract_dir: Path
    document_json_path: Path
    chunk_file_path: Path
    page_count: int
    chunk_count: int
    sha256_hex: str
    markdown_strategy: str
    issues: List[dict]


class RegulationCorpus:
    """Loaded regulation corpus and chunk artifacts."""

    def __init__(
        self,
        ingest_manifest: dict,
        source_manifest: dict,
        corpus_manifest: dict,
        chunk_manifest: dict,
        documents: List[dict],
        chunks: List[dict],
    ) -> None:
        self.ingest_manifest = ingest_manifest
        self.source_manifest = source_manifest
        self.corpus_manifest = corpus_manifest
        self.chunk_manifest = chunk_manifest
        self.documents = documents
        self.chunks = chunks

    @property
    def corpus_id(self) -> str:
        return self.ingest_manifest["corpus_id"]

    def summary(self) -> Dict[str, Any]:
        artifact_document_count = int(
            self.ingest_manifest.get("artifact_document_count", len(self.documents))
        )
        independent_source_count = int(
            self.ingest_manifest.get("independent_source_count", artifact_document_count)
        )
        alias_document_count = int(
            self.ingest_manifest.get("alias_document_count", 0)
        )
        return {
            "corpus_id": self.corpus_id,
            "version": self.ingest_manifest["version"],
            "document_count": artifact_document_count,
            "artifact_document_count": artifact_document_count,
            "independent_source_count": independent_source_count,
            "alias_document_count": alias_document_count,
            "chunk_count": len(self.chunks),
            "document_ids": [doc["document_id"] for doc in self.documents],
            "independent_document_ids": list(self.ingest_manifest.get("independent_document_ids", [])),
            "alias_document_ids": list(self.ingest_manifest.get("alias_document_ids", [])),
            "chunk_manifest": self.ingest_manifest["chunk_manifest"],
            "knowledge_base_entrypoint": self.ingest_manifest["knowledge_base"][
                "entrypoint"
            ],
        }


REGULATION_SPECS: Sequence[RegulationSpec] = (
    RegulationSpec(
        document_id="MBIS_CoP_2023",
        title="強制驗樓計劃及強制驗窗計劃作業守則（2023年修訂版）",
        publisher="Buildings Department, HKSAR",
        canonical_pdf_name="MBIS_CoP_2023.pdf",
        source_candidates=(
            Path("data/MBIS作业守则.pdf"),
            Path("../paper/MBIS作业守则.pdf"),
        ),
        preferred_markdown_candidates=(
            Path("data/MBIS作业守则_补全版.md"),
            Path("data/MBIS作业守则.md"),
            Path("../paper/MBIS作业守则.md"),
        ),
        preferred_markdown_starts_at_page=1,
    ),
    RegulationSpec(
        document_id="PNBI10_CoP_2023",
        title="屋宇署強制驗樓及強制驗窗計劃作業備考 PNBI-10（2023年修訂版）",
        publisher="Buildings Department, HKSAR",
        canonical_pdf_name="PNBI10_CoP_2023.pdf",
        source_candidates=(Path("../paper/屋宇署強制驗樓及強制驗窗計劃作業備考.pdf"),),
    ),
    RegulationSpec(
        document_id="MBIS_MWIS_CoP_2012_Legacy",
        title="MBIS / MWIS Code of Practice (2012 legacy markdown source)",
        publisher="Buildings Department, HKSAR",
        canonical_pdf_name="MBIS_MWIS_CoP_2012_Legacy.md",
        source_candidates=(Path("data/CoP_2012.md"),),
        source_kind="markdown",
    ),
    RegulationSpec(
        document_id="MBIS_MWIS_Operation_Note",
        title="MBIS / MWIS Operation Note",
        publisher="Buildings Department, HKSAR",
        canonical_pdf_name="MBIS_MWIS_Operation_Note.pdf",
        source_candidates=(Path("../paper/屋宇署強制驗樓及強制驗窗計劃作業備考.pdf"),),
        alias_of_document_id="PNBI10_CoP_2023",
        counts_as_independent_source=False,
    ),
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _regulations_root(project_root: Path) -> Path:
    return project_root / "regulations"


def _manifest_dir(project_root: Path) -> Path:
    return _regulations_root(project_root) / "manifests"


def _relative_to(base_dir: Path, target: Path) -> str:
    return Path(os.path.relpath(target, base_dir)).as_posix()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows: List[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_layout(project_root: Path) -> None:
    regs = _regulations_root(project_root)
    for rel in (
        "raw",
        "markdown",
        "failed",
        "manifests",
        "corpus/chunks",
        "corpus/documents",
        "extracted",
    ):
        (regs / rel).mkdir(parents=True, exist_ok=True)


def _normalize_line(line: str) -> str:
    text = (
        line.replace("\u3000", " ")
        .replace("\xa0", " ")
        .replace("\uf0bc", "-")
        .replace("\uf06e", "-")
        .replace("•", "-")
        .replace("\t", " ")
    )
    text = re.sub(r"[ ]+", " ", text).strip()
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", text)
        text = re.sub(r"(\d+)\s*\.\s+(?=[^\d])", r"\1. ", text)
        text = re.sub(r"^(\d+)\s*\.\s*$", r"\1.", text)
        text = re.sub(r"^(\d+(?:\.\d+)+)(?=[A-Za-z\u4e00-\u9fff])", r"\1 ", text)
        text = re.sub(r"^\(\s*([A-Za-zivx]+)\s*\)\s*", r"(\1) ", text, flags=re.IGNORECASE)
        text = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
        text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
        text = re.sub(r"(?<=\d)\s+(?=[年月日條章節頁款部段項])", "", text)
        text = re.sub(r"(?<=[第附錄附录])\s+(?=\d)", "", text)
        text = re.sub(r"(?<=[A-Z])\s+(?=[A-Z0-9])", "", text)
        text = re.sub(r"(?<=[a-z])\s+(?=[a-z])", "", text)
        text = re.sub(r"([A-Za-z])\s*\.\s*([A-Za-z])", r"\1.\2", text)
        text = re.sub(r"([A-Za-z])\s*/\s*([A-Za-z])", r"\1/\2", text)
        text = re.sub(r"(?<=[\u4e00-\u9fff])\s+-\s*(?=[\u4e00-\u9fff])", "", text)
        text = re.sub(r"(?<=[A-Za-z])\s+-\s+(?=\d)", "-", text)
    text = re.sub(r"\s+([，。；：、）】」》])", r"\1", text)
    text = re.sub(r"([（【「《])\s+", r"\1", text)
    text = re.sub(r"\s+-\s*(?=[，。；：、.!?]|$)", "", text)
    text = re.sub(r"^(\d+(?:\.\d+)+)(?=[A-Za-z\u4e00-\u9fff])", r"\1 ", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])(?=PNBI-\d+)", " ", text)
    text = re.sub(r"(?<=\d)\s+(?=[A-Za-z])", "", text)
    return text.strip()


def _is_page_artifact(line: str) -> bool:
    if re.fullmatch(r"-\s*\d+\s*-", line):
        return True
    if re.fullmatch(r"-\s*\d+\s*-?", line):
        return True
    if re.fullmatch(r"-?\s*\d+\s*-", line):
        return True
    if re.fullmatch(r"第\s*\d+\s*[頁页]", line):
        return True
    return False


def _extract_page_records(pdf_path: Path) -> tuple[list[dict], list[dict]]:
    doc = fitz.open(pdf_path)
    records: List[dict] = []
    issues: List[dict] = []
    for page_number, page in enumerate(doc, start=1):
        cleaned_lines: List[str] = []
        for raw_line in page.get_text("text").splitlines():
            line = _normalize_line(raw_line)
            if not line or _is_page_artifact(line):
                continue
            cleaned_lines.append(line)
        page_text = "\n".join(cleaned_lines).strip()
        char_count = len(page_text)
        record = {
            "page": page_number,
            "char_count": char_count,
            "line_count": len(cleaned_lines),
            "text": page_text,
            "lines": cleaned_lines,
        }
        records.append(record)
        if not page_text:
            issues.append(
                {
                    "severity": "error",
                    "issue_type": "empty_page_after_extraction",
                    "page": page_number,
                }
            )
        elif char_count < LOW_TEXT_THRESHOLD:
            issues.append(
                {
                    "severity": "warning",
                    "issue_type": "low_text_density",
                    "page": page_number,
                    "char_count": char_count,
                }
            )
    return records, issues


def _extract_page_records_from_markdown(markdown_text: str) -> tuple[list[dict], list[dict]]:
    cleaned_lines = _clean_markdown_lines(markdown_text)
    records: List[dict] = []
    page_lines: List[str] = []
    page_number = 1

    def flush_page() -> None:
        nonlocal page_lines, page_number
        normalized_lines = [line for line in page_lines if line.strip()]
        page_text = "\n".join(normalized_lines).strip()
        if page_text:
            records.append(
                {
                    "page": page_number,
                    "char_count": len(page_text),
                    "line_count": len(normalized_lines),
                    "text": page_text,
                    "lines": normalized_lines,
                }
            )
        page_lines = []
        page_number += 1

    for line in cleaned_lines:
        anchor_match = PAGE_ANCHOR_RE.match(line)
        if anchor_match:
            flush_page()
            anchored_page = int(anchor_match.group(1))
            if anchored_page >= page_number:
                page_number = anchored_page
            continue
        page_lines.append(line)
        if len(page_lines) >= 80 and line.startswith("#"):
            flush_page()

    flush_page()
    if not records:
        records.append(
            {
                "page": 1,
                "char_count": 0,
                "line_count": 0,
                "text": "",
                "lines": [],
            }
        )

    issues: List[dict] = []
    for record in records:
        if record["char_count"] < LOW_TEXT_THRESHOLD:
            issues.append(
                {
                    "severity": "warning",
                    "issue_type": "low_text_density",
                    "page": record["page"],
                    "char_count": record["char_count"],
                }
            )
    return records, issues


def _find_existing_candidate(project_root: Path, candidates: Sequence[Path]) -> Path | None:
    for candidate_rel in candidates:
        candidate = (project_root / candidate_rel).resolve()
        if candidate.exists():
            return candidate
    return None


def _normalize_lookup_text(text: str) -> str:
    value = text.replace("**", "").replace("`", "")
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("／", "/").replace("－", "-").replace("—", "-")
    value = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", value)
    value = re.sub(r"[#>*_|-]", " ", value)
    value = _normalize_line(value)
    value = re.sub(r"\s+", "", value)
    return value


def _clean_markdown_line(line: str) -> str:
    text = line.rstrip()
    if not text:
        return ""

    if text.startswith("#"):
        match = re.match(r"^(#+)\s*(.*)$", text)
        if match:
            prefix, content = match.groups()
            content = re.sub(r"^[*\-]\s*", "", content)
            content = _normalize_line(content.replace("**", ""))
            return f"{prefix} {content}".rstrip()

    for marker in ("* ", "- ", "> "):
        if text.startswith(marker):
            return marker + _normalize_line(text[len(marker):].replace("**", ""))

    if re.match(r"^\([A-Za-zivx]+\)\s*", text, re.IGNORECASE):
        return _normalize_line(text)

    if text.startswith("<") and text.endswith(">"):
        return text

    return _normalize_line(text.replace("**", ""))


def _clean_table_cell(cell: str) -> str:
    parts = cell.split("<br>")
    normalized_parts = [_normalize_line(part.replace("**", "")) for part in parts]
    return "<br>".join(part for part in normalized_parts if part)


def _clean_html_table_line(line: str) -> str:
    def _normalize_html_text(match: re.Match[str]) -> str:
        text = match.group(1)
        if not text.strip():
            return f">{text}<"
        return f">{_normalize_line(text.replace('**', ''))}<"

    return re.sub(r">([^<>]+)<", _normalize_html_text, line.rstrip())


def _clean_markdown_table_row(line: str) -> str:
    stripped = line.strip()
    if re.fullmatch(r"\|[\-\:\s|]+\|", stripped):
        return stripped
    cells = stripped.split("|")
    cleaned_cells: List[str] = []
    for idx, cell in enumerate(cells):
        if idx == 0 or idx == len(cells) - 1:
            cleaned_cells.append("")
        else:
            cleaned_cells.append(_clean_table_cell(cell))
    return "|".join(cleaned_cells)


def _collapse_blank_lines(lines: Sequence[str]) -> List[str]:
    collapsed: List[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank:
            if previous_blank:
                continue
            collapsed.append("")
            previous_blank = True
            continue
        collapsed.append(line)
        previous_blank = False

    while collapsed and not collapsed[0]:
        collapsed.pop(0)
    while collapsed and not collapsed[-1]:
        collapsed.pop()
    return collapsed


def _clean_markdown_lines(raw_markdown: str) -> List[str]:
    cleaned: List[str] = []
    in_html_table = False
    for raw_line in raw_markdown.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        if stripped == "---":
            continue
        if re.fullmatch(r"\*\*==>\s*picture\s*\[[^\]]+\]\s*intentionally omitted\s*<==\*\*", stripped):
            continue
        if "Startofpicturetext" in stripped or "Endofpicturetext" in stripped:
            continue
        if _is_page_artifact(stripped) or re.fullmatch(r"第\d+[頁页]", _normalize_lookup_text(stripped)):
            continue
        if stripped.startswith("<table"):
            in_html_table = True
        if in_html_table:
            cleaned.append(_clean_html_table_line(raw_line.rstrip()))
            if stripped.endswith("</table>") or stripped == "</table>":
                in_html_table = False
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            cleaned.append(_clean_markdown_table_row(stripped))
            continue
        cleaned.append(_clean_markdown_line(stripped))

    while cleaned and not cleaned[0]:
        cleaned.pop(0)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return cleaned


def _bbox_overlaps(bbox_a: Sequence[float], bbox_b: Sequence[float], padding: float = 1.0) -> bool:
    ax0, ay0, ax1, ay1 = bbox_a
    bx0, by0, bx1, by1 = bbox_b
    return not (
        ax1 <= bx0 - padding
        or bx1 <= ax0 - padding
        or ay1 <= by0 - padding
        or by1 <= ay0 - padding
    )


def _join_wrapped_text(lines: Sequence[str]) -> str:
    parts = [part.strip() for part in lines if part.strip()]
    if not parts:
        return ""
    text = parts[0]
    for part in parts[1:]:
        prev_char = text[-1]
        next_char = part[0]
        if prev_char in "-/(" or next_char in ".,:;!?%)]}，。；：、）》】":
            separator = ""
        elif re.search(r"[\u4e00-\u9fff]$", text) or re.match(r"^[\u4e00-\u9fff]", part):
            separator = ""
        else:
            separator = " "
        text = f"{text}{separator}{part}"
    return text


def _is_bullet_marker_only(line: str) -> bool:
    return bool(
        re.fullmatch(r"\([A-Za-zivx]+\)", line, re.IGNORECASE)
        or re.fullmatch(r"[A-Za-zivx]+\.", line, re.IGNORECASE)
    )


def _merge_wrapped_block_lines(lines: Sequence[str]) -> List[str]:
    merged: List[str] = []
    buffer: List[str] = []

    def flush_buffer() -> None:
        if not buffer:
            return
        joined = _join_wrapped_text(buffer)
        if joined:
            merged.append(joined)
        buffer.clear()

    combined_lines = list(_combine_heading_lines(lines))
    idx = 0
    while idx < len(combined_lines):
        line = combined_lines[idx]
        if _is_bullet_marker_only(line) and idx + 1 < len(combined_lines):
            nxt = combined_lines[idx + 1]
            if _heading_level(nxt) is None and _bulletize(nxt) is None:
                line = f"{line} {nxt}"
                idx += 1
        if _heading_level(line) is not None or _bulletize(line) is not None:
            flush_buffer()
            merged.append(line)
            idx += 1
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_buffer()
            merged.append(line)
            idx += 1
            continue
        if not buffer:
            buffer.append(line)
            idx += 1
            continue
        if buffer[-1].endswith(("。", "；", "：", ":", "！", "？", ".", "!", "?")):
            flush_buffer()
        buffer.append(line)
        idx += 1

    flush_buffer()
    return merged


def _table_is_high_confidence(rows: Sequence[Sequence[Any]]) -> bool:
    normalized_rows = [
        [_normalize_lookup_text(str(cell)) for cell in row if cell is not None and str(cell).strip()]
        for row in rows[:3]
    ]
    flattened = [cell for row in normalized_rows for cell in row]
    if not flattened:
        return False
    normalized_keywords = [_normalize_lookup_text(keyword) for keyword in TABLE_HEADER_KEYWORDS]
    keyword_hits = sum(1 for keyword in normalized_keywords if any(keyword in cell for cell in flattened))
    if keyword_hits >= 2:
        return True
    non_empty_counts = [len(row) for row in normalized_rows]
    return keyword_hits >= 1 and bool(non_empty_counts) and max(non_empty_counts) >= 4 and len(rows) >= 3


def _render_extracted_table(rows: Sequence[Sequence[Any]]) -> List[str]:
    normalized_rows: List[List[str]] = []
    width = max((len(row) for row in rows), default=0)
    if width == 0:
        return []

    for row in rows:
        padded = list(row) + [""] * (width - len(row))
        normalized_row = [
            _clean_table_cell(str(cell).replace("\n", "<br>")) if cell is not None else ""
            for cell in padded
        ]
        if any(cell for cell in normalized_row):
            normalized_rows.append(normalized_row)

    if not normalized_rows:
        return []

    header = normalized_rows[0]
    body = normalized_rows[1:] or [[""] * width]
    markdown_table = [
        "|" + "|".join(header) + "|",
        "|" + "|".join(["---"] * width) + "|",
    ]
    markdown_table.extend("|" + "|".join(row) + "|" for row in body)
    return markdown_table


def _extract_structured_page_items(page: fitz.Page) -> List[dict]:
    tables: List[Any] = []
    items: List[dict] = []

    for table in page.find_tables().tables:
        if not _table_is_high_confidence(table.extract()):
            continue
        tables.append(table)
        rendered_table = _render_extracted_table(table.extract())
        if rendered_table:
            items.append(
                {
                    "kind": "table",
                    "bbox": table.bbox,
                    "lines": rendered_table,
                }
            )

    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, *_ = block
        bbox = (x0, y0, x1, y1)
        if any(_bbox_overlaps(bbox, table.bbox) for table in tables):
            continue
        raw_lines = []
        for raw_line in text.splitlines():
            line = _normalize_line(raw_line)
            if not line or _is_page_artifact(line):
                continue
            raw_lines.append(line)
        lines = _merge_wrapped_block_lines(raw_lines)
        if lines:
            items.append(
                {
                    "kind": "text",
                    "bbox": bbox,
                    "lines": lines,
                }
            )

    items.sort(key=lambda item: (round(item["bbox"][1], 1), round(item["bbox"][0], 1)))
    return items


def _inject_page_anchors(
    lines: Sequence[str],
    page_records: Sequence[dict],
    *,
    start_page_hint: int | None = None,
) -> List[str]:
    page_texts = {
        record["page"]: _normalize_lookup_text(record["text"])
        for record in page_records
    }
    anchored: List[str] = []
    current_anchor: int | None = None
    search_start = start_page_hint or 1
    if start_page_hint is not None:
        anchored.extend(["", f"<!-- page: {start_page_hint} -->", ""])
        current_anchor = start_page_hint

    for line in lines:
        page_for_line: int | None = None
        if line.startswith("#"):
            heading_text = _normalize_lookup_text(re.sub(r"^(#+)\s*", "", line))
            if heading_text:
                for page_number in range(search_start, len(page_records) + 1):
                    if heading_text in page_texts.get(page_number, ""):
                        page_for_line = page_number
                        search_start = page_number
                        break
        if page_for_line is not None and page_for_line != current_anchor:
            anchored.extend(["", f"<!-- page: {page_for_line} -->", ""])
            current_anchor = page_for_line
        anchored.append(line)
    return anchored


def _render_preface_pages(page_records: Sequence[dict], stop_before_page: int) -> List[str]:
    preface_lines: List[str] = []
    for page_record in page_records:
        if page_record["page"] >= stop_before_page:
            break
        preface_lines.extend(["", f"<!-- page: {page_record['page']} -->", ""])
        preface_lines.extend(page_record["lines"])
    return preface_lines


def _render_curated_markdown(
    *,
    spec: RegulationSpec,
    project_root: Path,
    canonical_pdf_rel: str,
    sha256_hex: str,
    page_records: Sequence[dict],
) -> tuple[str, List[str], str]:
    preferred_path = _find_existing_candidate(project_root, spec.preferred_markdown_candidates)
    if preferred_path is None:
        raise FileNotFoundError(f"No preferred markdown candidate found for {spec.document_id}")

    body_lines = _clean_markdown_lines(preferred_path.read_text(encoding="utf-8"))
    anchored_body = _inject_page_anchors(
        body_lines,
        page_records,
        start_page_hint=spec.preferred_markdown_starts_at_page,
    )
    preface_lines: List[str] = []
    if spec.preferred_markdown_starts_at_page and spec.preferred_markdown_starts_at_page > 1:
        preface_lines = _render_preface_pages(page_records, spec.preferred_markdown_starts_at_page)

    markdown_lines: List[str] = [
        f"# {spec.title}",
        "",
        f"- document_id: `{spec.document_id}`",
        f"- canonical_pdf: `{canonical_pdf_rel}`",
        f"- publisher: `{spec.publisher}`",
        f"- page_count: `{len(page_records)}`",
        f"- sha256: `{sha256_hex}`",
        f"- markdown_strategy: `preferred_markdown_candidate`",
        f"- preferred_markdown_source: `{_relative_to(project_root, preferred_path)}`",
    ]
    markdown_lines.extend(preface_lines)
    markdown_lines.extend([""] if preface_lines else [])
    markdown_lines.extend(anchored_body)
    markdown_lines = _collapse_blank_lines(markdown_lines)
    return "\n".join(markdown_lines).strip() + "\n", markdown_lines, "preferred_markdown_candidate"


def _render_native_markdown(
    *,
    spec: RegulationSpec,
    project_root: Path,
    canonical_pdf_rel: str,
    sha256_hex: str,
    canonical_source_path: Path,
    page_records: Sequence[dict],
) -> tuple[str, List[str], str]:
    body_lines = _clean_markdown_lines(canonical_source_path.read_text(encoding="utf-8"))
    anchored_body: List[str] = []
    if any(PAGE_ANCHOR_RE.match(line) for line in body_lines):
        anchored_body = list(body_lines)
    else:
        for page_record in page_records:
            anchored_body.extend(["", f"<!-- page: {page_record['page']} -->", ""])
            anchored_body.extend(page_record["lines"])
    markdown_lines: List[str] = [
        f"# {spec.title}",
        "",
        f"- document_id: `{spec.document_id}`",
        f"- canonical_pdf: `{canonical_pdf_rel}`",
        f"- publisher: `{spec.publisher}`",
        f"- page_count: `{len(page_records)}`",
        f"- sha256: `{sha256_hex}`",
        f"- markdown_strategy: `native_markdown_source`",
        f"- native_markdown_source: `{_relative_to(project_root, canonical_source_path)}`",
    ]
    markdown_lines.extend(anchored_body)
    markdown_lines = _collapse_blank_lines(markdown_lines)
    return "\n".join(markdown_lines).strip() + "\n", markdown_lines, "native_markdown_source"


def _render_structured_markdown(
    *,
    spec: RegulationSpec,
    canonical_pdf_path: Path,
    canonical_pdf_rel: str,
    sha256_hex: str,
    page_records: Sequence[dict],
) -> tuple[str, List[str], str]:
    markdown_lines: List[str] = [
        f"# {spec.title}",
        "",
        f"- document_id: `{spec.document_id}`",
        f"- canonical_pdf: `{canonical_pdf_rel}`",
        f"- publisher: `{spec.publisher}`",
        f"- page_count: `{len(page_records)}`",
        f"- sha256: `{sha256_hex}`",
        f"- markdown_strategy: `pymupdf_text_tables`",
    ]
    pdf = fitz.open(canonical_pdf_path)
    for page_number, page in enumerate(pdf, start=1):
        markdown_lines.extend(["", f"<!-- page: {page_number} -->", ""])
        for item in _extract_structured_page_items(page):
            if item["kind"] == "table":
                markdown_lines.extend(item["lines"])
                markdown_lines.append("")
                continue
            for line in item["lines"]:
                if line == spec.title:
                    continue
                line = re.sub(r"^(\d+(?:\.\d+)+)(?=[A-Za-z\u4e00-\u9fff])", r"\1 ", line)
                bullet = _bulletize(line)
                if bullet is not None:
                    markdown_lines.append(f"- {bullet}")
                    continue
                heading_level = _heading_level(line)
                if heading_level is not None:
                    markdown_lines.append(f"{'#' * heading_level} {line}")
                    continue
                markdown_lines.append(line)
            markdown_lines.append("")

    markdown_lines = _collapse_blank_lines(markdown_lines)
    return "\n".join(markdown_lines).strip() + "\n", markdown_lines, "pymupdf_text_tables"


def _combine_heading_lines(lines: Sequence[str]) -> List[str]:
    combined: List[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if idx + 1 < len(lines) and re.fullmatch(r"\d+(?:\.\d+)*\.", line):
            nxt = lines[idx + 1]
            if nxt and len(nxt) <= 80:
                combined.append(f"{line} {nxt}")
                idx += 2
                continue
        combined.append(line)
        idx += 1
    return combined


def _heading_level(line: str) -> int | None:
    appendix_match = re.match(r"^(附錄|附录)[A-Za-z0-9一二三四五六七八九十百]+(?:\s+.+)?$", line)
    if (
        appendix_match
        and not line.endswith(("；", "。", "：", ":", "，", ","))
        and "以及" not in line
        and not re.search(r"\d{4}年", line)
    ):
        return 2
    if re.match(r"^\d+\.\s+.+", line) and not line.endswith(("；", "。", "：", ":", "，", ",")):
        return 2
    two_level_match = re.match(r"^(\d+)\.(\d+)\s+(.+)", line)
    if two_level_match:
        major = int(two_level_match.group(1))
        title = two_level_match.group(3)
        if major >= 10 and not re.search(r"(毫米|mm|厘米|cm|米|年|月|日|%)", title, re.IGNORECASE):
            return 3
        return None
    match = re.match(r"^(\d+(?:\.\d+){2,})\s+.+", line)
    if match:
        depth = match.group(1).count(".")
        return min(5, depth + 2)
    if re.match(r"^[A-Z]\)\s+.+", line) or re.match(r"^\([A-Z]\)\s*.+", line):
        return 5
    if re.match(r"^第\d+[章節條款部段].+", line) and not line.endswith(("；", "。", "：", ":", "，", ",")):
        return 3
    if line in {
        "概要",
        "說明",
        "參考文件",
        "檢驗結果",
        "建築物檢驗的方法說明",
        "修葺建議",
        "備註",
    }:
        return 4
    return None


def _bulletize(line: str) -> str | None:
    candidate = line
    if re.match(r"^[1-9]\.\s+", candidate):
        return candidate
    if re.match(r"^\([a-zivx]+\)\s*", candidate, re.IGNORECASE):
        return re.sub(r"^\(([^)]+)\)\s*", r"\1. ", candidate)
    if re.match(r"^[a-zivx]+\)\s*", candidate, re.IGNORECASE):
        return re.sub(r"^([a-zivx]+)\)\s*", r"\1. ", candidate, flags=re.IGNORECASE)
    if candidate.startswith("- "):
        return candidate[2:].strip()
    return None


def _render_markdown(
    spec: RegulationSpec,
    canonical_pdf_rel: str,
    sha256_hex: str,
    page_records: Sequence[dict],
) -> tuple[str, List[str]]:
    markdown_lines: List[str] = [
        f"# {spec.title}",
        "",
        f"- document_id: `{spec.document_id}`",
        f"- canonical_pdf: `{canonical_pdf_rel}`",
        f"- publisher: `{spec.publisher}`",
        f"- page_count: `{len(page_records)}`",
        f"- sha256: `{sha256_hex}`",
    ]

    for page_record in page_records:
        markdown_lines.extend(["", f"<!-- page: {page_record['page']} -->", ""])
        for line in _combine_heading_lines(page_record["lines"]):
            if line == spec.title:
                continue
            line = re.sub(r"^(\d+(?:\.\d+)+)(?=[A-Za-z\u4e00-\u9fff])", r"\1 ", line)
            bullet = _bulletize(line)
            if bullet is not None:
                markdown_lines.append(f"- {bullet}")
                continue
            heading_level = _heading_level(line)
            if heading_level is not None:
                markdown_lines.append(f"{'#' * heading_level} {line}")
                continue
            markdown_lines.append(line)

    markdown_lines = _collapse_blank_lines(markdown_lines)
    return "\n".join(markdown_lines).strip() + "\n", markdown_lines


def _build_chunks(
    spec: RegulationSpec,
    markdown_lines: Sequence[str],
    source_pdf_rel: str,
    source_markdown_rel: str,
) -> List[dict]:
    chunks: List[dict] = []
    heading_stack: List[str] = []
    current_page: int | None = None
    current_lines: List[str] = []
    chunk_pages: List[int] = []
    chunk_heading_path: List[str] = []
    chunk_index = 0

    def flush() -> None:
        nonlocal current_lines, chunk_pages, chunk_heading_path, chunk_index
        text = "\n".join(current_lines).strip()
        if not text:
            current_lines = []
            chunk_pages = []
            chunk_heading_path = []
            return
        chunk_index += 1
        chunks.append(
            {
                "chunk_id": f"{spec.document_id}-chunk-{chunk_index:04d}",
                "document_id": spec.document_id,
                "heading_path": chunk_heading_path,
                "page_start": min(chunk_pages) if chunk_pages else None,
                "page_end": max(chunk_pages) if chunk_pages else None,
                "char_count": len(text),
                "text": text,
                "source_pdf": source_pdf_rel,
                "source_markdown": source_markdown_rel,
            }
        )
        current_lines = []
        chunk_pages = []
        chunk_heading_path = []

    for line in markdown_lines:
        page_match = PAGE_ANCHOR_RE.match(line)
        if page_match:
            current_page = int(page_match.group(1))
            continue
        if not line.strip():
            if current_lines:
                current_lines.append("")
            continue
        if line.startswith("#"):
            flush()
            level = len(line) - len(line.lstrip("#"))
            heading = line[level:].strip()
            heading_stack = heading_stack[: max(level - 1, 0)]
            heading_stack.append(heading)
            continue
        if not current_lines:
            chunk_heading_path = list(heading_stack)
        current_lines.append(line)
        if current_page is not None:
            chunk_pages.append(current_page)
        current_text = "\n".join(current_lines).strip()
        if len(current_text) >= CHUNK_TARGET_CHARS:
            flush()
        elif len(current_text) >= CHUNK_MIN_CHARS and line.endswith(("。", "；", ":", "：")):
            flush()
    flush()
    return chunks


def _build_document_artifact(
    built: BuiltRegulation,
    manifest_dir: Path,
    source_manifest_path: Path,
) -> dict:
    extract_report_path = built.extract_dir / "extract_report.json"
    pages_path = built.extract_dir / "pages.jsonl"
    raw_text_path = built.extract_dir / "raw.txt"
    return {
        "document_id": built.spec.document_id,
        "title": built.spec.title,
        "source_kind": built.spec.source_kind,
        "canonical_source": _relative_to(manifest_dir, built.canonical_pdf_path),
        "canonical_pdf": (
            _relative_to(manifest_dir, built.canonical_pdf_path)
            if built.spec.source_kind == "pdf"
            else None
        ),
        "source_role": "independent" if built.spec.counts_as_independent_source else "alias",
        "alias_of_document_id": built.spec.alias_of_document_id,
        "counts_as_independent_source": built.spec.counts_as_independent_source,
        "canonical_markdown": _relative_to(manifest_dir, built.markdown_path),
        "extracted_pages": _relative_to(manifest_dir, pages_path),
        "raw_text": _relative_to(manifest_dir, raw_text_path),
        "extract_report": _relative_to(manifest_dir, extract_report_path),
        "document_artifact": _relative_to(manifest_dir, built.document_json_path),
        "chunk_file": _relative_to(manifest_dir, built.chunk_file_path),
        "page_count": built.page_count,
        "chunk_count": built.chunk_count,
        "sha256": built.sha256_hex,
        "markdown_strategy": built.markdown_strategy,
        "issue_count": len(built.issues),
        "source_manifest": _relative_to(manifest_dir, source_manifest_path),
    }


def build_regulation_corpus(project_root: Path | None = None) -> dict:
    project_root = project_root or _project_root()
    _ensure_layout(project_root)
    regulations_root = _regulations_root(project_root)
    manifest_dir = _manifest_dir(project_root)
    raw_dir = regulations_root / "raw"
    markdown_dir = regulations_root / "markdown"
    extracted_dir = regulations_root / "extracted"
    corpus_documents_dir = regulations_root / "corpus" / "documents"
    corpus_chunks_dir = regulations_root / "corpus" / "chunks"
    failed_dir = regulations_root / "failed"

    source_manifest_entries: List[dict] = []
    corpus_documents: List[dict] = []
    chunk_entries: List[dict] = []
    all_failures: List[dict] = []
    built_regulations: List[BuiltRegulation] = []

    for spec in REGULATION_SPECS:
        canonical_pdf_path = raw_dir / spec.canonical_pdf_name
        if not canonical_pdf_path.exists():
            copied = False
            for candidate_rel in spec.source_candidates:
                candidate = (project_root / candidate_rel).resolve()
                if candidate.exists():
                    canonical_pdf_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidate, canonical_pdf_path)
                    copied = True
                    break
            if not copied:
                raise FileNotFoundError(
                    f"Canonical PDF missing and no source candidate found for {spec.document_id}"
                )

        sha256_hex = _sha256(canonical_pdf_path)
        canonical_pdf_rel = _relative_to(project_root, canonical_pdf_path)
        if spec.source_kind == "markdown":
            source_text = canonical_pdf_path.read_text(encoding="utf-8")
            page_records, issues = _extract_page_records_from_markdown(source_text)
            markdown_text, markdown_lines, markdown_strategy = _render_native_markdown(
                spec=spec,
                project_root=project_root,
                canonical_pdf_rel=canonical_pdf_rel,
                sha256_hex=sha256_hex,
                canonical_source_path=canonical_pdf_path,
                page_records=page_records,
            )
        else:
            page_records, issues = _extract_page_records(canonical_pdf_path)
            if spec.preferred_markdown_candidates:
                markdown_text, markdown_lines, markdown_strategy = _render_curated_markdown(
                    spec=spec,
                    project_root=project_root,
                    canonical_pdf_rel=canonical_pdf_rel,
                    sha256_hex=sha256_hex,
                    page_records=page_records,
                )
            else:
                markdown_text, markdown_lines, markdown_strategy = _render_structured_markdown(
                    spec=spec,
                    canonical_pdf_path=canonical_pdf_path,
                    canonical_pdf_rel=canonical_pdf_rel,
                    sha256_hex=sha256_hex,
                    page_records=page_records,
                )

        spec_extract_dir = extracted_dir / spec.extract_dir_name
        spec_extract_dir.mkdir(parents=True, exist_ok=True)
        pages_path = spec_extract_dir / "pages.jsonl"
        raw_text_path = spec_extract_dir / "raw.txt"
        extract_report_path = spec_extract_dir / "extract_report.json"
        markdown_path = markdown_dir / f"{spec.document_id}.md"
        document_json_path = corpus_documents_dir / f"{spec.document_id}.json"
        chunk_file_path = corpus_chunks_dir / f"{spec.document_id}.jsonl"

        _write_jsonl(
            pages_path,
            (
                {
                    "page": record["page"],
                    "char_count": record["char_count"],
                    "line_count": record["line_count"],
                    "text": record["text"],
                }
                for record in page_records
            ),
        )
        raw_text = "\n\n".join(
            f"[page {record['page']}]\n{record['text']}".strip() for record in page_records
        ).strip()
        raw_text_path.write_text(raw_text + "\n", encoding="utf-8")

        _write_json(
            extract_report_path,
            {
                "document_id": spec.document_id,
                "canonical_pdf": canonical_pdf_rel,
                "markdown_strategy": markdown_strategy,
                "page_count": len(page_records),
                "issues": issues,
                "summary": {
                    "warning_count": sum(1 for issue in issues if issue["severity"] == "warning"),
                    "error_count": sum(1 for issue in issues if issue["severity"] == "error"),
                    "min_page_chars": min(record["char_count"] for record in page_records)
                    if page_records
                    else 0,
                    "max_page_chars": max(record["char_count"] for record in page_records)
                    if page_records
                    else 0,
                },
            },
        )
        markdown_path.write_text(markdown_text, encoding="utf-8")

        chunk_rows = _build_chunks(
            spec=spec,
            markdown_lines=markdown_lines,
            source_pdf_rel=canonical_pdf_rel,
            source_markdown_rel=_relative_to(project_root, markdown_path),
        )
        _write_jsonl(chunk_file_path, chunk_rows)

        built = BuiltRegulation(
            spec=spec,
            canonical_pdf_path=canonical_pdf_path,
            markdown_path=markdown_path,
            extract_dir=spec_extract_dir,
            document_json_path=document_json_path,
            chunk_file_path=chunk_file_path,
            page_count=len(page_records),
            chunk_count=len(chunk_rows),
            sha256_hex=sha256_hex,
            markdown_strategy=markdown_strategy,
            issues=issues,
        )
        built_regulations.append(built)

        duplicate_sources: List[dict] = []
        for candidate_rel in spec.source_candidates:
            candidate = (project_root / candidate_rel).resolve()
            duplicate_sources.append(
                {
                    "path": _relative_to(manifest_dir, candidate),
                    "exists": candidate.exists(),
                    "sha256": _sha256(candidate) if candidate.exists() else None,
                    "matches_canonical": candidate.exists()
                    and _sha256(candidate) == sha256_hex,
                }
            )

        source_manifest_entries.append(
            {
                "document_id": spec.document_id,
                "title": spec.title,
                "publisher": spec.publisher,
                "source_kind": spec.source_kind,
                "canonical_source": _relative_to(manifest_dir, canonical_pdf_path),
                "canonical_pdf": (
                    _relative_to(manifest_dir, canonical_pdf_path)
                    if spec.source_kind == "pdf"
                    else None
                ),
                "source_role": "independent" if spec.counts_as_independent_source else "alias",
                "alias_of_document_id": spec.alias_of_document_id,
                "counts_as_independent_source": spec.counts_as_independent_source,
                "sha256": sha256_hex,
                "page_count": len(page_records),
                "size_bytes": canonical_pdf_path.stat().st_size,
                "markdown_strategy": markdown_strategy,
                "duplicate_sources": duplicate_sources,
            }
        )

        all_failures.extend(
            {
                "document_id": spec.document_id,
                **issue,
            }
            for issue in issues
        )

    source_manifest_path = manifest_dir / "source_manifest.json"
    independent_document_ids = [
        spec.document_id for spec in REGULATION_SPECS if spec.counts_as_independent_source
    ]
    alias_document_ids = [
        spec.document_id for spec in REGULATION_SPECS if not spec.counts_as_independent_source
    ]
    _write_json(
        source_manifest_path,
        {
            "manifest_id": "regulation_source_manifest",
            "version": MANIFEST_VERSION,
            "canonical_root": "../raw",
            "artifact_document_count": len(source_manifest_entries),
            "independent_source_count": len(independent_document_ids),
            "alias_document_count": len(alias_document_ids),
            "independent_document_ids": independent_document_ids,
            "alias_document_ids": alias_document_ids,
            "documents": source_manifest_entries,
        },
    )

    for built in built_regulations:
        document_payload = _build_document_artifact(
            built=built,
            manifest_dir=manifest_dir,
            source_manifest_path=source_manifest_path,
        )
        _write_json(built.document_json_path, document_payload)
        corpus_documents.append(document_payload)
        chunk_entries.append(
            {
                "document_id": built.spec.document_id,
                "chunk_file": _relative_to(manifest_dir, built.chunk_file_path),
                "chunk_count": built.chunk_count,
                "page_count": built.page_count,
            }
        )

    corpus_manifest_path = manifest_dir / "corpus_manifest.json"
    _write_json(
        corpus_manifest_path,
        {
            "corpus_id": "hk_building_regulations",
            "version": MANIFEST_VERSION,
            "artifact_document_count": len(corpus_documents),
            "independent_source_count": len(independent_document_ids),
            "alias_document_count": len(alias_document_ids),
            "independent_document_ids": independent_document_ids,
            "alias_document_ids": alias_document_ids,
            "documents": corpus_documents,
        },
    )

    chunk_manifest_path = manifest_dir / "chunk_manifest.json"
    _write_json(
        chunk_manifest_path,
        {
            "manifest_id": "hk_building_regulations_chunks",
            "version": MANIFEST_VERSION,
            "artifact_document_count": len(chunk_entries),
            "independent_source_count": len(independent_document_ids),
            "alias_document_count": len(alias_document_ids),
            "total_chunks": sum(item["chunk_count"] for item in chunk_entries),
            "documents": chunk_entries,
        },
    )

    ingest_manifest_path = manifest_dir / "ingest_manifest.json"
    _write_json(
        ingest_manifest_path,
        {
            "corpus_id": "hk_building_regulations",
            "version": MANIFEST_VERSION,
            "artifact_document_count": len(corpus_documents),
            "independent_source_count": len(independent_document_ids),
            "alias_document_count": len(alias_document_ids),
            "independent_document_ids": independent_document_ids,
            "alias_document_ids": alias_document_ids,
            "source_manifest": _relative_to(manifest_dir, source_manifest_path),
            "corpus_manifest": _relative_to(manifest_dir, corpus_manifest_path),
            "chunk_manifest": _relative_to(manifest_dir, chunk_manifest_path),
            "documents": [
                {
                    "document_id": doc["document_id"],
                    "source_kind": doc.get("source_kind", "pdf"),
                    "source_role": doc.get("source_role", "independent"),
                    "alias_of_document_id": doc.get("alias_of_document_id"),
                    "counts_as_independent_source": doc.get("counts_as_independent_source", True),
                    "canonical_markdown": doc["canonical_markdown"],
                    "chunk_file": doc["chunk_file"],
                }
                for doc in corpus_documents
            ],
            "knowledge_base": {
                "entrypoint": "src/knowledge_base/ingestion.py",
                "markdown_files": [doc["canonical_markdown"] for doc in corpus_documents],
            },
            "relation_to_rule_skill_kg": {
                "current_mode": "parallel evidence corpus",
                "description": (
                    "Rule-Skill KG continues to encode fact-pattern/trigger/rule-card/skill "
                    "chains, while the regulation corpus provides page-grounded text evidence "
                    "for retrieval, chunking, and future indexing experiments."
                ),
            },
        },
    )

    _write_json(
        failed_dir / "extraction_failures.json",
        {
            "version": MANIFEST_VERSION,
            "issues": all_failures,
        },
    )

    return {
        "corpus_id": "hk_building_regulations",
        "version": MANIFEST_VERSION,
        "document_count": len(corpus_documents),
        "artifact_document_count": len(corpus_documents),
        "independent_source_count": len(independent_document_ids),
        "alias_document_count": len(alias_document_ids),
        "independent_document_ids": independent_document_ids,
        "alias_document_ids": alias_document_ids,
        "chunk_count": sum(item["chunk_count"] for item in chunk_entries),
        "documents": [
            {
                "document_id": built.spec.document_id,
                "source_kind": built.spec.source_kind,
                "source_role": "independent" if built.spec.counts_as_independent_source else "alias",
                "alias_of_document_id": built.spec.alias_of_document_id,
                "counts_as_independent_source": built.spec.counts_as_independent_source,
                "markdown": _relative_to(project_root, built.markdown_path),
                "chunk_file": _relative_to(project_root, built.chunk_file_path),
                "markdown_strategy": built.markdown_strategy,
                "issues": len(built.issues),
            }
            for built in built_regulations
        ],
        "manifests": {
            "source_manifest": _relative_to(project_root, source_manifest_path),
            "corpus_manifest": _relative_to(project_root, corpus_manifest_path),
            "chunk_manifest": _relative_to(project_root, chunk_manifest_path),
            "ingest_manifest": _relative_to(project_root, ingest_manifest_path),
        },
    }


def _validate_required_keys(payload: dict, keys: Sequence[str], label: str) -> None:
    for key in keys:
        if key not in payload:
            raise ValueError(f"{label} missing required key: {key}")


def load_regulation_corpus(ingest_manifest_path: Path) -> RegulationCorpus:
    ingest_manifest_path = ingest_manifest_path.resolve()
    base_dir = ingest_manifest_path.parent
    ingest_manifest = _read_json(ingest_manifest_path)
    _validate_required_keys(
        ingest_manifest,
        ("corpus_id", "version", "source_manifest", "corpus_manifest", "chunk_manifest", "documents", "knowledge_base"),
        "Ingest manifest",
    )

    source_manifest = _read_json((base_dir / ingest_manifest["source_manifest"]).resolve())
    corpus_manifest = _read_json((base_dir / ingest_manifest["corpus_manifest"]).resolve())
    chunk_manifest = _read_json((base_dir / ingest_manifest["chunk_manifest"]).resolve())

    _validate_required_keys(source_manifest, ("manifest_id", "version", "documents"), "Source manifest")
    _validate_required_keys(corpus_manifest, ("corpus_id", "version", "documents"), "Corpus manifest")
    _validate_required_keys(chunk_manifest, ("manifest_id", "version", "documents"), "Chunk manifest")

    documents: List[dict] = []
    chunks: List[dict] = []
    for document in ingest_manifest["documents"]:
        _validate_required_keys(
            document,
            ("document_id", "canonical_markdown", "chunk_file"),
            "Ingest document",
        )
        markdown_path = (base_dir / document["canonical_markdown"]).resolve()
        chunk_path = (base_dir / document["chunk_file"]).resolve()
        if not markdown_path.exists():
            raise FileNotFoundError(f"Canonical markdown missing: {markdown_path}")
        if not chunk_path.exists():
            raise FileNotFoundError(f"Chunk file missing: {chunk_path}")
        documents.append(
            {
                "document_id": document["document_id"],
                "canonical_markdown": document["canonical_markdown"],
                "chunk_file": document["chunk_file"],
            }
        )
        chunks.extend(_read_jsonl(chunk_path))

    return RegulationCorpus(
        ingest_manifest=ingest_manifest,
        source_manifest=source_manifest,
        corpus_manifest=corpus_manifest,
        chunk_manifest=chunk_manifest,
        documents=documents,
        chunks=chunks,
    )
