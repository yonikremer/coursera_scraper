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
    ElementClickInterceptedException,
)
from ..files import get_or_move_path
from .common import AssetManager


class QuizExtractor:
    def __init__(self, driver, session, asset_manager: AssetManager):
        self.driver = driver
        self.session = session
        self.asset_manager = asset_manager

    def process(
        self,
        course_dir: Path,
        module_dir: Path,
        item_counter: int,
        title: str,
        item_type: str,
    ) -> Tuple[bool, int]:
        """Process and save assignment or quiz content."""
        downloaded_count = 0
        downloaded_something = False

        print(f"  Processing {item_type}...")

        # If it's an assignment-submission or not yet on attempt page, try to click start
        # Special case for 'assignment-submission' as requested: it often has a start button
        # that doesn't change the URL.
        is_attempt_page = (
            "/attempt" in self.driver.current_url
            or "/assignment-submission" in self.driver.current_url
        )

        # Try clicking start button if we're not on a known attempt page,
        # or if we are on a submission page that might need a click to show the actual assignment.
        if not is_attempt_page or "/assignment-submission" in self.driver.current_url:
            if self._click_assignment_start_button():
                time.sleep(4)
            elif not is_attempt_page:
                print("  ℹ Already on assignment page or no start button found")

        # Wait for content to load
        print(f"  Waiting for {item_type} content...")
        # We want to wait for actual quiz elements, NOT just any form (which might be a search bar)
        # We also check that the search bar is NOT the ONLY thing present if it's there.
        quiz_selectors = [
            "div#TUNNELVISIONWRAPPER_CONTENT_ID",
            "div.rc-FormPartsQuestion",
            "div.rc-CMLOrHTML",
            ".rc-AssignmentPart",
            ".rc-PracticeAssignment",
            "div[data-testid^='part-Submission']",
        ]

        def content_loaded(d):
            if "/attempt" in d.current_url:
                return True
            for sel in quiz_selectors:
                elements = d.find_elements(By.CSS_SELECTOR, sel)
                if elements:
                    # Verify at least one element is NOT a search bar container
                    for el in elements:
                        if "rc-InCourseSearchBar" not in el.get_attribute("innerHTML"):
                            return True
            return False

        WebDriverWait(self.driver, 45).until(content_loaded)
        time.sleep(5)  # Give it plenty of time for mathjax/images

        print(f"  Current URL: {self.driver.current_url}")

        # Extract additional metadata (like due date, weight, etc.).
        metadata = ""
        try:
            # Look for header info in modern view.
            header_info = self.driver.find_elements(
                By.CSS_SELECTOR, "[data-testid='header-right'], .rc-AssignmentHeader"
            )
            if header_info:
                metadata = " • ".join(
                    [
                        el.text.strip().replace("\n", " ")
                        for el in header_info
                        if el.text.strip()
                    ]
                )
        except (NoSuchElementException, StaleElementReferenceException):
            pass  # Metadata extraction is optional.

        # Extract assignment content.
        assignment_content, image_count = self._extract_assignment_content(
            item_dir=module_dir
        )
        downloaded_count += image_count

        if assignment_content:
            # Download CSS.
            css_links_html = self.asset_manager.download_course_css(item_dir=module_dir)

            filename = f"{item_counter:03d}_{title}_{item_type}.html"
            assignment_file = get_or_move_path(course_dir, module_dir, filename)

            # Save to HTML file.
            self._save_assignment_html(
                assignment_file,
                title,
                item_type,
                assignment_content,
                css_links_html,
                metadata,
            )

            downloaded_count += 1
            downloaded_something = True
            print(f"  ✓ {item_type.title()} content saved (with {image_count} images)")

            # Try to click 'Save draft' button to avoid annoying popups on exit.
            self._click_save_draft_button()
        else:
            print("  ⚠ No assignment content found to save")

        return downloaded_something, downloaded_count

    def _click_assignment_start_button(self) -> bool:
        """Click the start/resume button for an assignment or quiz, handling multiple popups."""
        clicked_any = False
        url_before_click = self.driver.current_url

        quiz_selectors = [
            "div#TUNNELVISIONWRAPPER_CONTENT_ID",
            "div.rc-FormPartsQuestion",
            "div.rc-CMLOrHTML",
            ".rc-AssignmentPart",
            ".rc-PracticeAssignment",
            "div[data-testid^='part-Submission']",
        ]

        def is_quiz_loaded():
            for sel in quiz_selectors:
                if self.driver.find_elements(By.CSS_SELECTOR, sel):
                    return True
            return False

        def is_safe_to_click(element) -> bool:
            """Check if the button is safe to click (not a navigation button)."""
            try:
                # Check 1: Check attributes directly
                classes = element.get_attribute("class") or ""
                test_id = element.get_attribute("data-testid") or ""
                aria_label = element.get_attribute("aria-label") or ""
                text_content = element.text.lower()

                # Navigation buttons to avoid
                if (
                    "ItemNavigation" in classes
                    or "next-item" in test_id
                    or "prev-item" in test_id
                ):
                    return False

                # specific check for the "Next" arrow button which sometimes has "Next" text hidden
                if "next item" in aria_label.lower():
                    return False

                # Exclude specific text that indicates navigation or unwanted popups
                if "continue learning" in text_content:
                    return False
                if "next item" in text_content:
                    return False

                # Check 2: Check parents for navigation containers
                # We can do this by checking if it's inside a known navigation footer
                parent_nav = element.find_elements(
                    By.XPATH,
                    "./ancestor::div[contains(@class, 'course-item-navigation-footer')] | ./ancestor::div[contains(@class, 'rc-ItemNavigation')]",
                )
                if parent_nav:
                    return False

                return True
            except Exception:
                return False

        def click_and_validate(btn, label) -> bool:
            """Click a button and verify we didn't get redirected away from the quiz context."""
            try:
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", btn
                )
                time.sleep(1)
                self.driver.execute_script("arguments[0].click();", btn)
                print(f"  ✓ Clicked {label}")

                time.sleep(2)

                # Check URL
                current_url = self.driver.current_url

                # Permitted paths for staying in context
                valid_paths = ["/assignment", "/quiz", "/exam", "/attempt"]

                is_wrong_item = "/learn/" in current_url and not any(
                    x in current_url for x in valid_paths
                )

                # If we went to home or a lecture/reading (which don't have the valid_paths), go back.
                if "/home/" in current_url or "/home?" in current_url or is_wrong_item:
                    print(
                        f"  ℹ Redirected away (to {current_url}), returning to: {url_before_click}"
                    )
                    self.driver.get(url_before_click)
                    time.sleep(3)
                    return False

                return True
            except Exception as e:
                print(f"  ⚠ Error clicking validation: {e}")
                return False

        # We try multiple rounds to handle consecutive popups (e.g. Continue -> Start)
        for round in range(3):
            if is_quiz_loaded():
                break

            found_in_round = False

            # 0. Handle "Continue Learning" specifically by closing it if possible.
            # This popup often appears when revisiting content; clicking the main button skips to the next item.
            try:
                # Look for a modal or dialog containing "Continue Learning"
                # We use a broad search for the text within a dialog/modal container
                cl_popups = self.driver.find_elements(
                    By.XPATH,
                    "//div[@role='dialog'][.//*[contains(text(), 'Continue Learning')]] | "
                    + "//div[contains(@class, 'modal')][.//*[contains(text(), 'Continue Learning')]]",
                )

                if not cl_popups:
                    # Fallback: check if the button itself exists, maybe find its parent modal
                    cl_btns = self.driver.find_elements(
                        By.XPATH, "//button[contains(., 'Continue Learning')]"
                    )
                    if cl_btns and any(b.is_displayed() for b in cl_btns):
                        # If we see the button, try to close ANY visible modal
                        cl_popups = self.driver.find_elements(
                            By.XPATH,
                            "//div[@role='dialog'] | //div[contains(@class, 'modal')]",
                        )

                for popup in cl_popups:
                    if popup.is_displayed():
                        # Try to find a close button inside this popup
                        close_selectors = [
                            ".//button[@aria-label='Close']",
                            ".//button[@aria-label='close']",
                            ".//button[contains(@class, 'close')]",
                            ".//button[contains(@class, 'Close')]",
                            ".//svg[contains(@data-test-icon, 'close')]/ancestor::button",
                            ".//span[contains(@class, 'cui-icon')][contains(., 'close')]/ancestor::button",
                        ]
                        closed = False
                        for sel in close_selectors:
                            close_btns = popup.find_elements(By.XPATH, sel)
                            for c_btn in close_btns:
                                if c_btn.is_displayed():
                                    print(
                                        "  ℹ Found 'Continue Learning' popup, attempting to close..."
                                    )
                                    self.driver.execute_script(
                                        "arguments[0].click();", c_btn
                                    )
                                    print("  ✓ Closed 'Continue Learning' popup")
                                    time.sleep(2)
                                    closed = True
                                    break
                            if closed:
                                break
                        if closed:
                            break
            except Exception:
                pass

            # 1. Check for Barrier buttons (Honor Code, Agreements, Continue)
            # REMOVED "Continue" from this list as it is too ambiguous and often hits pagination
            barriers = ["I agree", "Agree", "Accept", "Confirm", "I understand"]
            for b_text in barriers:
                try:
                    xpath = f"//button[contains(., '{b_text}')] | //a[contains(., '{b_text}')] | //span[text()='{b_text}']/ancestor::button"
                    # Initial find to get count
                    potential_btns = self.driver.find_elements(By.XPATH, xpath)
                    count = len(potential_btns)

                    for i in range(count):
                        # Re-find elements to avoid StaleElementReferenceException if a previous click triggered a rollback
                        current_btns = self.driver.find_elements(By.XPATH, xpath)
                        if i >= len(current_btns):
                            break

                        btn = current_btns[i]
                        if btn.is_displayed() and btn.is_enabled():
                            if is_safe_to_click(btn):
                                if "rc-InCourseSearchBar" in btn.get_attribute(
                                    "outerHTML"
                                ):
                                    continue

                                # If validation fails (rollback), loop continues to i+1
                                if click_and_validate(btn, f"barrier: '{b_text}'"):
                                    clicked_any = True
                                    found_in_round = True
                                    break

                    if found_in_round:
                        break
                except Exception:
                    continue

                # Fallback purely for "Continue" button but with strict safety checks
                # matching only exact "Continue" or "Continue" inside a modal-like structure
                if not found_in_round:
                    try:
                        actions = self.driver.find_elements(
                            By.XPATH, "//button[contains(., 'Continue')]"
                        )
                        count = len(actions)

                        for i in range(count):
                            # Re-find elements
                            current_actions = self.driver.find_elements(
                                By.XPATH, "//button[contains(., 'Continue')]"
                            )
                            if i >= len(current_actions):
                                break

                            btn = current_actions[i]
                            if (
                                btn.is_displayed()
                                and btn.is_enabled()
                                and is_safe_to_click(btn)
                            ):
                                # Double check it's NOT a next item button (sometimes text is just Continue)
                                # We prefer buttons inside dialogs or main content
                                parents = btn.find_elements(
                                    By.XPATH,
                                    "./ancestor::div[@role='dialog'] | ./ancestor::div[contains(@class,'modal')]",
                                )
                                is_modal = len(parents) > 0

                                if is_modal or "Continue" == btn.text.strip():
                                    if click_and_validate(btn, "'Continue'"):
                                        clicked_any = True
                                        found_in_round = True
                                        break
                    except Exception:
                        pass

            # 2. Check for actual Start/Resume buttons if no barrier was clicked or if still not loaded
            if not is_quiz_loaded():
                button_texts = [
                    "Start",
                    "Resume",
                ]
                for btn_text in button_texts:
                    xpath = f"//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{btn_text.lower()}')] | //a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{btn_text.lower()}')]"

                    try:
                        potential_btns = self.driver.find_elements(By.XPATH, xpath)
                        count = len(potential_btns)

                        for i in range(count):
                            # Re-find to handle stale elements after rollback
                            current_btns = self.driver.find_elements(By.XPATH, xpath)
                            if i >= len(current_btns):
                                break

                            btn = current_btns[i]
                            if btn.is_displayed() and btn.is_enabled():
                                if is_safe_to_click(btn):
                                    btn_label = btn.text.strip() or btn_text

                                    if click_and_validate(btn, f"start: '{btn_label}'"):
                                        clicked_any = True
                                        found_in_round = True
                                        break
                    except Exception:
                        pass

                    if found_in_round:
                        break

            print("quiz is loaded, done")
            if not found_in_round:
                break

        return clicked_any

    def _extract_assignment_content(self, item_dir: Path = None) -> Tuple[str, int]:
        """Extract the HTML content of the assignment."""
        downloaded_count = 0
        selectors = [
            "div#TUNNELVISIONWRAPPER_CONTENT_ID",
            "div.rc-FormPartsQuestion",
            "div.rc-CMLOrHTML",
            "div[data-testid^='part-Submission']",
            ".rc-AssignmentPart",
            ".rc-PracticeAssignment",
            "form:not([data-test='rc-InCourseSearchBar'])",
            "div[role='main']",
            "main",
        ]

        # Try to remove any AI instructions if they are present before extracting.
        try:
            self.driver.execute_script("""
                // Remove search bars that sometimes appear instead of content
                const searchBars = document.querySelectorAll('[data-test="rc-InCourseSearchBar"]');
                searchBars.forEach(el => {
                    // Only remove if it's not the ONLY thing, but actually we probably never want it in the saved HTML
                    el.closest('form')?.remove() || el.remove();
                });

                // Remove AI instructions and integrity blocks
                const aiInstructions = document.querySelectorAll('[data-ai-instructions="true"], [data-testid="content-integrity-instructions"]');
                aiInstructions.forEach(el => el.remove());

                // Remove messy quiz footer elements (Like/Dislike, Honor Code, Submit, Save Draft, points)
                const messySelectors = [
                    '[data-testid="like-button"]',
                    '[data-testid="dislike-button"]',
                    '[data-testid="part-points"]',
                    '[data-testid="visually-hidden"]',
                    '[data-e2e="AttemptSubmitControls"]',
                    '[aria-label="Text Formatting"]',
                    '[data-testid="report-problem-button"]',
                    '[data-testid="flag-content-button"]',
                    '.rc-ReportProblem',
                    '.rc-A11yScreenReaderOnly'
                ];
                messySelectors.forEach(selector => {
                    document.querySelectorAll(selector).forEach(el => el.remove());
                });
            """)
        except JavascriptException:
            pass  # Script failure is non-critical.

        for selector in selectors:
            try:
                # Find all matching elements and combine them if there are multiple (like questions).
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    content = ""
                    for elem in elements:
                        try:
                            inner_html = elem.get_attribute("innerHTML")
                            # Skip if this element is JUST a search bar
                            if (
                                "rc-InCourseSearchBar" in inner_html
                                and len(inner_html) < 2000
                            ):
                                continue

                            # Localize images.
                            downloaded_count += self.asset_manager.localize_images(
                                elem, item_dir=item_dir
                            )

                            html = elem.get_attribute("outerHTML")
                            if html and len(html) > 100:
                                content += html + "\n<br>\n"
                        except StaleElementReferenceException:
                            continue
                    if content:
                        return content, downloaded_count
            except (NoSuchElementException, StaleElementReferenceException):
                continue
            except WebDriverException as e:
                print(
                    f"  ⚠ Browser error extracting content with selector '{selector}': {e}"
                )
                continue
        return "", 0

    def _save_assignment_html(
        self,
        filepath: Path,
        title: str,
        item_type: str,
        content: str,
        css_links_html: str = "",
        metadata: str = "",
    ):
        """Save assignment content to an HTML file."""
        # Format title: replace underscores with spaces and title case
        display_title = title.replace("_", " ").title()

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{display_title}</title>
{css_links_html}
    <style>
        *, *::before, *::after {{
            user-select: none !important;
            -webkit-user-select: none !important;
            -moz-user-select: none !important;
            -ms-user-select: none !important;
            outline: none !important;
            -webkit-tap-highlight-color: transparent !important;
        }}
        
        *::selection {{
            background-color: transparent !important;
            color: inherit !important;
            text-shadow: none !important;
        }}
        
        *::-moz-selection {{
            background-color: transparent !important;
            color: inherit !important;
            text-shadow: none !important;
        }}

        /* Make text containers pass-through clicks to parent label to prevent selection while keeping clicks functional */
        .rc-Option .rc-CML, 
        .rc-Option ._bc4egv,
        .rc-Option [data-testid="cml-viewer"],
        .rc-Option p {{
            pointer-events: none !important;
        }}

        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; 
            max-width: 900px; 
            margin: 0 auto; 
            padding: 40px 20px; 
            line-height: 1.6; 
            color: #333; 
            background: #f5f7f9; 
            -webkit-touch-callout: none !important;
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
        
        /* Question Blocks */
        [data-testid^="part-Submission"], .rc-FormPartsQuestion, .rc-AssignmentPart {{
            margin-bottom: 40px;
            padding: 25px;
            background: #fff;
            border: 1px solid #e1e4e8;
            border-radius: 12px;
            transition: transform 0.2s;
        }}
        [data-testid^="part-Submission"]:hover {{ border-color: #0056d2; }}
        
        /* Question Alignment Fix */
        .css-x3q7o9 {{ display: flex !important; align-items: flex-start !important; gap: 10px !important; }}
        .css-lyseg0 {{ 
            display: flex !important; 
            align-items: center !important; 
            white-space: nowrap !important; 
            margin-top: 2px !important; 
        }}
        .css-ybrhvy {{ flex: 1 !important; }}
        .css-6ecy9b {{ margin: 0 !important; font-size: 1.1rem !important; }}

        /* Question Legends/Titles */
        [data-testid="legend"], .rc-FormPartsQuestion__title {{
            font-weight: 600;
            font-size: 1.1rem;
            margin-bottom: 20px;
            color: #1f1f1f;
        }}
        
        /* Options */
        .rc-Option {{ 
            margin: 12px 0; 
            position: relative; 
            border: 1px solid #edeff1;
            border-radius: 8px;
            background: #fafbfc;
            transition: all 0.2s;
        }}
        .rc-Option, .rc-Option * {{ 
            -webkit-tap-highlight-color: transparent !important;
            outline: none !important;
        }}
        .rc-Option label {{ 
            display: flex !important; 
            align-items: center !important; 
            cursor: pointer; 
            padding: 15px; 
            gap: 15px;
            margin: 0 !important;
            width: 100%;
            box-sizing: border-box;
        }}
        .rc-Option:hover {{ background: #f0f4f8; border-color: #d0d7de; }}
        
        /* Clean up Coursera's custom input icons */
        ._1e7axzp, .cui-icon, ._2y6w19 {{ 
            display: inline-flex;
            width: 20px;
            height: 20px;
            border: 2px solid #0056d2;
            border-radius: 50%;
            background: #fff;
            flex-shrink: 0;
        }}
        
        /* If it's a checkbox, make it square */
        [data-testid="part-Submission_CheckboxQuestion"] ._1e7axzp {{
            border-radius: 4px;
        }}

        /* Hide the messy SVG inside the icon span and use CSS instead when checked */
        ._1e7axzp svg {{ display: none !important; }}
        
        .rc-Option input[type="radio"], 
        .rc-Option input[type="checkbox"] {{ 
            position: absolute;
            opacity: 0;
            cursor: pointer;
        }}

        /* Highlight selected option */
        .rc-Option:has(input:checked) {{
            background-color: transparent;
            border-color: transparent;
        }}
        .rc-Option input:checked + span, 
        .rc-Option:has(input:checked) ._1e7axzp {{
            background-color: #0056d2;
            box-shadow: inset 0 0 0 4px #fff;
            border-radius: 50%;
        }}
        
        .rc-CML {{ font-size: 1rem; }}
        .rc-CML p {{ margin: 0; }}
        
        hr {{ border: 0; border-top: 1px solid #d0d7de; margin: 30px 0; }}
        a {{ color: #0056d2; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{display_title}</h1>
        <div class="meta">
            <span><strong>Type:</strong> {item_type.title()}</span>
            {f" | <span><strong>Info:</strong> {metadata}</span>" if metadata else ""}
        </div>
        <div class="assignment-content">
            {content}
        </div>
    </div>
</body>
</html>""")

    def _click_save_draft_button(self):
        """Try to click the 'Save draft' button if it exists."""
        try:
            save_btn = self.driver.find_element(
                By.XPATH,
                "//button[contains(., 'Save draft') or contains(., 'Save Draft')]",
            )
            if save_btn.is_displayed() and save_btn.is_enabled():
                save_btn.click()
                print("  ✓ Clicked 'Save draft'")
                time.sleep(2)
        except NoSuchElementException:
            # Button not found; this is expected.
            pass
        except (WebDriverException, ElementClickInterceptedException) as e:
            print(f"  ⚠ Error clicking 'Save draft': {e}")
