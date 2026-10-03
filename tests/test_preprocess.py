"""Unit tests for standard clause preprocessing and validation."""

import csv
import unittest
from pathlib import Path

from src.preprocess import CSV_COLUMNS, OUTPUT_CSV, PROJECT_ROOT, preprocess_all


class TestClausePreprocessing(unittest.TestCase):
    """Test suite for security standard preprocessing pipeline."""

    @classmethod
    def setUpClass(cls):
        # Run preprocessing to ensure dataset is current
        cls.clauses = preprocess_all()
        cls.csv_path = OUTPUT_CSV

    def test_output_csv_exists_and_schema_valid(self):
        """Verify output CSV file exists and has the exact required schema."""
        self.assertTrue(self.csv_path.exists(), f"Missing output CSV: {self.csv_path}")

        with open(self.csv_path, mode="r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            self.assertEqual(header, CSV_COLUMNS, f"Header mismatch: {header} != {CSV_COLUMNS}")

            rows = list(reader)
            self.assertGreater(len(rows), 0, "Output CSV is empty")
            for idx, row in enumerate(rows, start=2):
                self.assertEqual(
                    len(row),
                    len(CSV_COLUMNS),
                    f"Row {idx} has {len(row)} columns, expected {len(CSV_COLUMNS)}",
                )

    def test_etsi_en_303645_provisions_integrity(self):
        """Verify ETSI EN 303 645 extracts exactly 78 provisions with complete text and valid pages."""
        etsi_en_clauses = [c for c in self.clauses if c.standard == "ETSI EN 303 645"]
        self.assertEqual(len(etsi_en_clauses), 78, f"Expected 78 provisions, got {len(etsi_en_clauses)}")

        clause_ids = [c.clause_id for c in etsi_en_clauses]
        self.assertEqual(len(clause_ids), len(set(clause_ids)), "Duplicate clause IDs detected in ETSI EN 303 645")

        # Spot-check key provisions
        by_id = {c.clause_id: c for c in etsi_en_clauses}

        self.assertIn("5.0-1", by_id)
        self.assertEqual(by_id["5.0-1"].page, "12")
        self.assertTrue(by_id["5.0-1"].normative)

        self.assertIn("5.1-1", by_id)
        self.assertEqual(by_id["5.1-1"].page, "13")
        self.assertIn("passwords shall be unique per device or defined by the user", by_id["5.1-1"].original_text)
        self.assertTrue(by_id["5.1-1"].normative)

        self.assertIn("5.2-1", by_id)
        self.assertEqual(by_id["5.2-1"].page, "15")
        self.assertIn("vulnerability disclosure policy", by_id["5.2-1"].original_text)
        self.assertIn("contact information for the reporting of issues", by_id["5.2-1"].original_text)

        self.assertIn("5.3-13", by_id)
        self.assertEqual(by_id["5.3-13"].page, "19")
        self.assertIn("defined support period", by_id["5.3-13"].original_text)

        self.assertIn("6-1", by_id)
        self.assertEqual(by_id["6-1"].page, "28")
        self.assertIn("personal data", by_id["6-1"].original_text)

        # Check all are marked normative
        for c in etsi_en_clauses:
            self.assertTrue(c.normative, f"Provision {c.clause_id} unexpectedly marked non-normative")
            self.assertTrue(c.original_text.strip(), f"Provision {c.clause_id} has empty text")
            self.assertTrue(c.page.isdigit(), f"Provision {c.clause_id} has non-numeric page: {c.page}")

    def test_multi_standard_coverage(self):
        """Verify all target standards are extracted and represented in dataset."""
        standards = {c.standard for c in self.clauses}
        expected_standards = {
            "ETSI EN 303 645",
            "ETSI TS 103 701",
            "NISTIR 8259A",
            "NISTIR 8259B",
            "EU CRA",
            "UK PSTI",
            "NIST IoT Catalog",
        }
        self.assertTrue(
            expected_standards.issubset(standards),
            f"Missing standards: {expected_standards - standards}",
        )

    def test_traceability_and_non_empty_fields(self):
        """Verify every record links to an existing source file and has non-empty text."""
        for c in self.clauses:
            self.assertTrue(c.standard.strip(), "Record missing standard")
            self.assertTrue(c.version.strip(), f"Record {c.clause_id} missing version")
            self.assertTrue(c.section.strip(), f"Record {c.clause_id} missing section")
            self.assertTrue(c.clause_id.strip(), "Record missing clause_id")
            self.assertTrue(c.original_text.strip(), f"Record {c.clause_id} missing original_text")
            self.assertTrue(c.source_file.strip(), f"Record {c.clause_id} missing source_file")

            full_source = PROJECT_ROOT / c.source_file
            self.assertTrue(full_source.exists(), f"Source file does not exist: {full_source}")

    def test_zero_duplicate_clause_ids_within_standards(self):
        """Verify that clause IDs are strictly unique within each standard."""
        by_standard = {}
        for c in self.clauses:
            by_standard.setdefault(c.standard, []).append(c.clause_id)

        for std, cids in by_standard.items():
            duplicates = [cid for cid in set(cids) if cids.count(cid) > 1]
            self.assertEqual(
                len(duplicates),
                0,
                f"Duplicate clause IDs detected in {std}: {duplicates}",
            )

    def test_etsi_ts_103701_coverage_of_en_303645(self):
        """Verify ETSI TS 103 701 extracts 258 test units covering all 78 ETSI EN 303 645 provisions."""
        ts_clauses = [c for c in self.clauses if c.standard == "ETSI TS 103 701"]
        self.assertEqual(len(ts_clauses), 258, f"Expected 258 test units, got {len(ts_clauses)}")

        # Extract base provisions tested in TS
        ts_base_provs = {c.clause_id.rsplit(" ", 1)[0].rsplit("-", 1)[0] for c in ts_clauses}
        en_provs = {c.clause_id for c in self.clauses if c.standard == "ETSI EN 303 645"}

        self.assertEqual(
            ts_base_provs,
            en_provs,
            f"Mismatch between EN provisions and TS coverage: diff = {ts_base_provs ^ en_provs}",
        )

    def test_eu_cra_ordering_and_integrity(self):
        """Verify EU CRA extracts 36 requirements in strict sequential order without orphan lead-ins."""
        cra_clauses = [c for c in self.clauses if c.standard == "EU CRA"]
        self.assertEqual(len(cra_clauses), 36, f"Expected 36 CRA clauses, got {len(cra_clauses)}")

        cra_cids = [c.clause_id for c in cra_clauses]
        annex1_p1_cids = [cid for cid in cra_cids if cid.startswith("Annex I, Part I,")]
        expected_annex1 = (
            ["Annex I, Part I, 1"]
            + [f"Annex I, Part I, 2({chr(c)})" for c in range(ord('a'), ord('m') + 1)]
            + ["Annex I, Part I, 3"]
        )
        self.assertEqual(annex1_p1_cids, expected_annex1, "CRA Annex I Part I clauses out of order")

    def test_uk_psti_provisions_integrity(self):
        """Verify UK PSTI extracts 16 requirements from Schedule 1 and Schedule 2."""
        psti_clauses = [c for c in self.clauses if c.standard == "UK PSTI"]
        self.assertEqual(len(psti_clauses), 16, f"Expected 16 PSTI clauses, got {len(psti_clauses)}")
        psti_cids = {c.clause_id for c in psti_clauses}
        self.assertIn("Schedule 1, Paragraph 1(2)", psti_cids)
        self.assertIn("Schedule 2, Paragraph 1(2)", psti_cids)
        self.assertIn("Schedule 2, Paragraph 3(2)", psti_cids)
        self.assertIn("Schedule 2, Paragraph 3(4)", psti_cids)


if __name__ == "__main__":
    unittest.main()
