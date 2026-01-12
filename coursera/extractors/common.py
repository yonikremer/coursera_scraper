"""
Shared utilities for extractors, including asset management and PDF extraction.
"""
import re
import hashlib
import urllib.parse
from pathlib import Path
from typing import Tuple, Dict, Optional

import requests
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    StaleElementReferenceException,
    WebDriverException,
)
from ..files import download_file, get_or_move_path
from ..utils import sanitize_filename


class AssetManager:
    """Manages downloading and localizing CSS and images."""

    def __init__(self, shared_assets_dir: Path, session: requests.Session, driver):
        self.shared_assets_dir = shared_assets_dir
        self.session = session
        self.driver = driver
        self.course_css_dir = self.shared_assets_dir / "css"
        self.course_images_dir = self.shared_assets_dir / "images"
        self.course_css_dir.mkdir(parents=True, exist_ok=True)
        self.course_images_dir.mkdir(parents=True, exist_ok=True)
        # Cache for image URL to local filename
        self.image_url_to_path: Dict[str, str] = {}

    def download_course_css(self, item_dir: Path) -> str:
        """Download all stylesheets and return HTML link tags."""
        css_links = []
        try:
            stylesheets = self.driver.find_elements(By.TAG_NAME, "link")
            for link in stylesheets:
                try:
                    rel = link.get_attribute("rel")
                    href = link.get_attribute("href")
                    if rel == "stylesheet" and href:
                        # Clean URL
                        clean_url = href.split("?")[0]
                        h = hashlib.md5(clean_url.encode()).hexdigest()[:8]
                        css_name = f"style_{h}.css"
                        css_path = self.course_css_dir / css_name

                        if not css_path.exists():
                            download_file(href, css_path, self.session)

                        # Calculate relative path
                        depth = len(item_dir.parts) - len(
                            self.shared_assets_dir.parent.parts
                        )
                        dots = "../" * depth
                        rel_path = f"{dots}shared_assets/css/{css_name}"
                        css_links.append(f'<link rel="stylesheet" href="{rel_path}">')
                except (StaleElementReferenceException, WebDriverException):
                    continue
        except WebDriverException:
            pass

        return "\n".join(css_links)

    def localize_images(self, container_element, item_dir: Path) -> int:
        """Download and localize images within a container element."""
        downloaded_count = 0
        try:
            images = container_element.find_elements(By.TAG_NAME, "img")
            for img in images:
                try:
                    src = img.get_attribute("src")
                    if not src or src.startswith("data:"):
                        continue

                    local_path = self._download_and_cache_image(src)
                    if local_path:
                        depth = len(item_dir.parts) - len(
                            self.shared_assets_dir.parent.parts
                        )
                        dots = "../" * depth
                        rel_path = f"{dots}shared_assets/images/{local_path.name}"
                        self.driver.execute_script(
                            "arguments[0].setAttribute('src', arguments[1]);",
                            img,
                            rel_path,
                        )
                        downloaded_count += 1
                except (StaleElementReferenceException, WebDriverException):
                    continue
        except WebDriverException:
            pass
        return downloaded_count

    def _download_and_cache_image(self, url: str) -> Optional[Path]:
        """Download to shared images dir and cache the result."""
        if url in self.image_url_to_path:
            return self.course_images_dir / self.image_url_to_path[url]

        try:
            h = hashlib.md5(url.encode()).hexdigest()[:10]
            ext = Path(url.split("?")[0]).suffix or ".png"
            if len(ext) > 5:
                ext = ".png"

            filename = f"img_{h}{ext}"
            filepath = self.course_images_dir / filename

            if not filepath.exists():
                if not download_file(url, filepath, self.session):
                    return None

            self.image_url_to_path[url] = filename
            return filepath
        except (OSError, ValueError):
            return None

    def save_image_cache(self):
        """No-op for compatibility."""


def localize_css_assets(
    css_content: str, css_url: str, session: requests.Session, assets_dir: Path
) -> str:
    """Download fonts/images from CSS and update references."""

    def replacer(match):
        url = match.group(1).split("?")[0].split("#")[0]
        if url.startswith("data:"):
            return match.group(0)

        full_url = urllib.parse.urljoin(css_url, url)
        h = hashlib.md5(full_url.encode()).hexdigest()[:8]
        ext = Path(url).suffix
        name = f"asset_{h}{ext}"
        path = assets_dir / name

        if not path.exists():
            download_file(full_url, path, session)
        return f"url('{name}')"

    return re.sub(r"url\(['\"]?(.*?)['\"]?\)", replacer, css_content)


def extract_pdfs(context: dict) -> Tuple[bool, int]:
    """Find and download all PDF links in the current page."""
    driver = context["driver"]
    course_dir = context["course_dir"]
    module_dir = context["module_dir"]
    item_counter = context["item_counter"]
    downloaded_files = context["downloaded_files"]
    session = context["session"]

    pdf_count = 0
    try:
        links = driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf')]")
        for link in links:
            try:
                href = link.get_attribute("href")
                if not href or href in downloaded_files:
                    continue

                name = sanitize_filename(link.text.strip() or Path(href).stem)
                filename = f"{item_counter:03d}_{name}.pdf"
                filepath = get_or_move_path(course_dir, module_dir, filename)

                if not filepath.exists():
                    print(f"  ⬇ Downloading PDF: {name}.pdf")
                    if download_file(href, filepath, session):
                        pdf_count += 1
                        downloaded_files.add(href)
            except (StaleElementReferenceException, WebDriverException):
                continue
    except WebDriverException:
        pass

    return pdf_count > 0, pdf_count
