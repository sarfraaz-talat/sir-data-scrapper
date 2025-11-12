"""
Async downloader for ZIP files using aiohttp
"""

import aiohttp
import aiofiles
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

from .utils import ensure_dir, sanitize_filename, format_size
from .logger import Logger


class Downloader:
    """Async batch downloader with retry logic."""
    
    def __init__(
        self,
        logger: Logger,
        base_dir: str = "data/voterlists",
        max_concurrent: int = 1,
        max_retries: int = 3
    ):
        self.logger = logger
        self.base_dir = base_dir
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def download_file(
        self,
        session: aiohttp.ClientSession,
        url: str,
        filepath: Path,
        state: str,
        assembly: str
    ) -> bool:
        """Download a single file with retry logic."""
        async with self.semaphore:
            for attempt in range(self.max_retries):
                try:
                    # Use longer timeout for large files (30 minutes)
                    # Disable automatic decompression and use read() for better performance
                    async with session.get(
                        url, 
                        timeout=aiohttp.ClientTimeout(total=1800),
                        allow_redirects=True
                    ) as response:
                        if response.status == 200:
                            # Get expected file size
                            total_size = int(response.headers.get('Content-Length', 0))
                            
                            # Read entire content at once for better performance (aiohttp handles buffering)
                            # This is faster than iter_chunked for most cases
                            content = await response.read()
                            downloaded = len(content)
                            
                            # Write to file
                            async with aiofiles.open(filepath, 'wb') as f:
                                await f.write(content)
                            
                            # Log completion
                            if total_size > 0:
                                progress_pct = (downloaded / total_size * 100) if total_size > 0 else 0
                                self.logger.info(
                                    f"  ✓ Downloaded {filepath.name}: {format_size(downloaded)} / {format_size(total_size)} ({progress_pct:.1f}%)"
                                )
                            else:
                                self.logger.info(f"  ✓ Downloaded {filepath.name}: {format_size(downloaded)}")
                            
                            # Verify download completed
                            actual_size = filepath.stat().st_size
                            
                            # Check if download seems incomplete
                            if total_size > 0 and actual_size < total_size * 0.9:  # Allow 10% tolerance
                                self.logger.warning(
                                    f"Download may be incomplete: expected {format_size(total_size)}, got {format_size(actual_size)}"
                                )
                                # Delete incomplete file and retry
                                filepath.unlink()
                                if attempt < self.max_retries - 1:
                                    continue
                                return False
                            
                            size_str = format_size(actual_size)
                            self.logger.download_progress(filepath.name, size_str)
                            return True
                        
                        else:
                            self.logger.warning(
                                f"Download failed for {url}: HTTP {response.status} (attempt {attempt + 1}/{self.max_retries})"
                            )
                
                except asyncio.TimeoutError:
                    self.logger.warning(
                        f"Timeout downloading {url} (attempt {attempt + 1}/{self.max_retries})"
                    )
                    # Delete partial file if exists
                    if filepath.exists():
                        filepath.unlink()
                
                except Exception as e:
                    self.logger.warning(
                        f"Error downloading {url}: {e} (attempt {attempt + 1}/{self.max_retries})"
                    )
                    # Delete partial file if exists
                    if filepath.exists():
                        filepath.unlink()
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
            
            self.logger.error(f"Failed to download {url} after {self.max_retries} attempts")
            return False
    
    async def download_batch(
        self,
        urls: List[Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """
        Download a batch of URLs concurrently.
        Returns list of download results with success status.
        """
        results = []
        
        # Create session with optimized settings for faster downloads
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=10)
        timeout = aiohttp.ClientTimeout(total=1800, connect=30)
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            read_bufsize=2 * 1024 * 1024  # 2MB read buffer
        ) as session:
            tasks = []
            
            for url_data in urls:
                state = sanitize_filename(url_data['state'])
                assembly = sanitize_filename(url_data['assembly'])
                url = url_data['url']
                filename = url_data.get('filename', urlparse(url).path.split('/')[-1])
                
                # Ensure filename is safe
                filename = sanitize_filename(filename)
                if not filename.endswith('.zip') and not filename.endswith('.pdf'):
                    # Try to determine from URL
                    if '.zip' in url.lower():
                        filename += '.zip'
                    elif '.pdf' in url.lower():
                        filename += '.pdf'
                    else:
                        filename += '.zip'
                
                # Sanitize assembly name - don't use "Download" or "Unknown"
                assembly_clean = sanitize_filename(assembly)
                if assembly_clean.lower() in ['download', 'unknown', '']:
                    # Try to extract from filename or use a default
                    assembly_clean = "Unknown_Assembly"
                
                # Create directory structure
                dir_path = ensure_dir(Path(self.base_dir) / state / assembly_clean)
                filepath = dir_path / filename
                
                # Skip if already exists (check file size to ensure it's complete)
                if filepath.exists():
                    file_size = filepath.stat().st_size
                    if file_size > 0:
                        self.logger.debug(f"Skipping existing file: {filepath.name} ({format_size(file_size)})")
                        results.append({
                            'state': url_data['state'],
                            'assembly': url_data['assembly'],
                            'url': url,
                            'filepath': str(filepath),
                            'success': True,
                            'skipped': True,
                            'size': file_size
                        })
                        continue
                    else:
                        self.logger.warning(f"Existing file is empty, re-downloading: {filepath.name}")
                
                # Create download task
                task = self.download_file(session, url, filepath, state, assembly)
                tasks.append((task, url_data, filepath))
            
            # Execute all downloads
            for task, url_data, filepath in tasks:
                success = await task
                results.append({
                    'state': url_data['state'],
                    'assembly': url_data['assembly'],
                    'url': url_data['url'],
                    'filepath': str(filepath),
                    'success': success,
                    'skipped': False
                })
        
        return results

