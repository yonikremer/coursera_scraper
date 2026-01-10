import time
import requests
import warnings
from pathlib import Path
from typing import Set, Tuple, List
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
)

from .auth import Authenticator
from .browser import BrowserManager
from .files import cleanup_stale_modules, find_items, get_or_move_path
from .utils import extract_slug, sanitize_filename
from .extractors.common import AssetManager, extract_pdfs
from .extractors.video import VideoExtractor
from .extractors.reading import ReadingExtractor
from .extractors.quiz import QuizExtractor
from .extractors.lab import LabExtractor


class CourseraScraper:
    """Download materials from Coursera courses."""

    def __init__(
        self,
        email: str,
        download_dir: str = "coursera_downloads",
        headless: bool = False,
    ):
        self.email = email
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)

        # Global shared assets for all courses.
        self.shared_assets_dir = self.download_dir / "shared_assets"

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Encoding": "gzip, deflate, br",
            }
        )

        # Initialize components
        self.browser = BrowserManager(self.download_dir, headless)
        self.browser.setup_driver()
        self.driver = self.browser.driver

        self.auth = Authenticator(
            self.driver, self.session, self.email, self.download_dir
        )
        self.asset_manager = AssetManager(
            self.shared_assets_dir, self.session, self.driver
        )

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
            self.driver, self.download_dir, self.shared_assets_dir
        )

    def shutdown(self):
        """Cleanup resources."""
        self.asset_manager.save_image_cache()
        if self.browser:
            print("\nClosing browser...")
            self.browser.quit()

    def _wait_for_module_content(self, module_num: int):
        """Wait for module content to load."""
        print(f"  Waiting for module {module_num} content to load...")
        try:
            # Look for either the item list or a message saying no items
            WebDriverWait(self.driver, 45).until(
                lambda d: d.find_elements(
                    By.XPATH, "//ul[@data-testid='named-item-list-list']//a"
                )
                or "No items found" in d.page_source
            )
            print(f"  ✓ Module {module_num} content loaded")
            time.sleep(2)
        except TimeoutException:
            print(f"  ⚠ Timeout waiting for module {module_num} content to load")

    def _extract_module_items(self) -> List[str]:
        """Extract all item links from the current module page."""
        link_elements = self.driver.find_elements(
            By.XPATH,
            "//ul[@data-testid='named-item-list-list']//a[contains(@href, '/lecture/') or "
            + "contains(@href, '/supplement/') or contains(@href, '/quiz/') or "
            + "contains(@href, '/exam/') or contains(@href, '/assignment/') or "
            + "contains(@href, '/assignment-submission/') or "
            + "contains(@href, '/programming/') or contains(@href, '/ungradedLab/') or "
            + "contains(@href, '/gradedLab/')]",
        )

        item_links = []
        for elem in link_elements:
            href = elem.get_attribute("href")
            if href and href not in item_links:
                item_links.append(href)

        return item_links

    @staticmethod
    def _determine_item_type(item_url: str) -> str:
        """Determine the type of the course item from its URL."""
        if "/lecture/" in item_url:
            return "video"
        elif "/supplement/" in item_url:
            return "reading"
        elif "/quiz/" in item_url or "/exam/" in item_url:
            return "quiz"
        elif (
            "/assignment/" in item_url
            or "/programming/" in item_url
            or "/assignment-submission/" in item_url
        ):
            return "assignment"
        elif "/ungradedLab/" in item_url or "/gradedLab/" in item_url:
            return "lab"
        else:
            warnings.warn(f"Unrecognized item type: {item_url}")
            return "other"

    def _get_item_title(self, item_url: str) -> str:
        """Extract the item title from the page."""
        title = "Untitled"
        try:
            for title_selector in [
                "h1",
                "h2",
                "[data-test='item-title']",
                ".item-title",
            ]:
                try:
                    title_elem = self.driver.find_element(
                        By.CSS_SELECTOR, title_selector
                    )
                    if title_elem.text.strip():
                        title = sanitize_filename(title_elem.text.strip())
                        break
                except NoSuchElementException:
                    continue
        except WebDriverException:
            pass  # If the driver fails, fall back to URL parsing.

        if title == "Untitled" and item_url:
            # Fallback to extracting from URL.
            try:
                # Remove query params and extract the last path segment.
                clean_url = item_url.split("?")[0]
                if "/" in clean_url:
                    parts = clean_url.split("/")
                    if parts[-1]:
                        title = parts[-1]
                    elif len(parts) > 1:
                        title = parts[-2]
            except (IndexError, AttributeError):
                pass

        return title

    def _process_course_item(
        self,
        item_url: str,
        course_dir: Path,
        module_dir: Path,
        item_counter: int,
        downloaded_files: Set[str],
    ) -> int:
        """Process a single course item and download its materials."""
        materials_downloaded = 0

        # Determine item type from URL (before navigating)
        item_type = self._determine_item_type(item_url)

        existing_items = find_items(course_dir, module_dir, item_url)

        # Check if an item already exists before navigating
        if len(existing_items) > 0:
            print(
                f"\n  [{item_counter}] ✓ Item materials already exist, skipping navigation"
            )

            # Check if we need to rename any found items to the correct prefix
            for item in existing_items:
                # If it has a prefix, but it's the wrong one, rename it
                if (
                    len(item.name) > 4
                    and item.name[3] == "_"
                    and not item.name.startswith(f"{item_counter:03d}_")
                ):
                    # Construct the target filename with the correct prefix
                    target_filename = f"{item_counter:03d}_{item.name[4:]}"
                    # get_or_move_path handles the actual move/rename and prefix correction
                    item_file = get_or_move_path(
                        course_dir, module_dir, target_filename
                    )
                    downloaded_files.add(str(item_file))
                else:
                    # Exact match or already corrected
                    item_file = get_or_move_path(course_dir, module_dir, item.name)
                    downloaded_files.add(str(item_file))

                materials_downloaded += 1
            return 0  # Return 0 since we're not downloading anything new

        print(f"\n  [{item_counter}] Navigating to item...")
        self.driver.get(item_url)

        # Wait for content to load
        # Look for main content or article or specialized assignment containers or video
        WebDriverWait(self.driver, 30).until(
            expected_conditions.presence_of_element_located(
                (
                    By.XPATH,
                    "//main | //div[@role='main'] | //article | //div[@id='TUNNELVISIONWRAPPER_CONTENT_ID'] | "
                    + "//video | //div[@class='rc-VideoItem'] | "
                    + "//div[contains(@class, 'rc-FormPartsQuestion')] | //div[contains(@class, 'rc-CMLOrHTML')] | "
                    + "//div[contains(@class, 'rc-CML')] | //div[contains(@class, 'ItemHeader')] | "
                    + "//div[contains(@class, 'rc-AssignmentPage')] | //h1 | //h2",
                )
            )
        )
        time.sleep(2)

        title = self._get_item_title(item_url)

        print(f"  📄 Item {item_counter}: {title} ({item_type})")

        downloaded_something = False

        # Process based on item type
        if item_type == "video":
            downloaded_something, count = self.video_extractor.process(
                course_dir, module_dir, item_counter, title, item_url, self.browser
            )
            materials_downloaded += count

        if item_type == "reading":
            downloaded_something, count = self.reading_extractor.process(
                course_dir, module_dir, item_counter, title, downloaded_files
            )
            materials_downloaded += count

        if item_type in ["quiz", "assignment"]:
            downloaded_something, count = self.quiz_extractor.process(
                course_dir, module_dir, item_counter, title, item_type
            )
            materials_downloaded += count

        if item_type == "lab":
            downloaded_something, count = self.lab_extractor.process(
                course_dir, module_dir, item_counter, title, item_url
            )
            materials_downloaded += count

        # Process PDFs (for all item types)
        _, pdf_count = extract_pdfs(
            self.driver,
            course_dir,
            module_dir,
            item_counter,
            downloaded_files,
            self.session,
        )
        materials_downloaded += pdf_count

        if not downloaded_something and item_type not in ["quiz", "assignment", "lab"]:
            print(f"  ℹ No downloadable materials found")

        return materials_downloaded

    def _process_module(
        self,
        course_url: str,
        course_slug: str,
        module_num: int,
        course_dir: Path,
        visited_urls: Set[str],
        downloaded_files: Set[str],
    ) -> Tuple[int, int]:
        """Process a single module and return (items_processed, materials_downloaded)."""
        module_url = f"{course_url}/home/module/{module_num}"

        print(f"\n{'─' * 60}")
        print(f"📂 Checking Module {module_num}")
        print(f"{'-' * 60}")

        self.driver.get(module_url)
        time.sleep(3)

        # Check if module exists
        if f"module/{module_num}" not in self.driver.current_url:
            # Try 'week' format if 'module' format didn't work
            week_url = f"{course_url}/home/week/{module_num}"
            print(
                f"  ℹ URL does not contain 'module/{module_num}', trying 'week/{module_num}'..."
            )
            self.driver.get(week_url)
            time.sleep(3)

            if f"week/{module_num}" not in self.driver.current_url:
                # Special handling for module/week 1:
                # Some courses redirect week/1 to 'welcome' or 'home', but the content is there.
                has_content = False
                if module_num == 1:
                    print(
                        f"  ℹ Checking for content despite URL mismatch (Current: {self.driver.current_url})..."
                    )
                    try:
                        # Quick check for items
                        items = self.driver.find_elements(
                            By.XPATH, "//ul[@data-testid='named-item-list-list']//a"
                        )
                        if items:
                            print(
                                f"  ✓ Found {len(items)} items on page, proceeding as Module 1"
                            )
                            has_content = True
                    except Exception:
                        pass

                if not has_content:
                    print(f"✓ No more modules found (attempted module {module_num})")
                    print(f"  Current URL: {self.driver.current_url}")
                    print(f"  Continuing to next course...")
                    return 0, 0
            else:
                print(f"  ✓ Found content at week/{module_num}")

        # Wait for content
        self._wait_for_module_content(module_num)

        # Extract items
        item_links = self._extract_module_items()
        print(f"  Found {len(item_links)} items in module {module_num}")

        if len(item_links) == 0:
            print(
                f"\n  ℹ No items found in module {module_num} (likely end of course)."
            )
            # Don't raise exception, just return 0 to stop the loop naturally
            return 0, 0

        # Create module directory - DEFERRED to get_or_move_path to avoid empty folders
        module_dir = course_dir / f"module_{module_num}"
        # module_dir.mkdir(exist_ok=True)

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
            materials_count = self._process_course_item(
                item_url, course_dir, module_dir, item_counter, downloaded_files
            )
            materials_downloaded += materials_count

        return items_processed, materials_downloaded

    def _handle_auto_enroll(self, course_url: str):
        """Check for and handle the 'Enroll' button if present."""
        # Look for Enroll button
        enroll_selectors = [
            "//button[@data-e2e='enroll-button']",
            "//button[contains(., 'Enroll')]",
            "//span[data-test='enroll-button-label']//ancestor::button",
            "//a[contains(@href, 'action=enroll')]",
        ]

        enroll_btn = None
        for selector in enroll_selectors:
            try:
                btns = self.driver.find_elements(By.XPATH, selector)
                for btn in btns:
                    if btn.is_displayed() and btn.is_enabled():
                        enroll_btn = btn
                        break
                if enroll_btn:
                    break
            except NoSuchElementException:
                continue

        if enroll_btn:
            print("  ℹ Enrollment required. Clicking 'Enroll' button...")
            self.driver.execute_script("arguments[0].click();", enroll_btn)
            time.sleep(5)

            # Sometimes there's a second 'Enroll' or 'Go to Course' button in a modal
            for second_btn_text in [
                "Enroll for Free",
                "Join Course",
                "Go to Course",
                "Go to course",
            ]:
                try:
                    second_btns = self.driver.find_elements(
                        By.XPATH,
                        f"//button[contains(., '{second_btn_text}')] | //a[contains(., '{second_btn_text}')]",
                    )
                    for sbtn in second_btns:
                        if sbtn.is_displayed():
                            print(f"  ✓ Clicking '{second_btn_text}'...")
                            self.driver.execute_script("arguments[0].click();", sbtn)
                            time.sleep(5)
                            break
                except Exception:
                    continue

            # If still on the same page, try navigating to the course home directly
            if (
                "learn" in self.driver.current_url
                and "/home" not in self.driver.current_url
            ):
                print("  ℹ Navigating to course home...")
                self.driver.get(f"{course_url}/home/module/1")
                time.sleep(5)

        # Also check for "Go to course" button which appears if already enrolled but not on course home
        try:
            go_to_course_btns = self.driver.find_elements(
                By.XPATH,
                "//a[contains(., 'Go to Course')] | //a[contains(., 'Go to course')]",
            )
            for btn in go_to_course_btns:
                if btn.is_displayed():
                    print("  ✓ Found 'Go to Course' button, clicking...")
                    self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(5)
                    break
        except Exception:
            pass

    def get_course_content(self, course_url: str) -> int:
        """Navigate through the course and collect all downloadable materials."""
        print(f"\n{'=' * 60}")
        course_slug = course_url.split("/learn/")[-1].split("/")[0]
        print(f"Processing course: {course_slug}")
        print(f"{'-' * 60}")

        course_dir = self.download_dir / sanitize_filename(course_slug)
        course_dir.mkdir(exist_ok=True)

        total_materials = 0
        visited_urls = set()
        downloaded_files = set()
        valid_modules = set()

        print("\nNavigating to course...")
        self.driver.get(course_url)
        time.sleep(5)

        # Handle auto-enrollment if needed
        self._handle_auto_enroll(course_url)

        # Iterate through modules
        for module_num in range(1, 21):
            items_processed, materials_downloaded = self._process_module(
                course_url,
                course_slug,
                module_num,
                course_dir,
                visited_urls,
                downloaded_files,
            )

            if items_processed > 0:
                valid_modules.add(module_num)

            total_materials += materials_downloaded
            if items_processed == 0:
                break

        # Cleanup stale modules (from previous runs or if they don't exist anymore)
        cleanup_stale_modules(course_dir, valid_modules)

        # Generate Navigation
        try:
            print("\n  Generating offline navigation...")
            # Import dynamically to avoid path issues
            import sys

            if str(Path.cwd()) not in sys.path:
                sys.path.append(str(Path.cwd()))
            from create_course_navigator import generate_course_navigation

            generate_course_navigation(course_dir)
        except Exception as e:
            print(f"  ⚠ Failed to generate navigation: {e}")

        print(f"\n{'=' * 60}")
        print("  Course complete!")
        print(f"  Items processed: {len(visited_urls)}")
        print(f"  Materials downloaded: {total_materials}")
        print(f"{'-' * 60}")

        if len(visited_urls) == 0:
            raise RuntimeError("No items found in course.")

        return total_materials

    def download_certificate(self, cert_url: str = None, courses: List[str] = None):
        """Download all courses from a professional certificate."""
        try:
            self.auth.login_with_persistence()

            if not courses:
                # Default courses list (can be made dynamic later)
                courses = [
                    # "https://www.coursera.org/learn/foundations-of-data-science",
                    "https://www.coursera.org/learn/get-started-with-python",
                    # "https://www.coursera.org/learn/go-beyond-the-numbers-translate-data-into-insight",
                    # "https://www.coursera.org/learn/the-power-of-statistics",
                    # "https://www.coursera.org/learn/regression-analysis-simplify-complex-data-relationships",
                    # "https://www.coursera.org/learn/the-nuts-and-bolts-of-machine-learning",
                    # "https://www.coursera.org/learn/google-advanced-data-analytics-capstone",
                ]

            total_materials = 0

            for i, course_url in enumerate(courses, 1):
                print(f"\n\n{'#' * 60}")
                print(f"Course {i}/{len(courses)}")
                print(f"{'-' * 60}")

                materials = self.get_course_content(course_url)
                total_materials += materials

            print(f"\n\n{'=' * 60}")
            print("  DOWNLOAD COMPLETE")
            print(f"{'-' * 60}")
            print(f"Total materials downloaded: {total_materials}")
            print(f"Download directory: {self.download_dir.absolute()}")

        except KeyboardInterrupt:
            print("\n\n  Download interrupted by user.")
            print(f"Partial downloads saved in: {self.download_dir.absolute()}")
        except Exception as e:
            print(f"\n\n  CRITICAL ERROR during download: {e}")
            import traceback

            traceback.print_exc()
            raise e
        finally:
            self.shutdown()
