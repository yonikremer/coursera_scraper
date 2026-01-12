"""
Base class and utilities for Coursera content extractors.
"""
import time
from typing import TYPE_CHECKING

from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver


class BaseExtractor:
    """Base class for content extractors with shared UI interaction logic."""

    def __init__(self, driver: "WebDriver"):
        self.driver = driver

    def close_continue_learning_popup(self) -> bool:
        """Find and close the 'Continue Learning' modal if it appears."""
        try:
            cont_learning = self.driver.find_elements(
                By.XPATH,
                "//button[contains(., 'Continue Learning')] | //a[contains(., 'Continue Learning')]",
            )
            if cont_learning and any(b.is_displayed() for b in cont_learning):
                close_selectors = [
                    "//button[@aria-label='Close']",
                    "//button[@aria-label='close']",
                    "//button[contains(@class, 'close')]",
                    "//button[contains(@class, 'Close')]",
                ]
                for sel in close_selectors:
                    close_btns = self.driver.find_elements(By.XPATH, sel)
                    for c_btn in close_btns:
                        if c_btn.is_displayed():
                            self.driver.execute_script("arguments[0].click();", c_btn)
                            time.sleep(1)
                            return True
        except WebDriverException:
            pass
        return False

    def handle_barriers(self) -> bool:
        """Find and click common barriers like 'I agree', 'Accept', etc."""
        barriers = ["Continue", "I agree", "Agree", "Accept", "Confirm", "I understand"]
        clicked_any = False
        for b_text in barriers:
            xpath = (
                f"//button[contains(., '{b_text}')] | "
                f"//a[contains(., '{b_text}')] | "
                f"//span[text()='{b_text}']/ancestor::button"
            )
            try:
                btns = self.driver.find_elements(By.XPATH, xpath)
                for btn in btns:
                    if btn.is_displayed() and btn.is_enabled():
                        # Avoid search buttons
                        outer_html = btn.get_attribute("outerHTML") or ""
                        if "rc-InCourseSearchBar" in outer_html:
                            continue
                        btn_label = btn.text.strip() or b_text
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block: 'center'});", btn
                        )
                        time.sleep(1)
                        self.driver.execute_script("arguments[0].click();", btn)
                        print(f"  Clicked barrier: '{btn_label}'")
                        time.sleep(3)
                        clicked_any = True
                        break  # Check next barrier text
            except WebDriverException:
                continue
        return clicked_any

    @staticmethod
    def get_shared_html_style() -> str:
        """Returns the shared CSS style for generated HTML pages."""
        return """
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6; color: #333; max-width: 900px; margin: 0 auto; padding: 20px; background-color: #f5f7f9;
        }
        .container { background: #fff; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
        h1 { font-size: 2.2rem; color: #0056d2; margin-bottom: 10px; border-bottom: 2px solid #e1e4e8; padding-bottom: 10px; }
        .meta { color: #666; font-size: 0.9rem; margin-bottom: 30px; user-select: none; -webkit-user-select: none; }
        img { max-width: 100%; height: auto; display: block; margin: 25px auto; border-radius: 8px; }
        code { background: #f0f2f5; padding: 3px 6px; border-radius: 4px; font-family: monospace; font-size: 0.9rem; }
        pre { background: #1e1e1e; color: #d4d4d4; padding: 20px; border-radius: 8px; overflow-x: auto; margin: 20px 0; }
        a { color: #0056d2; text-decoration: none; }
        a:hover { text-decoration: underline; }
        h1 { user-select: none; -webkit-user-select: none; }
        """

    def wrap_html(self, title: str, content: str, options: dict) -> str:
        """Helper to wrap content in a consistent HTML template."""
        css = options.get("css", "")
        meta = options.get("meta", "")
        extra_style = options.get("extra_style", "")
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
{css}
    <style>
{self.get_shared_html_style()}
{extra_style}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <div class="meta">{meta}</div>
        <div class="content-wrapper">{content}</div>
    </div>
</body>
</html>"""
