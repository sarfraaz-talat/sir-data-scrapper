# Changelog

All notable changes to the SIR Data Scraper project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- 3-stage pipeline architecture (Download → Parse → Store)
- Parallel processing for downloads and PDF parsing
- Checkpoint system with `latest.json` for resumable runs
- Support for records without EPIC numbers
- Unique ID field (UUID) instead of EPIC as primary key
- EPIC prefix extraction from PDF headers (e.g., "GJ/01")
- Address component extraction (house, area, village, taluka, district)
- OCR fallback for garbled PDFs (PyMuPDF + Tesseract)
- Optional translation to English (deep-translator)
- Comprehensive logging with rich console output
- `process_existing_pdfs.py` script for processing already-downloaded PDFs

### Changed
- Database schema: EPIC is now nullable, unique ID is primary key
- Parser keeps records even without EPIC numbers
- Address fields now include combined address from components
- Downloader skips existing files automatically
- Main entry point refactored to 3-stage pipeline

### Fixed
- Duplicate EPIC handling (now allows duplicates with unique IDs)
- CID-encoded font issues (automatic OCR fallback)
- React Select dropdown interaction issues
- Slow download speeds (optimized aiohttp settings)
- Assembly folder naming issues

---

## Process for Updating Changelog

When making a commit, update the `[Unreleased]` section with:

1. **Added**: New features
2. **Changed**: Changes in existing functionality
3. **Fixed**: Bug fixes
4. **Removed**: Removed features
5. **Security**: Security fixes

### Example:

```markdown
## [Unreleased]

### Added
- New feature X

### Changed
- Modified behavior Y

### Fixed
- Bug Z
```

When releasing a version, move `[Unreleased]` to a versioned section:

```markdown
## [1.0.0] - 2025-11-12

### Added
- All features from Unreleased
```

Then create a new `[Unreleased]` section for future changes.
