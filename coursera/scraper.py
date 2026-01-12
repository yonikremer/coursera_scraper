"""
Core scraper for downloading Coursera course materials.
"""
import time
import traceback
from pathlib import Path
from typing import List, Tuple, Optional

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)

from .auth import Authenticator
from .browser import BrowserManager
from .files import get_or_move_path, find_items
from .utils import sanitize_filename
from .extractors.reading import ReadingExtractor
from .extractors.quiz import QuizExtractor
from .extractors.video import VideoExtractor
from .extractors.lab import LabExtractor
from .extractors.common import AssetManager, extract_pdfs


class CourseraScraper:
    """Orchestrates the scraping of Coursera courses."""

    # pylint: disable=too-many-instance-attributes

    def __init__(
        self,
        download_dir: str = "coursera_downloads",
        email: Optional[str] = None,
        headless: bool = False,
        on_content_downloaded=None,
    ):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self.browser = BrowserManager(self.download_dir, headless=headless)
        self.browser.setup_driver()
        self.driver = self.browser.driver
        if not self.driver:
            raise RuntimeError("Failed to initialize browser driver.")

        self.session = requests.Session()
        self.auth = Authenticator(
            self.driver, self.session, email or "", self.download_dir
        )

        shared_assets_dir = self.download_dir / "shared_assets"
        self.asset_manager = AssetManager(shared_assets_dir, self.session, self.driver)

        # Initialize Extractors
        self.video_extractor = VideoExtractor(
            self.driver, self.download_dir, self.session
        )
        self.reading_extractor = ReadingExtractor(
            self.driver, self.session, self.asset_manager
        )
        self.quiz_extractor = QuizExtractor(
            self.driver, self.session, self.asset_manager
        )
        self.lab_extractor = LabExtractor(
            self.driver, self.download_dir, shared_assets_dir
        )

        self.on_content_downloaded = on_content_downloaded

    def shutdown(self):
        """Close the browser and session."""
        self.browser.quit()
        self.session.close()

    def get_course_content(self, course_url: str) -> int:
        """Main method to download an entire course."""
        print(f"\n{'=' * 60}\n🚀 PROCESSING COURSE: {course_url}\n{'=' * 60}")

        self.auth.login_with_persistence()
        self._handle_auto_enroll(course_url)

        course_slug = course_url.split("/")[-1]
        course_dir = self.download_dir / sanitize_filename(course_slug)
        course_dir.mkdir(parents=True, exist_ok=True)

        total_materials = 0
        visited_urls: set[str] = set()
        downloaded_files: set[str] = set()

        module_num = 1
        while True:
            context = {
                "course_url": course_url,
                "module_num": module_num,
                "course_dir": course_dir,
                "visited_urls": visited_urls,
                "downloaded_files": downloaded_files,
            }
            processed, dld = self._process_module(context)
            if processed == 0 and dld == 0:
                break
            total_materials += dld
            module_num += 1

        self.asset_manager.save_image_cache()
        self._generate_navigation(course_dir, visited_urls, total_materials)
        return total_materials

    def _determine_item_type(self, item_url: str) -> str:
        """Classify the item type based on URL patterns."""
        if "/lecture/" in item_url or "/video-item/" in item_url:
            return "video"
        if "/reading/" in item_url:
            return "reading"
        if "/quiz/" in item_url or "/exam/" in item_url or "/assignment/" in item_url:
            return "quiz"
        if "/ungradedLab/" in item_url or "/lab/" in item_url:
            return "lab"
        if "/supplement/" in item_url:
            return "supplement"

        print(f"  ⚠ Unrecognized item type: {item_url}")
        return "other"

    def _get_item_title(self, item_url: str) -> str:
        """Extract the item title from the page."""
        try:
            selectors = ["h1", "h2", "[data-test='item-title']", ".item-title"]
            if self.driver:
                for sel in selectors:
                    try:
                        title_elem = self.driver.find_element(By.CSS_SELECTOR, sel)
                        if title_elem.text.strip():
                            return sanitize_filename(title_elem.text.strip())
                    except NoSuchElementException:
                        continue
        except WebDriverException:
            pass

        # Fallback to URL
        try:
            clean_url = item_url.split("?")[0].rstrip("/")
            parts = clean_url.split("/")
            return sanitize_filename(parts[-1] if parts[-1] else "Untitled")
        except (IndexError, AttributeError):
            return "Untitled"

    def _process_course_item(self, context: dict) -> int:
        """Process a single course item and download its materials."""
        item_url = context["item_url"]
        item_type = self._determine_item_type(item_url)
        context["item_type"] = item_type

        if self._handle_existing_items(context):
            return 0

        print(f"\n  [{context['item_counter']}] Navigating to item...")
        if self.driver:
            self.driver.get(item_url)
        self._wait_for_item_content()

        title = self._get_item_title(item_url)
        print(f"  📄 Item {context['item_counter']}: {title} ({item_type})")
        context["title"] = title
        context["browser_manager"] = self.browser

        materials_downloaded = self._execute_extractor(context)

        # Process PDFs
        context["driver"] = self.driver
        context["session"] = self.session
        _, pdf_count = extract_pdfs(context)
        materials_downloaded += pdf_count

        if materials_downloaded == 0 and item_type not in ["quiz", "assignment", "lab"]:
            print("  ℹ No downloadable materials found")

        return materials_downloaded

    def _execute_extractor(self, context: dict) -> int:
        """Dispatch to the appropriate extractor."""
        item_type = context["item_type"]
        materials_downloaded = 0

        if item_type == "video":
            _, count, new_files = self.video_extractor.process(context)
            materials_downloaded += count
            self._notify_new_files(new_files)
        elif item_type == "reading":
            _, count, new_files = self.reading_extractor.process(context)
            materials_downloaded += count
            self._notify_new_files(new_files)
        elif item_type in ["quiz", "assignment"]:
            _, count = self.quiz_extractor.process(context)
            materials_downloaded += count
        elif item_type == "lab":
            _, count = self.lab_extractor.process(context)
            materials_downloaded += count

        return materials_downloaded

    def _notify_new_files(self, new_files):
        """Trigger external callback for new downloads."""
        if self.on_content_downloaded:
            for path, type_ in new_files:
                self.on_content_downloaded(path, type_)

    def _handle_existing_items(self, context: dict) -> bool:
        """Helper to find and register existing items."""
        existing = [
            i
            for i in find_items(
                context["course_dir"], context["module_dir"], context["item_url"]
            )
            if i.parent.resolve() == context["module_dir"].resolve()
        ]
        if not existing:
            return False

        print(
            f"\n  [{context['item_counter']}] ✓ Item materials already exist, skipping navigation"
        )
        for item in existing:
            if (
                len(item.name) > 4
                and item.name[3] == "_"
                and not item.name.startswith(f"{context['item_counter']:03d}_")
            ):
                target = f"{context['item_counter']:03d}_{item.name[4:]}"
                item_file = get_or_move_path(
                    context["course_dir"], context["module_dir"], target
                )
            else:
                item_file = get_or_move_path(
                    context["course_dir"], context["module_dir"], item.name
                )
            context["downloaded_files"].add(str(item_file))
        return True

    def _wait_for_item_content(self):
        """Wait for various possible content markers."""
        try:
            xp = (
                "//main | //div[@role='main'] | //article | //div[@id='TUNNELVISIONWRAPPER_CONTENT_ID'] | "
                "//video | //div[@class='rc-VideoItem'] | //div[contains(@class, 'rc-FormPartsQuestion')] | "
                "//div[contains(@class, 'rc-CMLOrHTML')] | //div[contains(@class, 'rc-CML')] | "
                "//div[contains(@class, 'ItemHeader')] | //div[contains(@class, 'rc-AssignmentPage')] | //h1 | //h2"
            )
            if self.driver:
                WebDriverWait(self.driver, 30).until(
                    EC.presence_of_element_located((By.XPATH, xp))
                )
                time.sleep(2)
        except (TimeoutException, WebDriverException):
            pass

    def _process_module(self, context: dict) -> Tuple[int, int]:
        """Process a single module."""
        course_url = context["course_url"]
        module_num = context["module_num"]
        module_url = f"{course_url}/home/module/{module_num}"
        print(f"\n{'─' * 60}\n📂 Checking Module {module_num}\n{'-' * 60}")

        if self.driver:
            self.driver.get(module_url)
            time.sleep(3)
            self._check_module_url_mismatch(course_url, module_num)

        self._wait_for_module_content(module_num)
        item_links = self._extract_module_items()
        print(f"  Found {len(item_links)} items in module {module_num}")

        if not item_links:
            return 0, 0

        module_dir = context["course_dir"] / f"module_{module_num}"
        items_processed = 0
        materials_downloaded = 0

        for idx, item_url in enumerate(item_links, 1):
            if item_url in context["visited_urls"]:
                print(f"\n  [{idx}/{len(item_links)}] ⏭ Already processed, skipping...")
                continue

            context["visited_urls"].add(item_url)
            items_processed += 1
            item_ctx = {
                "item_url": item_url,
                "course_dir": context["course_dir"],
                "module_dir": module_dir,
                "item_counter": len(context["visited_urls"]),
                "downloaded_files": context["downloaded_files"],
            }
            materials_downloaded += self._process_course_item(item_ctx)

        return items_processed, materials_downloaded

    def _check_module_url_mismatch(self, course_url: str, module_num: int):
        """Handle URL redirection logic for modules/weeks."""
        if self.driver and f"module/{module_num}" not in self.driver.current_url:
            week_url = f"{course_url}/home/week/{module_num}"
            print(f"  ℹ URL mismatch, trying: {week_url}")
            self.driver.get(week_url)
            time.sleep(3)

    def _handle_auto_enroll(self, _course_url: str):
        """Check for and handle the 'Enroll' button if present."""
        sels = [
            "//button[@data-e2e='enroll-button']",
            "//button[contains(., 'Enroll')]",
            "//a[contains(@href, 'action=enroll')]",
        ]
        if not self.driver:
            return
        for sel in sels:
            try:
                btns = [
                    b
                    for b in self.driver.find_elements(By.XPATH, sel)
                    if b.is_displayed()
                ]
                if btns:
                    btns[0].click()
                    time.sleep(5)
                    break
            except WebDriverException:
                continue

    def _wait_for_module_content(self, module_num: int):
        """Wait for module items to be visible."""
        try:
            if self.driver:
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "rc-ModuleItem"))
                )
        except (TimeoutException, WebDriverException):
            print(f"  ⚠ Timeout waiting for items in module {module_num}")

    def _extract_module_items(self) -> List[str]:
        """Extract all item URLs from the module page."""
        item_links = []
        if not self.driver:
            return item_links
        try:
            items = self.driver.find_elements(By.CLASS_NAME, "rc-ModuleItem")
            for item in items:
                try:
                    link_elem = item.find_element(By.TAG_NAME, "a")
                    href = link_elem.get_attribute("href")
                    if href and "/learn/" in href:
                        item_links.append(href)
                except NoSuchElementException:
                    continue
        except WebDriverException:
            pass
        return item_links

    def _generate_navigation(self, course_dir, visited_urls, total_materials):
        """Generate offline navigation page."""
        try:
            print("\n  Generating offline navigation...")
            # pylint: disable=import-outside-toplevel
            from create_course_navigator import generate_course_navigation

            generate_course_navigation(course_dir)
        except (RuntimeError, WebDriverException, ImportError) as e:
            print(f"  ⚠ Failed to generate navigation: {e}")

        print(
            f"\n{'=' * 60}\n  Course complete!\n  Items processed: {len(visited_urls)}"
        )
        print(f"  Materials downloaded: {total_materials}\n{'-' * 60}")

    def download_certificate(
        self, cert_url: Optional[str] = None, courses: Optional[List[str]] = None
    ):
        """Download all courses from a professional certificate or list."""
        if cert_url:
            # Placeholder for cert_url usage
            pass
        try:
            self.auth.login_with_persistence()
            if not courses:
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
                print(f"\n\n{'#' * 60}\nCourse {i}/{len(courses)}\n{'-' * 60}")
                total_materials += self.get_course_content(course_url)

            print(f"\n\n{'=' * 60}\n  DOWNLOAD COMPLETE\n{'-' * 60}")
            print(f"Total materials downloaded: {total_materials}")
            print(f"Download directory: {self.download_dir.absolute()}")

        except KeyboardInterrupt:
            print(
                f"\n\n  Download interrupted by user.\nPartial downloads saved in: {self.download_dir.absolute()}"
            )
        except (RuntimeError, WebDriverException) as e:
            print(f"\n\n  CRITICAL ERROR during download: {e}")
            traceback.print_exc()
            raise e
        finally:
            self.shutdown()
