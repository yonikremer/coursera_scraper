#!/usr/bin/env python3
"""
Coursera Material Downloader
Downloads all course materials from enrolled Coursera courses/professional certificates.
"""

import re
import time
import argparse
from pathlib import Path
from typing import Any


import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import yt_dlp


class CourseraDownloader:
    """Download materials from Coursera courses."""

    def __init__(self, email, download_dir="coursera_downloads", headless=False):
        self.email = email
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        self.session = requests.Session()
        self.driver = None
        self.headless = headless

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

        # Set download preferences
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
        """Login to Coursera using Google account."""
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
            # Wait for user to complete login manually
            # Check if we're logged in by looking for profile or authenticated content
            WebDriverWait(self.driver, 180).until(
                lambda driver: (
                                       "coursera.org" in driver.current_url and
                                       "authMode=login" not in driver.current_url and
                                       "authMode=signup" not in driver.current_url
                               ) or self._check_logged_in()
            )

            # Give extra time for page to fully load
            time.sleep(3)

            print("✓ Login successful!")

            # Extract cookies for requests session
            for cookie in self.driver.get_cookies():
                self.session.cookies.set(cookie['name'], cookie['value'])

        except TimeoutException:
            print("\n⚠ Login timeout. Please try again and complete the login process.")
            print("If you're having trouble, make sure you:")
            print("  - Click through the entire Google login flow")
            print("  - Wait until you see the main Coursera homepage")
            raise

    def _check_logged_in(self):
        """Check if user is logged in by looking for common authenticated elements."""
        try:
            # Try to find elements that only appear when logged in
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

    def get_professional_certificate_courses(self, cert_url):
        """Get all course URLs from a professional certificate."""
        print(f"\nFetching courses from: {cert_url}")
        self.driver.get(cert_url)
        time.sleep(5)

        courses = []

        try:
            # Scroll down to load all courses
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)

            # Look for course links in the certificate page
            course_elements = self.driver.find_elements(By.XPATH, "//a[contains(@href, '/learn/')]")

            for elem in course_elements:
                href = elem.get_attribute('href')
                if href and '/learn/' in href:
                    # Clean up URL
                    base_url = href.split('?')[0].split('#')[0]
                    if base_url not in courses:
                        courses.append(base_url)

            # Deduplicate and filter
            courses = list(dict.fromkeys(courses))  # Preserve order
            courses = [c for c in courses if '/learn/' in c and '/lecture/' not in c and '/supplement/' not in c]

            if not courses:
                print("⚠ No courses found automatically. Trying alternative method...")
                # Fallback: Try to find course titles and construct URLs
                course_cards = self.driver.find_elements(By.XPATH, "//h3[contains(@class, 'course')]")
                for card in course_cards:
                    try:
                        parent = card.find_element(By.XPATH, "./ancestor::a[contains(@href, '/learn/')]")
                        href = parent.get_attribute('href')
                        if href:
                            base_url = href.split('?')[0].split('#')[0]
                            if base_url not in courses:
                                courses.append(base_url)
                    except:
                        continue

            print(f"✓ Found {len(courses)} courses in the certificate")
            for i, course in enumerate(courses, 1):
                course_name = course.split('/learn/')[-1].split('/')[0]
                print(f"  {i}. {course_name}")

        except Exception as e:
            print(f"⚠ Error fetching courses: {e}")
            import traceback
            traceback.print_exc()

        return courses

    def sanitize_filename(self, filename):
        """Remove invalid characters from filename."""
        return re.sub(r'[<>:"/\\|?*]', '_', filename)

    def download_file(self, url, filepath):
        """Download a file from URL."""
        try:
            # Check if file already exists
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

    def download_video(self, video_url, filepath):
        """Download video using yt-dlp."""
        try:
            # Get cookies from selenium session
            cookies_dict = {}
            for cookie in self.driver.get_cookies():
                cookies_dict[cookie['name']] = cookie['value']

            # Create cookies file for yt-dlp
            cookies_file = self.download_dir / "cookies.txt"
            with open(cookies_file, 'w') as f:
                f.write("# Netscape HTTP Cookie File\n")
                for name, value in cookies_dict.items():
                    f.write(f".coursera.org\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")

            ydl_opts = {
                'outtmpl': str(filepath),
                'cookiefile': str(cookies_file),
                'format': 'best[height<=720]',  # Download 720p or lower quality
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

    def get_course_content(self, course_url):
        """Navigate through course and collect all downloadable materials."""
        print(f"\n{'=' * 60}")
        course_slug = course_url.split('/learn/')[-1].split('/')[0]
        print(f"Processing course: {course_slug}")
        print(f"{'=' * 60}")

        course_dir = self.download_dir / self.sanitize_filename(course_slug)
        course_dir.mkdir(exist_ok=True)

        materials_downloaded = 0
        visited_urls = set()
        downloaded_files = set()
        item_counter = 0

        try:
            # Navigate to course home
            print("\nNavigating to course...")
            self.driver.get(course_url)
            time.sleep(5)

            # Iterate through modules (1 to 20 max)
            for module_num in range(1, 21):
                module_url = f"{course_url}/home/module/{module_num}"

                print(f"\n{'─' * 60}")
                print(f"📂 Checking Module {module_num}")
                print(f"{'─' * 60}")

                self.driver.get(module_url)

                # Wait a moment for initial page load
                time.sleep(2)

                # Check if module exists (page doesn't redirect)
                if f"module/{module_num}" not in self.driver.current_url:
                    print(f"✓ No more modules found (attempted module {module_num})")
                    print(f"  Continuing to next course...")
                    break

                # Wait for the module content to actually load
                # Look for the named-item-list-list element with actual content
                print(f"  Waiting for module content to load...")

                try:
                    # Wait up to 30 seconds for the item list to appear and have content
                    WebDriverWait(self.driver, 30).until(
                        EC.presence_of_element_located((By.XPATH, "//ul[@data-testid='named-item-list-list']//a"))
                    )
                    print(f"  ✓ Module content loaded")

                    # Give a bit more time for all items to render
                    time.sleep(2)

                except TimeoutException:
                    print(f"  ⚠ Timeout waiting for module content to load")
                    # Continue anyway to check if items are there

                # Extract all item links from this module page
                # Look for links in the ul[data-testid="named-item-list-list"]
                item_links = []

                # Find all <a> elements that have href containing lecture, supplement, assignment, etc.
                link_elements = self.driver.find_elements(By.XPATH,
                                                          "//ul[@data-testid='named-item-list-list']//a[contains(@href, '/lecture/') or " +
                                                          "contains(@href, '/supplement/') or contains(@href, '/quiz/') or " +
                                                          "contains(@href, '/exam/') or contains(@href, '/assignment/') or " +
                                                          "contains(@href, '/programming/')]")

                for elem in link_elements:
                    href = elem.get_attribute('href')
                    if href and href not in item_links:
                        item_links.append(href)

                print(f"  Found {len(item_links)} items in module {module_num}")

                if len(item_links) == 0:
                    print(f"\n❌ ERROR: No items found in module {module_num}")
                    print(f"Current URL: {self.driver.current_url}")

                    # Save page source for debugging
                    debug_file = self.download_dir / f"debug_module_{module_num}_{course_slug}.html"
                    with open(debug_file, 'w', encoding='utf-8') as f:
                        f.write(self.driver.page_source)

                    print(f"Page source saved to: {debug_file}")
                    print(f"Page title: {self.driver.title}")

                    raise Exception(f"No items found in module {module_num}. Page source saved for debugging.")


                # Now visit each item in sequence
                for idx, item_url in enumerate(item_links, 1):
                    print(f"found item: {item_url}")
                    if item_url in visited_urls:
                        print(f"\n  [{idx}/{len(item_links)}] ⏭ Already processed, skipping...")
                        continue

                    visited_urls.add(item_url)
                    item_counter += 1

                    try:
                        print(f"\n  [{idx}/{len(item_links)}] Navigating to item...")
                        self.driver.get(item_url)

                        # Wait for the main content to load
                        try:
                            WebDriverWait(self.driver, 15).until(
                                EC.presence_of_element_located((By.XPATH, "//main | //div[@role='main']"))
                            )
                            time.sleep(2)  # Extra time for dynamic content
                        except TimeoutException:
                            print(f"  ⚠ Timeout waiting for page content")
                            time.sleep(3)  # Fallback wait

                        # Determine item type from URL
                        if '/lecture/' in item_url:
                            item_type = "video"
                        elif '/supplement/' in item_url:
                            item_type = "reading"
                        elif '/quiz/' in item_url or '/exam/' in item_url:
                            item_type = "quiz"
                        elif '/assignment/' in item_url or '/programming/' in item_url:
                            item_type = "assignment"
                        else:
                            item_type = "other"

                        # Get item title
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

                        print(f"  📄 Module {module_num} - Item {item_counter}: {title} ({item_type})")

                        # Download materials from current page
                        downloaded_something = False

                        # 1. Try to download videos
                        if item_type == "video":
                            try:
                                downloaded_something, materials_downloaded = self.download_vid(course_dir,
                                                                                               downloaded_something,
                                                                                               item_counter, item_url,
                                                                                               materials_downloaded,
                                                                                               title)
                            except Exception as e:
                                print(f"  ⚠ Error finding video: {e}")

                            # Also look for download buttons
                            try:
                                download_btns = self.driver.find_elements(By.XPATH,
                                                                          "//a[contains(text(), 'Download') and (contains(@href, '.mp4') or contains(@href, 'video'))]")

                                for btn in download_btns:
                                    href = btn.get_attribute('href')
                                    if href:
                                        print(f"  Found download link: {href[:80]}...")
                                        video_file = course_dir / f"{item_counter:03d}_{title}.mp4"
                                        if not video_file.exists():
                                            if self.download_file(href, video_file):
                                                materials_downloaded += 1
                                                downloaded_something = True
                                                print(f"  ✓ Video saved: {video_file.name}")
                            except:
                                pass

                        # 2. Try to download PDFs (exclude footer)
                        try:
                            # Only look for PDFs in main content area, not footer
                            pdf_links = self.driver.find_elements(By.XPATH,
                                                                  "//main//a[contains(@href, '.pdf')] | //div[@role='main']//a[contains(@href, '.pdf')] | " +
                                                                  "//article//a[contains(@href, '.pdf')]")

                            # Filter out footer links
                            main_pdf_links = []
                            for link in pdf_links:
                                try:
                                    # Check if link is inside footer
                                    parent_html = link.find_element(By.XPATH, "./ancestor::footer")
                                    # If we found a footer parent, skip this link
                                    continue
                                except:
                                    # No footer parent, this is a valid link
                                    main_pdf_links.append(link)

                            if main_pdf_links:
                                print(f"  Found {len(main_pdf_links)} PDF link(s) in main content")

                            for link in main_pdf_links:
                                href = link.get_attribute('href')
                                if href and href not in downloaded_files:
                                    downloaded_files.add(href)
                                    link_text = link.text.strip() or "document"
                                    filename = self.sanitize_filename(link_text)
                                    if not filename.endswith('.pdf'):
                                        filename += '.pdf'

                                    pdf_file = course_dir / f"{item_counter:03d}_{filename}"
                                    print(f"  ⬇ Downloading PDF: {filename}")
                                    if self.download_file(href, pdf_file):
                                        materials_downloaded += 1
                                        downloaded_something = True
                                        print(f"  ✓ PDF saved: {filename}")
                        except Exception as e:
                            print(f"  ⚠ Error processing PDFs: {e}")

                        # 3. Save reading content as HTML and download attachments
                        if item_type == "reading":
                            try:
                                content = None
                                for selector in [
                                    "div[class*='rc-CML']",
                                    "div[class*='content']",
                                    "div[role='main']",
                                    "article",
                                    "main"
                                ]:
                                    try:
                                        content_elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                                        content = content_elem.get_attribute('innerHTML')
                                        if content and len(content) > 100:
                                            break
                                    except:
                                        continue

                                # Download attachments from the reading
                                try:
                                    # Find attachment links (DOCX, PDF, etc.)
                                    attachment_links = self.driver.find_elements(By.XPATH,
                                        "//a[@data-e2e='asset-download-link'] | " +
                                        "//div[contains(@class, 'cml-asset')]//a[contains(@href, 'cloudfront.net')]")

                                    for attach_link in attachment_links:
                                        try:
                                            attach_url = attach_link.get_attribute('href')
                                            if not attach_url or attach_url in downloaded_files:
                                                continue

                                            downloaded_files.add(attach_url)

                                            # Try to get filename from data-name attribute or link text
                                            attach_name = None
                                            try:
                                                # Look for data-name attribute in child elements
                                                asset_elem = attach_link.find_element(By.XPATH, ".//div[@data-name]")
                                                attach_name = asset_elem.get_attribute('data-name')
                                            except:
                                                pass

                                            if not attach_name:
                                                # Try to get from data-e2e="asset-name" element
                                                try:
                                                    name_elem = attach_link.find_element(By.XPATH, ".//div[@data-e2e='asset-name']")
                                                    attach_name = name_elem.text.strip()
                                                except:
                                                    pass

                                            if not attach_name:
                                                # Fallback to URL filename
                                                attach_name = attach_url.split('/')[-1].split('?')[0]

                                            # Get file extension from data-extension or URL
                                            extension = None
                                            try:
                                                asset_elem = attach_link.find_element(By.XPATH, ".//div[@data-extension]")
                                                extension = asset_elem.get_attribute('data-extension')
                                            except:
                                                # Try to extract from URL
                                                if '.' in attach_url.split('/')[-1].split('?')[0]:
                                                    extension = attach_url.split('/')[-1].split('?')[0].split('.')[-1]

                                            # Ensure filename has extension
                                            attach_name = self.sanitize_filename(attach_name)
                                            if extension and not attach_name.endswith(f'.{extension}'):
                                                attach_name = f"{attach_name}.{extension}"

                                            attach_file = course_dir / f"{item_counter:03d}_attachment_{attach_name}"

                                            print(f"  ⬇ Downloading attachment: {attach_name}")
                                            if self.download_file(attach_url, attach_file):
                                                materials_downloaded += 1
                                                downloaded_something = True
                                                print(f"  ✓ Attachment saved: {attach_name}")
                                        except Exception as e:
                                            print(f"  ⚠ Error downloading attachment: {e}")
                                            continue
                                except Exception as e:
                                    print(f"  ⚠ Error processing attachments: {e}")

                                if content:
                                    html_file = course_dir / f"{item_counter:03d}_{title}.html"
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

                                materials_downloaded += 1
                                downloaded_something = True
                                print(f"  ✓ Reading saved as HTML")
                            except Exception as e:
                                print(f"  ⚠ Could not save reading: {e}")

                        # 4. Download other resources (exclude footer)
                        try:
                            # Only look in main content area
                            resource_links = self.driver.find_elements(By.XPATH,
                                                                       "//main//a[@download or contains(text(), 'Download')] | " +
                                                                       "//div[@role='main']//a[@download or contains(text(), 'Download')] | " +
                                                                       "//article//a[@download or contains(text(), 'Download')]")

                            # Filter out footer links
                            main_resource_links = []
                            for link in resource_links:
                                try:
                                    parent_html = link.find_element(By.XPATH, "./ancestor::footer")
                                    continue
                                except:
                                    main_resource_links.append(link)

                            for link in main_resource_links:
                                href = link.get_attribute('href')
                                if href and href not in downloaded_files and not any(
                                        x in href for x in ['.pdf', 'video', '.mp4']):
                                    downloaded_files.add(href)
                                    link_text = link.text.strip() or "resource"
                                    filename = self.sanitize_filename(link_text)

                                    resource_file = course_dir / f"{item_counter:03d}_{filename}"
                                    print(f"  ⬇ Downloading resource: {filename}")
                                    if self.download_file(href, resource_file):
                                        materials_downloaded += 1
                                        downloaded_something = True
                                        print(f"  ✓ Resource saved")
                        except Exception as e:
                            print(f"  ⚠ Error processing resources: {e}")

                        if not downloaded_something and item_type not in ["quiz", "assignment"]:
                            print(f"  ℹ No downloadable materials found")

                    except Exception as e:
                        print(f"  ⚠ Error processing item: {e}")
                        import traceback
                        traceback.print_exc()
                        continue

        except Exception as e:
            print(f"\n⚠ Error navigating course: {e}")
            import traceback
            traceback.print_exc()

        print(f"\n{'=' * 60}")
        print(f"✓ Course complete!")
        print(f"  Items processed: {item_counter}")
        print(f"  Materials downloaded: {materials_downloaded}")
        print(f"{'=' * 60}")

        if item_counter == 0:
            raise RuntimeError("No items found in course.")

        return materials_downloaded

    def download_vid(self, course_dir: Path, downloaded_something: bool, item_counter: int, item_url,
                     materials_downloaded: int | Any, title: str | Any) -> tuple[int | Any, bool]:
        video_elements = self.driver.find_elements(By.TAG_NAME, "video")
        print(f"  Found {len(video_elements)} video element(s)")

        for idx, video in enumerate(video_elements):
            sources = [
                video.get_attribute('src'),
                *[source.get_attribute('src') for source in
                  video.find_elements(By.TAG_NAME, 'source')]
            ]

            # Filter sources to get 720p if available
            # Look for sources with quality indicators in URL
            sources_720p = [s for s in sources if s and '720' in s]
            if sources_720p:
                sources = sources_720p
            else:
                # Fallback to all available sources
                sources = [s for s in sources if s]

            for video_src in sources:
                if video_src:
                    print(f"  Video source: {video_src[:80]}...")
                    video_file = course_dir / f"{item_counter:03d}_{title}_{idx}.mp4"

                    if not video_file.exists():
                        print(f"  ⬇ Downloading video (720p preferred)...")
                        try:
                            if self.download_file(video_src, video_file):
                                materials_downloaded += 1
                                downloaded_something = True
                                print(f"  ✓ Video saved: {video_file.name}")
                            else:
                                # Try with yt-dlp as fallback (with 720p format specification)
                                print(f"  Trying alternative download method (720p)...")
                                if self.download_video(item_url, video_file):
                                    materials_downloaded += 1
                                    downloaded_something = True
                                    print(f"  ✓ Video saved: {video_file.name}")
                        except Exception as e:
                            print(f"  ⚠ Error downloading video: {e}")
                    else:
                        print(f"  ℹ Video already exists: {video_file.name}")
                        downloaded_something = True
        return downloaded_something, materials_downloaded

    def download_certificate(self, cert_url):
        """Download all courses from a professional certificate."""
        try:
            self.setup_driver()
            self.login_with_google()

            # Get all courses in the certificate
            courses = [
                "https://www.coursera.org/learn/foundations-of-data-science",
                "https://www.coursera.org/learn/get-started-with-python",
                "https://www.coursera.org/learn/go-beyond-the-numbers-translate-data-into-insight",
                "https://www.coursera.org/learn/the-power-of-statistics",
                "https://www.coursera.org/learn/regression-analysis-simplify-complex-data-relationships",
                "https://www.coursera.org/learn/the-nuts- and -bolts-of-machine-learning",
                "https://www.coursera.org/learn/google-advanced-data-analytics-capstone",
                "https://www.coursera.org/learn/accelerate-your-job-search-with-ai"
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
        "--course-urls",
        nargs="+",
        help="Manually specify individual course URLs (space-separated)"
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
    if args.course_urls:
        print(f"Courses: {len(args.course_urls)} course(s) specified")
    else:
        print(f"Certificate: {args.cert_url}")
    print(f"Output directory: {args.output_dir}")
    print("=" * 60)

    downloader = CourseraDownloader(
        email=args.email,
        download_dir=args.output_dir,
        headless=args.headless
    )

    downloader.download_certificate(args.cert_url)


if __name__ == "__main__":
    main()
