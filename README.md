# 🧾 SIR Data Scraper

Automated ETL pipeline for extracting, parsing, and structuring voter roll data from the Election Commission of India's Search-in-Roll (SIR) portal.

## Documentation

- **[Design Document](docs/design.md)** - Architecture, components, and design decisions
- **[Changelog](docs/CHANGELOG.md)** - Version history and changes

## Overview

This tool systematically:
- Downloads voter list PDFs (via ZIP archives) for every state and assembly constituency
- Extracts structured data (voter name, EPIC number, address, etc.)
- Optionally translates fields into English
- Stores results in a relational database with strong indexing for fast retrieval

## Features

- ✅ **Automated ingestion** - Fully automated download of all state/assembly voter rolls
- ✅ **Structured storage** - Converts unstructured PDFs to tabular SQL data
- ✅ **Language-neutral** - Supports all Indian languages with optional English translation
- ✅ **Scalable** - Processes multiple states and assemblies in batches, asynchronously
- ✅ **Resilient** - Recovers from interruptions via checkpointing and resumable logs
- ✅ **Auditable** - Maintains progressive logs and optional full log dumps

## Installation

### Prerequisites

- Python 3.8+
- Tesseract OCR (for OCR fallback support)
  - macOS: `brew install tesseract tesseract-lang`
  - Ubuntu/Debian: `sudo apt-get install tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin`
  - Windows: Download from [GitHub](https://github.com/UB-Mannheim/tesseract/wiki)

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd sir-data-scrapper
```

2. Create and activate a virtual environment (recommended):
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install Python dependencies:
```bash
pip install -r requirements.txt
```

4. Install Playwright browsers:
```bash
python3 -m playwright install chromium
```

**Note**: If you get a "command not found: playwright" error, use `python3 -m playwright` instead of just `playwright`.

## Usage

### Basic Usage

**Important**: Make sure your virtual environment is activated before running:
```bash
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

Then run the scraper:

#### Process New Downloads (Full Pipeline)

```bash
# Process one constituency (test)
python main.py --state Gujarat --max-assemblies 1 --translate

# Process all Gujarat constituencies
python main.py --state Gujarat --translate

# With resume (skip completed constituencies)
python main.py --state Gujarat --translate --resume

# More parse workers (faster, more CPU)
python main.py --state Gujarat --translate --parse-workers 8

# Save logs to file
python main.py --state Gujarat --translate --savelogs
```

#### Process Existing PDFs

If you already have PDFs downloaded, the main pipeline will automatically skip downloads:

```bash
# Process existing PDFs (downloads will be skipped automatically)
python main.py --state Gujarat --translate --resume

# The pipeline will:
# 1. Extract URLs (fast, no actual download needed)
# 2. Skip downloads (files already exist)
# 3. Parse existing PDFs
# 4. Store in database
```

#### Check Status

```bash
# View latest checkpoint
cat data/checkpoints/latest.json | python3 -m json.tool

# Check incomplete constituencies
python3 -c "
from scraper.checkpoint import CheckpointManager
cm = CheckpointManager()
incomplete = cm.get_incomplete_constituencies()
print(f'Incomplete: {len(incomplete)}')
for key in incomplete:
    print(f'  - {key}')
"
```

### Command-Line Options

| Flag                   | Description                               |
| ---------------------- | ----------------------------------------- |
| `--state <name>`       | Limit to a specific state                 |
| `--max-assemblies <n>` | Limit assemblies (for testing)            |
| `--translate`          | Enable OG → English translation           |
| `--savelogs`           | Save extended logs to file                |
| `--resume`             | Continue from last checkpoint (checks latest.json) |
| `--db <path>`          | Custom DB path (default `data/voters.db`) |
| `--parse-workers <n>`  | Number of parallel workers for parsing (default: 4) |
| `--show-browser`       | Show browser window (debug mode) |

## Pipeline Architecture

The scraper uses a **3-stage pipeline** architecture:

1. **Stage 1: Download** - Parallel downloads, skips existing files
2. **Stage 2: Parse** - Parallel parsing within each constituency
3. **Stage 3: Store** - Database storage with optional translation

Each constituency is processed completely through all 3 stages before moving to the next, ensuring data integrity.

### Checkpoint System

- Checkpoints saved to `data/checkpoints/latest.json`
- Timestamped history in `data/checkpoints/history/`
- Resume mode automatically skips completed constituencies
- Each stage (download, parse, store) tracked separately

## Project Structure

```
sir-data-scraper/
│
├── data/
│   ├── voterlists/          # Downloaded ZIPs and extracted PDFs
│   │   ├── Gujarat/
│   │   │   ├── Abdasa/
│   │   │   │   └── P001/
│   │   │   │       └── *.pdf
│   │   └── ...
│   ├── checkpoints/         # Checkpoint files
│   │   ├── latest.json      # Current state
│   │   └── history/         # Timestamped checkpoints
│   └── voters.db            # SQLite database
│
├── logs/                    # Runtime logs (if --savelogs)
│   └── run_*.log
│
├── scraper/
│   ├── crawler.py           # Playwright web scraping
│   ├── downloader.py        # Async batch downloading
│   ├── extractor.py         # ZIP extraction
│   ├── parser.py            # PDF parsing + OCR
│   ├── translator.py        # Optional translation
│   ├── db_loader.py         # Database operations
│   ├── logger.py            # Rich logging
│   ├── utils.py             # Utility functions
│   ├── pipeline.py          # 3-stage pipeline
│   └── checkpoint.py        # Checkpoint management
│
├── tests/
│   ├── __init__.py
│   └── test_parser_validation.py
│
├── docs/
│   ├── design.md            # Architecture design
│   └── CHANGELOG.md         # Version history
│
├── requirements.txt
├── main.py                  # Main CLI entry point
└── README.md
```

## Data Model

The `voters` table contains:

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

## How It Works

1. **Crawler** - Uses Playwright to navigate SIR portal dropdowns and extract ZIP download URLs
2. **Downloader** - Parallel async downloads ZIP files, skips existing files
3. **Extractor** - Unzips files and validates extracted PDFs
4. **Parser** - Parallel parsing with PyMuPDF/pdfplumber, OCR fallback for garbled text
5. **Translator** - Optionally translates OG fields to English (deep-translator)
6. **DB Loader** - Batch inserts with unique IDs (UUID) into SQLite
7. **Checkpoint Manager** - Tracks progress and enables resume functionality

## Error Handling

- Network timeouts: Retry up to 3 times with exponential backoff
- Corrupted ZIPs: Skip and log warning
- OCR failures: Mark partial parse, continue
- Database locks: Retry with backoff
- Script crashes: Resume via checkpoint JSON
- Manual stop (Ctrl+C): Graceful shutdown and checkpoint save

## Performance

- **Parallel downloads**: 5 concurrent connections
- **Parallel parsing**: Configurable workers (default: 4, use `--parse-workers`)
- **Batch DB inserts**: Reduces I/O overhead
- **Skip existing files**: Automatic skip for already-downloaded files
- **Checkpoint system**: Resume from last completed constituency
- **Constituency-wise processing**: One at a time for data integrity

## Security & Compliance

> **Disclaimer**: This tool automates processing of publicly available electoral roll PDFs from the ECI's official SIR portal. No unauthorized data or credentials are accessed. The project only processes government-published PDFs that are publicly available.

## Troubleshooting

### Playwright Issues
```bash
# Reinstall browsers (use python3 -m playwright if playwright command not found)
python3 -m playwright install chromium
```

### OCR Not Working
- Ensure Tesseract is installed and in PATH
- Install language packs for Indian languages
- Check `pytesseract.pytesseract.tesseract_cmd` if needed

### Database Locked
- Close any other connections to the database
- The tool uses `check_same_thread=False` for SQLite to allow async access

## Future Enhancements

1. Language auto-detection for OG text
2. Local translation model (IndicTrans2)
3. REST/gRPC ingestion API
4. Integration with sir-lookup live DB
5. Dashboard (Streamlit) for monitoring progress

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## Releases

See [RELEASE.md](RELEASE.md) for the release process.

Releases are automated via GitHub Actions:
- Push a tag (e.g., `v1.0.0`) to trigger release workflow
- CI tests run automatically on push/PR
- GitHub releases created automatically from tags

