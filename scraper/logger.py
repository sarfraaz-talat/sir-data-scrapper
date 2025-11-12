"""
Logging module with rich console output and file logging
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.panel import Panel
from datetime import datetime

from .utils import ensure_dir, get_timestamp


class Logger:
    """Centralized logging with rich console output and optional file logging."""
    
    def __init__(self, save_logs: bool = False, log_dir: str = "logs"):
        self.save_logs = save_logs
        self.log_dir = log_dir
        self.console = Console()
        self.logger = logging.getLogger("sir_scraper")
        self.logger.setLevel(logging.DEBUG)
        
        # Rich console handler (always enabled)
        console_handler = RichHandler(
            console=self.console,
            rich_tracebacks=True,
            show_time=True,
            show_path=False
        )
        console_handler.setLevel(logging.INFO)
        self.logger.addHandler(console_handler)
        
        # File handler (if save_logs enabled)
        self.file_handler: Optional[logging.FileHandler] = None
        if save_logs:
            ensure_dir(log_dir)
            log_file = Path(log_dir) / f"run_{get_timestamp()}.log"
            self.file_handler = logging.FileHandler(log_file, encoding='utf-8')
            self.file_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            self.file_handler.setFormatter(formatter)
            self.logger.addHandler(self.file_handler)
            self.logger.info(f"Logging to file: {log_file}")
    
    def info(self, message: str):
        """Log info message."""
        self.logger.info(message)
    
    def warning(self, message: str):
        """Log warning message."""
        self.logger.warning(message)
    
    def error(self, message: str):
        """Log error message."""
        self.logger.error(message)
    
    def debug(self, message: str):
        """Log debug message."""
        self.logger.debug(message)
    
    def success(self, message: str):
        """Log success message with rich styling."""
        self.console.print(f"[green]✅ {message}[/green]")
        self.logger.info(message)
    
    def state_assembly(self, state: str, assembly: str):
        """Display state and assembly header."""
        panel = Panel(
            f"[bold cyan]State:[/bold cyan] {state}\n[bold cyan]Assembly:[/bold cyan] {assembly}",
            border_style="cyan",
            title="Processing"
        )
        self.console.print(panel)
        self.logger.info(f"Processing State: {state}, Assembly: {assembly}")
    
    def download_progress(self, filename: str, size: str):
        """Log download progress."""
        self.console.print(f"→ [yellow]Downloading[/yellow] {filename}... ✅ {size}")
        self.logger.info(f"Downloaded {filename} ({size})")
    
    def extraction_progress(self, count: int):
        """Log extraction progress."""
        self.console.print(f"→ [blue]Extracted[/blue] {count} PDFs")
        self.logger.info(f"Extracted {count} PDFs")
    
    def parsing_progress(self, count: int):
        """Log parsing progress."""
        self.console.print(f"→ [magenta]Parsed[/magenta] {count:,} records")
        self.logger.info(f"Parsed {count} records")
    
    def db_progress(self, new: int, updated: int):
        """Log database insertion progress."""
        self.console.print(f"→ [green]Inserted:[/green] {new:,} new | {updated:,} updated")
        self.logger.info(f"Database: {new} new, {updated} updated records")
    
    def create_progress(self) -> Progress:
        """Create a rich Progress instance."""
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console
        )
    
    def close(self):
        """Close file handler if exists."""
        if self.file_handler:
            self.file_handler.close()
            self.logger.removeHandler(self.file_handler)

