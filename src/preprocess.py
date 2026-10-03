"""Preprocesses security-standard documents into a unified, traceable clause dataset (Phase 1.5)."""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import bs4
import pypdf

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_CSV = PROCESSED_DIR / "clauses.csv"

CSV_COLUMNS = [
    "standard",
    "version",
    "document_role",
    "unit_type",
    "section",
    "clause_id",
    "page",
    "raw_text",
    "clean_text",
    "modality",
    "is_requirement_candidate",
    "source_file",
]

NORMATIVE_REGEX = re.compile(
    r"\b(shall|shall not|must|must not|should|should not|required to|is required|mandatory|obligation|complies with|requirements?\s+(?:in\s+this\s+paragraph\s+)?are\s+not\s+met)\b",
    re.IGNORECASE,
)


@dataclass
class ClauseRecord:
    standard: str
    version: str
    document_role: str
    unit_type: str
    section: str
    clause_id: str
    page: str
    raw_text: str
    clean_text: str
    modality: str
    is_requirement_candidate: bool
    source_file: str

    @property
    def original_text(self) -> str:
        """Backward-compatible alias for normalized text."""
        return self.clean_text

    @property
    def normative(self) -> bool:
        """Backward-compatible alias for normative requirement flag."""
        return self.modality in ("SHALL", "MUST")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_modality(text: str) -> str:
    """Extract requirement modality: SHALL | MUST | SHOULD | OTHER."""
    if re.search(r"\b(shall|shall not)\b", text, re.IGNORECASE):
        return "SHALL"
    if re.search(r"\b(must|must not)\b", text, re.IGNORECASE):
        return "MUST"
    if re.search(r"\b(should|should not|recommend|recommended)\b", text, re.IGNORECASE):
        return "SHOULD"
    return "OTHER"


def is_requirement_candidate_clause(
    text: str, document_role: str, unit_type: str, modality: str
) -> bool:
    """Determine whether the unit is a candidate for product requirement classification.
    
    - Product requirements (unit_type == 'requirement'): True.
    - Security capability statements (unit_type == 'capability'): True.
    - Assessment test steps (unit_type == 'assessment_step', e.g. TS 103 701): False
      because tester instructions are fundamentally distinct from product requirements.
    """
    if unit_type == "assessment_step" or document_role == "assessment":
        return False
    if unit_type in ("requirement", "capability"):
        return True
    if modality in ("SHALL", "MUST", "SHOULD"):
        return True
    return False


def is_normative_text(text: str) -> bool:
    """Check if text contains normative requirement phrasing."""
    return bool(NORMATIVE_REGEX.search(text))


def clean_text(text: str) -> str:
    """Normalize whitespace, unhyphenate broken words, and trim text."""
    # Unhyphenate words broken across line wraps (e.g., authen- tication -> authentication)
    text = re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", text)
    # Replace multiple whitespaces and newlines with a single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_etsi_en_303645(pdf_path: Path) -> List[ClauseRecord]:
    """Extract provisions from ETSI EN 303 645 V3.1.3 (Clauses 5 and 6)."""
    if not pdf_path.exists():
        logger.warning("ETSI EN 303 645 PDF not found at %s", pdf_path)
        return []

    reader = pypdf.PdfReader(str(pdf_path))
    records: List[ClauseRecord] = []

    def clean_page_lines(page_text: str) -> List[str]:
        lines: List[str] = []
        for l in page_text.split("\n"):
            ls = l.strip()
            if not ls:
                continue
            # Strip running headers and footers
            if ls == "ETSI" or re.match(r"^ETSI EN 303 645 V3\.1\.3.*", ls):
                continue
            lines.append(ls)
        return lines

    sec_re = re.compile(r"^(5\.\d+|6)\s+([A-Z].*)")
    prov_re = re.compile(r"^Provision\s+(5\.\d+-\d+[A-Za-z]?|6-\d+[A-Za-z]?|6\.\d+[A-Za-z]?)\s*(.*)")
    stop_re = re.compile(r"^(NOTE\s*\d*|EXAMPLE\s*\d*|Table\s+[A-Z0-9]|Clause\s+\d+|Annex\s+[A-Z])", re.IGNORECASE)

    current_section = "5 Baseline requirements for consumer IoT"
    # Clause 5 starts on page 12 (0-indexed 11); Clause 6 ends on page 29 (0-indexed 28)
    pages_lines = [(p + 1, clean_page_lines(reader.pages[p].extract_text())) for p in range(11, 29)]

    p_idx = 0
    while p_idx < len(pages_lines):
        page_num, lines = pages_lines[p_idx]
        l_idx = 0
        while l_idx < len(lines):
            line = lines[l_idx]
            sec_m = sec_re.match(line)
            if sec_m:
                current_section = f"{sec_m.group(1)} {sec_m.group(2)}"
                l_idx += 1
                continue

            prov_m = prov_re.match(line)
            if prov_m:
                clause_id = prov_m.group(1)
                first_text = prov_m.group(2).strip()

                # Skip void provisions
                if first_text.lower().startswith("void"):
                    l_idx += 1
                    continue

                collected: List[str] = []
                if first_text:
                    collected.append(first_text)

                cur_p_idx = p_idx
                cur_l_idx = l_idx + 1
                has_colon = ":" in first_text

                while True:
                    full_text = " ".join(collected)
                    # Complete when sentence ends with period, or bullet list finishes
                    if not has_colon and full_text.endswith("."):
                        break
                    if has_colon and len(collected) > 1 and full_text.endswith(".") and not collected[-1].endswith(":"):
                        # Check if next line is another bullet item
                        is_next_bullet = False
                        if cur_l_idx < len(pages_lines[cur_p_idx][1]):
                            peek = pages_lines[cur_p_idx][1][cur_l_idx]
                            if peek.startswith("•") or re.match(r"^\d+\)", peek) or peek.startswith("-"):
                                is_next_bullet = True
                        if not is_next_bullet:
                            break

                    if cur_l_idx >= len(pages_lines[cur_p_idx][1]):
                        cur_p_idx += 1
                        cur_l_idx = 0
                        if cur_p_idx >= len(pages_lines):
                            break
                        continue

                    next_line = pages_lines[cur_p_idx][1][cur_l_idx]
                    if prov_re.match(next_line) or sec_re.match(next_line) or stop_re.match(next_line):
                        break

                    if ":" in next_line:
                        has_colon = True

                    collected.append(next_line)
                    cur_l_idx += 1

                raw_val = "\n".join(collected)
                clean_val = clean_text(" ".join(collected))
                rel_path = str(pdf_path.relative_to(PROJECT_ROOT)) if pdf_path.is_relative_to(PROJECT_ROOT) else str(pdf_path)
                mod = extract_modality(clean_val)
                is_req = is_requirement_candidate_clause(clean_val, "requirement", "requirement", mod)

                records.append(ClauseRecord(
                    standard="ETSI EN 303 645",
                    version="V3.1.3",
                    document_role="requirement",
                    unit_type="requirement",
                    section=current_section,
                    clause_id=clause_id,
                    page=str(page_num),
                    raw_text=raw_val,
                    clean_text=clean_val,
                    modality=mod,
                    is_requirement_candidate=is_req,
                    source_file=rel_path,
                ))

                if cur_p_idx == p_idx:
                    l_idx = cur_l_idx
                else:
                    p_idx = cur_p_idx
                    lines = pages_lines[p_idx][1]
                    l_idx = cur_l_idx
                continue
            l_idx += 1
        p_idx += 1

    logger.info("ETSI EN 303 645: extracted %d provisions", len(records))
    return records


def extract_etsi_ts_103701(pdf_path: Path) -> List[ClauseRecord]:
    """Extract conformance assessment test units from ETSI TS 103 701 V2.1.1 (Clause 5)."""
    if not pdf_path.exists():
        logger.warning("ETSI TS 103 701 PDF not found at %s", pdf_path)
        return []

    reader = pypdf.PdfReader(str(pdf_path))
    records: List[ClauseRecord] = []

    def clean_page_lines(page_text: str) -> List[str]:
        lines: List[str] = []
        for l in page_text.split("\n"):
            ls = l.strip()
            if not ls or ls == "ETSI" or re.match(r"^ETSI TS 103 701 V2\.1\.1.*", ls):
                continue
            lines.append(ls)
        return lines

    sec_re = re.compile(r"^(5\.\d+(?:\.[0-9A-Za-z]+)?)\s+(TSO\s+.*|Test group\s+.*)")
    tc_re = re.compile(
        r"^(?:[0-9A-Za-z\.]+\s+)?Test case\s+([0-9A-Za-z\.-]+)\s*\((conceptual(?:/functional)?|functional)\)",
        re.IGNORECASE,
    )
    tu_re = re.compile(r"^([a-z])\)\s+(.*)", re.IGNORECASE)
    stop_re = re.compile(r"^(Assignment of verdict|Test purpose|NOTE\s*\d*|EXAMPLE\s*\d*)", re.IGNORECASE)

    current_section = "5 Technical Specification of Assessment Objectives (TSOs)"
    current_tc_id = ""

    rel_path = str(pdf_path.relative_to(PROJECT_ROOT)) if pdf_path.is_relative_to(PROJECT_ROOT) else str(pdf_path)

    # Clause 5 spans pages 23 to 105
    for p_idx in range(22, 105):
        page_num = p_idx + 1
        lines = clean_page_lines(reader.pages[p_idx].extract_text())
        i = 0
        while i < len(lines):
            line = lines[i]

            sec_m = sec_re.match(line)
            if sec_m:
                current_section = f"{sec_m.group(1)} {sec_m.group(2)}"
                i += 1
                continue

            tc_m = tc_re.match(line)
            if tc_m:
                current_tc_id = tc_m.group(1)
                i += 1
                continue

            tu_m = tu_re.match(line)
            if tu_m and current_tc_id:
                unit_letter = tu_m.group(1).lower()
                first_tu_text = tu_m.group(2).strip()

                tu_lines = [first_tu_text]
                i += 1
                while i < len(lines):
                    next_l = lines[i]
                    if tu_re.match(next_l) or stop_re.match(next_l) or tc_re.match(next_l) or sec_re.match(next_l):
                        break
                    tu_lines.append(next_l)
                    i += 1

                raw_val = "\n".join(tu_lines)
                clean_val = clean_text(" ".join(tu_lines))
                mod = extract_modality(clean_val)
                is_req = is_requirement_candidate_clause(clean_val, "assessment", "assessment_step", mod)

                records.append(ClauseRecord(
                    standard="ETSI TS 103 701",
                    version="V2.1.1",
                    document_role="assessment",
                    unit_type="assessment_step",
                    section=current_section,
                    clause_id=f"{current_tc_id} {unit_letter})",
                    page=str(page_num),
                    raw_text=raw_val,
                    clean_text=clean_val,
                    modality=mod,
                    is_requirement_candidate=is_req,
                    source_file=rel_path,
                ))
                continue
            i += 1

    logger.info("ETSI TS 103 701: extracted %d test unit requirements", len(records))
    return records


def extract_nistir_8259a(pdf_path: Path) -> List[ClauseRecord]:
    """Extract core capability baseline requirements from NISTIR 8259A Table 1."""
    if not pdf_path.exists():
        logger.warning("NISTIR 8259A PDF not found at %s", pdf_path)
        return []

    reader = pypdf.PdfReader(str(pdf_path))
    records: List[ClauseRecord] = []
    rel_path = str(pdf_path.relative_to(PROJECT_ROOT)) if pdf_path.is_relative_to(PROJECT_ROOT) else str(pdf_path)

    # Table 1: Core Device Cybersecurity Capability Baseline spans pages 11 to 16
    capabilities = [
        ("Device Identification", 11),
        ("Device Configuration", 12),
        ("Data Protection", 13),
        ("Logical Access to Interfaces", 14),
        ("Software Update", 15),
        ("Cybersecurity State Awareness", 16),
    ]

    elem_re = re.compile(r"^(\d+)\.\s+(.*)")

    for cap_name, page_num in capabilities:
        text = reader.pages[page_num - 1].extract_text()
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        current_elem_num = 0
        current_elem_lines: List[str] = []

        for line in lines:
            m = elem_re.match(line)
            if m:
                if current_elem_num > 0 and current_elem_lines:
                    raw_val = "\n".join(current_elem_lines)
                    clean_val = clean_text(" ".join(current_elem_lines))
                    mod = extract_modality(clean_val)
                    is_req = is_requirement_candidate_clause(clean_val, "guidance", "capability", mod)
                    records.append(ClauseRecord(
                        standard="NISTIR 8259A",
                        version="Final",
                        document_role="guidance",
                        unit_type="capability",
                        section=f"Table 1: {cap_name}",
                        clause_id=f"{cap_name} - Element {current_elem_num}",
                        page=str(page_num),
                        raw_text=raw_val,
                        clean_text=clean_val,
                        modality=mod,
                        is_requirement_candidate=is_req,
                        source_file=rel_path,
                    ))
                current_elem_num = int(m.group(1))
                current_elem_lines = [m.group(2)]
            elif current_elem_num > 0:
                # Stop reading element text when hitting Rationale, Note, or Examples
                if any(line.startswith(stop) for stop in ["•", "Note:", "Rationale", "IoT Reference", "Device Cybersecurity", "Capability"]):
                    if current_elem_num > 0 and current_elem_lines:
                        raw_val = "\n".join(current_elem_lines)
                        clean_val = clean_text(" ".join(current_elem_lines))
                        mod = extract_modality(clean_val)
                        is_req = is_requirement_candidate_clause(clean_val, "guidance", "capability", mod)
                        records.append(ClauseRecord(
                            standard="NISTIR 8259A",
                            version="Final",
                            document_role="guidance",
                            unit_type="capability",
                            section=f"Table 1: {cap_name}",
                            clause_id=f"{cap_name} - Element {current_elem_num}",
                            page=str(page_num),
                            raw_text=raw_val,
                            clean_text=clean_val,
                            modality=mod,
                            is_requirement_candidate=is_req,
                            source_file=rel_path,
                        ))
                        current_elem_num = 0
                        current_elem_lines = []
                    continue
                current_elem_lines.append(line)

        if current_elem_num > 0 and current_elem_lines:
            raw_val = "\n".join(current_elem_lines)
            clean_val = clean_text(" ".join(current_elem_lines))
            mod = extract_modality(clean_val)
            is_req = is_requirement_candidate_clause(clean_val, "guidance", "capability", mod)
            records.append(ClauseRecord(
                standard="NISTIR 8259A",
                version="Final",
                document_role="guidance",
                unit_type="capability",
                section=f"Table 1: {cap_name}",
                clause_id=f"{cap_name} - Element {current_elem_num}",
                page=str(page_num),
                raw_text=raw_val,
                clean_text=clean_val,
                modality=mod,
                is_requirement_candidate=is_req,
                source_file=rel_path,
            ))

    logger.info("NISTIR 8259A: extracted %d capability elements", len(records))
    return records


def extract_nistir_8259b(pdf_path: Path) -> List[ClauseRecord]:
    """Extract non-technical capability baseline requirements from NISTIR 8259B Table 1."""
    if not pdf_path.exists():
        logger.warning("NISTIR 8259B PDF not found at %s", pdf_path)
        return []

    reader = pypdf.PdfReader(str(pdf_path))
    records: List[ClauseRecord] = []
    rel_path = str(pdf_path.relative_to(PROJECT_ROOT)) if pdf_path.is_relative_to(PROJECT_ROOT) else str(pdf_path)

    # Table 1: Non-Technical Supporting Capabilities spans pages 12 to 16
    capabilities = [
        ("Documentation", [12, 13]),
        ("Information and Query Reception", [14]),
        ("Information Dissemination", [15]),
        ("Device Education and Awareness", [16]),
    ]

    elem_re = re.compile(r"^(\d+)\.\s+(.*)")

    for cap_name, page_nums in capabilities:
        full_lines = []
        for p in page_nums:
            t = reader.pages[p - 1].extract_text()
            for l in t.split("\n"):
                full_lines.append((p, l.strip()))

        current_elem_num = 0
        current_elem_lines: List[str] = []
        start_page = page_nums[0]

        for p_num, line in full_lines:
            if not line:
                continue
            m = elem_re.match(line)
            if m:
                if current_elem_num > 0 and current_elem_lines:
                    raw_val = "\n".join(current_elem_lines)
                    clean_val = clean_text(" ".join(current_elem_lines))
                    mod = extract_modality(clean_val)
                    is_req = is_requirement_candidate_clause(clean_val, "guidance", "capability", mod)
                    records.append(ClauseRecord(
                        standard="NISTIR 8259B",
                        version="Final",
                        document_role="guidance",
                        unit_type="capability",
                        section=f"Table 1: {cap_name}",
                        clause_id=f"{cap_name} - Element {current_elem_num}",
                        page=str(start_page),
                        raw_text=raw_val,
                        clean_text=clean_val,
                        modality=mod,
                        is_requirement_candidate=is_req,
                        source_file=rel_path,
                    ))
                current_elem_num = int(m.group(1))
                start_page = p_num
                current_elem_lines = [m.group(2)]
            elif current_elem_num > 0:
                if any(line.startswith(stop) for stop in ["•", "Note:", "Rationale", "IoT Reference", "Non-Technical", "Supporting", "NISTIR 8259B"]):
                    if current_elem_num > 0 and current_elem_lines:
                        raw_val = "\n".join(current_elem_lines)
                        clean_val = clean_text(" ".join(current_elem_lines))
                        mod = extract_modality(clean_val)
                        is_req = is_requirement_candidate_clause(clean_val, "guidance", "capability", mod)
                        records.append(ClauseRecord(
                            standard="NISTIR 8259B",
                            version="Final",
                            document_role="guidance",
                            unit_type="capability",
                            section=f"Table 1: {cap_name}",
                            clause_id=f"{cap_name} - Element {current_elem_num}",
                            page=str(start_page),
                            raw_text=raw_val,
                            clean_text=clean_val,
                            modality=mod,
                            is_requirement_candidate=is_req,
                            source_file=rel_path,
                        ))
                        current_elem_num = 0
                        current_elem_lines = []
                    continue
                current_elem_lines.append(line)

        if current_elem_num > 0 and current_elem_lines:
            raw_val = "\n".join(current_elem_lines)
            clean_val = clean_text(" ".join(current_elem_lines))
            mod = extract_modality(clean_val)
            is_req = is_requirement_candidate_clause(clean_val, "guidance", "capability", mod)
            records.append(ClauseRecord(
                standard="NISTIR 8259B",
                version="Final",
                document_role="guidance",
                unit_type="capability",
                section=f"Table 1: {cap_name}",
                clause_id=f"{cap_name} - Element {current_elem_num}",
                page=str(start_page),
                raw_text=raw_val,
                clean_text=clean_val,
                modality=mod,
                is_requirement_candidate=is_req,
                source_file=rel_path,
            ))

    logger.info("NISTIR 8259B: extracted %d capability elements", len(records))
    return records


def extract_cra_regulation(html_path: Path) -> List[ClauseRecord]:
    """Extract mandatory cybersecurity requirements from CRA Regulation (EU) 2024/2847."""
    if not html_path.exists():
        logger.warning("CRA HTML not found at %s", html_path)
        return []

    soup = bs4.BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    records: List[ClauseRecord] = []
    rel_path = str(html_path.relative_to(PROJECT_ROOT)) if html_path.is_relative_to(PROJECT_ROOT) else str(html_path)

    # Article 13: Obligations of manufacturers
    art13 = soup.find("section", id="article-13")
    if art13:
        for p in art13.find_all("p", id=re.compile(r"^art-13-\d+")):
            cid = p["id"].replace("art-13-", "Art. 13(") + ")"
            raw_val = p.get_text()
            clean_val = clean_text(raw_val)
            mod = extract_modality(clean_val)
            records.append(ClauseRecord(
                standard="EU CRA",
                version="Regulation 2024/2847",
                document_role="regulation",
                unit_type="requirement",
                section="Article 13 Obligations of manufacturers",
                clause_id=cid,
                page="",
                raw_text=raw_val,
                clean_text=clean_val,
                modality=mod,
                is_requirement_candidate=True,
                source_file=rel_path,
            ))

    # Annex I Part I: Essential cybersecurity requirements
    annex1_p1 = soup.find("section", id="annex-I-part-I")
    if annex1_p1:
        # Paragraph 1
        p1 = annex1_p1.find("p", id="annex-I-1")
        if p1:
            raw_val = p1.get_text()
            clean_val = clean_text(raw_val)
            mod = extract_modality(clean_val)
            records.append(ClauseRecord(
                standard="EU CRA",
                version="Regulation 2024/2847",
                document_role="regulation",
                unit_type="requirement",
                section="Annex I Part I Essential cybersecurity requirements",
                clause_id="Annex I, Part I, 1",
                page="",
                raw_text=raw_val,
                clean_text=clean_val,
                modality=mod,
                is_requirement_candidate=True,
                source_file=rel_path,
            ))

        # Paragraph 2 lead-in and points (a) to (m) in strict DOM order
        p2 = annex1_p1.find("p", id="annex-I-2")
        p2_leadin_raw = p2.get_text() if p2 else ""
        p2_leadin = clean_text(p2_leadin_raw)
        p2_leadin = re.sub(r"^2\.\s*", "", p2_leadin).strip()

        for li in annex1_p1.find_all("li", id=re.compile(r"^annex-I-2-[a-z]")):
            letter = li["id"].replace("annex-I-2-", "")
            cid = f"Annex I, Part I, 2({letter})"
            li_raw = li.get_text()
            li_txt = clean_text(li_raw)
            raw_val = f"{p2_leadin_raw}\n{li_raw}"
            clean_val = f"{p2_leadin} {li_txt}" if p2_leadin else li_txt
            mod = extract_modality(clean_val)
            records.append(ClauseRecord(
                standard="EU CRA",
                version="Regulation 2024/2847",
                document_role="regulation",
                unit_type="requirement",
                section="Annex I Part I Essential cybersecurity requirements",
                clause_id=cid,
                page="",
                raw_text=raw_val,
                clean_text=clean_val,
                modality=mod,
                is_requirement_candidate=True,
                source_file=rel_path,
            ))

        # Paragraph 3
        p3 = annex1_p1.find("p", id="annex-I-3")
        if p3:
            raw_val = p3.get_text()
            clean_val = clean_text(raw_val)
            mod = extract_modality(clean_val)
            records.append(ClauseRecord(
                standard="EU CRA",
                version="Regulation 2024/2847",
                document_role="regulation",
                unit_type="requirement",
                section="Annex I Part I Essential cybersecurity requirements",
                clause_id="Annex I, Part I, 3",
                page="",
                raw_text=raw_val,
                clean_text=clean_val,
                modality=mod,
                is_requirement_candidate=True,
                source_file=rel_path,
            ))

    # Annex I Part II: Vulnerability handling requirements
    annex1_p2 = soup.find("section", id="annex-I-part-II")
    if annex1_p2:
        leadin_p = annex1_p2.find("p")
        leadin_raw = leadin_p.get_text() if leadin_p else "Manufacturers of products with digital elements shall:"
        leadin_txt = clean_text(leadin_raw)
        for li in annex1_p2.find_all("li", id=re.compile(r"^annex-I-part-II-\d+")):
            cid = li["id"].replace("annex-I-part-II-", "Annex I, Part II, ")
            item_raw = li.get_text()
            item_txt = clean_text(item_raw)
            raw_val = f"{leadin_raw}\n{item_raw}"
            clean_val = f"{leadin_txt} {item_txt}"
            mod = extract_modality(clean_val)
            records.append(ClauseRecord(
                standard="EU CRA",
                version="Regulation 2024/2847",
                document_role="regulation",
                unit_type="requirement",
                section="Annex I Part II Vulnerability handling requirements",
                clause_id=cid,
                page="",
                raw_text=raw_val,
                clean_text=clean_val,
                modality=mod,
                is_requirement_candidate=True,
                source_file=rel_path,
            ))

    # Annex II: Information and instructions to the user
    annex2 = soup.find("section", id="annex-II")
    if annex2:
        leadin_p = annex2.find("p")
        leadin_raw = leadin_p.get_text() if leadin_p else "As a minimum, the product with digital elements shall be accompanied by:"
        leadin_txt = clean_text(leadin_raw)
        for li in annex2.find_all("li", id=re.compile(r"^annex-II-\d+")):
            cid = li["id"].replace("annex-II-", "Annex II, ")
            item_raw = li.get_text()
            item_txt = clean_text(item_raw)
            raw_val = f"{leadin_raw}\n{item_raw}"
            clean_val = f"{leadin_txt} {item_txt}"
            mod = extract_modality(clean_val)
            records.append(ClauseRecord(
                standard="EU CRA",
                version="Regulation 2024/2847",
                document_role="regulation",
                unit_type="requirement",
                section="Annex II Information and instructions to the user",
                clause_id=cid,
                page="",
                raw_text=raw_val,
                clean_text=clean_val,
                modality=mod,
                is_requirement_candidate=True,
                source_file=rel_path,
            ))

    logger.info("EU CRA 2024/2847: extracted %d requirements", len(records))
    return records


def extract_uk_psti(html_path: Path) -> List[ClauseRecord]:
    """Extract mandatory provisions from UK PSTI 2023 (SI 2023/1007, Schedules 1 and 2)."""
    if not html_path.exists():
        logger.warning("PSTI HTML not found at %s", html_path)
        return []

    soup = bs4.BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    records: List[ClauseRecord] = []
    rel_path = str(html_path.relative_to(PROJECT_ROOT)) if html_path.is_relative_to(PROJECT_ROOT) else str(html_path)

    target_provisions = [
        # Schedule 1: Security requirements for manufacturers
        ("Schedule 1", "Passwords", "1", "2"),
        ("Schedule 1", "Passwords", "1", "3"),
        ("Schedule 1", "Information on how to report security issues", "2", "2"),
        ("Schedule 1", "Information on how to report security issues", "2", "3"),
        ("Schedule 1", "Information on minimum security update periods", "3", "2"),
        ("Schedule 1", "Information on minimum security update periods", "3", "3"),
        ("Schedule 1", "Information on minimum security update periods", "3", "4"),
        ("Schedule 1", "Information on minimum security update periods", "3", "5"),
        ("Schedule 1", "Information on minimum security update periods", "3", "6"),
        # Schedule 2: Conditions for deemed compliance
        ("Schedule 2", "Passwords", "1", "2"),
        ("Schedule 2", "Information on how to report security issues", "2", "2"),
        ("Schedule 2", "Information on how to report security issues", "2", "3"),
        ("Schedule 2", "Information on how to report security issues", "2", "4"),
        ("Schedule 2", "Information on minimum security update periods", "3", "2"),
        ("Schedule 2", "Information on minimum security update periods", "3", "3"),
        ("Schedule 2", "Information on minimum security update periods", "3", "4"),
    ]

    for sched, sec_title, p_num, sp_num in target_provisions:
        found_p = None
        for p in soup.find_all("p", class_="LegP2ParaText"):
            t = p.get_text()
            if t.startswith(f"({sp_num})"):
                prev_h3 = p.find_previous("h3", class_="LegP1GroupTitle")
                prev_sched = p.find_previous("h2", class_=re.compile(r"LegSchedule"))
                if prev_sched and sched.upper() in prev_sched.get_text().upper() and prev_h3 and sec_title.upper() in prev_h3.get_text().upper():
                    found_p = p
                    break

        if found_p:
            parts = [found_p.get_text()]
            curr = found_p.find_next_sibling()
            while curr and curr.name == "p" and (
                "LegP3Container" in curr.get("class", []) or "LegP4Container" in curr.get("class", [])
            ):
                parts.append(curr.get_text())
                curr = curr.find_next_sibling()

            raw_val = "\n".join(parts)
            clean_val = clean_text(" ".join(parts))
            mod = extract_modality(clean_val)

            records.append(ClauseRecord(
                standard="UK PSTI",
                version="SI 2023/1007",
                document_role="regulation",
                unit_type="requirement",
                section=f"{sched}: {sec_title}",
                clause_id=f"{sched}, Paragraph {p_num}({sp_num})",
                page="",
                raw_text=raw_val,
                clean_text=clean_val,
                modality=mod,
                is_requirement_candidate=True,
                source_file=rel_path,
            ))

    logger.info("UK PSTI 2023: extracted %d requirements", len(records))
    return records


def extract_nist_catalog(catalog_dir: Path) -> List[ClauseRecord]:
    """Extract capability items from NIST IoT Cybersecurity Catalog HTML files."""
    if not catalog_dir.exists() or not catalog_dir.is_dir():
        logger.warning("NIST Catalog directory not found at %s", catalog_dir)
        return []

    records: List[ClauseRecord] = []
    html_files = sorted(catalog_dir.glob("*.html"))

    for p in html_files:
        soup = bs4.BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser")
        fname = p.stem
        category = fname.replace("technical_", "").replace("nontechnical_", "").capitalize()
        rel_path = str(p.relative_to(PROJECT_ROOT)) if p.is_relative_to(PROJECT_ROOT) else str(p)

        container = soup.find("div", class_="container")
        if not container:
            continue

        current_h1 = category
        item_idx = 0
        for elem in container.find_all(["h1", "li"]):
            if elem.name == "h1":
                txt = elem.get_text(strip=True)
                if txt not in ["Technical Capabilities", "Non-Technical Capabilities"]:
                    current_h1 = txt
            elif elem.name == "li":
                raw_txt = elem.get_text()
                # Exclude nested examples or non-requirement notes
                if "Example" in raw_txt:
                    raw_txt = raw_txt.split("Example")[0]
                clean_txt = clean_text(raw_txt)
                if any(clean_txt.startswith(w) for w in ["Ability", "Document", "Educate", "Make customers", "Establish", "Maintain"]):
                    item_idx += 1
                    mod = extract_modality(clean_txt)
                    is_req = is_requirement_candidate_clause(clean_txt, "guidance", "capability", mod)
                    records.append(ClauseRecord(
                        standard="NIST IoT Catalog",
                        version="Current Public",
                        document_role="guidance",
                        unit_type="capability",
                        section=f"Catalog: {current_h1}",
                        clause_id=f"{fname}-{item_idx}",
                        page="",
                        raw_text=raw_txt,
                        clean_text=clean_txt,
                        modality=mod,
                        is_requirement_candidate=is_req,
                        source_file=rel_path,
                    ))

    logger.info("NIST IoT Catalog: extracted %d capability items", len(records))
    return records


def preprocess_all(
    raw_dir: Path = RAW_DIR,
    output_path: Path = OUTPUT_CSV,
) -> List[ClauseRecord]:
    """Execute complete extraction pipeline across all standard documents."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    all_clauses: List[ClauseRecord] = []

    # 1. ETSI EN 303 645
    en_pdf = raw_dir / "etsi" / "etsi_en_303645_v313.pdf"
    all_clauses.extend(extract_etsi_en_303645(en_pdf))

    # 2. ETSI TS 103 701
    ts_pdf = raw_dir / "etsi" / "etsi_ts_103701_v211.pdf"
    all_clauses.extend(extract_etsi_ts_103701(ts_pdf))

    # 3. NISTIR 8259A
    nist_a_pdf = raw_dir / "nist" / "nistir_8259a.pdf"
    all_clauses.extend(extract_nistir_8259a(nist_a_pdf))

    # 4. NISTIR 8259B
    nist_b_pdf = raw_dir / "nist" / "nistir_8259b.pdf"
    all_clauses.extend(extract_nistir_8259b(nist_b_pdf))

    # 5. CRA Regulation EU 2024/2847
    cra_html = raw_dir / "cra" / "cra_regulation_2024_2847.html"
    all_clauses.extend(extract_cra_regulation(cra_html))

    # 6. UK PSTI SI 2023/1007
    psti_html = raw_dir / "psti" / "uk_psti_2023_1007.html"
    all_clauses.extend(extract_uk_psti(psti_html))

    # 7. NIST Catalog
    cat_dir = raw_dir / "nist" / "catalog"
    all_clauses.extend(extract_nist_catalog(cat_dir))

    # Write output CSV
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in all_clauses:
            writer.writerow(record.to_dict())

    logger.info("Successfully wrote %d clause records to %s", len(all_clauses), output_path)
    return all_clauses


def main() -> int:
    """CLI runner for preprocessing pipeline."""
    clauses = preprocess_all()
    print(f"\nPreprocessing complete. Total clauses extracted: {len(clauses)}")
    by_standard: Dict[str, int] = {}
    by_unit_type: Dict[str, int] = {}
    by_modality: Dict[str, int] = {}
    req_candidates = 0

    for c in clauses:
        by_standard[c.standard] = by_standard.get(c.standard, 0) + 1
        by_unit_type[c.unit_type] = by_unit_type.get(c.unit_type, 0) + 1
        by_modality[c.modality] = by_modality.get(c.modality, 0) + 1
        if c.is_requirement_candidate:
            req_candidates += 1

    print("\nBy Standard:")
    for std, count in sorted(by_standard.items()):
        print(f"  - {std}: {count} clauses")

    print("\nBy Unit Type:")
    for utype, count in sorted(by_unit_type.items()):
        print(f"  - {utype}: {count}")

    print("\nBy Modality:")
    for mod, count in sorted(by_modality.items()):
        print(f"  - {mod}: {count}")

    print(f"\nRequirement Candidates (for C1-C5 classification): {req_candidates}")
    print(f"Auxiliary Assessment Steps (TS 103 701): {len(clauses) - req_candidates}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
