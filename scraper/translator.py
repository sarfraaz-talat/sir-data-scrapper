"""
Optional translator for converting OG text to English
"""

from typing import List, Dict, Any, Optional
from .logger import Logger

# Optional translation import
try:
    from deep_translator import GoogleTranslator
    TRANSLATION_AVAILABLE = True
except ImportError:
    TRANSLATION_AVAILABLE = False


class VoterTranslator:
    """Translate voter data fields from original language to English."""
    
    def __init__(self, logger: Logger, enabled: bool = True):
        self.logger = logger
        if enabled and not TRANSLATION_AVAILABLE:
            self.logger.warning("Translation requested but deep-translator not available")
        self.enabled = enabled and TRANSLATION_AVAILABLE
        self.translator = GoogleTranslator(source='auto', target='en') if self.enabled else None
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
        
        # Translate name
        if 'name_og' in record and record['name_og']:
            record['name_en'] = self.translate_text(record['name_og'])
        
        # Translate relation
        if 'relation_og' in record and record['relation_og']:
            record['relation_en'] = self.translate_text(record['relation_og'])
        
        # Translate address
        if 'address_og' in record and record['address_og']:
            record['address_en'] = self.translate_text(record['address_og'])
        
        return record
    
    def translate_batch(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Translate a batch of records."""
        if not self.enabled:
            return records
        
        self.logger.info(f"Translating {len(records)} records...")
        
        translated = []
        for i, record in enumerate(records):
            try:
                translated_record = self.translate_record(record)
                translated.append(translated_record)
                
                # Log progress every 100 records
                if (i + 1) % 100 == 0:
                    self.logger.debug(f"Translated {i + 1}/{len(records)} records")
            
            except Exception as e:
                self.logger.warning(f"Translation error for record {i}: {e}")
                translated.append(record)  # Keep original if translation fails
        
        return translated

