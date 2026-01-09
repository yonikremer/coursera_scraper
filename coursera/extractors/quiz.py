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
            assignment_content, image_count = self._extract_assignment_content()
            downloaded_count += image_count

            if assignment_content:
                # Download CSS.
                css_links_html = self.asset_manager.download_course_css()
                
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
        
        # Try to remove any AI instructions if they are present before extracting.
        try:
            self.driver.execute_script("""
                const aiInstructions = document.querySelectorAll('[data-ai-instructions="true"]');
                aiInstructions.forEach(el => el.remove());
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
                            downloaded_count += self.asset_manager.localize_images(elem)
                                
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
