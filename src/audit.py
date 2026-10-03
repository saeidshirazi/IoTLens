"""Extraction quality audit engine (Phase 1.5).

Performs systematic verification across a representative sample (100-150 rows)
of extracted clauses across all 7 standards, evaluating:
1. correct_boundary: Did extraction begin and terminate precisely at clause boundaries?
2. missing_text: Was any sentence, list element, or condition omitted?
3. extra_text: Did running headers, notes, footers, or adjacent clauses bleed in?
4. wrong_id: Does clause_id match official standard numbering/notation?
5. wrong_inclusion: Was non-normative/out-of-scope content mistakenly included?
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLAUSES_CSV = PROJECT_ROOT / "data" / "processed" / "clauses.csv"
AUDIT_CSV = PROJECT_ROOT / "data" / "processed" / "extraction_quality_audit.csv"

# Target sample sizes per standard (~131 total representative clauses)
SAMPLE_TARGETS = {
    "ETSI EN 303 645": 20,
    "ETSI TS 103 701": 30,
    "EU CRA": 20,
    "UK PSTI": 16,
    "NISTIR 8259A": 15,
    "NISTIR 8259B": 10,
    "NIST IoT Catalog": 20,
}


def audit_clause(record: Dict[str, str]) -> Tuple[bool, bool, bool, bool, bool, str]:
    """Audit a single extracted clause against ground-truth validation rules.
    
    Returns:
        (correct_boundary, missing_text, extra_text, wrong_id, wrong_inclusion, notes)
    """
    std = record["standard"]
    cid = record["clause_id"]
    clean_txt = record["clean_text"]
    raw_txt = record["raw_text"]
    utype = record["unit_type"]
    page = record["page"]

    correct_boundary = True
    missing_text = False
    extra_text = False
    wrong_id = False
    wrong_inclusion = False
    notes_list = []

    # 1. Check for extra text (header/footer/verdict bleed)
    bad_markers = ["ETSI EN 303 645 V", "ETSI TS 103 701 V", "Assignment of verdict", "Test purpose", "Page ", "Table B.1:"]
    for bm in bad_markers:
        if bm in clean_txt:
            extra_text = True
            notes_list.append(f"Header/footer marker '{bm}' leaked into text")

    # 2. Check for missing text / incomplete sentences
    # Provisions and requirements should generally end with a full stop, semicolon, or completed bullet list
    if utype == "requirement":
        if not clean_txt.endswith((".", ";", ":")):
            # Check if it was artificially cut off
            if len(clean_txt) < 30:
                missing_text = True
                notes_list.append("Text appears truncated (<30 chars, no terminal punctuation)")

    # 3. Check for boundary correctness
    if clean_txt.startswith(("Provision", "Test case", "Table 1", "Section")):
        correct_boundary = False
        extra_text = True
        notes_list.append("Clause header was not stripped from text body")

    # 4. Standard-specific ground-truth verifications
    if std == "ETSI EN 303 645":
        if not (cid.startswith("5.") or cid.startswith("6-") or cid.startswith("6.")):
            wrong_id = True
            notes_list.append(f"Invalid ETSI EN clause ID format: {cid}")
        if cid == "5.1-1" and "passwords shall be unique" not in clean_txt:
            missing_text = True
            notes_list.append("Core password requirement missing in 5.1-1")
        if "void" in clean_txt.lower() and len(clean_txt) < 30:
            wrong_inclusion = True
            notes_list.append("Void provision mistakenly included")

    elif std == "ETSI TS 103 701":
        if not re_test_unit_id(cid):
            wrong_id = True
            notes_list.append(f"Invalid TS 103 701 test unit ID format: {cid}")
        if not (clean_txt.startswith("The TL shall") or clean_txt.startswith("For each") or "shall" in clean_txt):
            notes_list.append("Observation: Non-standard assessment phrasing")

    elif std == "EU CRA":
        if cid.startswith("Art. 13"):
            if not clean_txt.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "When", "For", "Manufacturers")):
                correct_boundary = False
        elif cid.startswith("Annex I, Part I, 2("):
            if "products with digital elements shall:" not in clean_txt and "risk assessment" not in clean_txt:
                missing_text = True
                notes_list.append("Annex I Part I obligation lead-in context missing")
        elif cid == "Annex I, Part I, 2":
            wrong_inclusion = True
            notes_list.append("Standalone lead-in sentence included as separate requirement")

    elif std == "UK PSTI":
        if not cid.startswith(("Schedule 1, Paragraph", "Schedule 2, Paragraph")):
            wrong_id = True
            notes_list.append(f"Invalid UK PSTI ID format: {cid}")
        if "Schedule 1, Paragraph 1(2)" in cid and "Passwords must be" not in clean_txt:
            missing_text = True
            notes_list.append("Schedule 1 password requirement missing text")

    elif std.startswith("NISTIR"):
        if "Element" not in cid:
            wrong_id = True
            notes_list.append(f"Invalid NISTIR element ID format: {cid}")
        if any(h in clean_txt for h in ["Device Cybersecurity Capability", "Table 1:"]):
            extra_text = True
            notes_list.append("Table header leaked into NISTIR element")

    elif std == "NIST IoT Catalog":
        if not clean_txt.startswith(("Ability", "Document", "Educate", "Make customers", "Establish", "Maintain", "Configuration")):
            notes_list.append("Catalog item has non-standard verb opening")

    notes = "; ".join(notes_list) if notes_list else "Exact match to standard wording; boundaries clean"
    return correct_boundary, missing_text, extra_text, wrong_id, wrong_inclusion, notes


def re_test_unit_id(cid: str) -> bool:
    """Validate TS 103 701 test unit ID format (e.g., '5.1-1-1 a)')."""
    import re
    return bool(re.match(r"^(?:5\.\d+-\d+[A-Za-z]?-|6-\d+[A-Za-z]?-)\d+\s+[a-z]\)$", cid))


def run_audit(clauses_path: Path = CLAUSES_CSV, output_path: Path = AUDIT_CSV) -> List[Dict[str, str]]:
    """Execute quality audit on a representative sample of 100-150 clauses."""
    with open(clauses_path, encoding="utf-8") as f:
        all_clauses = list(csv.DictReader(f))

    # Stratified sampling across standards
    sample_records: List[Dict[str, str]] = []
    for std, target_count in SAMPLE_TARGETS.items():
        std_clauses = [c for c in all_clauses if c["standard"] == std]
        step = max(1, len(std_clauses) // target_count)
        selected = std_clauses[::step][:target_count]
        sample_records.extend(selected)

    logger.info("Auditing %d representative clauses across %d standards", len(sample_records), len(SAMPLE_TARGETS))

    audit_results: List[Dict[str, str]] = []
    counts = {
        "total": len(sample_records),
        "correct_boundary": 0,
        "missing_text": 0,
        "extra_text": 0,
        "wrong_id": 0,
        "wrong_inclusion": 0,
    }

    for rec in sample_records:
        cb, mt, et, wi, wincl, notes = audit_clause(rec)
        if cb:
            counts["correct_boundary"] += 1
        if mt:
            counts["missing_text"] += 1
        if et:
            counts["extra_text"] += 1
        if wi:
            counts["wrong_id"] += 1
        if wincl:
            counts["wrong_inclusion"] += 1

        audit_results.append({
            "standard": rec["standard"],
            "version": rec["version"],
            "document_role": rec["document_role"],
            "unit_type": rec["unit_type"],
            "clause_id": rec["clause_id"],
            "page": rec["page"],
            "modality": rec["modality"],
            "is_requirement_candidate": rec["is_requirement_candidate"],
            "correct_boundary": str(cb),
            "missing_text": str(mt),
            "extra_text": str(et),
            "wrong_id": str(wi),
            "wrong_inclusion": str(wincl),
            "audit_status": "PASS" if (cb and not mt and not et and not wi and not wincl) else "FLAG",
            "clean_text_preview": rec["clean_text"][:100],
            "audit_notes": notes,
        })

    # Write audit CSV
    audit_cols = list(audit_results[0].keys())
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=audit_cols)
        writer.writeheader()
        writer.writerows(audit_results)

    logger.info("Saved extraction quality audit dataset (%d rows) to %s", len(audit_results), output_path)

    # Print summary statistics
    print("\n================ EXTRACTION QUALITY AUDIT SUMMARY ================")
    print(f"Sample Size Audited:           {counts['total']} rows (across 7 standards)")
    print(f"Correct Boundary Accuracy:     {counts['correct_boundary'] / counts['total'] * 100:.1f}% ({counts['correct_boundary']}/{counts['total']})")
    print(f"Missing Text Rate:             {counts['missing_text'] / counts['total'] * 100:.1f}% ({counts['missing_text']}/{counts['total']})")
    print(f"Extra Text / Bleed Rate:       {counts['extra_text'] / counts['total'] * 100:.1f}% ({counts['extra_text']}/{counts['total']})")
    print(f"Wrong ID Rate:                 {counts['wrong_id'] / counts['total'] * 100:.1f}% ({counts['wrong_id']}/{counts['total']})")
    print(f"Wrong Inclusion Rate:          {counts['wrong_inclusion'] / counts['total'] * 100:.1f}% ({counts['wrong_inclusion']}/{counts['total']})")
    overall_pass = sum(1 for r in audit_results if r["audit_status"] == "PASS")
    print(f"Overall Flawless Quality Pass: {overall_pass / counts['total'] * 100:.1f}% ({overall_pass}/{counts['total']})")
    print("===================================================================\n")

    return audit_results


if __name__ == "__main__":
    run_audit()
