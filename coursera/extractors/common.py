import json
import hashlib
from pathlib import Path
from typing import Set, Tuple
import requests
from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException, NoSuchElementException
from ..files import download_file, get_or_move_path
from ..utils import sanitize_filename

class AssetManager:
    """Manages shared assets like CSS and Images across the course."""
    
    def __init__(self, shared_assets_dir: Path, session: requests.Session, driver):
        self.shared_assets_dir = shared_assets_dir
        self.session = session
        self.driver = driver
        
        self.shared_assets_dir.mkdir(exist_ok=True, parents=True)
        (self.shared_assets_dir / "css").mkdir(exist_ok=True)
        (self.shared_assets_dir / "images").mkdir(exist_ok=True)
        
        self.image_cache_file = self.shared_assets_dir / "image_cache.json"
        self.image_url_to_path = {}
        self.load_image_cache()

    def load_image_cache(self):
        """Load the image URL to path cache from a file."""
        try:
            if self.image_cache_file.exists():
                with open(self.image_cache_file, 'r', encoding='utf-8') as f:
                    self.image_url_to_path = json.load(f)
                print(f"✓ Loaded {len(self.image_url_to_path)} image cache entries.")
        except (IOError, json.JSONDecodeError) as e:
            print(f"⚠ Could not load image cache, starting fresh: {e}")
            self.image_url_to_path = {}

    def save_image_cache(self):
        """Save the image URL to path cache to a file."""
        try:
            with open(self.image_cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.image_url_to_path, f, indent=4)
        except IOError as e:
            print(f"⚠ Could not save image cache: {e}")

    def download_course_css(self) -> str:
        """Download all CSS files for the course and return HTML link tags."""
        css_links_html = ""
        css_dir = self.shared_assets_dir / "css"
        
        # 1. Capture external stylesheets.
        try:
            css_elements = self.driver.find_elements(By.XPATH, "//link[@rel='stylesheet']")
            for idx, link in enumerate(css_elements):
                try:
                    href = link.get_attribute('href')
                    if not href or not href.startswith('http'): continue
                    
                    url_filename = href.split('/')[-1].split('?')[0]
                    base_name = Path(url_filename).stem
                    if not base_name or len(base_name) < 2:
                        base_name = "style"
                    
                    # Truncate base_name to prevent excessively long filenames.
                    MAX_BASENAME_LEN = 60
                    if len(base_name) > MAX_BASENAME_LEN:
                        base_name = base_name[:MAX_BASENAME_LEN]
                    
                    # Include a hash to avoid collisions while keeping the name descriptive.
                    css_hash = hashlib.md5(href.encode()).hexdigest()[:8]
                    css_filename = f"{sanitize_filename(base_name)}_{css_hash}.css"
                    
                    css_path = css_dir / css_filename
                    if download_file(href, css_path, self.session):
                        # Path is relative to files in module_N/ directory (two levels up to coursera_downloads).
                        css_links_html += f'    <link rel="stylesheet" href="../../shared_assets/css/{css_filename}">\n'
                except (StaleElementReferenceException, WebDriverException):
                    continue
        except WebDriverException as e:
            print(f"  ⚠ Browser error finding stylesheets: {e}")

        # 2. Capture inline styles.
        try:
            style_elements = self.driver.find_elements(By.TAG_NAME, "style")
            inline_count = 0
            for idx, style in enumerate(style_elements):
                try:
                    css_text = style.get_attribute('innerHTML')
                    if not css_text or len(css_text.strip()) < 20: continue
                    
                    # Hash the content to avoid duplicates across pages.
                    content_hash = hashlib.md5(css_text.encode('utf-8', errors='ignore')).hexdigest()
                    css_filename = f"inline_{content_hash[:12]}.css"
                    css_path = css_dir / css_filename
                    
                    if not css_path.exists():
                        with open(css_path, 'w', encoding='utf-8') as f:
                            f.write(css_text)
                    
                    css_links_html += f'    <link rel="stylesheet" href="../../shared_assets/css/{css_filename}">\n'
                    inline_count += 1
                except (StaleElementReferenceException, WebDriverException):
                    continue
            if inline_count > 0:
                print(f"  ✓ Captured {inline_count} inline style(s)")
        except WebDriverException as e:
            print(f"  ⚠ Browser error finding inline styles: {e}")
            
        return css_links_html

    def localize_images(self, content_elem) -> int:
        """Download images in content_elem and update their src to global shared paths."""
        downloaded_count = 0
        try:
            images = content_elem.find_elements(By.TAG_NAME, "img")
            if images:
                global_images_dir = self.shared_assets_dir / "images"
                
                for img in images:
                    try:
                        src = img.get_attribute('src')
                        if not src or src.startswith('data:'): continue
                        
                        if src in self.image_url_to_path:
                            local_src = self.image_url_to_path[src]
                            self.driver.execute_script("arguments[0].setAttribute('src', arguments[1])", img, local_src)
                            continue

                        # Determine extension.
                        ext = src.split('?')[0].split('.')[-1] if '.' in src.split('?')[0] else "png"
                        if len(ext) > 4 or not ext.isalnum(): ext = "png"

                        # Extract filename from URL for better readability.
                        url_filename = src.split('/')[-1].split('?')[0]
                        base_name = Path(url_filename).stem
                        if not base_name or len(base_name) < 2:
                            base_name = "image"
                        
                        # Truncate base_name to prevent excessively long filenames.
                        # This balances descriptiveness with OS filename length limits.
                        MAX_BASENAME_LEN = 60
                        if len(base_name) > MAX_BASENAME_LEN:
                            base_name = base_name[:MAX_BASENAME_LEN]
                        
                        # Fetch the image to get its hash for deduplication.
                        try:
                            response = self.session.get(src, timeout=20)
                            response.raise_for_status()
                            img_content = response.content
                        except requests.RequestException as e:
                            print(f"  ⚠ Failed to fetch image {src}: {e}")
                            continue

                        # Hash image content for deduplication.
                        content_hash = hashlib.md5(img_content).hexdigest()
                        # Include both base name and hash to ensure uniqueness while remaining descriptive.
                        img_name = f"{sanitize_filename(base_name)}_{content_hash[:8]}.{ext}"
                        img_path = global_images_dir / img_name
                        
                        # Save if it doesn't exist.
                        if not img_path.exists():
                            with open(img_path, 'wb') as f:
                                f.write(img_content)
                            downloaded_count += 1
                        
                        # Update the DOM to point to global shared assets.
                        local_src = f"../../shared_assets/images/{img_name}"
                        self.image_url_to_path[src] = local_src
                        self.driver.execute_script("arguments[0].setAttribute('src', arguments[1])", img, local_src)
                    except (StaleElementReferenceException, WebDriverException):
                        continue
        except (StaleElementReferenceException, WebDriverException):
            pass
        return downloaded_count

def extract_pdfs(driver, course_dir: Path, module_dir: Path, item_counter: int,
                          downloaded_files: Set[str], session: requests.Session) -> Tuple[bool, int]:
    """Process and download PDF items."""
    downloaded_count = 0
    downloaded_something = False

    try:
        pdf_links = driver.find_elements(By.XPATH,
            "//main//a[contains(@href, '.pdf')] | //div[@role='main']//a[contains(@href, '.pdf')] | " +
            "//article//a[contains(@href, '.pdf')]")

        main_pdf_links = []
        for link in pdf_links:
            try:
                try:
                    link.find_element(By.XPATH, "./ancestor::footer")
                    continue
                except NoSuchElementException:
                    main_pdf_links.append(link)
            except StaleElementReferenceException:
                continue

        if main_pdf_links:
            print(f"  Found {len(main_pdf_links)} PDF link(s) in the main content")

        for link in main_pdf_links:
            try:
                href = link.get_attribute('href')
                if href and href not in downloaded_files:
                    downloaded_files.add(href)
                    link_text = link.text.strip() or "document"
                    base_filename = sanitize_filename(link_text)
                    if not base_filename.endswith('.pdf'):
                        base_filename += '.pdf'

                    filename = f"{item_counter:03d}_{base_filename}"
                    pdf_file = get_or_move_path(course_dir, module_dir, filename)

                    if not pdf_file.exists():
                        print(f"  ⬇ Downloading PDF: {base_filename}")
                        if download_file(href, pdf_file, session):
                            downloaded_count += 1
                            downloaded_something = True
                            print(f"  ✓ PDF saved: {base_filename}")
            except StaleElementReferenceException:
                continue

    except (NoSuchElementException, WebDriverException) as e:
        print(f"  ⚠ Browser error while processing PDFs: {e}")

    return downloaded_something, downloaded_count