"""
Optional translator for converting OG text to English
"""

from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from .logger import Logger

# Optional translation import
try:
    from deep_translator import GoogleTranslator
    TRANSLATION_AVAILABLE = True
except ImportError:
    TRANSLATION_AVAILABLE = False


class VoterTranslator:
    """Translate voter data fields from original language to English."""
    
    def __init__(self, logger: Logger, enabled: bool = True, max_workers: int = 4):
        self.logger = logger
        if enabled and not TRANSLATION_AVAILABLE:
            self.logger.warning("Translation requested but deep-translator not available")
        self.enabled = enabled and TRANSLATION_AVAILABLE
        self.translator = GoogleTranslator(source='auto', target='en') if self.enabled else None
        self.max_workers = max_workers if self.enabled else 1
        self.batch_size = 50  # Batch size for translation
    
    def translate_text(self, text: str, source_lang: str = 'auto', target_lang: str = 'en') -> str:
        """Translate a single text string."""
        if not self.enabled or not text or not self.translator:
            return text
        
        try:
            # deep-translator handles auto-detection
            result = self.translator.translate(text)
            return result
        except Exception as e:
            self.logger.warning(f"Translation failed for '{text[:50]}...': {e}")
            return text
    
    def translate_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Translate all OG fields in a record to English."""
        if not self.enabled:
            return record
        
        # Create a new translator instance for thread safety
        # Each thread needs its own translator instance
        try:
            thread_translator = GoogleTranslator(source='auto', target='en')
        except Exception:
            thread_translator = self.translator
        
        # Translate name
        if 'name_og' in record and record['name_og']:
            try:
                record['name_en'] = thread_translator.translate(record['name_og'])
            except Exception as e:
                self.logger.debug(f"Translation failed for name: {e}")
                record['name_en'] = record.get('name_og', '')
        
        # Translate relation
        if 'relation_og' in record and record['relation_og']:
            try:
                record['relation_en'] = thread_translator.translate(record['relation_og'])
            except Exception as e:
                self.logger.debug(f"Translation failed for relation: {e}")
                record['relation_en'] = record.get('relation_og', '')
        
        # Translate address
        if 'address_og' in record and record['address_og']:
            try:
                record['address_en'] = thread_translator.translate(record['address_og'])
            except Exception as e:
                self.logger.debug(f"Translation failed for address: {e}")
                record['address_en'] = record.get('address_og', '')
        
        return record
    
    def translate_batch(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Translate a batch of records using parallel workers."""
        if not self.enabled:
            return records
        
        total_records = len(records)
        self.logger.info(f"Translating {total_records:,} records using {self.max_workers} workers...")
        
        # Use ThreadPoolExecutor for parallel translation
        translated = [None] * total_records  # Pre-allocate list to maintain order
        completed_count = 0
        failed_count = 0
        
        def translate_single_record(index: int, record: Dict[str, Any]) -> tuple:
            """Translate a single record and return (index, translated_record, success)."""
            try:
                translated_record = self.translate_record(record)
                return (index, translated_record, True)
            except Exception as e:
                self.logger.debug(f"Translation error for record {index}: {e}")
                return (index, record, False)
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_index = {
                executor.submit(translate_single_record, i, record): i
                for i, record in enumerate(records)
            }
            
            # Process results as they complete
            for future in as_completed(future_to_index):
                try:
                    index, translated_record, success = future.result()
                    translated[index] = translated_record
                    completed_count += 1
                    
                    if not success:
                        failed_count += 1
                    
                    # Progressive logging: every 10 records for small batches, every 50 for large batches
                    log_interval = 10 if total_records < 1000 else 50
                    if completed_count % log_interval == 0 or completed_count == total_records:
                        progress_pct = (completed_count / total_records * 100) if total_records > 0 else 0
                        self.logger.info(
                            f"  Translation progress: {completed_count:,}/{total_records:,} "
                            f"({progress_pct:.1f}%) - {failed_count} failed"
                        )
                
                except Exception as e:
                    index = future_to_index[future]
                    self.logger.warning(f"Translation error for record {index}: {e}")
                    translated[index] = records[index]  # Keep original if translation fails
                    completed_count += 1
                    failed_count += 1
        
        self.logger.info(
            f"✓ Translation complete: {completed_count:,}/{total_records:,} records "
            f"({failed_count} failed)"
        )
        
        return translated

