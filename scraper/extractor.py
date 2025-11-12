"""
ZIP extractor to unzip downloaded files and validate PDFs
"""

import zipfile
from pathlib import Path
from typing import List, Dict, Any

from .utils import ensure_dir, save_checkpoint, load_checkpoint, sanitize_filename
from .logger import Logger


class Extractor:
    """Extract ZIP files and validate PDFs."""
    
    def __init__(
        self,
        logger: Logger,
        base_dir: str = "data/voterlists",
        manifest_path: str = "data/manifest.json"
    ):
        self.logger = logger
        self.base_dir = Path(base_dir)
        self.manifest_path = manifest_path
    
    def extract_zip(self, zip_path: Path, extract_dir: Path) -> List[str]:
        """Extract ZIP file and return list of extracted PDF filenames."""
        pdfs = []
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # List all files in ZIP
                file_list = zip_ref.namelist()
                
                # Extract all files
                zip_ref.extractall(extract_dir)
                
                # Filter PDFs
                for filename in file_list:
                    if filename.lower().endswith('.pdf'):
                        pdf_path = extract_dir / filename
                        if pdf_path.exists():
                            pdfs.append(filename)
                
                self.logger.debug(f"Extracted {len(pdfs)} PDFs from {zip_path.name}")
                return pdfs
        
        except zipfile.BadZipFile:
            self.logger.warning(f"Corrupted ZIP file: {zip_path}")
            return []
        
        except Exception as e:
            self.logger.error(f"Error extracting {zip_path}: {e}")
            return []
    
    def validate_pdf(self, pdf_path: Path) -> bool:
        """Basic PDF validation (check if file exists and has PDF header)."""
        if not pdf_path.exists():
            return False
        
        try:
            # Check PDF magic bytes
            with open(pdf_path, 'rb') as f:
                header = f.read(4)
                return header == b'%PDF'
        except Exception:
            return False
    
    def extract_assembly(self, state: str, assembly: str) -> Dict[str, Any]:
        """
        Extract all ZIPs for a state-assembly combination.
        Returns manifest of extracted PDFs.
        """
        state_dir = self.base_dir / sanitize_filename(state)
        assembly_dir = state_dir / sanitize_filename(assembly)
        
        if not assembly_dir.exists():
            self.logger.warning(f"Assembly directory not found: {assembly_dir}")
            return {}
        
        # Find all ZIP files
        zip_files = list(assembly_dir.glob("*.zip"))
        
        if not zip_files:
            self.logger.info(f"No ZIP files found in {assembly_dir}")
            return {}
        
        self.logger.info(f"Found {len(zip_files)} ZIP files in {assembly_dir}")
        
        all_pdfs = []
        extracted_count = 0
        
        for zip_path in zip_files:
            pdfs = self.extract_zip(zip_path, assembly_dir)
            
            if pdfs:
                all_pdfs.extend(pdfs)
                extracted_count += 1
                
                # Validate extracted PDFs
                valid_pdfs = []
                for pdf_name in pdfs:
                    pdf_path = assembly_dir / pdf_name
                    if self.validate_pdf(pdf_path):
                        valid_pdfs.append(pdf_name)
                    else:
                        self.logger.warning(f"Invalid PDF: {pdf_path}")
                
                # Remove ZIP after successful extraction
                try:
                    zip_path.unlink()
                    self.logger.debug(f"Removed ZIP: {zip_path.name}")
                except Exception as e:
                    self.logger.warning(f"Could not remove ZIP {zip_path}: {e}")
        
        self.logger.extraction_progress(len(all_pdfs))
        
        # Update manifest
        manifest = load_checkpoint(self.manifest_path)
        if state not in manifest:
            manifest[state] = {}
        manifest[state][assembly] = all_pdfs
        save_checkpoint(self.manifest_path, manifest)
        
        return {
            'state': state,
            'assembly': assembly,
            'pdfs': all_pdfs,
            'extracted_zips': extracted_count
        }
    
    def get_manifest(self) -> Dict[str, Any]:
        """Load and return the extraction manifest."""
        return load_checkpoint(self.manifest_path)

