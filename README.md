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
│   │   └── clauses.csv
│   └── sources.json
├── src/
│   ├── __init__.py
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
   ```

   Output is written to `data/processed/clauses.csv`.

3. **Run unit tests:**
   ```bash
   pytest
   ```

## Dataset Schema

The generated `data/processed/clauses.csv` contains the following fields:

| Field | Description |
|---|---|
| `standard` | Standard identifier (e.g., `ETSI EN 303 645`, `ETSI TS 103 701`, `EU CRA`, `UK PSTI`, `NISTIR 8259A`) |
| `version` | Document release/statute version (e.g., `V3.1.3`, `V2.1.1`, `SI 2023/1007`) |
| `section` | Document section or clause title |
| `clause_id` | Provision, article, or test unit identifier |
| `page` | Source page number in original PDF (empty for HTML sources) |
| `original_text` | Exact original text of the clause |
| `normative` | Boolean flag indicating whether the clause contains normative requirements |
| `source_file` | Relative path to the original raw document |