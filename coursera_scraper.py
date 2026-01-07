#!/usr/bin/env python3
"""
Coursera Material Downloader
Downloads all course materials from enrolled Coursera courses/professional certificates.
"""
import re
import time
import argparse
import warnings
import pickle
import zipfile
import shutil
import hashlib
import json
from pathlib import Path
from typing import Set, Tuple

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import yt_dlp


class CourseraDownloader:
    """Download materials from Coursera courses."""

    def __init__(self, email: str, download_dir: str = "coursera_downloads", headless: bool = False):
        self.email = email
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        
        # Global shared assets for all courses
        self.shared_assets_dir = self.download_dir / "shared_assets"
        self.shared_assets_dir.mkdir(exist_ok=True)
        (self.shared_assets_dir / "css").mkdir(exist_ok=True)
        (self.shared_assets_dir / "images").mkdir(exist_ok=True)

        self.session = requests.Session()
        self.image_cache_file = self.shared_assets_dir / "image_cache.json"
        self.image_url_to_path = {}  # Cache to avoid re-downloading same URL in one session
        self._load_image_cache()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Encoding": "gzip, deflate, br"
        })
        self.driver = None
        self.headless = headless
        self.cookies_file = self.download_dir / "coursera_cookies.pkl"

    def _load_image_cache(self):
        """Load the image URL to path cache from a file."""
        try:
            if self.image_cache_file.exists():
                with open(self.image_cache_file, 'r', encoding='utf-8') as f:
                    self.image_url_to_path = json.load(f)
                print(f"✓ Loaded {len(self.image_url_to_path)} image cache entries.")
        except (IOError, json.JSONDecodeError) as e:
            print(f"⚠ Could not load image cache, starting fresh: {e}")
            self.image_url_to_path = {}

    def _save_image_cache(self):
        """Save the image URL to path cache to a file."""
        try:
            with open(self.image_cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.image_url_to_path, f, indent=4)
            print(f"✓ Saved {len(self.image_url_to_path)} image cache entries.")
        except IOError as e:
            print(f"⚠ Could not save image cache: {e}")

    def setup_driver(self):
        """Initialize Selenium WebDriver with Chrome."""
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        prefs = {
            "download.default_directory": str(self.download_dir.absolute()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True
        }
        chrome_options.add_experimental_option("prefs", prefs)

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    def login_with_google(self):
        """Login to Coursera using a Google account."""
        print(f"Logging in with Google account: {self.email}")
        print("\nOpening Coursera login page...")
        print("Please complete the ENTIRE login process manually in the browser window.")
        print("This includes:")
        print("  1. Click 'Continue with Google' (or 'Log In' then 'Continue with Google')")
        print("  2. Select your Google account or enter credentials")
        print("  3. Complete any 2FA if required")
        print("  4. Wait until you're on the main Coursera page")
        print("\nWaiting for you to complete login (up to 180 seconds)...\n")

        self.driver.get("https://www.coursera.org/?authMode=login")
        time.sleep(3)

        try:
            WebDriverWait(self.driver, 180).until(
                lambda driver: (
                    "coursera.org" in driver.current_url and
                    "authMode=login" not in driver.current_url and
                    "authMode=signup" not in driver.current_url
                ) or self._check_logged_in()
            )

            time.sleep(3)
            print("✓ Login successful!")

            # Save cookies for future sessions
            self._save_cookies()

            for cookie in self.driver.get_cookies():
                self.session.cookies.set(cookie['name'], cookie['value'])

        except TimeoutException:
            print("\n⚠ Login timeout. Please try again and complete the login process.")
            print("If you're having trouble, make sure you:")
            print("  - Click through the entire Google login flow")
            print("  - Wait until you see the main Coursera homepage")
            raise

    def _check_logged_in(self) -> bool:
        """Check if a user is logged in by looking for commonly authenticated elements."""
        try:
            self.driver.find_element(By.XPATH, "//button[contains(@aria-label, 'Profile')]")
            return True
        except NoSuchElementException:
            pass

        try:
            self.driver.find_element(By.XPATH, "//a[contains(@href, '/my-courses')]")
            return True
        except NoSuchElementException:
            pass

        return False

    def _save_cookies(self):
        """Save browser cookies to a file for persistent login."""
        try:
            cookies = self.driver.get_cookies()
            with open(self.cookies_file, 'wb') as f:
                pickle.dump(cookies, f)
            print(f"✓ Cookies saved to {self.cookies_file}")
        except Exception as e:
            print(f"⚠ Error saving cookies: {e}")

    def _load_cookies(self) -> bool:
        """Load cookies from file and add them to the browser session."""
        if not self.cookies_file.exists():
            print("ℹ No saved cookies found")
            return False

        try:
            with open(self.cookies_file, 'rb') as f:
                cookies = pickle.load(f)

            # Navigate to Coursera first (required to set cookies for the domain)
            self.driver.get("https://www.coursera.org")
            time.sleep(2)

            # Add each cookie to the browser
            for cookie in cookies:
                try:
                    # Remove domain if it starts with a dot (compatibility fix)
                    if 'domain' in cookie and cookie['domain'].startswith('.'):
                        cookie['domain'] = cookie['domain'][1:]
                    self.driver.add_cookie(cookie)
                except Exception as e:
                    # Skip cookies that can't be added
                    pass

            print("✓ Cookies loaded successfully")
            return True
        except Exception as e:
            print(f"⚠ Error loading cookies: {e}")
            return False

    def _verify_login(self) -> bool:
        """Verify if the current session is logged in."""
        try:
            # Navigate to a protected page to check login status
            self.driver.get("https://www.coursera.org/my-learning")
            time.sleep(3)

            # Check if we're still on the my-learning page (logged in)
            if "my-learning" in self.driver.current_url or self._check_logged_in():
                print("✓ Already logged in")
                return True
            else:
                print("ℹ Not logged in (redirected or login elements not found)")
                return False
        except Exception as e:
            print(f"⚠ Error verifying login: {e}")
            return False

    def login_with_persistence(self):
        """
        Attempt to login using saved cookies, fall back to manual login if needed.
        This allows users to stay logged in between script runs.
        """
        print(f"Attempting to login for: {self.email}")

        # Try to load saved cookies first
        if self._load_cookies():
            # Sync cookies to requests session
            for cookie in self.driver.get_cookies():
                self.session.cookies.set(cookie['name'], cookie['value'])

            # Verify the login is still valid
            if self._verify_login():
                # Login successful with saved cookies
                return
            else:
                print("\nℹ Saved cookies are expired or invalid")
                print("  Proceeding with manual login...\n")

        # No saved cookies or they expired - do manual login
        self.login_with_google()

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Remove invalid characters from filename, convert to lowercase with underscores."""
        # Replace invalid characters and punctuation with underscores
        sanitized = re.sub(r'[<>:"/\\|?*,!]', '_', filename)
        # Handle ellipsis and multiple dots (replace with single underscore)
        sanitized = re.sub(r'\.{2,}', '_', sanitized)
        # Replace spaces and hyphens with underscores
        sanitized = sanitized.replace(' ', '_').replace('-', '_')
        # Convert to lowercase
        sanitized = sanitized.lower()
        # Remove multiple consecutive underscores
        sanitized = re.sub(r'_+', '_', sanitized)
        # Strip leading/trailing underscores
        sanitized = sanitized.strip('_')
        return sanitized or "untitled"

    @staticmethod
    def _extract_slug(item_url: str) -> str:
        """Extract a meaningful slug from Coursera URL."""
        if not item_url:
            return ""
        # Remove query parameters
        url = item_url.split('?')[0]
        # Split by /
        parts = [p for p in url.split('/') if p]
        if not parts:
            return ""
        
        # If it ends in /attempt, /submission, /view, etc., skip that part
        if parts[-1].lower() in ['attempt', 'submission', 'view', 'instructions', 'gradedLab', 'ungradedLab']:
            slug = parts[-2] if len(parts) >= 2 else parts[-1]
        else:
            slug = parts[-1]
            
        return CourseraDownloader.sanitize_filename(slug)

    @staticmethod
    def _get_or_move_path(course_dir: Path, module_dir: Path, target_name: str) -> Path:
        """
        Check if a file or directory exists in the course directory (from old runs), 
        move it to the module directory.
        Also handles fixing numbering prefixes and moving between modules.
        """
        target_path = module_dir / target_name
        
        # Ensure module directory exists
        module_dir.mkdir(exist_ok=True)

        # 1. If an item already exists in the module directory with the exact name, return it
        if target_path.exists():
            return target_path

        # 2. Search for the item in all possible locations
        # Locations: course root, current module, and all other module directories
        search_dirs = [course_dir, module_dir]
        if course_dir.exists():
            search_dirs.extend([d for d in course_dir.glob("module_*") if d.is_dir()])
        
        # Unique resolved paths
        unique_search_dirs = []
        seen_resolved = set()
        for sd in search_dirs:
            if sd.exists():
                res = sd.resolve()
                if res not in seen_resolved:
                    unique_search_dirs.append(sd)
                    seen_resolved.add(res)

        # 2.1. Check for exact name match in other directories
        for sd in unique_search_dirs:
            if sd.resolve() == module_dir.resolve(): continue
            source_path = sd / target_name
            if source_path.exists():
                print(f"  📦 Moving existing item to module directory: {target_name} (from {sd.name})")
                try:
                    shutil.move(str(source_path), str(target_path))
                    return target_path
                except Exception as e:
                    print(f"  ⚠ Error moving item: {e}")

        # 3. Fix numbering: check if item exists with a different number prefix
        # target_name is expected to be like "035_title.ext" or "035_title_assets"
        if len(target_name) > 4 and target_name[3] == '_':
            suffix = target_name[4:]
            for sd in unique_search_dirs:
                # Look for items with any 3-digit prefix and the same suffix
                for existing in sd.glob(f"[0-9][0-9][0-9]_{suffix}"):
                    if existing.exists() and existing.resolve() != target_path.resolve():
                        print(f"  🔄 Correcting item number/location: {existing.name} (in {sd.name}) → {target_name}")
                        try:
                            shutil.move(str(existing), str(target_path))
                            return target_path
                        except Exception as e:
                            print(f"  ⚠ Error correcting item number for {existing.name}: {e}")

        return target_path

    @staticmethod
    def _find_items(course_dir: Path, module_dir: Path, item_counter: int,
                    item_type: str, item_url: str = None) -> list[Path]:
        """
        Check if an item's materials already exist across any module or course directory.
        Relies on slug-based matching to handle re-ordering accurately and avoid prefix hijacking.
        """
        prefix = f"{item_counter:03d}_"
        all_found = []
        
        # Get all directories to search (all modules + course root)
        search_dirs = [module_dir, course_dir]
        if course_dir.exists():
            search_dirs.extend([d for d in course_dir.glob("module_*") if d.is_dir()])
        
        # Resolve to unique paths
        unique_search_dirs = []
        seen_resolved = set()
        for sd in search_dirs:
            if sd.exists():
                res = sd.resolve()
                if res not in seen_resolved:
                    unique_search_dirs.append(sd)
                    seen_resolved.add(res)

        # 1. Primary Search: Match by slug (best for identifying moved items)
        if item_url:
            slug = CourseraDownloader._extract_slug(item_url)
            if slug:
                for directory in unique_search_dirs:
                    # Match any 3-digit prefix followed by our slug
                    slug_matches = list(directory.glob(f"[0-9][0-9][0-9]_{slug}*"))
                    all_found.extend(slug_matches)

        # Remove duplicates and resolve to actual paths
        unique_found = []
        seen_paths = set()
        for p in all_found:
            resolved_p = str(p.resolve())
            if resolved_p not in seen_paths:
                unique_found.append(p)
                seen_paths.add(resolved_p)

        return unique_found

    def download_file(self, url: str, filepath: Path) -> bool:
        """Download a file from URL."""
        try:
            if filepath.exists() and filepath.stat().st_size > 0:
                print(f"  ℹ File already exists, skipping: {filepath.name}")
                return True

            response = self.session.get(url, stream=True, timeout=30)
            response.raise_for_status()

            filepath.parent.mkdir(parents=True, exist_ok=True)

            # For small files (not videos), we can just use response.content to ensure proper decompression
            if filepath.suffix.lower() not in ['.mp4', '.zip']:
                with open(filepath, 'wb') as f:
                    f.write(response.content)
            else:
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

            return True
        except Exception as e:
            print(f"  ⚠ Error downloading {url}: {e}")
            return False

    def download_video(self, video_url: str, filepath: Path) -> bool:
        """Download video using yt-dlp."""
        try:
            cookies_dict = {}
            for cookie in self.driver.get_cookies():
                cookies_dict[cookie['name']] = cookie['value']

            cookies_file = self.download_dir / "cookies.txt"
            with open(cookies_file, 'w') as f:
                f.write("# Netscape HTTP Cookie File\n")
                for name, value in cookies_dict.items():
                    f.write(f".coursera.org\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")

            ydl_opts = {
                'outtmpl': str(filepath),
                'cookiefile': str(cookies_file),
                'format': 'best[height<=720]',
                'quiet': True,
                'no_warnings': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            cookies_file.unlink(missing_ok=True)
            return True

        except Exception as e:
            print(f"  ⚠ Error downloading video: {e}")
            return False

    def _wait_for_module_content(self, module_num: int):
        """Wait for module content to load."""
        print(f"  Waiting for module {module_num} content to load...")
        try:
            # Look for either the item list or a message saying no items
            WebDriverWait(self.driver, 45).until(
                lambda d: d.find_elements(By.XPATH, "//ul[@data-testid='named-item-list-list']//a") or 
                         "No items found" in d.page_source
            )
            print(f"  ✓ Module {module_num} content loaded")
            time.sleep(2)
        except TimeoutException:
            print(f"  ⚠ Timeout waiting for module {module_num} content to load")

    def _extract_module_items(self) -> list:
        """Extract all item links from the current module page."""
        link_elements = self.driver.find_elements(By.XPATH,
            "//ul[@data-testid='named-item-list-list']//a[contains(@href, '/lecture/') or " +
            "contains(@href, '/supplement/') or contains(@href, '/quiz/') or " +
            "contains(@href, '/exam/') or contains(@href, '/assignment/') or " +
            "contains(@href, '/assignment-submission/') or " +
            "contains(@href, '/programming/') or contains(@href, '/ungradedLab/') or " +
            "contains(@href, '/gradedLab/')]")

        item_links = []
        for elem in link_elements:
            href = elem.get_attribute('href')
            if href and href not in item_links:
                item_links.append(href)

        return item_links

    @staticmethod
    def _determine_item_type(item_url: str) -> str:
        """Determine the type of the course item from its URL."""
        if '/lecture/' in item_url:
            return "video"
        elif '/supplement/' in item_url:
            return "reading"
        elif '/quiz/' in item_url or '/exam/' in item_url:
            return "quiz"
        elif '/assignment/' in item_url or '/programming/' in item_url or '/assignment-submission/' in item_url:
            return "assignment"
        elif '/ungradedLab/' in item_url or '/gradedLab/' in item_url:
            return "lab"
        else:
            warnings.warn(f"Un-recognized item type: {item_url}")
            return "other"

    def _get_item_title(self, item_url: str) -> str:
        """Extract the item title from the page."""
        title = "Untitled"
        try:
            for title_selector in ["h1", "h2", "[data-test='item-title']", ".item-title"]:
                try:
                    title_elem = self.driver.find_element(By.CSS_SELECTOR, title_selector)
                    if title_elem.text.strip():
                        title = self.sanitize_filename(title_elem.text.strip())
                        break
                except:
                    continue
        except:
            title = item_url.split('/')[-1].split('?')[0]

        return title

    def _process_video_item(self, course_dir: Path, module_dir: Path, item_counter: int,
                           title: str, item_url: str) -> Tuple[bool, int]:
        """Process and download video items."""
        downloaded_count = 0
        downloaded_something = False

        try:
            video_elements = self.driver.find_elements(By.TAG_NAME, "video")
            print(f"  Found {len(video_elements)} video element(s)")

            for idx, video in enumerate(video_elements):
                sources = [
                    video.get_attribute('src'),
                    *[source.get_attribute('src') for source in video.find_elements(By.TAG_NAME, 'source')]
                ]

                sources_720p = [s for s in sources if s and '720' in s]
                if sources_720p:
                    sources = sources_720p
                else:
                    sources = [s for s in sources if s]

                for video_src in sources:
                    if video_src:
                        print(f"  Video source: {video_src[:80]}...")
                        filename = f"{item_counter:03d}_{title}_{idx}.mp4"
                        video_file = self._get_or_move_path(course_dir, module_dir, filename)

                        if not video_file.exists():
                            print(f"  ⬇ Downloading video (720p preferred)...")
                            try:
                                if self.download_file(video_src, video_file):
                                    downloaded_count += 1
                                    downloaded_something = True
                                    print(f"  ✓ Video saved: {video_file.name}")
                                else:
                                    print(f"  Trying alternative download method (720p)...")
                                    if self.download_video(item_url, video_file):
                                        downloaded_count += 1
                                        downloaded_something = True
                                        print(f"  ✓ Video saved: {video_file.name}")
                            except Exception as e:
                                print(f"  ⚠ Error downloading video: {e}")
                        else:
                            print(f"  ℹ Video already exists: {video_file.name}")
                            downloaded_something = True

            # Also check for download buttons
            download_btns = self.driver.find_elements(By.XPATH,
                "//a[contains(text(), 'Download') and (contains(@href, '.mp4') or contains(@href, 'video'))]")

            for btn in download_btns:
                href = btn.get_attribute('href')
                if href:
                    href = href.replace("full/540p", "full/720p")
                    print(f"  Found download link: {href[:80]}...")
                    filename = f"{item_counter:03d}_{title}.mp4"
                    video_file = self._get_or_move_path(course_dir, module_dir, filename)
                    if not video_file.exists():
                        if self.download_file(href, video_file):
                            downloaded_count += 1
                            downloaded_something = True
                            print(f"  ✓ Video saved: {video_file.name}")

        except Exception as e:
            print(f"  ⚠ Error processing video: {e}")

        return downloaded_something, downloaded_count

    def _process_pdf_items(self, course_dir: Path, module_dir: Path, item_counter: int,
                          downloaded_files: Set[str]) -> Tuple[bool, int]:
        """Process and download PDF items."""
        downloaded_count = 0
        downloaded_something = False

        try:
            pdf_links = self.driver.find_elements(By.XPATH,
                "//main//a[contains(@href, '.pdf')] | //div[@role='main']//a[contains(@href, '.pdf')] | " +
                "//article//a[contains(@href, '.pdf')]")

            main_pdf_links = []
            for link in pdf_links:
                try:
                    link.find_element(By.XPATH, "./ancestor::footer")
                    continue
                except:
                    main_pdf_links.append(link)

            if main_pdf_links:
                print(f"  Found {len(main_pdf_links)} PDF link(s) in main content")

            for link in main_pdf_links:
                href = link.get_attribute('href')
                if href and href not in downloaded_files:
                    downloaded_files.add(href)
                    link_text = link.text.strip() or "document"
                    base_filename = self.sanitize_filename(link_text)
                    if not base_filename.endswith('.pdf'):
                        base_filename += '.pdf'

                    filename = f"{item_counter:03d}_{base_filename}"
                    pdf_file = self._get_or_move_path(course_dir, module_dir, filename)

                    if not pdf_file.exists():
                        print(f"  ⬇ Downloading PDF: {base_filename}")
                        if self.download_file(href, pdf_file):
                            downloaded_count += 1
                            downloaded_something = True
                            print(f"  ✓ PDF saved: {base_filename}")

        except Exception as e:
            print(f"  ⚠ Error processing PDFs: {e}")

        return downloaded_something, downloaded_count

    def _process_reading_item(self, course_dir: Path, module_dir: Path, item_counter: int,
                             title: str, downloaded_files: Set[str]) -> Tuple[bool, int]:
        """Process and save reading content and attachments."""
        downloaded_count = 0
        downloaded_something = False

        try:
            # Get reading content
            content_elem = None
            content = None
            selector_used = None
            
            for selector in ["div[class*='rc-CML']", "div[class*='content']", "div[role='main']",
                           "article", "main"]:
                try:
                    elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    inner_html = elem.get_attribute('innerHTML')
                    if inner_html and len(inner_html) > 100:
                        content_elem = elem
                        content = inner_html
                        selector_used = selector
                        break
                except:
                    continue

            # Download attachments
            downloaded_count += self._download_attachments(course_dir, module_dir, item_counter, downloaded_files)

            # Process assets if content was found
            css_links_html = ""
            if content and selector_used:
                # 1. Download CSS (shared for the course)
                css_links_html = self._download_course_css()

                # 2. Download Images within content
                # Re-find the element to ensure it's not stale after CSS download
                try:
                    content_elem = self.driver.find_element(By.CSS_SELECTOR, selector_used)
                    downloaded_count += self._localize_images(content_elem)
                except Exception as e:
                    print(f"  ⚠ Error localizing images: {e}")
                
                # Get updated content with local image paths
                try:
                    # Re-find again just to be safe
                    content_elem = self.driver.find_element(By.CSS_SELECTOR, selector_used)
                    content = content_elem.get_attribute('innerHTML')
                except Exception as e:
                    print(f"  ⚠ Error getting final content: {e}")
                    # Fallback to original content if update fails
                    pass

                # 3. Save HTML content
                filename = f"{item_counter:03d}_{title}.html"
                html_file = self._get_or_move_path(course_dir, module_dir, filename)
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

                downloaded_count += 1
                downloaded_something = True
                print(f"  ✓ Reading saved as HTML with assets")

        except Exception as e:
            print(f"  ⚠ Could not save reading: {e}")

        return downloaded_something, downloaded_count

    def _download_course_css(self) -> str:
        """Download all CSS files for the course and return HTML link tags."""
        css_links_html = ""
        # Use global shared assets for deduplication across all courses
        css_dir = self.shared_assets_dir / "css"
        css_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Capture external stylesheets
        try:
            css_elements = self.driver.find_elements(By.XPATH, "//link[@rel='stylesheet']")
            for idx, link in enumerate(css_elements):
                try:
                    href = link.get_attribute('href')
                    if not href or not href.startswith('http'): continue
                    
                    css_filename = self.sanitize_filename(href.split('/')[-1].split('?')[0])
                    if not css_filename.endswith('.css'): css_filename += ".css"
                    if len(css_filename) > 100 or len(css_filename) < 5: 
                        css_filename = f"style_{hashlib.md5(href.encode()).hexdigest()[:10]}.css"
                    
                    css_path = css_dir / css_filename
                    if self.download_file(href, css_path):
                        # Path is relative to files in module_N/ directory (two levels up to coursera_downloads)
                        css_links_html += f'    <link rel="stylesheet" href="../../shared_assets/css/{css_filename}">\n'
                except:
                    continue
        except:
            pass

        # 2. Capture inline styles
        try:
            style_elements = self.driver.find_elements(By.TAG_NAME, "style")
            inline_count = 0
            for idx, style in enumerate(style_elements):
                try:
                    css_text = style.get_attribute('innerHTML')
                    if not css_text or len(css_text.strip()) < 20: continue
                    
                    # Hash the content to avoid duplicates across pages
                    content_hash = hashlib.md5(css_text.encode('utf-8', errors='ignore')).hexdigest()
                    css_filename = f"inline_{content_hash[:12]}.css"
                    css_path = css_dir / css_filename
                    
                    if not css_path.exists():
                        with open(css_path, 'w', encoding='utf-8') as f:
                            f.write(css_text)
                    
                    css_links_html += f'    <link rel="stylesheet" href="../../shared_assets/css/{css_filename}">\n'
                    inline_count += 1
                except:
                    continue
            if inline_count > 0:
                print(f"  ✓ Captured {inline_count} inline style(s)")
        except:
            pass
            
        return css_links_html

    def _localize_images(self, content_elem) -> int:
        """Download images in content_elem and update their src to global shared paths."""
        downloaded_count = 0
        try:
            images = content_elem.find_elements(By.TAG_NAME, "img")
            if images:
                # Use global shared images for deduplication across all courses
                global_images_dir = self.shared_assets_dir / "images"
                
                for img in images:
                    try:
                        src = img.get_attribute('src')
                        if not src or src.startswith('data:'): continue
                        
                        if src in self.image_url_to_path:
                            local_src = self.image_url_to_path[src]
                            self.driver.execute_script("arguments[0].setAttribute('src', arguments[1])", img, local_src)
                            continue

                        # Determine extension
                        ext = src.split('?')[0].split('.')[-1] if '.' in src.split('?')[0] else "png"
                        if len(ext) > 4 or not ext.isalnum(): ext = "png"
                        
                        # Fetch the image to get its hash for deduplication
                        try:
                            response = self.session.get(src, timeout=20)
                            response.raise_for_status()
                            img_content = response.content
                        except Exception as e:
                            print(f"  ⚠ Failed to fetch image {src}: {e}")
                            continue

                        # Hash image content
                        content_hash = hashlib.md5(img_content).hexdigest()
                        img_name = f"{content_hash}.{ext}"
                        img_path = global_images_dir / img_name
                        
                        # Save if it doesn't exist
                        if not img_path.exists():
                            with open(img_path, 'wb') as f:
                                f.write(img_content)
                            downloaded_count += 1
                        
                        # Update the DOM to point to global shared assets
                        # HTML files are usually 2 levels deep from coursera_downloads (course/module/file.html)
                        local_src = f"../../shared_assets/images/{img_name}"
                        self.image_url_to_path[src] = local_src
                        self.driver.execute_script("arguments[0].setAttribute('src', arguments[1])", img, local_src)
                    except:
                        continue
        except:
            pass
        return downloaded_count

    def _download_attachments(self, course_dir: Path, module_dir: Path, item_counter: int,
                             downloaded_files: Set[str]) -> int:
        """Download attachments from reading items."""
        downloaded_count = 0

        try:
            # Expanded selectors for better coverage of attachments
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

                    # Get filename from data-name attribute or link text
                    attach_name = None
                    try:
                        asset_elem = attach_link.find_element(By.XPATH, ".//div[@data-name]")
                        attach_name = asset_elem.get_attribute('data-name')
                    except:
                        pass

                    if not attach_name:
                        try:
                            name_elem = attach_link.find_element(By.XPATH, ".//div[@data-e2e='asset-name']")
                            attach_name = name_elem.text.strip()
                        except:
                            pass

                    if not attach_name:
                        attach_name = attach_url.split('/')[-1].split('?')[0]

                    # Get file extension
                    extension = None
                    try:
                        asset_elem = attach_link.find_element(By.XPATH, ".//div[@data-extension]")
                        extension = asset_elem.get_attribute('data-extension')
                    except:
                        if '.' in attach_url.split('/')[-1].split('?')[0]:
                            extension = attach_url.split('/')[-1].split('?')[0].split('.')[-1]

                    attach_name = self.sanitize_filename(attach_name)
                    if extension and not attach_name.endswith(f'.{extension}'):
                        attach_name = f"{attach_name}.{extension}"

                    filename = f"{item_counter:03d}_attachment_{attach_name}"
                    attach_file = self._get_or_move_path(course_dir, module_dir, filename)

                    if not attach_file.exists():
                        print(f"  ⬇ Downloading attachment: {attach_name}")
                        if self.download_file(attach_url, attach_file):
                            downloaded_count += 1
                            print(f"  ✓ Attachment saved: {attach_name}")

                except Exception as e:
                    print(f"  ⚠ Error downloading attachment: {e}")
                    continue

        except Exception as e:
            print(f"  ⚠ Error processing attachments: {e}")

        return downloaded_count

    def _click_assignment_start_button(self) -> bool:
        """Click the start/resume button for an assignment or quiz."""
        # Common Coursera button texts for starting assignments/quizzes
        button_texts = ["Start", "Start Assignment", "Resume", "Continue", "Start Quiz", "Retake Quiz", "Review", "Open", "Launch"]
        
        for btn_text in button_texts:
            try:
                # Try to find button or link with the text
                xpath = f"//button[contains(., '{btn_text}')] | //a[contains(., '{btn_text}')]"
                start_btn = self.driver.find_element(By.XPATH, xpath)
                
                if start_btn.is_displayed() and start_btn.is_enabled():
                    # Scroll into view to ensure it's clickable
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", start_btn)
                    time.sleep(1)
                    start_btn.click()
                    print(f"  ✓ Clicked '{btn_text}' button")
                    return True
            except:
                continue
        return False

    def _extract_assignment_content(self) -> Tuple[str, int]:
        """Extract the HTML content of the assignment."""
        downloaded_count = 0
        selectors = [
            "div#TUNNELVISIONWRAPPER_CONTENT_ID",
            "div.rc-FormPartsQuestion", 
            "div.rc-CMLOrHTML", 
            "div[data-testid^='part-Submission']",
            ".rc-AssignmentPart", 
            ".rc-PracticeAssignment",
            "form",
            "div[role='main']", 
            "main"
        ]
        
        # Try to remove AI instructions if present before extracting
        try:
            self.driver.execute_script("""
                const aiInstructions = document.querySelectorAll('[data-ai-instructions="true"]');
                aiInstructions.forEach(el => el.remove());
            """)
        except:
            pass
        
        for selector in selectors:
            try:
                # Find all matching elements and combine them if there are multiple (like questions)
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    content = ""
                    for elem in elements:
                        # Localize images
                        downloaded_count += self._localize_images(elem)
                            
                        html = elem.get_attribute('outerHTML')
                        if html and len(html) > 100:
                            content += html + "\n<br>\n"
                    if content:
                        return content, downloaded_count
            except:
                continue
        return "", 0

    def _save_assignment_html(self, filepath: Path, title: str, item_type: str, content: str, css_links_html: str = "", metadata: str = ""):
        """Save assignment content to an HTML file."""
        metadata_html = f"<p><strong>Info:</strong> {metadata}</p>" if metadata else ""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
{css_links_html}
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; max-width: 1000px; margin: 0 auto; padding: 30px; line-height: 1.6; color: #1f1f1f; background: #fff; }}
        img {{ max-width: 100%; height: auto; display: block; margin: 25px auto; border-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        code {{ background: #f5f5f5; padding: 2px 5px; border-radius: 3px; font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; font-size: 85%; }}
        pre {{ background: #f5f5f5; padding: 16px; border-radius: 6px; overflow-x: auto; line-height: 1.45; margin-bottom: 20px; }}
        .question {{ margin: 20px 0; padding: 20px; background: #f9f9f9; border-left: 5px solid #007bff; border-radius: 4px; }}
        hr {{ border: 0; border-top: 1px solid #eee; margin: 40px 0; }}
        h1 {{ font-size: 32px; border-bottom: 1px solid #e1e4e8; padding-bottom: 0.3em; margin-bottom: 16px; }}
        .assignment-content {{ margin-top: 20px; }}
        
        /* Quiz/Assignment layout fixes */
        .rc-FormPartsQuestion {{ margin-bottom: 30px; padding: 20px; background: #fdfdfd; border: 1px solid #eee; border-radius: 8px; }}
        .rc-Option {{ margin: 5px 0; position: relative; }}
        .rc-Option label {{ 
            display: flex !important; 
            align-items: flex-start !important; 
            cursor: pointer; 
            gap: 10px; 
            padding: 10px; 
            border-radius: 6px; 
            transition: background 0.2s; 
            position: relative; 
        }}
        .rc-Option label:hover {{ background: #f5f5f5; }}
        
        /* Hide native radio/checkbox but keep it clickable and functional */
        .rc-Option input[type="radio"], 
        .rc-Option input[type="checkbox"] {{ 
            opacity: 0;
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 5;
            cursor: pointer;
            margin: 0;
        }}

        /* Highlight selected option */
        .rc-Option:has(input:checked) label {{
            background-color: #e8f0fe;
        }}
        .rc-Option input:checked + span {{
            color: #1a73e8;
            font-weight: 600;
        }}

        /* Ensure Coursera's custom icons and text are aligned */
        ._1e7axzp, .cui-icon, ._htmk7zm + span {{ display: flex; align-items: center; justify-content: center; flex-shrink: 0; }}
        .rc-Option label span {{ line-height: 1.5; }}
        #TUNNELVISIONWRAPPER_CONTENT_ID {{ padding: 0 !important; margin: 0 !important; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <p><strong>Type:</strong> {item_type.title()}</p>
    {metadata_html}
    <p><strong>URL:</strong> {self.driver.current_url}</p>
    <hr>
    <div class="assignment-content">
        {content}
    </div>
</body>
</html>""")

    def _click_save_draft_button(self):
        """Try to click 'Save draft' button if it exists."""
        try:
            save_btn = self.driver.find_element(By.XPATH,
                "//button[contains(., 'Save draft') or contains(., 'Save Draft')]")
            if save_btn.is_displayed() and save_btn.is_enabled():
                save_btn.click()
                print(f"  ✓ Clicked 'Save draft'")
                time.sleep(2)
        except:
            pass

    def _process_assignment_or_quiz(self, course_dir: Path, module_dir: Path, item_counter: int,
                                    title: str, item_type: str) -> Tuple[bool, int]:
        """Process and save assignment or quiz content."""
        downloaded_count = 0
        downloaded_something = False

        try:
            print(f"  Processing {item_type}...")

            # If it's an assignment-submission or not yet on attempt page, try to click start
            # Special case for 'assignment-submission' as requested: it often has a start button 
            # that doesn't change the URL.
            is_attempt_page = '/attempt' in self.driver.current_url or '/assignment-submission' in self.driver.current_url
            
            # Try clicking start button if we're not on a known attempt page, 
            # or if we are on a submission page that might need a click to show the actual assignment.
            if not is_attempt_page or '/assignment-submission' in self.driver.current_url:
                if self._click_assignment_start_button():
                    time.sleep(4)
                elif not is_attempt_page:
                    print(f"  ℹ Already on assignment page or no start button found")

            # Wait for content to load
            print(f"  Waiting for {item_type} content...")
            try:
                WebDriverWait(self.driver, 30).until(
                    lambda d: '/attempt' in d.current_url or 
                             d.find_elements(By.CSS_SELECTOR, "div#TUNNELVISIONWRAPPER_CONTENT_ID, div.rc-FormPartsQuestion, form, div.rc-CMLOrHTML, .rc-AssignmentPart, .rc-PracticeAssignment, div[data-testid^='part-Submission'], [data-testid='header-right']")
                )
                time.sleep(2)
            except TimeoutException:
                print(f"  ⚠ Timeout waiting for {item_type} content, but proceeding anyway...")
            except Exception as e:
                print(f"  ⚠ Error while waiting: {e}")

            print(f"  Current URL: {self.driver.current_url}")

            # Extract additional metadata (like due date, weight, etc.)
            metadata = ""
            try:
                # Look for header info in modern view
                header_info = self.driver.find_elements(By.CSS_SELECTOR, "[data-testid='header-right'], .rc-AssignmentHeader")
                if header_info:
                    metadata = " • ".join([el.text.strip().replace('\n', ' ') for el in header_info if el.text.strip()])
            except:
                pass

            # Extract assignment content
            assignment_content, image_count = self._extract_assignment_content()
            downloaded_count += image_count

            if assignment_content:
                # Download CSS
                css_links_html = self._download_course_css()
                
                filename = f"{item_counter:03d}_{title}_{item_type}.html"
                assignment_file = self._get_or_move_path(course_dir, module_dir, filename)
                
                # Save to HTML file
                self._save_assignment_html(assignment_file, title, item_type, assignment_content, css_links_html, metadata)
                
                downloaded_count += 1
                downloaded_something = True
                print(f"  ✓ {item_type.title()} content saved (with {image_count} images)")

                # Try to click 'Save draft' button to avoid annoying popups on exit
                self._click_save_draft_button()
            else:
                print(f"  ⚠ No assignment content found to save")

        except Exception as e:
            print(f"  ⚠ Error processing {item_type}: {e}")

        return downloaded_something, downloaded_count

    def _process_lab_item(self, course_dir: Path, module_dir: Path, item_counter: int,
                         title: str) -> Tuple[bool, int]:
        """Process and download Jupyter lab notebooks and data files."""
        downloaded_count = 0
        downloaded_something = False
        original_window = None
        lab_window = None

        try:
            print(f"  Processing lab...")

            # Remember the original window handle
            original_window = self.driver.current_window_handle
            print(f"  Original window: {original_window}")

            # Launch lab
            launch_clicked = False
            for btn_text in ["Launch Lab", "Open Tool", "Launch", "Continue"]:
                try:
                    launch_btn = self.driver.find_element(By.XPATH,
                        f"//button[contains(., '{btn_text}')] | //a[contains(., '{btn_text}')]")
                    if launch_btn.is_displayed() and launch_btn.is_enabled():
                        print(f"  ✓ Clicking '{btn_text}'...")
                        launch_btn.click()
                        launch_clicked = True
                        break
                except:
                    continue

            if not launch_clicked:
                print(f"  ℹ Could not launch lab")
                return downloaded_something, downloaded_count

            # Wait for a new tab / window to open
            print(f"  ⏳ Waiting for new tab to open...")
            time.sleep(5)  # Give time for a new tab to open

            # Check if a new window/tab was opened
            all_windows = self.driver.window_handles
            print(f"  Windows open: {len(all_windows)}")

            if len(all_windows) > 1:
                # New tab opened - switch to it
                for window in all_windows:
                    if window != original_window:
                        lab_window = window
                        break

                if lab_window:
                    print(f"  Switching to lab tab: {lab_window}")
                    self.driver.switch_to.window(lab_window)
                    time.sleep(2)

            # Wait for a lab to load (either in new tab or same window)
            print(f"  ⏳ Waiting for lab environment to load (up to 60 seconds)...")
            try:
                WebDriverWait(self.driver, 60).until(
                    lambda d: '/lab' in d.current_url and 'path=' in d.current_url
                )
                print(f"  ✓ Lab loaded: {self.driver.current_url}")
                time.sleep(5)
            except TimeoutException:
                print(f"  ⚠ Timeout waiting for lab to load")
                print(f"  Current URL: {self.driver.current_url}")
                # Switch back to the original window before returning
                if original_window and lab_window:
                    print(f"  Switching back to original window")
                    self.driver.switch_to.window(original_window)
                return downloaded_something, downloaded_count

            # Check if lab directory exists in old location or with different numbering
            lab_dir_name = f"{item_counter:03d}_{title}_lab"
            lab_dir = self._get_or_move_path(course_dir, module_dir, lab_dir_name)

            # Create lab directory if it still doesn't exist
            lab_dir.mkdir(exist_ok=True)

            # Download all lab files using the "Download all files" button
            current_url = self.driver.current_url
            print(f"  Lab URL: {current_url}")

            try:
                # Click "Lab files" button to show the file panel
                print(f"  Looking for 'Lab files' button...")
                lab_files_btn = None
                for btn_selector in [
                    "//button[contains(., 'Lab files')]",
                    "//button[contains(@aria-label, 'Lab files')]",
                    "//*[contains(text(), 'Lab files')]//ancestor::button",
                ]:
                    try:
                        lab_files_btn = self.driver.find_element(By.XPATH, btn_selector)
                        if lab_files_btn.is_displayed():
                            break
                    except Exception:
                        continue

                if lab_files_btn and lab_files_btn.is_displayed():
                    print(f"  ✓ Clicking 'Lab files' button...")
                    lab_files_btn.click()
                    time.sleep(2)
                else:
                    error_msg = f"❌ CRITICAL ERROR: 'Lab files' button not found!\n"
                    error_msg += f"  Lab: {title}\n"
                    error_msg += f"  URL: {current_url}\n"
                    error_msg += f"  Cannot proceed with downloading lab files.\n"
                    print(f"  {error_msg}")
                    raise RuntimeError(error_msg)

                # Click "Download all files" button
                print(f"  Looking for 'Download all files' button...")
                download_all_btn = None
                for btn_selector in [
                    "//button[contains(., 'Download all files')]",
                    "//span[contains(text(), 'Download all files')]//ancestor::button",
                    "//button[contains(@aria-label, 'Download all files')]",
                ]:
                    try:
                        download_all_btn = self.driver.find_element(By.XPATH, btn_selector)
                        if download_all_btn.is_displayed() and download_all_btn.is_enabled():
                            break
                    except Exception:
                        continue

                if download_all_btn and download_all_btn.is_displayed() and download_all_btn.is_enabled():
                    print(f"  ✓ Clicking 'Download all files' button...")
                    download_all_btn.click()
                    time.sleep(3)  # Give time for download to start
                else:
                    error_msg = f"❌ CRITICAL ERROR: 'Download all files' button not found!\n"
                    error_msg += f"  Lab: {title}\n"
                    error_msg += f"  URL: {current_url}\n"
                    error_msg += f"  Cannot proceed with downloading lab files.\n"
                    print(f"  {error_msg}")
                    raise RuntimeError(error_msg)

                # Wait for Files.zip to be downloaded
                print(f"  ⏳ Waiting for Files.zip to download...")
                zip_file = None
                for attempt in range(30):  # Wait up to 30 seconds
                    # Check in download directory
                    potential_zip = self.download_dir / "Files.zip"
                    if potential_zip.exists():
                        zip_file = potential_zip
                        break
                    # Also check in user's Downloads folder
                    downloads_folder = Path.home() / "Downloads" / "Files.zip"
                    if downloads_folder.exists():
                        zip_file = downloads_folder
                        break
                    time.sleep(1)

                if zip_file and zip_file.exists():
                    print(f"  ✓ Files.zip downloaded: {zip_file}")

                    # Extract the zip file
                    print(f"  📦 Extracting Files.zip...")
                    with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                        zip_ref.extractall(lab_dir)

                    # The zip contains: Files/home/jovyan/work/
                    # Move files from work directory to lab_dir root
                    work_dir = lab_dir / "Files" / "home" / "jovyan" / "work"
                    if work_dir.exists():
                        print(f"  📁 Moving files from work directory to lab directory...")
                        for item in work_dir.iterdir():
                            # Skip Jupyter checkpoints
                            if item.name == '.ipynb_checkpoints':
                                continue

                            dest = lab_dir / item.name
                            if dest.exists():
                                print(f"    ℹ Skipping existing: {item.name}")
                            else:
                                shutil.move(str(item), str(dest))
                                print(f"    ✓ Moved: {item.name}")
                                downloaded_count += 1
                                downloaded_something = True

                        # Clean up the Files directory structure
                        files_dir = lab_dir / "Files"
                        if files_dir.exists():
                            shutil.rmtree(files_dir)
                            print(f"  ✓ Cleaned up temporary Files directory")
                    else:
                        # Fallback: extract all files directly
                        print(f"  ℹ Work directory not found, extracting all files from zip...")
                        for item in lab_dir.iterdir():
                            if item.is_file() and item.suffix in ['.ipynb', '.csv', '.txt', '.json', '.xlsx', '.py']:
                                print(f"    ✓ Found: {item.name}")
                                downloaded_count += 1
                                downloaded_something = True

                    # Delete the zip file
                    zip_file.unlink()
                    print(f"  ✓ Deleted Files.zip")

                    # Recursive cleanup of any .ipynb_checkpoints that might have been extracted
                    for checkpoint_dir in lab_dir.rglob(".ipynb_checkpoints"):
                        if checkpoint_dir.is_dir():
                            try:
                                shutil.rmtree(checkpoint_dir)
                                print(f"  ✓ Removed checkpoint directory: {checkpoint_dir.name}")
                            except Exception as e:
                                print(f"  ⚠ Could not remove checkpoint directory {checkpoint_dir}: {e}")

                    # Save lab info
                    lab_info_file = lab_dir / "lab_info.txt"
                    with open(lab_info_file, 'w', encoding='utf-8') as f:
                        f.write(f"Lab: {title}\n")
                        f.write(f"URL: {current_url}\n")
                        f.write(f"\nFiles downloaded from Lab files → Download all files\n")
                        f.write(f"Check the lab directory for all downloaded files.\n")

                    print(f"  ✓ Lab processing complete")
                else:
                    # CRITICAL: If lab files were not downloaded, raise an error and stop
                    error_msg = f"❌ CRITICAL ERROR: Lab files were NOT downloaded!\n"
                    error_msg += f"  Lab: {title}\n"
                    error_msg += f"  URL: {current_url}\n"
                    error_msg += f"  Expected: Files.zip in {self.download_dir}\n"
                    error_msg += f"  This is a critical failure - the script must stop.\n"
                    print(f"  {error_msg}")
                    raise RuntimeError(error_msg)

            except Exception as e:
                print(f"  ⚠ Error downloading lab files: {e}")
                import traceback
                traceback.print_exc()

        except Exception as e:
            print(f"  ⚠ Error processing lab: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Clean up: close the lab tab and switch back to the original window
            if lab_window and original_window:
                try:
                    # Check if the lab window is still open
                    if lab_window in self.driver.window_handles:
                        print(f"  Closing lab tab...")
                        self.driver.switch_to.window(lab_window)
                        self.driver.close()
                        print(f"  ✓ Lab tab closed")

                    # Switch back to the original window
                    if original_window in self.driver.window_handles:
                        print(f"  Switching back to original window...")
                        self.driver.switch_to.window(original_window)
                        print(f"  ✓ Back to course page")
                except Exception as e:
                    print(f"  ⚠ Error during cleanup: {e}")
                    # Try to switch back to any available window
                    try:
                        if len(self.driver.window_handles) > 0:
                            self.driver.switch_to.window(self.driver.window_handles[0])
                    except:
                        pass

        return downloaded_something, downloaded_count

    def _process_course_item(self, item_url: str, course_dir: Path, module_dir: Path,
                           item_counter: int, downloaded_files: Set[str]) -> int:
        """Process a single course item and download its materials."""
        materials_downloaded = 0

        try:
            # Determine item type from URL (before navigating)
            item_type = self._determine_item_type(item_url)

            existing_items = self._find_items(course_dir, module_dir, item_counter, item_type, item_url)

            # Check if an item already exists before navigating
            if len(existing_items) > 0:
                print(f"\n  [{item_counter}] ✓ Item materials already exist, skipping navigation")
                
                # Check if we need to rename any found items to the correct prefix
                for item in existing_items:
                    # If it has a prefix but it's the wrong one, rename it
                    if len(item.name) > 4 and item.name[3] == '_' and not item.name.startswith(f"{item_counter:03d}_"):
                        # Construct the target filename with the correct prefix
                        target_filename = f"{item_counter:03d}_{item.name[4:]}"
                        # _get_or_move_path handles the actual move/rename and prefix correction
                        item_file = self._get_or_move_path(course_dir, module_dir, target_filename)
                        downloaded_files.add(item_file)
                    else:
                        # Exact match or already corrected
                        item_file = self._get_or_move_path(course_dir, module_dir, item.name)
                        downloaded_files.add(item_file)
                    
                    materials_downloaded += 1
                return 0  # Return 0 since we're not downloading anything new

            print(f"\n  [{item_counter}] Navigating to item...")
            self.driver.get(item_url)

            # Wait for content to load
            try:
                # Look for main content or article or specialized assignment containers or video
                WebDriverWait(self.driver, 30).until(
                    expected_conditions.presence_of_element_located((By.XPATH, 
                        "//main | //div[@role='main'] | //article | //div[@id='TUNNELVISIONWRAPPER_CONTENT_ID'] | " +
                        "//video | //div[@class='rc-VideoItem'] | " +
                        "//div[contains(@class, 'rc-FormPartsQuestion')] | //div[contains(@class, 'rc-CMLOrHTML')] | " +
                        "//div[contains(@class, 'rc-CML')] | //div[contains(@class, 'ItemHeader')]"
                    ))
                )
                time.sleep(2)
            except TimeoutException:
                print(f"  ⚠ Timeout waiting for page content on {item_url}")
                # Sometimes Coursera loads slowly but the elements eventually appear during processing
                time.sleep(3)
            except Exception as e:
                print(f"  ⚠ Unexpected error waiting for page content: {e}")

            title = self._get_item_title(item_url)

            print(f"  📄 Item {item_counter}: {title} ({item_type})")

            downloaded_something = False

            # Process based on item type
            if item_type == "video":
                downloaded_something, count = self._process_video_item(course_dir, module_dir, item_counter, title, item_url)
                materials_downloaded += count

            if item_type == "reading":
                downloaded_something, count = self._process_reading_item(course_dir, module_dir, item_counter, title, downloaded_files)
                materials_downloaded += count

            if item_type in ["quiz", "assignment"]:
                downloaded_something, count = self._process_assignment_or_quiz(course_dir, module_dir, item_counter, title, item_type)
                materials_downloaded += count

            if item_type == "lab":
                downloaded_something, count = self._process_lab_item(course_dir, module_dir, item_counter, title)
                materials_downloaded += count

            # Process PDFs (for all item types)
            _, pdf_count = self._process_pdf_items(course_dir, module_dir, item_counter, downloaded_files)
            materials_downloaded += pdf_count

            if not downloaded_something and item_type not in ["quiz", "assignment", "lab"]:
                print(f"  ℹ No downloadable materials found")

        except Exception as e:
            print(f"  ⚠ Error processing item: {e}")
            import traceback
            traceback.print_exc()

        return materials_downloaded

    def _process_module(self, course_url: str, course_slug: str, module_num: int,
                       course_dir: Path, visited_urls: Set[str], downloaded_files: Set[str]) -> Tuple[int, int]:
        """Process a single module and return (items_processed, materials_downloaded)."""
        module_url = f"{course_url}/home/module/{module_num}"

        print(f"\n{'─' * 60}")
        print(f"📂 Checking Module {module_num}")
        print(f"{'─' * 60}")

        self.driver.get(module_url)
        time.sleep(2)

        # Check if module exists
        if f"module/{module_num}" not in self.driver.current_url:
            print(f"✓ No more modules found (attempted module {module_num})")
            print(f"  Continuing to next course...")
            return 0, 0

        # Wait for content
        self._wait_for_module_content(module_num)

        # Extract items
        item_links = self._extract_module_items()
        print(f"  Found {len(item_links)} items in module {module_num}")

        if len(item_links) == 0:
            print(f"\n❌ ERROR: No items found in module {module_num}")
            print(f"Current URL: {self.driver.current_url}")

            debug_file = self.download_dir / f"debug_module_{module_num}_{course_slug}.html"
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source)

            print(f"Page source saved to: {debug_file}")
            print(f"Page title: {self.driver.title}")

            raise Exception(f"No items found in module {module_num}. Page source saved for debugging.")

        # Create module directory
        module_dir = course_dir / f"module_{module_num}"
        module_dir.mkdir(exist_ok=True)

        # Process each item
        items_processed = 0
        materials_downloaded = 0

        for idx, item_url in enumerate(item_links, 1):
            if item_url in visited_urls:
                print(f"\n  [{idx}/{len(item_links)}] ⏭ Already processed, skipping...")
                continue

            visited_urls.add(item_url)
            items_processed += 1

            item_counter = len(visited_urls)
            materials_count = self._process_course_item(item_url, course_dir, module_dir, item_counter, downloaded_files)
            materials_downloaded += materials_count

        return items_processed, materials_downloaded

    def get_course_content(self, course_url: str) -> int:
        """Navigate through the course and collect all downloadable materials."""
        print(f"\n{'=' * 60}")
        course_slug = course_url.split('/learn/')[-1].split('/')[0]
        print(f"Processing course: {course_slug}")
        print(f"{'=' * 60}")

        course_dir = self.download_dir / self.sanitize_filename(course_slug)
        course_dir.mkdir(exist_ok=True)

        total_materials = 0
        visited_urls = set()
        downloaded_files = set()

        print("\nNavigating to course...")
        self.driver.get(course_url)
        time.sleep(5)

        # Iterate through modules
        for module_num in range(1, 21):
            items_processed, materials_downloaded = self._process_module(
                course_url, course_slug, module_num, course_dir, visited_urls, downloaded_files
            )
            total_materials += materials_downloaded
            if items_processed == 0:
                break

        print(f"\n{'=' * 60}")
        print(f"✓ Course complete!")
        print(f"  Items processed: {len(visited_urls)}")
        print(f"  Materials downloaded: {total_materials}")
        print(f"{'=' * 60}")

        if len(visited_urls) == 0:
            raise RuntimeError("No items found in course.")

        return total_materials

    def download_certificate(self):
        """Download all courses from a professional certificate."""
        try:
            self.setup_driver()
            self.login_with_persistence()

            courses = [
                "https://www.coursera.org/learn/foundations-of-data-science",
                "https://www.coursera.org/learn/get-started-with-python",
                "https://www.coursera.org/learn/go-beyond-the-numbers-translate-data-into-insight",
                "https://www.coursera.org/learn/the-power-of-statistics",
                "https://www.coursera.org/learn/regression-analysis-simplify-complex-data-relationships",
                "https://www.coursera.org/learn/the-nuts-and-bolts-of-machine-learning",
                "https://www.coursera.org/learn/google-advanced-data-analytics-capstone",
            ]

            total_materials = 0

            for i, course_url in enumerate(courses, 1):
                print(f"\n\n{'#' * 60}")
                print(f"Course {i}/{len(courses)}")
                print(f"{'#' * 60}")

                materials = self.get_course_content(course_url)
                total_materials += materials

            print(f"\n\n{'=' * 60}")
            print(f"✓ DOWNLOAD COMPLETE")
            print(f"{'=' * 60}")
            print(f"Total materials downloaded: {total_materials}")
            print(f"Download directory: {self.download_dir.absolute()}")

        except KeyboardInterrupt:
            print("\n\n⚠ Download interrupted by user.")
            print(f"Partial downloads saved in: {self.download_dir.absolute()}")
        except Exception as e:
            print(f"\n\n⚠ Error during download: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._save_image_cache()
            if self.driver:
                print("\nClosing browser...")
                self.driver.quit()


def main():
    parser = argparse.ArgumentParser(
        description="Download all materials from Coursera Professional Certificate"
    )
    parser.add_argument(
        "--email",
        default="yoni.kremer@gmail.com",
        help="Google account email (default: yoni.kremer@gmail.com)"
    )
    parser.add_argument(
        "--cert-url",
        default="https://www.coursera.org/professional-certificates/google-advanced-data-analytics",
        help="Professional certificate URL"
    )
    parser.add_argument(
        "--output-dir",
        default="coursera_downloads",
        help="Output directory for downloads (default: coursera_downloads)"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (not recommended for login)"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Coursera Material Downloader")
    print("=" * 60)
    print(f"Email: {args.email}")
    print(f"Certificate: {args.cert_url}")
    print(f"Output directory: {args.output_dir}")
    print("=" * 60)

    downloader = CourseraDownloader(
        email=args.email,
        download_dir=args.output_dir,
        headless=args.headless
    )

    downloader.download_certificate()


if __name__ == "__main__":
    main()
