from pathlib import Path
from typing import Set, Tuple
import requests
import urllib.parse
import os
import time
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)
from ..files import get_or_move_path, download_file
from ..utils import sanitize_filename
from .common import AssetManager


class ReadingExtractor:
    def __init__(self, driver, session: requests.Session, asset_manager: AssetManager):
        self.driver = driver
        self.session = session
        self.asset_manager = asset_manager

    def _handle_barriers(self):
        """Handle 'Continue' or 'Agree' buttons that might appear before content."""
        # Handle "Continue Learning" specifically by closing it if possible
        try:
            cont_learning = self.driver.find_elements(
                By.XPATH,
                "//button[contains(., 'Continue Learning')] | //a[contains(., 'Continue Learning')]",
            )
            if cont_learning and any(b.is_displayed() for b in cont_learning):
                close_selectors = [
                    "//button[@aria-label='Close']",
                    "//button[@aria-label='close']",
                    "//button[contains(@class, 'close')]",
                    "//button[contains(@class, 'Close')]",
                ]
                closed = False
                for sel in close_selectors:
                    close_btns = self.driver.find_elements(By.XPATH, sel)
                    for c_btn in close_btns:
                        if c_btn.is_displayed():
                            self.driver.execute_script("arguments[0].click();", c_btn)
                            print("  ✓ Closed 'Continue Learning' popup")
                            time.sleep(2)
                            closed = True
                            break
                    if closed:
                        break
        except Exception:
            pass

        barriers = ["Continue", "I agree", "Agree", "Accept", "Confirm", "I understand"]
        for round in range(2):
            clicked = False
            for b_text in barriers:
                try:
                    xpath = f"//button[contains(., '{b_text}')] | //a[contains(., '{b_text}')] | //span[text()='{b_text}']/ancestor::button"
                    btns = self.driver.find_elements(By.XPATH, xpath)
                    for btn in btns:
                        if btn.is_displayed() and btn.is_enabled():
                            if "rc-InCourseSearchBar" in btn.get_attribute("outerHTML"):
                                continue
                            btn_label = btn.text.strip() or b_text
                            self.driver.execute_script(
                                "arguments[0].scrollIntoView({block: 'center'});", btn
                            )
                            time.sleep(1)
                            self.driver.execute_script("arguments[0].click();", btn)
                            print(f"  ✓ Clicked reading barrier: '{btn_label}'")
                            time.sleep(3)
                            clicked = True
                            break
                    if clicked:
                        break
                except Exception:
                    continue
            if not clicked:
                break

    def process(
        self,
        course_dir: Path,
        module_dir: Path,
        item_counter: int,
        title: str,
        downloaded_files: Set[str],
    ) -> Tuple[bool, int]:
        """Process and save reading content and attachments."""
        downloaded_count = 0
        downloaded_something = False

        # Handle barriers (Honor Code etc) before waiting for content
        url_before_barriers = self.driver.current_url
        self._handle_barriers()

        if "/home/" in self.driver.current_url or "/home?" in self.driver.current_url:
            print(f"  ℹ Redirected to home, returning to: {url_before_barriers}")
            self.driver.get(url_before_barriers)
            time.sleep(2)
        elif (
            self.driver.current_url != url_before_barriers
            and "/learn/" in self.driver.current_url
        ):
            print(f"  ℹ URL changed to: {self.driver.current_url}")

        # Wait for reading content to load
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.common.exceptions import TimeoutException

        print(f"  Waiting for reading content...")
        reading_selectors = ["div[class*='rc-CML']", "div.content", "article", "main"]
        WebDriverWait(self.driver, 20).until(
            lambda d: any(
                d.find_elements(By.CSS_SELECTOR, sel) for sel in reading_selectors
            )
        )
        time.sleep(2)

        # Get the reading content.
        content = None
        selector_used = None

        # Remove messy elements before extraction.
        self.driver.execute_script("""
            const messySelectors = [
                '[data-ai-instructions="true"]',
                '[data-testid="content-integrity-instructions"]',
                '[data-test="rc-InCourseSearchBar"]',
                '[data-testid="visually-hidden"]',
                '[data-testid="like-button"]',
                '[data-testid="dislike-button"]',
                '[aria-label="Text Formatting"]',
                '.rc-A11yScreenReaderOnly'
            ];
            messySelectors.forEach(selector => {
                document.querySelectorAll(selector).forEach(el => {
                    if (selector === '[data-test="rc-InCourseSearchBar"]') {
                        el.closest('form')?.remove() || el.remove();
                    } else {
                        el.remove();
                    }
                });
            });
        """)

        for selector in reading_selectors + ["div[role='main']"]:
            try:
                elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                inner_html = elem.get_attribute("innerHTML")
                if inner_html and len(inner_html) > 100:
                    content = inner_html
                    selector_used = selector
                    break
            except (NoSuchElementException, StaleElementReferenceException):
                continue

        # Download the attachments.
        new_downloads, url_to_local = self._download_attachments(
            course_dir, module_dir, item_counter, downloaded_files
        )
        downloaded_count += new_downloads

        # Process the assets if content was found.
        if content and selector_used:
            # 1. Download the CSS (shared for the course).
            css_links_html = self.asset_manager.download_course_css(item_dir=module_dir)

            # 2. Download the images within the content.
            # Re-find the element to ensure it's not stale after the CSS download.
            try:
                content_elem = self.driver.find_element(By.CSS_SELECTOR, selector_used)
                downloaded_count += self.asset_manager.localize_images(
                    content_elem, item_dir=module_dir
                )
            except (NoSuchElementException, StaleElementReferenceException) as e:
                print(f"  ⚠ Error localizing images: {e}")

            # Get the updated content with local image paths.
            try:
                # Re-find again just to be safe.
                content_elem = self.driver.find_element(By.CSS_SELECTOR, selector_used)
                content = content_elem.get_attribute("innerHTML")
            except (NoSuchElementException, StaleElementReferenceException) as e:
                print(f"  ⚠ Error getting final content: {e}")
                # Fallback to the original content if the update fails.
                pass

            # 3. Save the HTML content.
            # Update attachment links to point to local files
            soup = BeautifulSoup(content, "html.parser")
            attachment_files = [
                f
                for f in module_dir.iterdir()
                if f.is_file() and "_attachment_" in f.name
            ]

            # Helper to find local file for a URL or name
            def find_local_match(href, data_name=None):
                # Priority 1: Direct map from download session
                matched = url_to_local.get(href)
                if matched:
                    return matched

                # Priority 2: Use data-name and existing files
                if data_name:
                    clean_name = sanitize_filename(data_name)
                    for lf in attachment_files:
                        if f"_attachment_{clean_name}" in lf.name:
                            return lf.name

                # Priority 3: Check URL parts
                try:
                    parsed_url = urllib.parse.urlparse(href)
                    url_filename = os.path.basename(parsed_url.path)
                    if url_filename:
                        url_filename = urllib.parse.unquote(url_filename)
                        clean_url_name = sanitize_filename(url_filename)
                        for lf in attachment_files:
                            if clean_url_name in lf.name or (
                                Path(clean_url_name).stem in lf.stem
                                and lf.suffix == Path(clean_url_name).suffix
                            ):
                                return lf.name
                except Exception:
                    pass
                return None

            # Process standard <a> tags
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if not href or not href.startswith(("http://", "https://")):
                    continue

                data_name = a_tag.get("data-name")
                if not data_name:
                    child_with_data = a_tag.find(attrs={"data-name": True})
                    if child_with_data:
                        data_name = child_with_data.get("data-name")

                matched_file_name = find_local_match(href, data_name)

                # Last resort: download if it looks like a Coursera asset
                if not matched_file_name:
                    is_asset = any(
                        pattern in href
                        for pattern in [
                            "api.coursera.org/api/asset/v1/",
                            "cloudfront.net",
                            "coursera-university-assets",
                        ]
                    )
                    if is_asset:
                        try:
                            url_filename = os.path.basename(
                                urllib.parse.urlparse(href).path
                            )
                            if url_filename:
                                clean_url_name = sanitize_filename(
                                    urllib.parse.unquote(url_filename)
                                )
                                filename = (
                                    f"{item_counter:03d}_attachment_{clean_url_name}"
                                )
                                attach_file = get_or_move_path(
                                    course_dir, module_dir, filename
                                )
                                if not attach_file.exists():
                                    print(
                                        f"  ⬇ Downloading asset link: {clean_url_name}"
                                    )
                                    if download_file(href, attach_file, self.session):
                                        matched_file_name = attach_file.name
                                        downloaded_count += 1
                                        downloaded_files.add(href)
                                else:
                                    matched_file_name = attach_file.name
                        except Exception:
                            pass

                if matched_file_name:
                    a_tag["href"] = matched_file_name
                    a_tag["target"] = "_self"
                    if "rel" in a_tag.attrs:
                        del a_tag.attrs["rel"]

            # Process <div> assets (CML assets)
            for asset_div in soup.find_all("div", attrs={"data-url": True}):
                href = asset_div["data-url"]
                data_name = asset_div.get("data-name")

                matched_file_name = find_local_match(href, data_name)

                if matched_file_name:
                    # Wrap the asset div in a link to make it clickable
                    new_a = soup.new_tag("a", href=matched_file_name, target="_self")
                    new_a["style"] = (
                        "text-decoration: none; color: inherit; cursor: pointer; display: block;"
                    )
                    asset_div.wrap(new_a)
                    # Also update data-url to local just in case
                    asset_div["data-url"] = matched_file_name

            content = str(soup)

            # Format title: replace underscores with spaces and title case
            display_title = title.replace("_", " ").title()

            filename = f"{item_counter:03d}_{title}.html"
            html_file = get_or_move_path(course_dir, module_dir, filename)
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{display_title}</title>
{css_links_html}
    <style>
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; 
            max-width: 900px; 
            margin: 0 auto; 
            padding: 40px 20px; 
            line-height: 1.6; 
            color: #333; 
            background: #f5f7f9; 
        }}
        .container {{
            background: #fff;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        }}
        h1 {{ font-size: 2.2rem; color: #0056d2; margin-bottom: 10px; border-bottom: 2px solid #e1e4e8; padding-bottom: 10px; }}
        .meta {{ color: #666; font-size: 0.9rem; margin-bottom: 30px; }}
        img {{ max-width: 100%; height: auto; display: block; margin: 25px auto; border-radius: 8px; }}
        code {{ background: #f0f2f5; padding: 3px 6px; border-radius: 4px; font-family: monospace; font-size: 0.9rem; }}
        pre {{ background: #1e1e1e; color: #d4d4d4; padding: 20px; border-radius: 8px; overflow-x: auto; margin: 20px 0; }}
        .content-wrapper {{ margin-top: 20px; }}
        hr {{ border: 0; border-top: 1px solid #d0d7de; margin: 30px 0; }}
        a {{ color: #0056d2; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        
        /* Prevent accidental selection on titles */
        h1 {{ 
            user-select: none;
            -webkit-user-select: none;
        }}
        .meta {{
            user-select: none;
            -webkit-user-select: none;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{display_title}</h1>
        <div class="meta">
            <span><strong>Type:</strong> Reading</span>
        </div>
        <div class="content-wrapper">
            {content}
        </div>
    </div>
</body>
</html>""")

            downloaded_count += 1
            downloaded_something = True
            print(f"  Reading saved as HTML with assets")

        return downloaded_something, downloaded_count

    def _download_attachments(
        self,
        course_dir: Path,
        module_dir: Path,
        item_counter: int,
        downloaded_files: Set[str],
    ) -> Tuple[int, dict]:
        """Download attachments from reading items and return count and url->filename map."""
        downloaded_count = 0
        url_to_local = {}

        try:
            # Expanded selectors for better coverage of the attachments.
            selectors = [
                "//a[@data-e2e='asset-download-link']",
                "//div[contains(@class, 'cml-asset')]//a[contains(@href, 'cloudfront.net')]",
                "//div[contains(@class, 'cml-asset')]//a[contains(@href, 'coursera-university-assets')]",
                "//a[contains(@href, 'api.coursera.org/api/asset/v1/')]",
                "//a[contains(@class, 'download-link')]",
                "//div[contains(@class, 'resource')]//a",
                "//div[@data-url and contains(@class, 'cml-asset')]",
            ]
            attachment_links = self.driver.find_elements(
                By.XPATH, " | ".join(selectors)
            )

            for attach_link in attachment_links:
                try:
                    # Try href first (for <a>), then data-url (for <div>)
                    attach_url = attach_link.get_attribute(
                        "href"
                    ) or attach_link.get_attribute("data-url")

                    if not attach_url or not attach_url.startswith("http"):
                        continue

                    # Get the filename from the data-name attribute or link text.
                    attach_name = attach_link.get_attribute("data-name")
                    try:
                        asset_elem = attach_link.find_element(
                            By.XPATH, ".//div[@data-name]"
                        )
                        attach_name = asset_elem.get_attribute("data-name")
                    except (NoSuchElementException, StaleElementReferenceException):
                        pass

                    if not attach_name:
                        try:
                            name_elem = attach_link.find_element(
                                By.XPATH, ".//div[@data-e2e='asset-name']"
                            )
                            attach_name = name_elem.text.strip()
                        except (NoSuchElementException, StaleElementReferenceException):
                            pass

                    if not attach_name:
                        attach_name = attach_url.split("/")[-1].split("?")[0]

                    # Get the file extension.
                    extension = None
                    try:
                        asset_elem = attach_link.find_element(
                            By.XPATH, ".//div[@data-extension]"
                        )
                        extension = asset_elem.get_attribute("data-extension")
                    except (NoSuchElementException, StaleElementReferenceException):
                        if "." in attach_url.split("/")[-1].split("?")[0]:
                            extension = (
                                attach_url.split("/")[-1].split("?")[0].split(".")[-1]
                            )

                    attach_name = sanitize_filename(attach_name)
                    if extension and not attach_name.endswith(f".{extension}"):
                        attach_name = f"{attach_name}.{extension}"

                    filename = f"{item_counter:03d}_attachment_{attach_name}"
                    attach_file = get_or_move_path(course_dir, module_dir, filename)

                    if not attach_file.exists():
                        if attach_url in downloaded_files:
                            # Skip if already downloaded but file missing (shouldn't happen with get_or_move_path usually)
                            continue

                        print(f"  Downloading attachment: {attach_name}")
                        if download_file(attach_url, attach_file, self.session):
                            downloaded_count += 1
                            downloaded_files.add(attach_url)
                            print(f"  Attachment saved: {attach_name}")

                    if attach_file.exists():
                        url_to_local[attach_url] = attach_file.name

                except (StaleElementReferenceException, WebDriverException) as e:
                    print(f"  Error downloading attachment: {e}")
                    continue

        except (NoSuchElementException, WebDriverException) as e:
            print(f"  Error processing attachments: {e}")

        return downloaded_count, url_to_local
