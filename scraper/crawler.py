"""
Web crawler using Playwright to extract ZIP download URLs from SIR portal
"""

import asyncio
from typing import List, Dict, Any, Optional, Iterator
from playwright.async_api import async_playwright, Browser, Page
import json
from pathlib import Path

from .utils import save_checkpoint, load_checkpoint, sanitize_filename
from .logger import Logger


class Crawler:
    """Crawler to extract ZIP URLs from SIR portal."""
    
    SIR_URL = "https://voters.eci.gov.in/searchInSIR/S2UA4DPDF-JK4QWODSE"
    
    # Direct state URLs (for bypassing React Select when needed)
    STATE_DIRECT_URLS = {
        "Gujarat": "https://erms.gujarat.gov.in/ceo-gujarat/master/voterlist2002.aspx"
    }
    
    def __init__(self, logger: Logger, checkpoint_path: str = "data/checkpoint.json", headless: bool = True):
        self.logger = logger
        self.checkpoint_path = checkpoint_path
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
    
    async def initialize(self):
        """Initialize Playwright browser."""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=self.headless)
        self.page = await self.browser.new_page()
        self.logger.info(f"Browser initialized (headless={self.headless})")
    
    async def close(self):
        """Close browser."""
        if self.browser:
            await self.browser.close()
    
    async def get_states(self) -> List[str]:
        """Extract all state names from React Select dropdown."""
        try:
            await self.page.goto(self.SIR_URL, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(3)  # Wait for page to load
            
            # Find the state dropdown React Select
            state_dropdown = await self.page.query_selector('div.css-13cymwt-control')
            if not state_dropdown:
                self.logger.error("Could not find state React Select dropdown")
                return []
            
            # Click to open the dropdown
            await state_dropdown.click()
            await asyncio.sleep(2)  # Wait for dropdown menu to appear
            
            # Find the menu
            menu = None
            for attempt in range(5):
                menu = await self.page.query_selector('div[role="listbox"]:visible')
                if menu and await menu.is_visible():
                    break
                await asyncio.sleep(0.5)
            
            if not menu:
                self.logger.error("Could not find state dropdown menu after opening")
                await self.page.keyboard.press('Escape')
                return []
            
            # Get all option elements
            options = await menu.query_selector_all('div[role="option"]')
            states = []
            
            for option in options:
                try:
                    text = await option.inner_text()
                    if text and text.strip():
                        text_clean = text.strip()
                        # Skip placeholder/empty options
                        if text_clean.lower() not in ['select state', 'select', 'choose state', '--select--', '']:
                            states.append(text_clean)
                except Exception:
                    continue
            
            # Close the dropdown
            await self.page.keyboard.press('Escape')
            await asyncio.sleep(0.5)
            
            self.logger.info(f"Found {len(states)} states")
            return states
        
        except Exception as e:
            self.logger.error(f"Error getting states: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return []
    
    async def _get_state_code(self, state_name: str) -> Optional[str]:
        """Get state code (e.g., S06 for Gujarat)."""
        # State code mapping (can be expanded)
        state_codes = {
            "Gujarat": "S06",
        }
        # First check if we have it in our mapping
        if state_name in state_codes:
            return state_codes[state_name]
        
        # Otherwise, try to get it from the page
        try:
            # Open state dropdown
            state_dropdown = await self.page.query_selector('div.css-13cymwt-control')
            if not state_dropdown:
                return None
            
            await state_dropdown.click()
            await asyncio.sleep(2)
            
            # Find menu
            menu = await self.page.query_selector('div[role="listbox"]:visible')
            if not menu:
                await self.page.keyboard.press('Escape')
                return None
            
            # Find the option matching the state name
            options = await menu.query_selector_all('div[role="option"]')
            for option in options:
                text = await option.inner_text()
                if text.strip() == state_name:
                    # Get the data-value attribute
                    data_value = await option.get_attribute('data-value')
                    if data_value:
                        await self.page.keyboard.press('Escape')
                        return data_value
                    
                    # Click the option to select it, then read the hidden input
                    await option.click()
                    await asyncio.sleep(1)
                    
                    # Read the hidden input value
                    hidden_input = await self.page.query_selector('input[name="stateCd"]')
                    if hidden_input:
                        value = await hidden_input.get_attribute('value')
                        await self.page.keyboard.press('Escape')
                        return value
            
            await self.page.keyboard.press('Escape')
            return None
        except Exception as e:
            self.logger.debug(f"Error getting state code: {e}")
            return None
    
    async def get_assemblies(self, state: str) -> List[str]:
        """Get assembly names for a given state using React Select."""
        try:
            # Get state code first (e.g., S06 for Gujarat)
            state_code = await self._get_state_code(state)
            if not state_code:
                self.logger.warning(f"Could not get state code for {state}, trying direct selection")
                # Fallback to direct selection
                state_code = None
            
            # Method 1: Set hidden input directly if we have the code
            if state_code:
                try:
                    # Use JavaScript to set the value and trigger React Select update
                    await self.page.evaluate(f'''
                        () => {{
                            const hiddenInput = document.querySelector('input[name="stateCd"]');
                            if (hiddenInput) {{
                                hiddenInput.value = '{state_code}';
                                hiddenInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                hiddenInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            }}
                            // Also try to trigger React Select directly
                            const reactSelect = document.querySelector('div.css-13cymwt-control');
                            if (reactSelect) {{
                                reactSelect.click();
                            }}
                        }}
                    ''')
                    await asyncio.sleep(2)  # Wait for assembly dropdown to load
                    self.logger.debug(f"Set state code {state_code} for {state}")
                except Exception as e:
                    self.logger.debug(f"Error setting hidden input: {e}")
                    state_code = None
            
            # Method 2: If setting hidden input didn't work, try selecting via dropdown
            if not state_code:
                state_dropdown = await self.page.query_selector('div.css-13cymwt-control')
                if not state_dropdown:
                    self.logger.error(f"Could not find state dropdown to select {state}")
                    return []
                
                await state_dropdown.click()
                await asyncio.sleep(2)
                
                menu = await self.page.query_selector('div[role="listbox"]:visible')
                if menu:
                    options = await menu.query_selector_all('div[role="option"]')
                    found = False
                    for option in options:
                        text = await option.inner_text()
                        if text.strip() == state:
                            try:
                                await option.click()
                                found = True
                                await asyncio.sleep(2)
                                break
                            except:
                                try:
                                    await option.evaluate('el => el.click()')
                                    found = True
                                    await asyncio.sleep(2)
                                    break
                                except:
                                    continue
                    
                    if not found:
                        self.logger.warning(f"Could not find state option: {state}")
                        await self.page.keyboard.press('Escape')
                        return []
                else:
                    self.logger.error("Could not find state dropdown menu")
                    await self.page.keyboard.press('Escape')
                    return []
            
            # Now find the assembly dropdown (should be the second React Select)
            assembly_dropdowns = await self.page.query_selector_all('div.css-13cymwt-control')
            if len(assembly_dropdowns) < 2:
                self.logger.warning(f"Could not find assembly dropdown for {state}")
                return []
            
            # The second React Select should be the assembly dropdown
            assembly_dropdown = assembly_dropdowns[1]
            
            # Click to open assembly dropdown
            await assembly_dropdown.click()
            await asyncio.sleep(1)
            
            # Get assembly options
            menu = await self.page.query_selector('div[role="listbox"], div[class*="menu"]')
            if not menu:
                self.logger.warning(f"Could not find assembly dropdown menu for {state}")
                return []
            
            options = await menu.query_selector_all('div[role="option"]')
            assemblies = []
            for option in options:
                text = await option.inner_text()
                if text and text.strip():
                    text_clean = text.strip()
                    # Skip placeholder options
                    if text_clean.lower() not in ['select assembly', 'select', 'choose assembly', '--select--', '']:
                        assemblies.append(text_clean)
            
            # Close dropdown
            await self.page.keyboard.press('Escape')
            await asyncio.sleep(0.5)
            
            return assemblies
        
        except Exception as e:
            self.logger.error(f"Error getting assemblies for {state}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return []
    
    async def get_download_urls_direct(self, state: str, url: str) -> List[Dict[str, str]]:
        """Get all download URLs from a direct state URL (bypassing React Select)."""
        try:
            self.logger.info(f"Navigating to direct URL for {state}: {url}")
            await self.page.goto(url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(3)  # Wait for page to load
            
            # Find all download links (ZIP files, PDFs, etc.)
            # Try multiple selectors for different link types
            link_selectors = [
                'a[href*=".zip"]',
                'a[href*=".ZIP"]',
                'a[href*=".pdf"]',
                'a[href*=".PDF"]',
                'a[href*="download"]',
                'a[href*="Download"]',
            ]
            
            all_links = []
            for selector in link_selectors:
                links = await self.page.query_selector_all(selector)
                for link in links:
                    href = await link.get_attribute('href')
                    if not href:
                        continue
                    
                    # Make absolute URL if relative
                    if href.startswith('/'):
                        # Relative to domain
                        from urllib.parse import urlparse
                        parsed = urlparse(url)
                        href = f"{parsed.scheme}://{parsed.netloc}{href}"
                    elif not href.startswith('http'):
                        # Relative to current path
                        from urllib.parse import urljoin
                        href = urljoin(url, href)
                    
                    # Extract assembly name from adjacent table cell
                    assembly_name = "Unknown"
                    try:
                        # Find the parent table row
                        row = await link.evaluate_handle('el => el.closest("tr")')
                        if row:
                            # Get all cells in the row
                            cells = await row.as_element().query_selector_all('td')
                            
                            # Find which cell contains the link
                            link_cell_index = -1
                            for i, cell in enumerate(cells):
                                cell_links = await cell.query_selector_all('a')
                                for cell_link in cell_links:
                                    cell_href = await cell_link.get_attribute('href')
                                    if cell_href == href or (href.endswith(cell_href) if cell_href else False):
                                        link_cell_index = i
                                        break
                                if link_cell_index >= 0:
                                    break
                            
                            # Get assembly name from adjacent cell (usually the first or second cell)
                            # Try different positions: first cell, second cell, or cell before link
                            for cell_index in [0, 1, link_cell_index - 1]:
                                if 0 <= cell_index < len(cells):
                                    cell_text = await cells[cell_index].inner_text()
                                    cell_text = cell_text.strip()
                                    # Skip if it's the link text or empty/download text
                                    if (cell_text and 
                                        len(cell_text) > 2 and 
                                        cell_text.lower() not in ['download', 'click here', '', 'link'] and
                                        not cell_text.endswith('.zip') and
                                        not cell_text.endswith('.pdf')):
                                        assembly_name = cell_text
                                        break
                    except Exception as e:
                        self.logger.debug(f"Error extracting assembly name: {e}")
                        # Fallback: try to get from link text
                        text = await link.inner_text()
                        if text and text.strip() and text.strip().lower() not in ['download', 'click here']:
                            assembly_name = text.strip()
                    
                    all_links.append({
                        "state": state,
                        "assembly": assembly_name,
                        "url": href,
                        "filename": href.split('/')[-1] if '/' in href else href
                    })
            
            # Remove duplicates
            seen = set()
            unique_links = []
            for link in all_links:
                url_key = link['url']
                if url_key not in seen:
                    seen.add(url_key)
                    unique_links.append(link)
            
            self.logger.info(f"Found {len(unique_links)} download URLs for {state}")
            return unique_links
        
        except Exception as e:
            self.logger.error(f"Error getting download URLs from direct URL for {state}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return []
    
    async def get_download_urls(self, state: str, assembly: str) -> List[Dict[str, str]]:
        """Get all ZIP download URLs for a state-assembly combination using React Select."""
        try:
            # Navigate to the page
            await self.page.goto(self.SIR_URL, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(3)
            
            # Select state from React Select
            state_dropdowns = await self.page.query_selector_all('div.css-13cymwt-control')
            if not state_dropdowns:
                self.logger.error("Could not find state dropdown")
                return []
            
            state_dropdown = state_dropdowns[0]
            await state_dropdown.click()
            await asyncio.sleep(2)  # Wait for dropdown menu to appear
            
            # Find and click state option - wait for menu to appear
            menu = None
            for attempt in range(5):
                menu = await self.page.query_selector('div[role="listbox"]:visible')
                if menu and await menu.is_visible():
                    break
                await asyncio.sleep(0.5)
            
            if menu:
                options = await menu.query_selector_all('div[role="option"]')
                found = False
                
                # Try clicking first
                for option in options:
                    try:
                        text = await option.inner_text()
                        if text.strip() == state:
                            await option.scroll_into_view_if_needed()
                            await asyncio.sleep(0.3)
                            
                            try:
                                await option.click()
                                found = True
                                await asyncio.sleep(2)  # Wait for assembly dropdown to load
                                break
                            except:
                                try:
                                    await option.evaluate('el => el.click()')
                                    found = True
                                    await asyncio.sleep(2)
                                    break
                                except Exception as e:
                                    self.logger.debug(f"Error clicking state option: {e}")
                                    continue
                    except Exception as e:
                        self.logger.debug(f"Error processing state option: {e}")
                        continue
                
                # Fallback to keyboard navigation
                if not found:
                    self.logger.debug("Trying keyboard navigation for state selection")
                    try:
                        # Find the input field in the React Select
                        input_field = await self.page.query_selector('input[id*="react-select"], input[role="combobox"]')
                        if input_field:
                            await input_field.click()
                            await asyncio.sleep(0.3)
                            await input_field.fill('')
                            await asyncio.sleep(0.2)
                            await input_field.type(state, delay=30)
                            await asyncio.sleep(1)
                            await self.page.keyboard.press('Enter')
                            await asyncio.sleep(2)
                            found = True
                        else:
                            await self.page.keyboard.type(state, delay=30)
                            await asyncio.sleep(1)
                            await self.page.keyboard.press('Enter')
                            await asyncio.sleep(2)
                            found = True
                    except Exception as e:
                        self.logger.debug(f"Keyboard navigation failed: {e}")
                
                if not found:
                    self.logger.error(f"Could not find state option: {state}")
                    await self.page.keyboard.press('Escape')
                    return []
            else:
                self.logger.error("Could not find state dropdown menu")
                await self.page.keyboard.press('Escape')
                return []
            
            # Select assembly from React Select (second dropdown)
            assembly_dropdowns = await self.page.query_selector_all('div.css-13cymwt-control')
            if len(assembly_dropdowns) < 2:
                self.logger.error("Could not find assembly dropdown")
                return []
            
            assembly_dropdown = assembly_dropdowns[1]
            await assembly_dropdown.click()
            await asyncio.sleep(2)  # Wait for dropdown menu to appear
            
            # Find and click assembly option - wait for menu to appear
            menu = None
            for attempt in range(5):
                menu = await self.page.query_selector('div[role="listbox"]:visible')
                if menu and await menu.is_visible():
                    break
                await asyncio.sleep(0.5)
            
            if menu:
                options = await menu.query_selector_all('div[role="option"]')
                found = False
                
                # Try clicking first
                for option in options:
                    try:
                        text = await option.inner_text()
                        if text.strip() == assembly:
                            await option.scroll_into_view_if_needed()
                            await asyncio.sleep(0.3)
                            try:
                                await option.click()
                                found = True
                                await asyncio.sleep(2)
                                break
                            except:
                                try:
                                    await option.evaluate('el => el.click()')
                                    found = True
                                    await asyncio.sleep(2)
                                    break
                                except Exception as e:
                                    self.logger.debug(f"Error clicking assembly option: {e}")
                                    continue
                    except Exception as e:
                        self.logger.debug(f"Error processing assembly option: {e}")
                        continue
                
                # Fallback to keyboard navigation
                if not found:
                    self.logger.debug("Trying keyboard navigation for assembly selection")
                    try:
                        input_field = await self.page.query_selector('input[id*="react-select"], input[role="combobox"]')
                        if input_field:
                            await input_field.click()
                            await asyncio.sleep(0.3)
                            await input_field.fill('')
                            await asyncio.sleep(0.2)
                            await input_field.type(assembly, delay=30)
                            await asyncio.sleep(1)
                            await self.page.keyboard.press('Enter')
                            await asyncio.sleep(2)
                            found = True
                        else:
                            await self.page.keyboard.type(assembly, delay=30)
                            await asyncio.sleep(1)
                            await self.page.keyboard.press('Enter')
                            await asyncio.sleep(2)
                            found = True
                    except Exception as e:
                        self.logger.debug(f"Keyboard navigation failed: {e}")
                
                if not found:
                    self.logger.error(f"Could not find assembly option: {assembly}")
                    await self.page.keyboard.press('Escape')
                    return []
            else:
                self.logger.error("Could not find assembly dropdown menu")
                await self.page.keyboard.press('Escape')
                return []
            
            # Click submit/search button
            submit_button = await self.page.query_selector(
                'button[type="submit"], input[type="submit"], button:has-text("Search"), button:has-text("Download"), button:has-text("Submit")'
            )
            if submit_button:
                await submit_button.click()
                await asyncio.sleep(5)  # Wait for results to load
            else:
                # Try pressing Enter or finding any button
                await self.page.keyboard.press('Enter')
                await asyncio.sleep(5)
            
            # Find all download links (ZIP files)
            links = await self.page.query_selector_all('a[href*=".zip"], a[href*=".ZIP"]')
            urls = []
            
            for link in links:
                href = await link.get_attribute('href')
                text = await link.inner_text()
                if href:
                    # Make absolute URL if relative
                    if href.startswith('/'):
                        href = f"https://voters.eci.gov.in{href}"
                    elif not href.startswith('http'):
                        href = f"{self.SIR_URL.rsplit('/', 1)[0]}/{href}"
                    
                    urls.append({
                        "state": state,
                        "assembly": assembly,
                        "url": href,
                        "filename": text.strip() if text else href.split('/')[-1]
                    })
            
            self.logger.info(f"Found {len(urls)} download URLs for {state}/{assembly}")
            return urls
        
        except Exception as e:
            self.logger.error(f"Error getting download URLs for {state}/{assembly}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return []
    
    async def crawl_all(self, state_filter: Optional[str] = None, max_assemblies: Optional[int] = None, use_checkpoint: bool = False) -> Iterator[Dict[str, str]]:
        """
        Crawl all states and assemblies, yielding download URL metadata.
        Supports checkpointing and resume (only if use_checkpoint=True).
        Uses direct URLs when available, otherwise falls back to React Select.
        """
        checkpoint = {}
        processed_states = set()
        
        if use_checkpoint:
            checkpoint = load_checkpoint(self.checkpoint_path)
            processed_states = set(checkpoint.get('processed_states', []))
        
        await self.initialize()
        
        try:
            # Check if we have a direct URL for the filtered state
            if state_filter and state_filter in self.STATE_DIRECT_URLS:
                direct_url = self.STATE_DIRECT_URLS[state_filter]
                self.logger.info(f"Using direct URL for {state_filter}")
                
                if use_checkpoint and state_filter in processed_states:
                    self.logger.info(f"Skipping already processed state: {state_filter}")
                    return
                
                # Get all URLs from direct page
                urls = await self.get_download_urls_direct(state_filter, direct_url)
                
                for url_data in urls:
                    yield url_data
                
                # Mark state as processed (only if checkpointing enabled)
                if use_checkpoint:
                    processed_states.add(state_filter)
                    checkpoint['processed_states'] = list(processed_states)
                    save_checkpoint(self.checkpoint_path, checkpoint)
                return
            
            # Otherwise, use the React Select approach
            states = await self.get_states()
            
            if state_filter:
                states = [s for s in states if state_filter.lower() in s.lower()]
            
            for state in states:
                if use_checkpoint and state in processed_states:
                    self.logger.info(f"Skipping already processed state: {state}")
                    continue
                
                self.logger.info(f"Processing state: {state}")
                assemblies = await self.get_assemblies(state)
                
                if max_assemblies:
                    assemblies = assemblies[:max_assemblies]
                
                processed_assemblies = checkpoint.get('processed_assemblies', {}).get(state, []) if use_checkpoint else []
                
                for assembly in assemblies:
                    if use_checkpoint and assembly in processed_assemblies:
                        self.logger.info(f"Skipping already processed assembly: {state}/{assembly}")
                        continue
                    
                    urls = await self.get_download_urls(state, assembly)
                    
                    for url_data in urls:
                        yield url_data
                    
                    # Update checkpoint (only if checkpointing enabled)
                    if use_checkpoint:
                        if state not in checkpoint.get('processed_assemblies', {}):
                            checkpoint['processed_assemblies'][state] = []
                        checkpoint['processed_assemblies'][state].append(assembly)
                        save_checkpoint(self.checkpoint_path, checkpoint)
                
                # Mark state as processed (only if checkpointing enabled)
                if use_checkpoint:
                    processed_states.add(state)
                    checkpoint['processed_states'] = list(processed_states)
                    save_checkpoint(self.checkpoint_path, checkpoint)
        
        finally:
            await self.close()

