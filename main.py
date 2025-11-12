#!/usr/bin/env python3
"""
Main entry point for SIR Data Scraper - Refactored 3-Stage Pipeline
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

from scraper.logger import Logger
from scraper.crawler import Crawler
from scraper.downloader import Downloader
from scraper.extractor import Extractor
from scraper.parser import Parser
from scraper.translator import VoterTranslator
from scraper.db_loader import DBLoader
from scraper.checkpoint import CheckpointManager
from scraper.pipeline import Pipeline


class SIRScraper:
    """Main orchestrator for the SIR data scraping pipeline."""
    
    def __init__(
        self,
        state_filter: Optional[str] = None,
        max_assemblies: Optional[int] = None,
        translate: bool = False,
        save_logs: bool = False,
        resume: bool = False,
        db_path: str = "data/voters.db",
        headless: bool = True,
        max_parse_workers: int = 4
    ):
        self.state_filter = state_filter
        self.max_assemblies = max_assemblies
        self.translate = translate
        self.save_logs = save_logs
        self.resume = resume
        self.db_path = db_path
        self.max_parse_workers = max_parse_workers
        
        # Initialize components
        self.logger = Logger(save_logs=save_logs)
        self.crawler = Crawler(self.logger, headless=headless)
        self.downloader = Downloader(self.logger, max_concurrent=5)  # Parallel downloads
        self.extractor = Extractor(self.logger)
        self.parser = Parser(self.logger, use_ocr=True)
        self.translator = VoterTranslator(self.logger, enabled=translate) if translate else None
        self.db_loader = DBLoader(db_path)
        self.checkpoint = CheckpointManager()
        
        # Create pipeline
        self.pipeline = Pipeline(
            self.logger,
            self.downloader,
            self.extractor,
            self.parser,
            self.translator,
            self.db_loader,
            self.checkpoint,
            max_parse_workers=max_parse_workers
        )
    
    async def run(self):
        """Main execution loop."""
        try:
            self.logger.info("="*80)
            self.logger.info("SIR DATA SCRAPER - 3-STAGE PIPELINE")
            self.logger.info("="*80)
            self.logger.info("Stage 1: Download (parallel, skip if exists)")
            self.logger.info("Stage 2: Parse (parallel within constituency)")
            self.logger.info("Stage 3: Store (database)")
            self.logger.info("="*80)
            
            # Check resume status
            if self.resume:
                self.logger.info("\nResume mode: Checking checkpoints...")
                incomplete = self.checkpoint.get_incomplete_constituencies()
                if incomplete:
                    self.logger.info(f"Found {len(incomplete)} incomplete constituency(ies)")
                    for key in incomplete:
                        self.logger.info(f"  - {key}")
                else:
                    self.logger.info("No incomplete constituencies found")
            
            # Group URLs by state/assembly
            url_groups = {}
            
            self.logger.info("\nExtracting download URLs...")
            async for url_data in self.crawler.crawl_all(
                state_filter=self.state_filter,
                max_assemblies=self.max_assemblies,
                use_checkpoint=self.resume
            ):
                key = (url_data['state'], url_data['assembly'])
                if key not in url_groups:
                    url_groups[key] = []
                url_groups[key].append(url_data)
            
            self.logger.info(f"Found URLs for {len(url_groups)} assembly(ies)")
            self.logger.info("Browser closed. Starting pipeline...")
            
            # Process each assembly through 3 stages
            base_dir = Path("data/voterlists")
            for (state, assembly), urls in url_groups.items():
                # Check if already complete
                if self.resume and self.checkpoint.is_constituency_complete(state, assembly):
                    self.logger.info(f"\nSkipping completed constituency: {state}/{assembly}")
                    continue
                
                # Process through pipeline
                await self.pipeline.process_constituency(
                    state, assembly, urls, base_dir
                )
            
            # Print final stats
            stats = self.db_loader.get_stats()
            self.logger.info(f"\n{'='*80}")
            self.logger.info("FINAL STATISTICS")
            self.logger.info(f"{'='*80}")
            self.logger.info(f"Total records: {stats['total_records']:,}")
            self.logger.info(f"States: {stats['states']}")
            self.logger.info(f"Assemblies: {stats['assemblies']}")
            self.logger.info(f"{'='*80}")
            
        except KeyboardInterrupt:
            self.logger.warning("\nInterrupted by user. Checkpoints saved.")
        except Exception as e:
            self.logger.error(f"Fatal error: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            raise
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Cleanup resources."""
        self.logger.close()
        self.db_loader.close()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="SIR Data Scraper - 3-Stage Pipeline (Download → Parse → Store)"
    )
    
    parser.add_argument(
        '--state',
        type=str,
        help='Limit to a specific state'
    )
    
    parser.add_argument(
        '--max-assemblies',
        type=int,
        help='Limit assemblies (for testing)'
    )
    
    parser.add_argument(
        '--translate',
        action='store_true',
        help='Enable OG → English translation'
    )
    
    parser.add_argument(
        '--savelogs',
        action='store_true',
        help='Save extended logs to file'
    )
    
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Continue from last checkpoint (checks latest.json)'
    )
    
    parser.add_argument(
        '--db',
        type=str,
        default='data/voters.db',
        help='Custom DB path (default: data/voters.db)'
    )
    
    parser.add_argument(
        '--headless',
        action='store_true',
        default=True,
        help='Run browser in headless mode (default: True)'
    )
    
    parser.add_argument(
        '--show-browser',
        action='store_true',
        help='Show browser window (sets headless=False)'
    )
    
    parser.add_argument(
        '--parse-workers',
        type=int,
        default=4,
        help='Number of parallel workers for parsing (default: 4)'
    )
    
    args = parser.parse_args()
    
    # Determine headless mode
    headless = not args.show_browser if args.show_browser else args.headless
    
    # Create scraper instance
    scraper = SIRScraper(
        state_filter=args.state,
        max_assemblies=args.max_assemblies,
        translate=args.translate,
        save_logs=args.savelogs,
        resume=args.resume,
        db_path=args.db,
        headless=headless,
        max_parse_workers=args.parse_workers
    )
    
    # Run async pipeline
    try:
        asyncio.run(scraper.run())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)


if __name__ == "__main__":
    main()

