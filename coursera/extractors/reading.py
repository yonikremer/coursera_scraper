"""
Extractor for reading content from Coursera.
"""
import re
from pathlib import Path
from typing import Tuple, List, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from ..files import download_file, get_or_move_path
from ..utils import sanitize_filename
from .common import AssetManager
from .base import BaseExtractor


class ReadingExtractor(BaseExtractor):
    """Extractor for Coursera reading items."""

    def __init__(self, driver, session, asset_manager: AssetManager):
        super().__init__(driver)
        self.session = session
        self.asset_manager = asset_manager

    def process(self, context: dict) -> Tuple[bool, int, List[Tuple[Path, str]]]:
        """Process and save reading content and attachments."""
        self._navigate_and_handle_barriers()
        selectors = ["div[class*='rc-CML']", "div.content", "article", "main"]
        self._wait_for_content(selectors)
        self._cleanup_page_elements()

        content, sel_used = self._extract_content(selectors)
        new_dl, url_map = self._download_attachments(
            context["course_dir"],
            context["module_dir"],
            context["item_counter"],
            context["downloaded_files"],
        )

        if not content or not sel_used:
            return False, new_dl, []

        processed = self._localize_reading_assets(context["module_dir"], url_map)
        h_name = f"{context['item_counter']:03d}_{context['title']}.html"
        h_file = get_or_move_path(context["course_dir"], context["module_dir"], h_name)

        options = {
            "css": self.asset_manager.download_course_css(
                item_dir=context["module_dir"]
            ),
            "meta": "<span><strong>Type:</strong> Reading</span>",
            "extra_style": ".content-wrapper { margin-top: 20px; } hr { border: 0; border-top: 1px solid #d0d7de; margin: 30px 0; }",
        }
        html = self.wrap_html(context["title"], processed, options)

        with open(h_file, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"  ✓ Reading content saved: {h_file.name}")
        return True, new_dl, [(h_file, "reading")]

    def _navigate_and_handle_barriers(self):
        """Handle initial page state and popups."""
        self.close_continue_learning_popup()
        self.handle_barriers()

    def _wait_for_content(self, selectors: List[str]):
        """Wait for reading content to appear."""
        try:
            WebDriverWait(self.driver, 20).until(
                lambda d: any(d.find_elements(By.CSS_SELECTOR, s) for s in selectors)
            )
        except (WebDriverException, TimeoutException):
            pass

    def _cleanup_page_elements(self):
        """Remove messy UI elements."""
        removals = [
            ".rc-ItemAdminTools",
            ".rc-ItemFeedback",
            ".rc-ItemNavigation",
            "button",
            ".rc-CertificateLink",
        ]
        for selector in removals:
            try:
                self.driver.execute_script(
                    f"document.querySelectorAll('{selector}').forEach(e => e.remove());"
                )
            except WebDriverException:
                pass

    def _extract_content(
        self, selectors: List[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Extract HTML content from the page."""
        for selector in selectors:
            try:
                elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                if elem.is_displayed():
                    return elem.get_attribute("innerHTML"), selector
            except NoSuchElementException:
                continue
        return None, None

    def _download_attachments(
        self, course_dir: Path, module_dir: Path, counter: int, downloaded: set
    ) -> Tuple[int, dict]:
        """Find and download reading attachments."""
        url_to_local = {}
        downloaded_count = 0
        try:
            links = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='asset']")
            for link in links:
                try:
                    href = link.get_attribute("href")
                    if not href or href in downloaded:
                        continue

                    name = sanitize_filename(link.text.strip() or Path(href).stem)
                    filename = f"{counter:03d}_{name}{Path(href).suffix}"
                    filepath = get_or_move_path(course_dir, module_dir, filename)

                    if not filepath.exists():
                        if download_file(href, filepath, self.session):
                            downloaded_count += 1
                            downloaded.add(href)

                    url_to_local[href] = filepath.name
                except (StaleElementReferenceException, WebDriverException):
                    continue
        except WebDriverException:
            pass
        return downloaded_count, url_to_local

    def _localize_reading_assets(self, item_dir: Path, url_map: dict) -> str:
        """Localize images and internal attachment links."""
        try:
            # First localize images using AssetManager
            container = self.driver.find_element(By.TAG_NAME, "body")
            self.asset_manager.localize_images(container, item_dir)

            # Then get the HTML and replace attachment links
            html = container.get_attribute("innerHTML") or ""
            for href, local_name in url_map.items():
                html = html.replace(href, local_name)

            # Clean up Coursera internal links
            html = re.sub(r'href="/learn/.*?/reading/.*?"', 'href="#"', html)
            return html
        except (NoSuchElementException, WebDriverException):
            return ""
