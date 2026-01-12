"""
Browser management using Selenium and Chrome.
"""
import json
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException


class BrowserManager:
    """Manages the Selenium WebDriver instance."""

    def __init__(self, download_dir: Path, headless: bool = False):
        self.download_dir = download_dir
        self.headless = headless
        self.driver: Optional[webdriver.Chrome] = None

    def setup_driver(self):
        """Initialize Selenium WebDriver with Chrome."""
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        prefs = {
            "download.default_directory": str(self.download_dir.absolute()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        }
        chrome_options.add_experimental_option("prefs", prefs)
        chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        # Use default service or specific path if needed.
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    def quit(self):
        """Shutdown the browser."""
        if self.driver:
            self.driver.quit()

    def get_network_m3u8(self) -> str:
        """Extract m3u8 URL from browser network logs."""
        if not self.driver:
            return ""
        try:
            logs = self.driver.get_log("performance")
            for entry in logs:
                try:
                    message = json.loads(entry.get("message", "{}"))
                    params = message.get("message", {}).get("params", {})
                    request = params.get("request", {})
                    url = request.get("url", "")

                    if (
                        url
                        and ".m3u8" in url
                        and ("coursera" in url or "cloudfront" in url)
                    ):
                        return url
                except (json.JSONDecodeError, KeyError):
                    continue
        except (WebDriverException, json.JSONDecodeError) as e:
            print(f"  ⚠ Error reading performance logs: {e}")
        return ""
