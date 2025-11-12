"""
PDF parser using pdfplumber with OCR fallback (pytesseract)
"""

import re
import pdfplumber
from pathlib import Path
from typing import List, Dict, Any, Optional

from .logger import Logger
from .utils import sanitize_filename

# Optional OCR imports
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


class Parser:
    """Parse PDFs to extract voter data with OCR fallback."""
    
    def __init__(self, logger: Logger, use_ocr: bool = True):
        self.logger = logger
        self.use_ocr = use_ocr
        
        # Precompile regex patterns for field extraction
        # EPIC pattern: Can be "ABC1234567" or "001/000006" format
        # Try multiple variations as format may vary
        self.patterns = {
            'epic': re.compile(r'(?:EPIC|Epic|epic)[:\s]*([A-Z]{3}\d{7}|\d{3}/\d{6})', re.IGNORECASE),
            'epic_alt': re.compile(r'\b([A-Z]{3}\d{7}|\d{3}/\d{6})\b'),  # Just the pattern without label
            'name': re.compile(r'(?:Name|નામ|નામ)[:\s]+(.+?)(?:\n|Father|Husband|પિતા|પતિ|Age|Gender|Address|$)', re.IGNORECASE | re.DOTALL),
            'relation': re.compile(r'(?:Father|Husband|પિતા|પતિ)[:\s]+(.+?)(?:\n|Age|Gender|Address|$)', re.IGNORECASE | re.DOTALL),
            'age': re.compile(r'(?:Age|ઉંમર|आयु)[:\s]+(\d+)', re.IGNORECASE),
            'gender': re.compile(r'(?:Gender|લિંગ|लिंग)[:\s]+(Male|Female|Other|પુરુષ|સ્ત્રી|पुरुष|स्त्री|પુ\.|સ્ત્રી)', re.IGNORECASE),
            'address': re.compile(r'(?:Address|સરનામું|पता)[:\s]+(.+?)(?:\n\n|$)', re.IGNORECASE | re.DOTALL),
        }
    
    def extract_text_pdfplumber(self, pdf_path: Path) -> str:
        """Extract text using pdfplumber."""
        text = ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        except Exception as e:
            self.logger.warning(f"pdfplumber extraction failed for {pdf_path}: {e}")
        return text
    
    def extract_text_pymupdf(self, pdf_path: Path) -> str:
        """Extract text using PyMuPDF (fitz) - better for CID-encoded fonts."""
        text = ""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            for page in doc:
                page_text = page.get_text()
                if page_text:
                    text += page_text + "\n"
            doc.close()
        except ImportError:
            self.logger.debug("PyMuPDF not available, skipping")
        except Exception as e:
            self.logger.warning(f"PyMuPDF extraction failed for {pdf_path}: {e}")
        return text
    
    def extract_text_ocr(self, pdf_path: Path) -> str:
        """Extract text using OCR (pytesseract)."""
        if not self.use_ocr or not OCR_AVAILABLE:
            if self.use_ocr and not OCR_AVAILABLE:
                self.logger.warning("OCR requested but pytesseract/PIL not available")
            return ""
        
        text = ""
        try:
            # Use PyMuPDF for better image rendering
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            for page_num, page in enumerate(doc):
                # Render page as image with higher resolution (3x zoom for better OCR)
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
                # Convert to PIL Image
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                # OCR with PSM 6 (assume uniform block of text - better for tables)
                # Use Gujarati + English languages
                page_text = pytesseract.image_to_string(img, lang='guj+eng', config='--psm 6')
                text += page_text + "\n"
            doc.close()
        except Exception as e:
            self.logger.warning(f"OCR extraction failed for {pdf_path}: {e}")
        
        return text
    
    def extract_fields(self, text: str) -> Dict[str, Any]:
        """Extract structured fields from text using regex."""
        record = {}
        
        # Extract EPIC number - try with label first, then just pattern
        epic_match = self.patterns['epic'].search(text)
        if not epic_match:
            epic_match = self.patterns['epic_alt'].search(text)
        
        if epic_match:
            record['epic_no'] = epic_match.group(1).strip().upper()
        # Don't return empty - keep records without EPIC
        
        # Extract name
        name_match = self.patterns['name'].search(text)
        if name_match:
            record['name_og'] = name_match.group(1).strip()
        
        # Extract relation
        relation_match = self.patterns['relation'].search(text)
        if relation_match:
            record['relation_og'] = relation_match.group(1).strip()
        
        # Extract age
        age_match = self.patterns['age'].search(text)
        if age_match:
            try:
                record['age'] = int(age_match.group(1))
            except ValueError:
                pass
        
        # Extract gender
        gender_match = self.patterns['gender'].search(text)
        if gender_match:
            record['gender'] = gender_match.group(1).strip()
        
        # Extract address
        address_match = self.patterns['address'].search(text)
        if address_match:
            record['address_og'] = address_match.group(1).strip()
        
        return record
    
    def parse_pdf(self, pdf_path: Path) -> List[Dict[str, Any]]:
        """Parse a PDF file and return list of voter records."""
        records = []
        
        try:
            # Try PyMuPDF first (better for CID-encoded fonts)
            text = self.extract_text_pymupdf(pdf_path)
            
            # If PyMuPDF didn't work or returned empty, try pdfplumber
            if not text.strip():
                text = self.extract_text_pdfplumber(pdf_path)
            
            # Check if text is garbled (contains CID codes or has too many non-ASCII special chars)
            # PyMuPDF sometimes extracts garbled text with special chars like æ¤©¤≠ı¤¡ı
            has_cid = '(cid:' in text
            # Check if first 500 chars have too many non-printable/special characters
            # (more than 30% non-alphanumeric, non-space, non-punctuation)
            sample = text[:500] if len(text) > 500 else text
            if sample:
                special_chars = sum(1 for c in sample if not (c.isalnum() or c.isspace() or c in '.,;:()[]{}-\'\"'))
                special_ratio = special_chars / len(sample) if len(sample) > 0 else 0
                is_garbled = has_cid or (special_ratio > 0.3 and len(text.strip()) > 100)
            else:
                is_garbled = has_cid
            
            # If text is garbled or empty, try OCR
            if (is_garbled or not text.strip()) and self.use_ocr:
                self.logger.info(f"Text extraction failed or garbled for {pdf_path.name}, using OCR...")
                text = self.extract_text_ocr(pdf_path)
                if text.strip():
                    self.logger.debug(f"OCR extracted {len(text)} characters from {pdf_path.name}")
                    # Log first 200 chars to see format
                    self.logger.debug(f"OCR sample: {text[:200]}")
            
            if not text.strip():
                self.logger.warning(f"No text extracted from {pdf_path.name}")
                return records
            
            # Extract PDF metadata (EPIC prefix, address components, voter counts)
            pdf_metadata = self.extract_pdf_metadata(text)
            
            # Try extracting from tables first (many voter lists are in table format)
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    for page in pdf.pages:
                        tables = page.extract_tables()
                        for table in tables:
                            if table and len(table) > 1:  # Has header and data rows
                                # Try to parse table rows as voter records
                                for row in table[1:]:  # Skip header
                                    if row and len(row) > 0:
                                        # Join row cells into text and try to extract
                                        row_text = ' '.join([str(cell) if cell else '' for cell in row])
                                        record = self.extract_fields(row_text)
                                        if record:  # Keep records even without EPIC
                                            records.append(record)
            except Exception as e:
                self.logger.debug(f"Table extraction failed for {pdf_path.name}: {e}")
            
            # If no records from tables, try parsing OCR text as table structure
            if not records:
                records = self.parse_ocr_table(text, pdf_metadata)
            
            # If still no records, try text-based parsing
            if not records:
                # Split text into potential voter records
                sections = text.split('\n\n')  # Assume records are separated by double newlines
                
                for section in sections:
                    if not section.strip():
                        continue
                    
                    record = self.extract_fields(section)
                    if record:  # Keep records even without EPIC
                        records.append(record)
                
                # If no records found with section splitting, try parsing entire text
                if not records:
                    record = self.extract_fields(text)
                    if record:  # Keep records even without EPIC
                        records.append(record)
            
            # Add PDF metadata to all records (EPIC prefix, address components)
            for record in records:
                # Add EPIC prefix if EPIC exists
                if record.get('epic_no') and pdf_metadata.get('epic_prefix'):
                    record['epic_no'] = f"{pdf_metadata['epic_prefix']}/{record['epic_no']}"
                
                # Add address components (build address if components exist)
                if pdf_metadata.get('address_components'):
                    address = self.build_address(pdf_metadata['address_components'], record)
                    if address:
                        # Merge with existing address if present, otherwise set new
                        if record.get('address_og'):
                            record['address_og'] = f"{record['address_og']}, {address}"
                        else:
                            record['address_og'] = address
                
                # Store metadata for validation (but don't store in DB)
                record['_pdf_metadata'] = pdf_metadata
        
        except Exception as e:
            self.logger.error(f"Error parsing {pdf_path}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
        
        return records
    
    def parse_assembly(
        self,
        state: str,
        assembly: str,
        pdf_files: List[str],
        base_dir: Path
    ) -> List[Dict[str, Any]]:
        """Parse all PDFs for an assembly and return all records."""
        all_records = []
        
        state_dir = base_dir / sanitize_filename(state)
        assembly_dir = state_dir / sanitize_filename(assembly)
        
        for pdf_name in pdf_files:
            pdf_path = assembly_dir / pdf_name
            
            if not pdf_path.exists():
                self.logger.warning(f"PDF not found: {pdf_path}")
                continue
            
            # Log progress for large batches
            if len(pdf_files) > 10 and len(all_records) % 10 == 0:
                self.logger.debug(f"Parsing PDF {len(all_records) // 10 * 10 + 1}/{len(pdf_files)}: {pdf_name}")
            
            records = self.parse_pdf(pdf_path)
            
            if records:
                self.logger.debug(f"Extracted {len(records)} records from {pdf_name}")
            
            # Add metadata to each record
            for record in records:
                record['state'] = state
                record['assembly'] = assembly
                record['source_file'] = pdf_name
                # Remove _pdf_metadata before saving (it's only for validation)
                record.pop('_pdf_metadata', None)
            
            all_records.extend(records)
        
        return all_records
    
    def extract_pdf_metadata(self, text: str) -> Dict[str, Any]:
        """Extract metadata from PDF: EPIC prefix, address components, voter counts."""
        metadata = {
            'epic_prefix': None,
            'address_components': {},
            'voter_counts': {}
        }
        
        lines = text.split('\n')
        
        # Extract EPIC prefix (e.g., "GJ/01" from header)
        for line in lines[:50]:  # Check first 50 lines
            # Look for pattern like "GJ/01" or "EPIC નંબર GJ/01"
            epic_prefix_match = re.search(r'([A-Z]{2}/\d{2})', line)
            if epic_prefix_match:
                metadata['epic_prefix'] = epic_prefix_match.group(1)
                break
        
        # Extract address components
        for i, line in enumerate(lines):
            if not line or not isinstance(line, str):
                continue
            line_lower = line.lower()
            
            # Village/City name - look for pattern like "મુખ્ય ગામ/શહેરનું નામ : છેરનાની"
            if 'મુખ્ય ગામ' in line or 'શહેરનું નામ' in line:
                # Extract name after colon, but clean it up
                match = re.search(r'[:]\s*([^,\n]+?)(?:\s*રેવન્યુ|\s*તાલુકો|\s*જિલ્લો|$)', line)
                if match:
                    village = match.group(1).strip()
                    # Remove common prefixes
                    village = re.sub(r'^\d+\s*', '', village)  # Remove leading numbers
                    village = re.sub(r'\s*મુખ્ય ગામ.*?નામ\s*', '', village)  # Remove label text
                    if village and len(village) < 50:  # Reasonable length
                        metadata['address_components']['village_city'] = village.strip()
            
            # Revenue Circle - look for "રેવન્યુ સર્કલ : દયાપર"
            if 'રેવન્યુ સર્કલ' in line:
                match = re.search(r'રેવન્યુ સર્કલ\s*[:]\s*([^,\n]+?)(?:\s*તાલુકો|\s*જિલ્લો|$)', line)
                if match:
                    rc = match.group(1).strip()
                    if rc and len(rc) < 50:
                        metadata['address_components']['revenue_circle'] = rc
            
            # Taluka - look for "તાલુકો : લખપત"
            if 'તાલુકો' in line:
                match = re.search(r'તાલુકો\s*[:]\s*([^,\n]+?)(?:\s*જિલ્લો|$)', line)
                if match:
                    taluka = match.group(1).strip()
                    if taluka and len(taluka) < 50:
                        metadata['address_components']['taluka'] = taluka
            
            # District - look for "જિલ્લો : કચ્છ"
            if 'જિલ્લો' in line:
                match = re.search(r'જિલ્લો\s*[:]\s*([^,\n]+?)(?:\s*વર્ગીકરણ|\s*કેન્દ્ર|$)', line)
                if match:
                    district = match.group(1).strip()
                    # Clean up common suffixes
                    district = re.sub(r'\s*વર્ગીકરણ.*$', '', district)
                    if district and len(district) < 50:
                        metadata['address_components']['district'] = district
            
            # Voter area/division (વિભાગ) - look for "વિભાગ 1 - છેરનાની - છેરનાની"
            if 'વિભાગ' in line and '-' in line:
                # Format: "વિભાગ 1 - છેરનાની - છેરનાની, પિન કોડ - 370627"
                # Extract the area name (the part after first dash, before second dash or comma)
                match = re.search(r'વિભાગ\s*\d+\s*-\s*([^,-]+?)(?:\s*-\s*[^,]+|,|$)', line)
                if match:
                    area = match.group(1).strip()
                    # Clean up - remove common prefixes/suffixes
                    area = re.sub(r'^\d+\s*', '', area)  # Remove leading numbers
                    if area and len(area) > 1 and len(area) < 50:  # At least 2 chars
                        metadata['address_components']['area'] = area
        
        # Extract voter counts (total, male, female)
        # Look for table format: "કુલ પુરુષ સ્ત્રી" followed by numbers
        for i, line in enumerate(lines):
            if not line or not isinstance(line, str):
                continue
            
            # Look for patterns like "કુલ 609" or "Total 609" or "કુલ 282 327 609"
            # Try to find a line with multiple numbers that might be male/female/total
            numbers = re.findall(r'\b(\d{2,4})\b', line)
            
            # If line contains "કુલ" or "Total", extract numbers
            if 'કુલ' in line or 'Total' in line.lower():
                if len(numbers) >= 1:
                    # Last number is usually total
                    try:
                        metadata['voter_counts']['total'] = int(numbers[-1])
                    except:
                        pass
                if len(numbers) >= 3:
                    # Format might be: male female total
                    try:
                        metadata['voter_counts']['male'] = int(numbers[0])
                        metadata['voter_counts']['female'] = int(numbers[1])
                        metadata['voter_counts']['total'] = int(numbers[2])
                    except:
                        pass
            
            # Look for patterns like "પુરુષ 282" or "Male 282"
            male_match = re.search(r'(?:પુરુષ|Male|પુ\.)[:\s]+(\d+)', line, re.IGNORECASE)
            if male_match:
                try:
                    metadata['voter_counts']['male'] = int(male_match.group(1))
                except:
                    pass
            
            # Look for patterns like "સ્ત્રી 327" or "Female 327"
            female_match = re.search(r'(?:સ્ત્રી|Female)[:\s]+(\d+)', line, re.IGNORECASE)
            if female_match:
                try:
                    metadata['voter_counts']['female'] = int(female_match.group(1))
                except:
                    pass
            
            # Also check for table format where numbers are in columns
            # Format: "પુરુષ સ્ત્રી કુલ" on one line, numbers on next
            # Or: "પુરૂષ સ્ત્રી કુલ" (line 24) followed by "282 327 609" (line 30)
            if ('પુરુષ' in line or 'પુરૂષ' in line or 'Male' in line) and ('સ્ત્રી' in line or 'Female' in line) and ('કુલ' in line or 'Total' in line):
                # Check next few lines for numbers (skip lines with text)
                for j in range(i+1, min(i+10, len(lines))):
                    next_line = lines[j] if j < len(lines) else ''
                    if next_line and isinstance(next_line, str):
                        # Look for line with 3 numbers (male, female, total)
                        nums = re.findall(r'\b(\d{2,4})\b', next_line)
                        # Filter out numbers that are too small (likely page numbers or serials)
                        nums = [n for n in nums if 10 <= int(n) <= 10000]
                        if len(nums) >= 3:
                            try:
                                # Usually format: male female total
                                metadata['voter_counts']['male'] = int(nums[0])
                                metadata['voter_counts']['female'] = int(nums[1])
                                metadata['voter_counts']['total'] = int(nums[2])
                                break
                            except:
                                pass
                        elif len(nums) == 2:
                            # Might be male and female, total might be on another line
                            try:
                                metadata['voter_counts']['male'] = int(nums[0])
                                metadata['voter_counts']['female'] = int(nums[1])
                            except:
                                pass
        
        return metadata
    
    def build_address(self, address_components: Dict[str, str], record: Dict[str, Any]) -> str:
        """Build address string from components and record data."""
        address_parts = []
        
        # House number from record
        house_no = record.get('house_no', '')
        if house_no and house_no != '-':
            address_parts.append(f"House {house_no}")
        
        # Area/Village/City (prefer area, then village_city)
        area = address_components.get('area')
        if area and isinstance(area, str) and area.strip():
            address_parts.append(area.strip())
        else:
            village_city = address_components.get('village_city')
            if village_city and isinstance(village_city, str):
                # Clean up village_city if it has duplicates
                village = village_city.strip()
                # Remove duplicates (e.g., "છેરનાની: છેરનાની" -> "છેરનાની")
                if ':' in village:
                    village = village.split(':')[-1].strip()
                if village:
                    address_parts.append(village)
        
        # Revenue Circle
        rc = address_components.get('revenue_circle')
        if rc and isinstance(rc, str) and rc.strip():
            address_parts.append(rc.strip())
        
        # Taluka
        taluka = address_components.get('taluka')
        if taluka and isinstance(taluka, str) and taluka.strip():
            address_parts.append(taluka.strip())
        
        # District
        district = address_components.get('district')
        if district and isinstance(district, str) and district.strip():
            address_parts.append(district.strip())
        
        return ", ".join(address_parts) if address_parts else ""
    
    def parse_ocr_table(self, text: str, pdf_metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Parse OCR text that's in table format (like Gujarati voter lists).
        
        Expected format per line:
        Serial House Name Relation RelationName Gender Age EPIC
        Example: "1 1ક કેર ઇસાક પિ. આમદ પુ. 41 001/000006"
        """
        records = []
        lines = text.split('\n')
        
        # Look for header row to identify column positions
        header_found = False
        epic_col_idx = None
        
        for i, line in enumerate(lines):
            if not line or not isinstance(line, str):
                continue
            line = line.strip()
            if not line:
                continue
            
            # Check if this is a header row
            if 'EPIC' in line.upper() or 'નંબર' in line:
                header_found = True
                # Try to find EPIC column
                parts = line.split()
                for idx, part in enumerate(parts):
                    if 'EPIC' in part.upper() or 'નંબર' in part:
                        epic_col_idx = idx
                        break
                continue
            
            # Skip lines that are clearly not data rows
            if any(x in line for x in ['વિભાગ', 'પૃષ્ઠ', 'ભાગ', 'સંબંધ', 'જાતિ', 'ઉંમર']):
                continue
            
            # Try to extract EPIC number from line (format: XXX/XXXXXX or ABC1234567)
            # But don't skip if EPIC is not found - keep the record
            epic_match = self.patterns['epic_alt'].search(line)
            epic_no = epic_match.group(1) if epic_match else None
            
            # Parse the line - split by spaces but be careful with Gujarati text
            # EPIC is usually at the end, so work backwards
            parts = line.split()
            
            # Find EPIC position
            epic_pos = -1
            for j, part in enumerate(parts):
                if (epic_no and epic_no in part) or (epic_col_idx and j == epic_col_idx):
                    epic_pos = j
                    break
            
            if epic_pos == -1:
                # EPIC not found in split, try to extract from end
                # Usually format: ... Age EPIC
                if len(parts) >= 2:
                    # Last part might be EPIC, second last might be age
                    if re.match(r'\d{3}/\d{6}', parts[-1]) or re.match(r'[A-Z]{3}\d{7}', parts[-1]):
                        epic_pos = len(parts) - 1
            
            # Extract fields (working backwards from EPIC if found)
            record = {}
            if epic_no:
                record['epic_no'] = epic_no
            
            # Extract house number (usually second field after serial number)
            if len(parts) > 1:
                house_no = parts[1]
                # House number might have Gujarati characters (like "1ક", "1કખ")
                # Clean it up but keep the format
                if house_no and house_no != '-':
                    record['house_no'] = house_no.strip()
            
            # If EPIC not found, try to parse from line structure anyway
            # EPIC position helps us parse other fields, but we can work without it
            if epic_pos == -1:
                # Try to find age and gender without EPIC position
                # Look for age pattern (2-3 digits) near the end
                for j in range(len(parts) - 3, len(parts)):
                    if j >= 0 and j < len(parts):
                        age_match = re.search(r'\b(\d{2,3})\b', parts[j])
                        if age_match:
                            try:
                                age = int(age_match.group(1))
                                if 18 <= age <= 120:  # Reasonable age range
                                    record['age'] = age
                                    # Gender might be before age
                                    if j > 0:
                                        gender_text = parts[j - 1]
                                        if 'પુ' in gender_text or 'પુરુષ' in gender_text or 'Male' in gender_text:
                                            record['gender'] = 'Male'
                                        elif 'સ્ત્રી' in gender_text or 'Female' in gender_text:
                                            record['gender'] = 'Female'
                                    break
                            except:
                                pass
                
                # If we still don't have enough info, skip this line
                if not record.get('name_og') and not record.get('age'):
                    continue
                
                # Set epic_pos to end for name extraction
                epic_pos = len(parts)
            
            # Age is usually before EPIC
            if epic_pos > 0:
                age_match = re.search(r'\b(\d{2,3})\b', parts[epic_pos - 1])
                if age_match:
                    try:
                        record['age'] = int(age_match.group(1))
                    except:
                        pass
            
            # Gender is usually before age (પુ. or સ્ત્રી)
            if epic_pos > 1:
                gender_text = parts[epic_pos - 2] if epic_pos >= 2 else ''
                if 'પુ' in gender_text or 'પુરુષ' in gender_text or 'Male' in gender_text:
                    record['gender'] = 'Male'
                elif 'સ્ત્રી' in gender_text or 'Female' in gender_text:
                    record['gender'] = 'Female'
            
            # Name and relation are at the beginning
            # Format is usually: Serial House Name Relation RelationName Gender Age EPIC
            # Example: "47 7 કેર હાજી પિ. હસણ પુ. 29 001/000034"
            name_start = 2  # Skip serial (0) and house (1)
            if len(parts) <= name_start:
                name_start = 1  # Fallback if only one number at start
            
            # Find where relation starts (look for relation indicators)
            # Note: OCR may produce different Unicode variants (પ vs ૫)
            relation_start = epic_pos
            for j in range(name_start, min(epic_pos, len(parts))):
                part = parts[j]
                # Check for relation indicators (including Unicode variants)
                if any(x in part for x in ['પિ.', 'મા.', 'પ.', '૫.', 'અ.', 'U', 'Father', 'Husband', 'Mother']):
                    relation_start = j
                    break
            
            # Extract name (everything from name_start to relation_start)
            if relation_start > name_start:
                name_parts = []
                for j in range(name_start, relation_start):
                    if j < len(parts):
                        part = parts[j]
                        # Skip if it's clearly not a name (pure numbers, EPIC patterns)
                        if re.match(r'^\d+$', part) or re.match(r'\d{3}/\d{6}', part) or re.match(r'^[A-Z]{3}\d{7}$', part):
                            continue
                        name_parts.append(part)
                
                if name_parts:
                    name = ' '.join(name_parts)
                    # Remove "કેર" prefix if present (house/household indicator)
                    name = re.sub(r'^કેર\s+', '', name).strip()
                    # Don't set name if it's empty, just a dash, or looks like EPIC/number
                    if name and name != '-' and not re.match(r'^\d+/\d+$', name) and not re.match(r'^[A-Z]{3}\d{7}$', name):
                        record['name_og'] = name
            
            # Extract relation type and relation name separately
            # Note: OCR may produce different Unicode variants (પ vs ૫)
            # relation_type: "Father", "Husband", "Mother"
            # relation_og: just the relation name in OG (e.g., "આમદ")
            for j in range(name_start, min(len(parts), epic_pos - 2)):
                part = parts[j]
                if 'પિ.' in part or 'પિતા' in part or 'Father' in part:
                    record['relation_type'] = 'Father'
                    # Next part is the relation name (just the name, not the type)
                    if j + 1 < len(parts):
                        rel_name = parts[j + 1]
                        if rel_name and rel_name != '-' and not rel_name.isdigit():
                            record['relation_og'] = rel_name.strip()
                    break
                elif 'મા.' in part or 'માતા' in part or 'Mother' in part:
                    record['relation_type'] = 'Mother'
                    if j + 1 < len(parts):
                        rel_name = parts[j + 1]
                        if rel_name and rel_name != '-' and not rel_name.isdigit():
                            record['relation_og'] = rel_name.strip()
                    break
                elif 'પ.' in part or '૫.' in part or 'પતિ' in part or 'Husband' in part:
                    # Both પ. and ૫. are variants of "husband/wife" relation
                    record['relation_type'] = 'Husband'
                    if j + 1 < len(parts):
                        rel_name = parts[j + 1]
                        if rel_name and rel_name != '-' and not rel_name.isdigit():
                            record['relation_og'] = rel_name.strip()
                    break
            
            # Keep record if it has at least name or age (don't require EPIC)
            if record.get('name_og') or record.get('age'):
                records.append(record)
        
        return records

