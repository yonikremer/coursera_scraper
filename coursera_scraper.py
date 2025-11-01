#!/usr/bin/env python3
"""
Coursera Material Downloader
Downloads all course materials from enrolled Coursera courses/professional certificates.
"""
import os
import re
import time
import argparse
import urllib.parse
from pathlib import Path
from typing import Set, Tuple, Optional

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import yt_dlp
from yt_dlp.utils import sanitize_filename


class CourseraDownloader:
    """Download materials from Coursera courses."""

    def __init__(self, email: str, download_dir: str = "coursera_downloads", headless: bool = False):
        self.email = email
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        self.session = requests.Session()
        self.driver = None
        self.headless = headless
        self.cookies_file = self.download_dir / "coursera_cookies.pkl"

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
        # Replace invalid characters with underscores
        sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Replace spaces with underscores
        sanitized = sanitized.replace(' ', '_')
        sanitized = sanitized.replace('-', '_')
        # Convert to lowercase
        sanitized = sanitized.lower()
        # Remove multiple consecutive underscores
        sanitized = re.sub(r'_+', '_', sanitized)
        return sanitized

    @staticmethod
    def _get_or_move_file(course_dir: Path, module_dir: Path, filename: str) -> Path:
        """
        Check if a file exists in the course directory (from old runs), move it to the module directory.
        Also handles renaming files from the old naming convention (spaces, mixed case) to new (lowercase, underscores).
        If not found, return the module directory path for saving.

        Args:
            course_dir: The course root directory
            module_dir: The module subdirectory
            filename: The filename to check/save (should be already sanitized)

        Returns:
            Path object for the file in the module directory
        """
        module_file = module_dir / filename
        course_file = course_dir / filename

        # Ensure module directory exists
        module_dir.mkdir(exist_ok=True)

        # If a file already exists in the module directory with the correct name, return it
        if module_file.exists():
            return module_file

        # Check if a file exists in the course directory with the new naming
        if course_file.exists():
            print(f"  📦 Moving existing file to module directory: {filename}")
            try:
                # Move file from course root to the module directory
                course_file.rename(module_file)
                print(f"  ✓ Moved: {filename}")
                return module_file
            except Exception as e:
                print(f"  ⚠ Error moving file: {e}")


        return module_file

    @staticmethod
    def _find_items(course_dir: Path, module_dir: Path, item_counter: int,
                    item_type: str) -> list[Path]:
        """
        Check if an item's materials already exist (either in module or course directory).
        This allows skipping navigation to items that have already been downloaded.

        Args:
            course_dir: The course root directory
            module_dir: The module subdirectory
            item_counter: The item number
            item_type: Type of item (video, reading, quiz, assignment, lab)

        Returns:
            True if the item likely exists, False otherwise
        """
        # Create the pattern for the item counter-prefix
        prefix = f"{item_counter:03d}_"

        # Check the module directory first
        if module_dir.exists():
            files_in_module = list(module_dir.glob(f"{prefix}*"))
            if files_in_module:
                # Found files with this counter in the module directory
                return files_in_module

        # Check course root directory for old structure
        files_in_course = list(course_dir.glob(f"{prefix}*"))
        if files_in_course:
            # Found files with this counter in course root
            return files_in_course

        # For labs, check if the lab directory exists
        if item_type == "lab":
            # Lab directories have a pattern: NNN_title_lab/
            lab_dirs_module = list(module_dir.glob(f"{prefix}*_lab"))
            if lab_dirs_module and any(d.is_dir() for d in lab_dirs_module):
                return files_in_course

            lab_dirs_course = list(course_dir.glob(f"{prefix}*_lab"))
            if lab_dirs_course and any(d.is_dir() for d in lab_dirs_course):
                return lab_dirs_course

        return []

    def download_file(self, url: str, filepath: Path) -> bool:
        """Download a file from URL."""
        try:
            if filepath.exists() and filepath.stat().st_size > 0:
                print(f"  ℹ File already exists, skipping: {filepath.name}")
                return True

            response = self.session.get(url, stream=True, timeout=30)
            response.raise_for_status()

            filepath.parent.mkdir(parents=True, exist_ok=True)

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

    def _wait_for_module_content(self):
        """Wait for module content to load."""
        print(f"  Waiting for module content to load...")
        try:
            WebDriverWait(self.driver, 30).until(
                expected_conditions.presence_of_element_located((By.XPATH, "//ul[@data-testid='named-item-list-list']//a"))
            )
            print(f"  ✓ Module content loaded")
            time.sleep(2)
        except TimeoutException:
            print(f"  ⚠ Timeout waiting for module content to load")

    def _extract_module_items(self) -> list:
        """Extract all item links from the current module page."""
        link_elements = self.driver.find_elements(By.XPATH,
            "//ul[@data-testid='named-item-list-list']//a[contains(@href, '/lecture/') or " +
            "contains(@href, '/supplement/') or contains(@href, '/quiz/') or " +
            "contains(@href, '/exam/') or contains(@href, '/assignment/') or " +
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
        elif '/assignment/' in item_url or '/programming/' in item_url:
            return "assignment"
        elif '/ungradedLab/' in item_url or '/gradedLab/' in item_url:
            return "lab"
        else:
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
                        video_file = self._get_or_move_file(course_dir, module_dir, filename)

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
                    video_file = self._get_or_move_file(course_dir, module_dir, filename)
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
                    pdf_file = self._get_or_move_file(course_dir, module_dir, filename)

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
            content = None
            for selector in ["div[class*='rc-CML']", "div[class*='content']", "div[role='main']",
                           "article", "main"]:
                try:
                    content_elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    content = content_elem.get_attribute('innerHTML')
                    if content and len(content) > 100:
                        break
                except:
                    continue

            # Download attachments
            downloaded_count += self._download_attachments(course_dir, module_dir, item_counter, downloaded_files)

            # Save HTML content
            if content:
                filename = f"{item_counter:03d}_{title}.html"
                html_file = self._get_or_move_file(course_dir, module_dir, filename)
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.6; }}
        img {{ max-width: 100%; height: auto; }}
        code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
        pre {{ background: #f4f4f4; padding: 10px; border-radius: 5px; overflow-x: auto; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    {content}
</body>
</html>""")

                downloaded_count += 1
                downloaded_something = True
                print(f"  ✓ Reading saved as HTML")

        except Exception as e:
            print(f"  ⚠ Could not save reading: {e}")

        return downloaded_something, downloaded_count

    def _download_attachments(self, course_dir: Path, module_dir: Path, item_counter: int,
                             downloaded_files: Set[str]) -> int:
        """Download attachments from reading items."""
        downloaded_count = 0

        try:
            attachment_links = self.driver.find_elements(By.XPATH,
                "//a[@data-e2e='asset-download-link'] | " +
                "//div[contains(@class, 'cml-asset')]//a[contains(@href, 'cloudfront.net')]")

            for attach_link in attachment_links:
                try:
                    attach_url = attach_link.get_attribute('href')
                    if not attach_url or attach_url in downloaded_files:
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
                    attach_file = self._get_or_move_file(course_dir, module_dir, filename)

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

    def _process_assignment_or_quiz(self, course_dir: Path, module_dir: Path, item_counter: int,
                                    title: str, item_type: str) -> Tuple[bool, int]:
        """Process and save assignment or quiz content."""
        downloaded_count = 0
        downloaded_something = False

        try:
            print(f"  Processing {item_type}...")

            # Navigate to the attempt page
            if '/attempt' not in self.driver.current_url:
                start_clicked = False
                for btn_text in ["Start Assignment", "Resume", "Continue", "Start Quiz", "Retake Quiz", "Review"]:
                    try:
                        start_btn = self.driver.find_element(By.XPATH,
                            f"//button[contains(., '{btn_text}')] | //a[contains(., '{btn_text}')]")
                        if start_btn.is_displayed() and start_btn.is_enabled():
                            start_btn.click()
                            print(f"  ✓ Clicked '{btn_text}'")
                            time.sleep(4)
                            start_clicked = True
                            break
                    except:
                        continue

                if not start_clicked:
                    print(f"  ℹ Already on assignment/quiz page or no start button found")

            # Wait for attempt page
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: '/attempt' in d.current_url or
                             d.find_element(By.CSS_SELECTOR, "div.rc-FormPartsQuestion, form, div.rc-CMLOrHTML")
                )
                time.sleep(2)
            except:
                pass

            print(f"  Current URL: {self.driver.current_url}")

            # Save content
            assignment_content = None
            for selector in ["div[role='main']", "main", "div.rc-FormPartsQuestion",
                           "div.rc-CMLOrHTML", "form"]:
                try:
                    content_elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    assignment_content = content_elem.get_attribute('outerHTML')
                    if assignment_content and len(assignment_content) > 100:
                        break
                except:
                    continue

            if assignment_content:
                filename = f"{item_counter:03d}_{title}_{item_type}.html"
                assignment_file = self._get_or_move_file(course_dir, module_dir, filename)
                with open(assignment_file, 'w', encoding='utf-8') as f:
                    f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; line-height: 1.6; }}
        img {{ max-width: 100%; height: auto; }}
        code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
        pre {{ background: #f4f4f4; padding: 10px; border-radius: 5px; overflow-x: auto; }}
        .question {{ margin: 20px 0; padding: 15px; background: #f9f9f9; border-left: 4px solid #007bff; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <p><strong>Type:</strong> {item_type.title()}</p>
    <p><strong>URL:</strong> {self.driver.current_url}</p>
    <hr>
    {assignment_content}
</body>
</html>""")
                downloaded_count += 1
                downloaded_something = True
                print(f"  ✓ {item_type.title()} content saved")

                # Click the Save Draft button
                try:
                    save_btn = self.driver.find_element(By.XPATH,
                        "//button[contains(., 'Save draft') or contains(., 'Save Draft')]")
                    if save_btn.is_displayed() and save_btn.is_enabled():
                        save_btn.click()
                        print(f"  ✓ Clicked 'Save draft'")
                        time.sleep(2)
                except:
                    print(f"  ℹ No 'Save draft' button found")

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

            # Check if lab directory exists in old location (course root) or with old naming
            lab_dir_name = f"{item_counter:03d}_{title}_lab"
            old_lab_dir = course_dir / lab_dir_name
            lab_dir = module_dir / lab_dir_name

            # Check if lab directory already exists with correct name
            if lab_dir.exists() and lab_dir.is_dir():
                print(f"  ℹ Lab directory already exists: {lab_dir_name}")
            else:
                # Try to find lab directory with new naming in course root (flat structure)
                if old_lab_dir.exists() and old_lab_dir.is_dir():
                    print(f"  📦 Moving existing lab directory to module directory")
                    try:
                        import shutil
                        module_dir.mkdir(exist_ok=True)
                        shutil.move(str(old_lab_dir), str(lab_dir))
                        print(f"  ✓ Moved lab directory")
                    except Exception as e:
                        print(f"  ⚠ Error moving lab directory: {e}")
                else:
                    # Try to find lab directory with old naming convention (spaces, mixed case)
                    counter_prefix = f"{item_counter:03d}_"
                    for directory in [module_dir, course_dir]:
                        if directory.exists():
                            # Find directories that start with the counter and end with _lab
                            for old_dir in directory.glob(f"{counter_prefix}*_lab"):
                                if old_dir.is_dir() and old_dir.name.lower() == lab_dir_name.lower() and old_dir.name != lab_dir_name:
                                    # Found lab directory with old naming - move and rename it
                                    print(f"  📦 Moving and renaming lab directory: {old_dir.name} → {lab_dir_name}")
                                    try:
                                        module_dir.mkdir(exist_ok=True)
                                        import shutil
                                        shutil.move(str(old_dir), str(lab_dir))
                                        print(f"  ✓ Renamed and moved lab directory")
                                        break
                                    except Exception as e:
                                        print(f"  ⚠ Error renaming lab directory: {e}")

            # Create lab directory if it still doesn't exist
            lab_dir.mkdir(exist_ok=True)

            # Download notebook and data files
            current_url = self.driver.current_url
            parsed_url = urllib.parse.urlparse(current_url)
            params = urllib.parse.parse_qs(parsed_url.query)
            notebook_path = params.get('path', [''])[0]

            if notebook_path:
                notebook_path = urllib.parse.unquote(notebook_path)
                notebook_name = notebook_path.split('/')[-1]
                print(f"  Notebook: {notebook_name}")

                base_lab_url = current_url.split('/lab?')[0]

                # Download notebook
                notebook_download_url = f"{base_lab_url}/lab/api/contents/{notebook_path}"
                print(f"  ⬇ Downloading notebook: {notebook_name}")

                notebook_file = lab_dir / notebook_name

                try:
                    response = self.session.get(notebook_download_url, timeout=30)
                    if response.status_code == 200:
                        with open(notebook_file, 'wb') as f:
                            f.write(response.content)
                        print(f"  ✓ Notebook downloaded: {notebook_name}")
                        downloaded_count += 1
                        downloaded_something = True
                    else:
                        print(f"  ⚠ Could not download notebook (HTTP {response.status_code})")
                except Exception as e:
                    print(f"  ⚠ Error downloading notebook: {e}")

                time.sleep(3)

                # Find and download data files
                data_files = self._find_lab_data_files()
                print(f"  Found {len(data_files)} potential data file(s): {', '.join(sorted(data_files))}")

                for data_filename in sorted(data_files):
                    try:
                        data_download_url = f"{base_lab_url}/lab/api/contents/{data_filename}"
                        print(f"  ⬇ Downloading data file: {data_filename}")

                        data_file = lab_dir / data_filename

                        response = self.session.get(data_download_url, timeout=30)
                        if response.status_code == 200:
                            with open(data_file, 'wb') as f:
                                f.write(response.content)
                            print(f"  ✓ Data file downloaded: {data_filename}")
                            downloaded_count += 1
                            downloaded_something = True
                        else:
                            print(f"  ⚠ Could not download {data_filename} (HTTP {response.status_code})")
                    except Exception as e:
                        print(f"  ⚠ Error downloading {data_filename}: {e}")

                # Save lab info
                lab_info_file = lab_dir / "lab_info.txt"
                with open(lab_info_file, 'w', encoding='utf-8') as f:
                    f.write(f"Lab: {title}\n")
                    f.write(f"URL: {current_url}\n")
                    f.write(f"Notebook: {notebook_name}\n")
                    f.write(f"\nData files found:\n")
                    for df in sorted(data_files):
                        f.write(f"  - {df}\n")
                    f.write(f"\nNote: Download attempts were made for all files above.\n")
                    f.write(f"Check the lab directory for successfully downloaded files.\n")

                print(f"  ✓ Lab processing complete")

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

    def _find_lab_data_files(self) -> Set[str]:
        """Find data files referenced in the lab notebook."""
        page_source = self.driver.page_source

        file_patterns = [
            r'["\']([^"\']+\.csv)["\']',
            r'["\']([^"\']+\.txt)["\']',
            r'["\']([^"\']+\.json)["\']',
            r'["\']([^"\']+\.xlsx?)["\']',
            r'["\']([^"\']+\.parquet)["\']',
            r'["\']([^"\']+\.pkl)["\']',
            r'["\']([^"\']+\.dat)["\']',
            r'["\']([^"\']+\.h5)["\']',
            r'["\']([^"\']+\.hdf5?)["\']',
        ]

        data_files = set()
        for pattern in file_patterns:
            matches = re.findall(pattern, page_source)
            for match in matches:
                if not any(x in match for x in ['http://', 'https://', '/usr/', '/opt/',
                                                '/home/', '/var/', '/tmp/']):
                    filename = match.split('/')[-1]
                    if filename and len(filename) < 100 and '.' in filename:
                        data_files.add(filename)

        return data_files

    def _process_course_item(self, item_url: str, course_dir: Path, module_dir: Path,
                           item_counter: int, downloaded_files: Set[str]) -> int:
        """Process a single course item and download its materials."""
        materials_downloaded = 0

        try:
            # Determine item type from URL (before navigating)
            item_type = self._determine_item_type(item_url)

            existing_items = self._find_items(course_dir, module_dir, item_counter, item_type)

            # Check if an item already exists before navigating
            if len(existing_items) > 0:
                print(f"\n  [{item_counter}] ✓ Item materials already exist, skipping navigation")
                # Still need to move files if they're in the old location,
                print(f"found existing items: {existing_items}")
                for item in existing_items:
                    # move the file to the module directory and sanitize the file name
                    print(f"moving item: {item}")
                    item_file = self._get_or_move_file(course_dir, module_dir, item.name)
                    downloaded_files.add(item_file)
                    materials_downloaded += 1
                return 0  # Return 0 since we're not downloading anything new

            print(f"\n  [{item_counter}] Navigating to item...")
            self.driver.get(item_url)

            # Wait for content to load
            try:
                WebDriverWait(self.driver, 15).until(
                    expected_conditions.presence_of_element_located((By.XPATH, "//main | //div[@role='main']"))
                )
                time.sleep(2)
            except TimeoutException:
                print(f"  ⚠ Timeout waiting for page content")
                time.sleep(3)

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
        self._wait_for_module_content()

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
