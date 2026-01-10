import time
from pathlib import Path
from typing import Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, JavascriptException, TimeoutException, WebDriverException, ElementClickInterceptedException
from ..files import get_or_move_path
from .common import AssetManager

class QuizExtractor:
    def __init__(self, driver, session, asset_manager: AssetManager):
        self.driver = driver
        self.session = session
        self.asset_manager = asset_manager

    def process(self, course_dir: Path, module_dir: Path, item_counter: int,
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
            except WebDriverException as e:
                print(f"  ⚠ Error while waiting: {e}")

            print(f"  Current URL: {self.driver.current_url}")

            # Extract additional metadata (like due date, weight, etc.).
            metadata = ""
            try:
                # Look for header info in modern view.
                header_info = self.driver.find_elements(By.CSS_SELECTOR, "[data-testid='header-right'], .rc-AssignmentHeader")
                if header_info:
                    metadata = " • ".join([el.text.strip().replace('\n', ' ') for el in header_info if el.text.strip()])
            except (NoSuchElementException, StaleElementReferenceException):
                pass  # Metadata extraction is optional.

            # Extract assignment content.
            assignment_content, image_count = self._extract_assignment_content(item_dir=module_dir)
            downloaded_count += image_count

            if assignment_content:
                # Download CSS.
                css_links_html = self.asset_manager.download_course_css(item_dir=module_dir)
                
                filename = f"{item_counter:03d}_{title}_{item_type}.html"
                assignment_file = get_or_move_path(course_dir, module_dir, filename)
                
                # Save to HTML file.
                self._save_assignment_html(assignment_file, title, item_type, assignment_content, css_links_html, metadata)
                
                downloaded_count += 1
                downloaded_something = True
                print(f"  ✓ {item_type.title()} content saved (with {image_count} images)")

                # Try to click 'Save draft' button to avoid annoying popups on exit.
                self._click_save_draft_button()
            else:
                print(f"  ⚠ No assignment content found to save")

        except WebDriverException as e:
            print(f"  ⚠ Error processing {item_type}: {e}")

        return downloaded_something, downloaded_count

    def _click_assignment_start_button(self) -> bool:
        """Click the start/resume button for an assignment or quiz."""
        # Common Coursera button texts for starting assignments/quizzes.
        button_texts = ["Start", "Start Assignment", "Resume", "Continue", "Start Quiz", "Retake Quiz", "Review", "Open", "Launch"]
        
        for btn_text in button_texts:
            try:
                # Try to find button or link with the text.
                xpath = f"//button[contains(., '{btn_text}')] | //a[contains(., '{btn_text}')]"
                start_btn = self.driver.find_element(By.XPATH, xpath)
                
                if start_btn.is_displayed() and start_btn.is_enabled():
                    # Scroll into view to ensure it's clickable.
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", start_btn)
                    time.sleep(1)
                    start_btn.click()
                    print(f"  ✓ Clicked '{btn_text}' button")
                    return True
            except (NoSuchElementException, StaleElementReferenceException, ElementClickInterceptedException):
                continue
            except WebDriverException as e:
                print(f"  ⚠ Browser error clicking start button: {e}")
                continue
        return False

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
            "form",
            "div[role='main']", 
            "main"
        ]
        
        # Try to remove any AI instructions if they are present before extracting.
        try:
            self.driver.execute_script("""
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
                            # Localize images.
                            downloaded_count += self.asset_manager.localize_images(elem, item_dir=item_dir)
                                
                            html = elem.get_attribute('outerHTML')
                            if html and len(html) > 100:
                                content += html + "\n<br>\n"
                        except StaleElementReferenceException:
                            continue
                    if content:
                        return content, downloaded_count
            except (NoSuchElementException, StaleElementReferenceException):
                continue
            except WebDriverException as e:
                print(f"  ⚠ Browser error extracting content with selector '{selector}': {e}")
                continue
        return "", 0

    def _save_assignment_html(self, filepath: Path, title: str, item_type: str, content: str, css_links_html: str = "", metadata: str = ""):
        """Save assignment content to an HTML file."""
        # Format title: replace underscores with spaces and title case
        display_title = title.replace('_', ' ').title()
        metadata_html = f"<p><strong>Info:</strong> {metadata}</p>" if metadata else ""
        with open(filepath, 'w', encoding='utf-8') as f:
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
            save_btn = self.driver.find_element(By.XPATH,
                "//button[contains(., 'Save draft') or contains(., 'Save Draft')]")
            if save_btn.is_displayed() and save_btn.is_enabled():
                save_btn.click()
                print(f"  ✓ Clicked 'Save draft'")
                time.sleep(2)
        except NoSuchElementException:
            # Button not found; this is expected.
            pass
        except (WebDriverException, ElementClickInterceptedException) as e:
            print(f"  ⚠ Error clicking 'Save draft': {e}")
