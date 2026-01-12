"""
Extractor for quiz and assignment content from Coursera.
"""
import time
from pathlib import Path
from typing import Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    JavascriptException,
    WebDriverException,
)
from ..files import get_or_move_path
from .common import AssetManager
from .base import BaseExtractor


class QuizExtractor(BaseExtractor):
    """Extractor for Coursera quiz and assignment items."""

    def __init__(self, driver, session, asset_manager: AssetManager):
        super().__init__(driver)
        self.session = session
        self.asset_manager = asset_manager

    def process(self, context: dict) -> Tuple[bool, int]:
        """Process and save assignment or quiz content."""
        item_type = context["item_type"]
        print(f"  Processing {item_type}...")

        if not self._prepare_page():
            print(f"  ⚠ Could not load {item_type} content")
            return False, 0

        metadata = self._extract_metadata()
        content, image_count = self._extract_assignment_content(
            item_dir=context["module_dir"]
        )

        if content:
            css_links = self.asset_manager.download_course_css(
                item_dir=context["module_dir"]
            )
            title = context["title"]
            filename = f"{context['item_counter']:03d}_{title}_{item_type}.html"
            filepath = get_or_move_path(
                context["course_dir"], context["module_dir"], filename
            )

            self._save_quiz_html(
                filepath,
                title,
                {
                    "itype": item_type,
                    "content": content,
                    "css": css_links,
                    "meta": metadata,
                },
            )
            self._click_save_draft_button()

            print(f"  ✓ {item_type.title()} content saved (with {image_count} images)")
            return True, image_count + 1

        print("  ⚠ No assignment content found to save")
        return False, 0

    def _prepare_page(self) -> bool:
        """Handle redirects and wait for content to load."""
        is_attempt = (
            "/attempt" in self.driver.current_url
            or "/assignment-submission" in self.driver.current_url
        )
        if not is_attempt or "/assignment-submission" in self.driver.current_url:
            self._click_assignment_start_button()
            time.sleep(4)

        print("  Waiting for content...")
        selectors = [
            "div#TUNNELVISIONWRAPPER_CONTENT_ID",
            "div.rc-FormPartsQuestion",
            "div.rc-CMLOrHTML",
            ".rc-AssignmentPart",
            ".rc-PracticeAssignment",
            "div[data-testid^='part-Submission']",
        ]

        def loaded(d):
            if "/attempt" in d.current_url:
                return True
            for sel in selectors:
                els = d.find_elements(By.CSS_SELECTOR, sel)
                if els and any(
                    "rc-InCourseSearchBar" not in (e.get_attribute("innerHTML") or "")
                    for e in els
                ):
                    return True
            return False

        try:
            WebDriverWait(self.driver, 45).until(loaded)
            time.sleep(5)
            return True
        except (WebDriverException, TimeoutError):
            return False

    def _extract_metadata(self) -> str:
        """Extract header metadata string."""
        try:
            sels = ["[data-testid='header-right']", ".rc-AssignmentHeader"]
            for sel in sels:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    return " • ".join(
                        [
                            e.text.strip().replace("\n", " ")
                            for e in els
                            if e.text.strip()
                        ]
                    )
        except (NoSuchElementException, StaleElementReferenceException):
            pass
        return ""

    def _click_assignment_start_button(self) -> bool:
        """Robust clicker for quiz start buttons."""
        url_before = self.driver.current_url
        self.close_continue_learning_popup()

        for _ in range(3):
            if self._is_content_visible():
                break

            # Try barriers
            if self.handle_barriers():
                continue

            # Try explicit start buttons
            if self._try_click_start_btn(url_before):
                continue
            break
        return True

    def _is_content_visible(self) -> bool:
        """Check if quiz content is already visible."""
        selectors = [
            "div.rc-FormPartsQuestion",
            "div.rc-CMLOrHTML",
            ".rc-AssignmentPart",
        ]
        return any(self.driver.find_elements(By.CSS_SELECTOR, s) for s in selectors)

    def _try_click_start_btn(self, url_before: str) -> bool:
        """Look for and click start/resume buttons."""
        # Check standard testid
        cover_btns = self.driver.find_elements(
            By.CSS_SELECTOR, "[data-testid='CoverPageActionButton']"
        )
        for btn in cover_btns:
            if self._safe_and_click(btn, url_before):
                return True

        # Text based
        for txt in ["Start", "Resume"]:
            xpath = f"//button[contains(translate(., 'ABC', 'abc'), '{txt.lower()}')]"
            btns = self.driver.find_elements(By.XPATH, xpath)
            for btn in btns:
                if self._safe_and_click(btn, url_before):
                    return True
        return False

    def _safe_and_click(self, btn, url_before: str) -> bool:
        """Check safety and click with rollback support."""
        if not btn.is_displayed() or not btn.is_enabled():
            return False
        if not self._is_btn_safe(btn):
            return False

        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", btn
            )
            time.sleep(1)
            self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(2)

            # Rollback if redirected away
            curr = self.driver.current_url
            if "/home/" in curr or (
                "/learn/" in curr
                and not any(x in curr for x in ["/assignment", "/quiz", "/attempt"])
            ):
                self.driver.get(url_before)
                time.sleep(3)
                return False
            return True
        except WebDriverException:
            return False

    def _is_btn_safe(self, btn) -> bool:
        """Verify button isn't a navigation arrow."""
        try:
            txt = btn.text.lower()
            if "next item" in txt or "continue learning" in txt:
                return False
            aria = (btn.get_attribute("aria-label") or "").lower()
            if "next item" in aria:
                return False

            # Check for navigation container
            nav = btn.find_elements(
                By.XPATH, "./ancestor::div[contains(@class, 'rc-ItemNavigation')]"
            )
            return len(nav) == 0
        except WebDriverException:
            return False

    def _extract_assignment_content(self, item_dir: Path) -> Tuple[str, int]:
        """Extract combined HTML and localize images."""
        downloaded = 0
        self._cleanup_messy_elements()

        selectors = [
            "div#TUNNELVISIONWRAPPER_CONTENT_ID",
            "div.rc-FormPartsQuestion",
            "div.rc-CMLOrHTML",
        ]
        content = ""
        for sel in selectors:
            try:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    inner = el.get_attribute("innerHTML") or ""
                    if "rc-InCourseSearchBar" in inner and len(inner) < 2000:
                        continue

                    downloaded += self.asset_manager.localize_images(
                        el, item_dir=item_dir
                    )
                    html = el.get_attribute("outerHTML")
                    if html and len(html) > 100:
                        content += html + "\n<br>\n"
            except (NoSuchElementException, StaleElementReferenceException):
                continue
        return content, downloaded

    def _cleanup_messy_elements(self):
        """Remove UI noise via JS."""
        try:
            self.driver.execute_script(
                """
                const selectors = [
                    '[data-test="rc-InCourseSearchBar"]', '[data-ai-instructions="true"]',
                    '[data-testid="like-button"]', '[data-testid="dislike-button"]',
                    '[data-testid="part-points"]', '[data-e2e="AttemptSubmitControls"]',
                    '[aria-label="Text Formatting"]', '.rc-ReportProblem', '.rc-A11yScreenReaderOnly'
                ];
                selectors.forEach(s => document.querySelectorAll(s).forEach(el => {
                    if (s.includes('SearchBar')) el.closest('form')?.remove() || el.remove();
                    else el.remove();
                }));
            """
            )
        except JavascriptException:
            pass

    def _save_quiz_html(self, path, title, data):
        """Write the HTML file."""
        display_title = title.replace("_", " ").title()
        meta_html = f"<span><strong>Type:</strong> {data['itype'].title()}</span>"
        if data["meta"]:
            meta_html += f" | <span><strong>Info:</strong> {data['meta']}</span>"

        extra_css = """
        *, *::before, *::after { user-select: none !important; outline: none !important; }
        .rc-Option .rc-CML, .rc-Option p { pointer-events: none !important; }
        [data-testid^="part-Submission"], .rc-FormPartsQuestion {
            margin-bottom: 40px; padding: 25px; border: 1px solid #e1e4e8; border-radius: 12px; background: #fff;
        }
        .rc-Option { margin: 12px 0; border: 1px solid #edeff1; border-radius: 8px; background: #fafbfc; }
        .rc-Option label { display: flex !important; align-items: center !important; padding: 15px; gap: 15px; margin: 0 !important; cursor: pointer; }
        input[type="radio"], input[type="checkbox"] { position: absolute; opacity: 0; }
        .rc-Option:has(input:checked) { border-color: #0056d2; background: #f0f7ff; }
        """

        html = self.wrap_html(
            display_title,
            data["content"],
            {"css": data["css"], "meta": meta_html, "extra_style": extra_css},
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

    def _click_save_draft_button(self):
        """Click 'Save draft' to prevent exit popups."""
        try:
            xpath = "//button[contains(translate(., 'S', 's'), 'save draft')]"
            btn = self.driver.find_element(By.XPATH, xpath)
            if btn.is_displayed():
                btn.click()
                time.sleep(2)
        except NoSuchElementException:
            pass
        except WebDriverException:
            pass
