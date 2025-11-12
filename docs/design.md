# 🧾 **Design Document — SIR Data Scraper**

## 1. Overview

### 1.1 Project Summary

**SIR Data Scraper** is a Python-based ETL pipeline designed to **automate extraction, parsing, and structuring** of voter roll data published on the *Election Commission of India’s Search-in-Roll (SIR)* portal.

It systematically downloads voter list PDFs (via ZIP archives) for every state and assembly constituency, extracts structured data (voter name, EPIC number, address, etc.), optionally translates fields into English, and stores the results into a relational database with strong indexing for fast retrieval and filtering.

---

## 2. Objectives

| Goal                    | Description                                                                             |
| ----------------------- | --------------------------------------------------------------------------------------- |
| **Automated ingestion** | Fully automate download of all state/assembly voter rolls from the SIR portal           |
| **Structured storage**  | Convert unstructured PDFs to tabular SQL data                                           |
| **Language-neutral**    | Support all Indian languages (OG = Original language) with optional English translation |
| **Scalable**            | Process multiple states and assemblies in batches, asynchronously                       |
| **Resilient**           | Recover from interruptions via checkpointing and resumable logs                         |
| **Auditable**           | Maintain progressive logs and optional full log dumps (`--savelogs` flag)               |

---

## 3. High-Level Architecture

**3-Stage Pipeline Architecture:**

```
+---------------------------------------------------------------+
|                         SIR Portal                            |
| (https://voters.eci.gov.in/searchInSIR/S2UA4DPDF-JK4QWODSE)   |
+---------------------------------------------------------------+
                  │
                  ▼
+--------------------------------+
| Crawler (Playwright)           |
| → Extract ZIP download URLs    |
| → Group by State/Assembly      |
+--------------------------------+
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    STAGE 1: DOWNLOAD                        │
│  Downloader (aiohttp) - Parallel downloads                  │
│  → Skip if file exists                                       │
│  → Retry on failure                                          │
│  → Save checkpoint after each constituency                  │
└─────────────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    STAGE 2: PARSE                           │
│  Extractor → Unzip ZIPs to PDFs                            │
│  Parser (pdfplumber / PyMuPDF / OCR) - Parallel parsing    │
│  → Extract voter data with regex                            │
│  → Extract EPIC prefix, address components                   │
│  → Keep records without EPIC                                │
│  → Save checkpoint after parsing                            │
└─────────────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    STAGE 3: STORE                           │
│  Translator (optional) → Translate OG → English            │
│  DB Loader (SQLAlchemy) → Store in SQLite                  │
│  → Unique ID (UUID) as primary key                          │
│  → EPIC nullable (allows duplicates)                        │
│  → Save checkpoint after storage                            │
└─────────────────────────────────────────────────────────────┘
                  │
                  ▼
+--------------------------------+
| Checkpoint Manager             |
| → latest.json (current state)  |
| → Timestamped history files    |
| → Resume support               |
+--------------------------------+
```

---

## 4. Core Components & Responsibilities

### 4.1 `crawler.py`

* Uses **Playwright** to navigate `SIR` dropdowns.
* Iterates through each **state**, loads assemblies, and extracts all **ZIP/PDF download links**.
* Yields structured metadata:

  ```json
  {
    "state": "Gujarat",
    "assembly": "Maninagar",
    "url": "https://.../Part42.zip"
  }
  ```
* Saves checkpoint after every state.

### 4.2 `downloader.py`

* Async batch downloader using `aiohttp` with parallel downloads (default 5 concurrent).
* **Skips existing files automatically** (checks file size to ensure completeness).
* Writes ZIPs to:

  ```
  ./data/voterlists/<State>/<Assembly>/<file>.zip
  ```
* Retries up to 3 times on network failures.
* Emits progressive logs: `[Downloading]`, `[Success]`, `[Retry]`, `[Failed]`.

### 4.3 `extractor.py`

* Unzips all files under each assembly.
* Validates extracted PDFs (by extension and basic file integrity).
* Removes successfully processed ZIPs.
* Updates manifest (JSON):

  ```json
  {"Gujarat": {"Maninagar": ["Part1.pdf", "Part2.pdf"]}}
  ```

### 4.4 `parser.py`

* Handles text extraction with fallback chain:

  1. **PyMuPDF** (fitz) - Better for CID-encoded fonts
  2. **pdfplumber** - Standard text extraction
  3. **pytesseract** (OCR) - Fallback for garbled text/images
* Regex-based field extraction with multilingual support:

  ```
  EPIC: ([A-Z]{2}/\d{2}/)?([A-Z]{3}\d{7}|\d{3}/\d{6})  # With prefix
  Name: (.*)
  Relation Type: (Father|Husband|Mother)
  Relation Name: (.*)
  Age: (\d+)
  Gender: (Male|Female|Other|પુરુષ|સ્ત્રી)
  Address: (House, Area, Village, Taluka, District)
  ```
* **Extracts EPIC prefix** from PDF headers (e.g., "GJ/01").
* **Extracts address components** (house, area, village, taluka, district).
* **Keeps records without EPIC** (EPIC is nullable).
* **Parallel parsing** within each constituency (configurable workers).
* Creates structured Python dicts for each voter.

### 4.5 `translator.py`

* Uses `deep-translator` (GoogleTranslator) for translation.
* Batch translates fields: `name_og`, `relation_og`, `address_og` → `_en`.
* Optional toggle via `--translate`.
* Gracefully handles missing translation library.

### 4.6 `db_loader.py`

* Uses SQLAlchemy ORM for schema management.
* **Unique ID (UUID)** as primary key (not EPIC).
* **EPIC is nullable** (allows duplicates and missing EPICs).
* Inserts data in batches (no UPSERT - each record gets unique ID).
* Creates indexes for efficient filtering:

  ```sql
  CREATE INDEX idx_epic_no ON voters(epic_no);
  CREATE INDEX idx_state ON voters(state);
  CREATE INDEX idx_assembly ON voters(assembly);
  CREATE INDEX idx_state_assembly ON voters(state, assembly);
  ```

### 4.7 `logger.py`

* Uses Python’s `logging` + `rich` for colorful console output.
* Progressive log stream always enabled.
* If `--savelogs` is passed:

  * Dumps full structured logs into `/logs/run_<timestamp>.log`
  * Includes timings, record counts, warnings, failures, etc.

---

## 5. Data Model

### SQL Table: `voters`

| Column         | Type      | Description                                    |
| -------------- | --------- | ---------------------------------------------- |
| `id`           | TEXT (PK) | Unique UUID (generated at runtime)             |
| `epic_no`      | TEXT      | EPIC voter ID (nullable, allows duplicates)    |
| `name_og`      | TEXT      | Name in original language                      |
| `name_en`      | TEXT      | English translation                            |
| `relation_type`| TEXT      | Relation type (Father/Husband/Mother)          |
| `relation_og`  | TEXT      | Relation name (OG)                             |
| `relation_en`  | TEXT      | Relation (EN)                                  |
| `age`          | INTEGER   |                                                |
| `gender`       | TEXT      |                                                |
| `address_og`   | TEXT      | Combined address (OG)                          |
| `address_en`   | TEXT      | Combined address (EN)                          |
| `state`        | TEXT      |                                                |
| `assembly`     | TEXT      |                                                |
| `source_file`  | TEXT      | Source PDF name                                |
| `last_updated` | DATETIME  | Timestamp                                      |

---

## 6. Command-Line Interface (CLI)

### **Usage**

```bash
python main.py [options]
```

### **Arguments**

| Flag                   | Description                                    |
| ---------------------- | ---------------------------------------------- |
| `--state <name>`       | Limit to a specific state                      |
| `--max-assemblies <n>` | Limit assemblies (for testing)                 |
| `--translate`          | Enable OG → English translation                |
| `--savelogs`           | Save extended logs to file                     |
| `--resume`             | Continue from last checkpoint (checks latest.json) |
| `--db <path>`          | Custom DB path (default `data/voters.db`)      |
| `--parse-workers <n>`  | Number of parallel workers for parsing (default: 4) |
| `--show-browser`       | Show browser window (debug mode)               |

### **Examples**

```bash
# Download all Gujarat assemblies
python main.py --state Gujarat --savelogs

# Full India run (resume if interrupted)
python main.py --resume --translate --savelogs
```

---

## 7. Logging Design

### **Progressive Output (always on)**

```
[STATE: Gujarat] [ASSEMBLY: Maninagar]
→ Found 42 ZIPs
→ Downloading Part12.zip... ✅ 12.4 MB
→ Extracted 15 PDFs
→ Parsed 3,842 records
→ Inserted: 3,828 new | 14 updated
```

### **Saved Logs (`--savelogs`)**

JSON file example:

```json
{
  "run_id": "2025-11-11T19:45:22",
  "state": "Gujarat",
  "assembly": "Maninagar",
  "files_downloaded": 42,
  "pdfs_extracted": 351,
  "records_inserted": 38428,
  "errors": 2,
  "duration_sec": 1765.4
}
```

---

## 8. Error Handling & Resilience

| Scenario             | Behavior                              |
| -------------------- | ------------------------------------- |
| Network timeout      | Retry (max 3) then mark failed        |
| ZIP corrupted        | Skip, log warning                     |
| OCR failure          | Mark partial parse, continue          |
| DB lock / busy       | Retry with backoff                    |
| Script crash         | Resume via checkpoint JSON            |
| Manual stop (Ctrl+C) | Graceful shutdown and checkpoint save |

---

## 9. Storage Layout

```
sir-data-scraper/
│
├── data/
│   ├── voterlists/
│   │   ├── Gujarat/
│   │   │   ├── Maninagar/
│   │   │   │   ├── Part1.pdf
│   │   │   │   ├── Part2.pdf
│   │   │   │   └── ...
│   │   └── Maharashtra/...
│   └── voters.db
│
├── logs/
│   └── run_2025-11-11T19-45-22.log
│
├── scraper/
│   ├── crawler.py
│   ├── downloader.py
│   ├── extractor.py
│   ├── parser.py
│   ├── translator.py
│   ├── db_loader.py
│   ├── logger.py
│   ├── utils.py
│   ├── pipeline.py          # 3-stage pipeline
│   └── checkpoint.py        # Checkpoint management
│
├── data/
│   └── checkpoints/
│       ├── latest.json       # Current state
│       └── history/          # Timestamped checkpoints
│
├── requirements.txt
├── main.py                   # Main entry point
└── process_existing_pdfs.py  # Process existing PDFs
```

---

## 10. Performance & Scaling

| Optimization                    | Description                            |
| ------------------------------- | -------------------------------------- |
| Async IO                        | Parallel downloads (5 concurrent)      |
| Parallel parsing                | ThreadPoolExecutor (configurable workers) |
| Batch DB inserts                | Reduces I/O overhead                   |
| Regex precompilation            | Faster text parsing                    |
| Incremental resume              | Checkpoint system (latest.json)        |
| Skip existing files             | Automatic skip for already-downloaded  |
| Constituency-wise processing    | One constituency at a time (data integrity) |

---

## 11. Future Enhancements

1. Add language auto-detection for OG text.
2. Move translation to local model (IndicTrans2).
3. Expose pipeline as a REST or gRPC ingestion API.
4. Integrate directly with the **sir-lookup** live DB.
5. Add dashboard (e.g., Streamlit) for monitoring ingestion progress.

---

## 12. Security & Compliance

* Project is for **publicly available voter roll data** (no private API scraping).
* Only processes government-published PDFs.
* Each run should include a disclaimer in the README:

  > “This tool automates processing of publicly available electoral roll PDFs from the ECI’s official SIR portal. No unauthorized data or credentials are accessed.”

---

## 13. Summary

| Component    | Technology                    | Description                     |
| ------------ | ----------------------------- | ------------------------------- |
| Web scraping | Playwright                    | Extract ZIP URLs from dropdowns |
| Download     | aiohttp                       | Parallel async downloading      |
| Parsing      | PyMuPDF / pdfplumber / OCR    | Extract text with fallback chain|
| Translation  | deep-translator               | Optional multilingual support   |
| Database     | SQLAlchemy + SQLite           | Fast local store (UUID PK)      |
| Checkpoint   | JSON (latest.json)            | Resume support                  |
| Pipeline     | 3-stage architecture          | Download → Parse → Store        |
| Logging      | rich + logging                | Real-time + savelogs            |
| CLI          | argparse                      | Clean user control              |
