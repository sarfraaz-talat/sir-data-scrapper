"""
3-Stage Pipeline: Download → Parse → Store
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from .logger import Logger
from .downloader import Downloader
from .extractor import Extractor
from .parser import Parser
from .translator import VoterTranslator
from .db_loader import DBLoader
from .checkpoint import CheckpointManager
from .utils import sanitize_filename


class Pipeline:
    """3-stage pipeline: Download → Parse → Store"""
    
    def __init__(
        self,
        logger: Logger,
        downloader: Downloader,
        extractor: Extractor,
        parser: Parser,
        translator: Optional[VoterTranslator],
        db_loader: DBLoader,
        checkpoint_manager: CheckpointManager,
        max_parse_workers: int = 4
    ):
        self.logger = logger
        self.downloader = downloader
        self.extractor = extractor
        self.parser = parser
        self.translator = translator
        self.db_loader = db_loader
        self.checkpoint = checkpoint_manager
        self.max_parse_workers = max_parse_workers
    
    async def stage1_download(
        self,
        state: str,
        assembly: str,
        urls: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Stage 1: Download ZIP files (parallel, skip if exists)."""
        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"STAGE 1: DOWNLOAD - {state}/{assembly}")
        self.logger.info(f"{'='*80}")
        self.logger.info(f"Found {len(urls)} ZIP file(s) to download")
        
        # Check checkpoint
        status = self.checkpoint.get_constituency_status(state, assembly)
        if status.get('download', {}).get('status') == 'completed':
            self.logger.info(f"✓ Download already completed (skipping)")
            return status['download']['data']
        
        # Mark as in progress
        self.checkpoint.save_checkpoint(
            state, assembly, 'download', 'in_progress',
            {'urls': len(urls), 'started': True}
        )
        
        # Download (parallel, skips existing files)
        download_results = await self.downloader.download_batch(urls)
        
        successful = [r for r in download_results if r['success']]
        failed = [r for r in download_results if not r['success']]
        skipped = [r for r in download_results if r.get('skipped', False)]
        
        self.logger.info(f"Download Results:")
        self.logger.info(f"  ✓ Successful: {len(successful)}")
        self.logger.info(f"  ⊘ Skipped (exists): {len(skipped)}")
        self.logger.info(f"  ✗ Failed: {len(failed)}")
        
        if failed:
            for result in failed:
                self.logger.warning(f"  Failed: {result.get('url', 'unknown')}")
        
        # Save checkpoint
        download_data = {
            'total_urls': len(urls),
            'successful': len(successful),
            'skipped': len(skipped),
            'failed': len(failed),
            'files': [r.get('filepath') for r in successful + skipped]
        }
        
        self.checkpoint.save_checkpoint(
            state, assembly, 'download', 'completed',
            download_data
        )
        
        self.logger.info(f"✓ Stage 1 Complete: {len(successful + skipped)} files ready")
        return download_data
    
    def stage2_parse(
        self,
        state: str,
        assembly: str,
        base_dir: Path
    ) -> Dict[str, Any]:
        """Stage 2: Parse PDFs (parallel within constituency)."""
        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"STAGE 2: PARSE - {state}/{assembly}")
        self.logger.info(f"{'='*80}")
        
        # Check checkpoint
        status = self.checkpoint.get_constituency_status(state, assembly)
        if status.get('parse', {}).get('status') == 'completed':
            self.logger.info(f"✓ Parse already completed (skipping)")
            return status['parse']['data']
        
        # Find PDFs
        state_dir = base_dir / sanitize_filename(state)
        assembly_dir = state_dir / sanitize_filename(assembly)
        
        pdf_files = sorted(assembly_dir.rglob('*.pdf'))
        total_pdfs = len(pdf_files)
        
        if total_pdfs == 0:
            self.logger.warning(f"No PDFs found in {state}/{assembly}")
            parse_data = {
                'total_pdfs': 0,
                'parsed_pdfs': 0,
                'total_records': 0,
                'records': []
            }
            self.checkpoint.save_checkpoint(
                state, assembly, 'parse', 'completed', parse_data
            )
            return parse_data
        
        self.logger.info(f"Found {total_pdfs} PDF file(s) to parse")
        self.logger.info(f"Using {self.max_parse_workers} parallel workers")
        
        # Mark as in progress
        self.checkpoint.save_checkpoint(
            state, assembly, 'parse', 'in_progress',
            {'total_pdfs': total_pdfs, 'started': True}
        )
        
        # Parse in parallel
        all_records = []
        parsed_count = 0
        failed_count = 0
        
        def parse_single_pdf(pdf_path: Path) -> tuple:
            """Parse a single PDF and return (success, records, pdf_name)."""
            try:
                records = self.parser.parse_pdf(pdf_path)
                
                # Add metadata
                for record in records:
                    record['state'] = state
                    record['assembly'] = assembly
                    record['source_file'] = pdf_path.name
                    record.pop('_pdf_metadata', None)
                
                return (True, records, pdf_path.name)
            except Exception as e:
                self.logger.error(f"Error parsing {pdf_path.name}: {e}")
                return (False, [], pdf_path.name)
        
        # Use ThreadPoolExecutor for parallel parsing
        with ThreadPoolExecutor(max_workers=self.max_parse_workers) as executor:
            # Submit all tasks
            future_to_pdf = {
                executor.submit(parse_single_pdf, pdf_path): pdf_path
                for pdf_path in pdf_files
            }
            
            # Process results as they complete
            for future in as_completed(future_to_pdf):
                pdf_path = future_to_pdf[future]
                try:
                    success, records, pdf_name = future.result()
                    
                    if success:
                        all_records.extend(records)
                        parsed_count += 1
                        
                        if parsed_count % 10 == 0:
                            self.logger.info(
                                f"  Progress: {parsed_count}/{total_pdfs} PDFs parsed, "
                                f"{len(all_records):,} records extracted"
                            )
                    else:
                        failed_count += 1
                        
                except Exception as e:
                    self.logger.error(f"Error processing {pdf_path.name}: {e}")
                    failed_count += 1
        
        self.logger.info(f"\nParse Results:")
        self.logger.info(f"  ✓ Parsed: {parsed_count}/{total_pdfs} PDFs")
        self.logger.info(f"  ✗ Failed: {failed_count} PDFs")
        self.logger.info(f"  📊 Total Records: {len(all_records):,}")
        
        # Save checkpoint
        parse_data = {
            'total_pdfs': total_pdfs,
            'parsed_pdfs': parsed_count,
            'failed_pdfs': failed_count,
            'total_records': len(all_records),
            'records': all_records  # Store records for stage 3
        }
        
        self.checkpoint.save_checkpoint(
            state, assembly, 'parse', 'completed', parse_data
        )
        
        self.logger.info(f"✓ Stage 2 Complete: {len(all_records):,} records extracted")
        return parse_data
    
    def stage3_store(
        self,
        state: str,
        assembly: str,
        records: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Stage 3: Store records in database."""
        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"STAGE 3: STORE - {state}/{assembly}")
        self.logger.info(f"{'='*80}")
        
        if not records:
            self.logger.warning(f"No records to store for {state}/{assembly}")
            store_data = {
                'total_records': 0,
                'inserted': 0,
                'updated': 0,
                'stored_in_db': False
            }
            self.checkpoint.save_checkpoint(
                state, assembly, 'db', 'completed', store_data
            )
            return store_data
        
        # Check checkpoint
        status = self.checkpoint.get_constituency_status(state, assembly)
        if status.get('db', {}).get('status') == 'completed':
            self.logger.info(f"✓ Database storage already completed (skipping)")
            return status['db']['data']
        
        self.logger.info(f"Storing {len(records):,} records in database...")
        
        # Mark as in progress
        self.checkpoint.save_checkpoint(
            state, assembly, 'db', 'in_progress',
            {'total_records': len(records), 'started': True}
        )
        
        # Translate if enabled
        if self.translator and self.translator.enabled:
            self.logger.info("Translating records...")
            records = self.translator.translate_batch(records)
            self.logger.info(f"✓ Translation complete")
        
        # Store in database
        new_count, updated_count = self.db_loader.batch_insert(records)
        
        self.logger.info(f"\nDatabase Results:")
        self.logger.info(f"  ✓ New records: {new_count:,}")
        self.logger.info(f"  ↻ Updated records: {updated_count:,}")
        self.logger.info(f"  📊 Total stored: {new_count + updated_count:,}")
        
        # Save checkpoint
        store_data = {
            'total_records': len(records),
            'inserted': new_count,
            'updated': updated_count,
            'stored_in_db': True
        }
        
        self.checkpoint.save_checkpoint(
            state, assembly, 'db', 'completed', store_data
        )
        
        self.logger.info(f"✓ Stage 3 Complete: Records stored in database")
        return store_data
    
    async def process_constituency(
        self,
        state: str,
        assembly: str,
        urls: List[Dict[str, str]],
        base_dir: Path
    ) -> Dict[str, Any]:
        """Process one constituency through all 3 stages."""
        self.logger.info(f"\n{'#'*80}")
        self.logger.info(f"PROCESSING CONSTITUENCY: {state}/{assembly}")
        self.logger.info(f"{'#'*80}")
        
        result = {
            'state': state,
            'assembly': assembly,
            'stages': {}
        }
        
        try:
            # Stage 1: Download
            download_data = await self.stage1_download(state, assembly, urls)
            result['stages']['download'] = download_data
            
            # Stage 2: Extract (if needed)
            if download_data.get('successful', 0) > 0:
                self.logger.info(f"\nExtracting ZIP files...")
                extract_result = self.extractor.extract_assembly(state, assembly)
                if extract_result and extract_result.get('pdfs'):
                    self.logger.info(f"✓ Extracted {len(extract_result['pdfs'])} PDFs")
            
            # Stage 2: Parse
            parse_data = self.stage2_parse(state, assembly, base_dir)
            result['stages']['parse'] = parse_data
            
            # Stage 3: Store
            records = parse_data.get('records', [])
            store_data = self.stage3_store(state, assembly, records)
            result['stages']['store'] = store_data
            
            # Final summary
            self.logger.info(f"\n{'#'*80}")
            self.logger.info(f"✓ CONSTITUENCY COMPLETE: {state}/{assembly}")
            self.logger.info(f"{'#'*80}")
            self.logger.info(f"  Downloads: {download_data.get('successful', 0) + download_data.get('skipped', 0)} files")
            self.logger.info(f"  Parsed: {parse_data.get('parsed_pdfs', 0)}/{parse_data.get('total_pdfs', 0)} PDFs")
            self.logger.info(f"  Records: {parse_data.get('total_records', 0):,}")
            self.logger.info(f"  Stored: {store_data.get('inserted', 0) + store_data.get('updated', 0):,} records")
            self.logger.info(f"{'#'*80}\n")
            
        except Exception as e:
            self.logger.error(f"Error processing {state}/{assembly}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            result['error'] = str(e)
        
        return result

