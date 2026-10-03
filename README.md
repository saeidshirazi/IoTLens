# IoTLens

IoTLens is a research pipeline for preprocessing and analyzing cybersecurity standard documents across independently authored standard families into reliable, traceable clause datasets.

## Project Structure

```text
IoTLens/
├── data/
│   ├── raw/
│   │   ├── cra/
│   │   ├── etsi/
│   │   ├── nist/
│   │   └── psti/
│   ├── processed/
│   │   ├── clauses.csv
│   │   └── extraction_quality_audit.csv
│   └── sources.json
├── src/
│   ├── __init__.py
│   ├── audit.py
│   ├── download.py
│   └── preprocess.py
├── tests/
│   └── test_preprocess.py
├── Makefile
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Setup

```bash
pip install -r requirements.txt
```

## Usage

1. **Verify and download standards:**
   ```bash
   python -m src.download
   ```

2. **Preprocess standards into clause dataset:**
   ```bash
   python -m src.preprocess
   # or: make preprocess
   ```

   Output is written to `data/processed/clauses.csv`.

3. **Run extraction-quality audit:**
   ```bash
   python -m src.audit
   # or: make audit
   ```

   Audits 131 representative sampled clauses across all 7 standards against 5 quality criteria and writes results to `data/processed/extraction_quality_audit.csv`.

4. **Run unit tests:**
   ```bash
   pytest
   # or: make test
   ```

## Dataset Schema (Phase 1.5)

The generated `data/processed/clauses.csv` contains 628 rows across 12 fields:

| Field | Type | Description | Values / Examples |
|---|---|---|---|
| `standard` | string | Standard identifier | `ETSI EN 303 645`, `ETSI TS 103 701`, `EU CRA`, `UK PSTI`, `NISTIR 8259A`, `NISTIR 8259B`, `NIST IoT Catalog` |
| `version` | string | Document release/statute version | `V2.1.1`, `V1.1.1`, `2024/0284(COD)`, `SI 2023/1007`, etc. |
| `document_role` | string | Semantic role of the document | `requirement`, `regulation`, `assessment`, `guidance` |
| `unit_type` | string | Nature of the semantic unit | `requirement`, `capability`, `assessment_step` |
| `section` | string | Document section or clause title | e.g. `5.1 No universal default passwords` |
| `clause_id` | string | Provision, article, or test unit identifier | e.g. `5.1-1`, `Annex I, Part I, 1`, `Schedule 1, Paragraph 1(2)` |
| `page` | string | Source page number in original PDF (empty for HTML) | e.g. `13`, `24` |
| `raw_text` | string | Untouched source text preserved directly from document | Untouched original wording with source linebreaks |
| `clean_text` | string | Normalized text for NLP/LLM tasks | De-hyphenated and whitespace-cleaned text |
| `modality` | string | Grammatical requirement modality | `SHALL`, `MUST`, `SHOULD`, `OTHER` |
| `is_requirement_candidate` | boolean | Whether the row is a candidate for requirement classification | `True` for 370 requirements/capabilities; `False` for 258 assessment steps |
| `source_file` | string | Relative path to original document | e.g. `data/raw/etsi/en_303645v020101p.pdf` |

### Dataset Composition

- **Requirement Candidates (`is_requirement_candidate = True`, 370 total)**:
  - `ETSI EN 303 645`: 78 provisions (`document_role = requirement`, `unit_type = requirement`)
  - `EU CRA`: 36 provisions (`document_role = regulation`, `unit_type = requirement`)
  - `UK PSTI`: 16 provisions (`document_role = regulation`, `unit_type = requirement`)
  - `NISTIR 8259A`: 22 capabilities (`document_role = guidance`, `unit_type = capability`)
  - `NISTIR 8259B`: 14 capabilities (`document_role = guidance`, `unit_type = capability`)
  - `NIST IoT Catalog`: 204 capabilities (`document_role = guidance`, `unit_type = capability`)
- **Auxiliary Assessment Steps (`is_requirement_candidate = False`, 258 total)**:
  - `ETSI TS 103 701`: 258 test evaluation units (`document_role = assessment`, `unit_type = assessment_step`)