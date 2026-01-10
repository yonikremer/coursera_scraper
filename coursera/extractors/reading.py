from pathlib import Path
from typing import Set, Tuple
import requests
import urllib.parse
import os
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, WebDriverException
from ..files import get_or_move_path, download_file
from ..utils import sanitize_filename
from .common import AssetManager

class ReadingExtractor:
    def __init__(self, driver, session: requests.Session, asset_manager: AssetManager):
        self.driver = driver
        self.session = session
        self.asset_manager = asset_manager

    def process(self, course_dir: Path, module_dir: Path, item_counter: int,
                             title: str, downloaded_files: Set[str]) -> Tuple[bool, int]:
        """Process and save reading content and attachments."""
        downloaded_count = 0
        downloaded_something = False

        try:
            # Get the reading content.
            content = None
            selector_used = None
            
            for selector in ["div[class*='rc-CML']", "div[class*='content']", "div[role='main']",
                           "article", "main"]:
                try:
                    # Remove messy elements before extraction.
                    self.driver.execute_script("""
                        const messySelectors = [
                            '[data-ai-instructions="true"]',
                            '[data-testid="like-button"]',
                            '[data-testid="dislike-button"]',
                            '[aria-label="Text Formatting"]'
                        ];
                        messySelectors.forEach(selector => {
                            document.querySelectorAll(selector).forEach(el => el.remove());
                        });
                    """)
                    
                    elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    inner_html = elem.get_attribute('innerHTML')
                    if inner_html and len(inner_html) > 100:
                        content = inner_html
                        selector_used = selector
                        break
                except (NoSuchElementException, StaleElementReferenceException):
                    continue

            # Download the attachments.
            downloaded_count += self._download_attachments(course_dir, module_dir, item_counter, downloaded_files)

            # Process the assets if content was found.
            if content and selector_used:
                # 1. Download the CSS (shared for the course).
                css_links_html = self.asset_manager.download_course_css()

                # 2. Download the images within the content.
                # Re-find the element to ensure it's not stale after the CSS download.
                try:
                    content_elem = self.driver.find_element(By.CSS_SELECTOR, selector_used)
                    downloaded_count += self.asset_manager.localize_images(content_elem)
                except (NoSuchElementException, StaleElementReferenceException) as e:
                    print(f"  ⚠ Error localizing images: {e}")
                
                # Get the updated content with local image paths.
                try:
                    # Re-find again just to be safe.
                    content_elem = self.driver.find_element(By.CSS_SELECTOR, selector_used)
                    content = content_elem.get_attribute('innerHTML')
                except (NoSuchElementException, StaleElementReferenceException) as e:
                    print(f"  ⚠ Error getting final content: {e}")
                    # Fallback to the original content if the update fails.
                    pass

                # 3. Save the HTML content.
                # Update attachment links to point to local files
                soup = BeautifulSoup(content, 'html.parser')
                attachment_files = [f for f in module_dir.iterdir() if f.is_file() and "_attachment_" in f.name]
                
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href']
                    if not href or not href.startswith(('http://', 'https://')):
                        continue
                        
                    matched_file = None
                    
                    # Check data-name on <a> tag or children
                    data_name = a_tag.get('data-name')
                    if not data_name:
                        child_with_data = a_tag.find(attrs={"data-name": True})
                        if child_with_data:
                            data_name = child_with_data.get('data-name')
                            
                    if data_name:
                        clean_name = sanitize_filename(data_name)
                        for lf in attachment_files:
                            if f"_attachment_{clean_name}" in lf.name:
                                matched_file = lf
                                break
                    
                    # Fallback: Check filename in URL
                    if not matched_file:
                        try:
                            parsed_url = urllib.parse.urlparse(href)
                            url_filename = os.path.basename(parsed_url.path)
                            if url_filename:
                                url_filename = urllib.parse.unquote(url_filename)
                                clean_url_name = sanitize_filename(url_filename)
                                for lf in attachment_files:
                                    if clean_url_name in lf.name:
                                        matched_file = lf
                                        break
                                    if Path(clean_url_name).stem in lf.stem and lf.suffix == Path(clean_url_name).suffix:
                                        matched_file = lf
                                        break
                        except Exception:
                            pass
                            
                    if matched_file:
                        a_tag['href'] = matched_file.name
                        a_tag['target'] = "_self"
                        if 'rel' in a_tag.attrs: del a_tag.attrs['rel']

                content = str(soup)

                filename = f"{item_counter:03d}_{title}.html"
                html_file = get_or_move_path(course_dir, module_dir, filename)
                try:
                    with open(html_file, 'w', encoding='utf-8') as f:
                        f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
{css_links_html}
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 30px; line-height: 1.6; background: #fff; color: #1f1f1f; }}
        img {{ max-width: 100%; height: auto; display: block; margin: 25px auto; border-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        code {{ background: #f5f5f5; padding: 2px 5px; border-radius: 3px; font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; font-size: 85%; }}
        pre {{ background: #f5f5f5; padding: 16px; border-radius: 6px; overflow-x: auto; line-height: 1.45; margin-bottom: 20px; }}
        h1 {{ font-size: 32px; border-bottom: 1px solid #e1e4e8; padding-bottom: 0.3em; margin-bottom: 16px; }}
        .content-wrapper {{ margin-top: 20px; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <div class="content-wrapper">
        {content}
    </div>
</body>
</html>""")
                except OSError as e:
                    print(f"  ⚠ Error writing reading HTML: {e}")

                downloaded_count += 1
                downloaded_something = True
                print(f"  ✓ Reading saved as HTML with assets")

        except WebDriverException as e:
            print(f"  ⚠ Browser error processing reading item: {e}")

        return downloaded_something, downloaded_count

    def _download_attachments(self, course_dir: Path, module_dir: Path, item_counter: int,
                             downloaded_files: Set[str]) -> int:
        """Download attachments from reading items."""
        downloaded_count = 0

        try:
            # Expanded selectors for better coverage of the attachments.
            selectors = [
                "//a[@data-e2e='asset-download-link']",
                "//div[contains(@class, 'cml-asset')]//a[contains(@href, 'cloudfront.net')]",
                "//div[contains(@class, 'cml-asset')]//a[contains(@href, 'coursera-university-assets')]",
                "//a[contains(@href, 'api.coursera.org/api/asset/v1/')]",
                "//a[contains(@class, 'download-link')]",
                "//div[contains(@class, 'resource')]//a"
            ]
            attachment_links = self.driver.find_elements(By.XPATH, " | ".join(selectors))

            for attach_link in attachment_links:
                try:
                    attach_url = attach_link.get_attribute('href')
                    if not attach_url or attach_url in downloaded_files or not attach_url.startswith('http'):
                        continue

                    downloaded_files.add(attach_url)

                    # Get the filename from the data-name attribute or link text.
                    attach_name = None
                    try:
                        asset_elem = attach_link.find_element(By.XPATH, ".//div[@data-name]")
                        attach_name = asset_elem.get_attribute('data-name')
                    except (NoSuchElementException, StaleElementReferenceException):
                        pass

                    if not attach_name:
                        try:
                            name_elem = attach_link.find_element(By.XPATH, ".//div[@data-e2e='asset-name']")
                            attach_name = name_elem.text.strip()
                        except (NoSuchElementException, StaleElementReferenceException):
                            pass

                    if not attach_name:
                        attach_name = attach_url.split('/')[-1].split('?')[0]

                    # Get the file extension.
                    extension = None
                    try:
                        asset_elem = attach_link.find_element(By.XPATH, ".//div[@data-extension]")
                        extension = asset_elem.get_attribute('data-extension')
                    except (NoSuchElementException, StaleElementReferenceException):
                        if '.' in attach_url.split('/')[-1].split('?')[0]:
                            extension = attach_url.split('/')[-1].split('?')[0].split('.')[-1]

                    attach_name = sanitize_filename(attach_name)
                    if extension and not attach_name.endswith(f'.{extension}'):
                        attach_name = f"{attach_name}.{extension}"

                    filename = f"{item_counter:03d}_attachment_{attach_name}"
                    attach_file = get_or_move_path(course_dir, module_dir, filename)

                    if not attach_file.exists():
                        print(f"  ⬇ Downloading attachment: {attach_name}")
                        if download_file(attach_url, attach_file, self.session):
                            downloaded_count += 1
                            print(f"  ✓ Attachment saved: {attach_name}")

                except (StaleElementReferenceException, WebDriverException) as e:
                    print(f"  ⚠ Error downloading attachment: {e}")
                    continue

        except (NoSuchElementException, WebDriverException) as e:
            print(f"  ⚠ Error processing attachments: {e}")

        return downloaded_count
