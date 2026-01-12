"""
Authentication logic for Coursera using Selenium and persistent cookies.
"""
import time
import pickle
from pathlib import Path

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
)


class Authenticator:
    """Handles manual and persistent login to Coursera."""

    def __init__(
        self, driver, session: requests.Session, email: str, download_dir: Path
    ):
        self.driver = driver
        self.session = session
        self.email = email
        self.cookies_file = download_dir / "coursera_cookies.pkl"

    def login_with_google(self):
        """Login to Coursera using a Google account manually."""
        print(f"Logging in with Google account: {self.email}")
        print("\nOpening Coursera login page...")
        print(
            "Please complete the ENTIRE login process manually in the browser window."
        )
        print("This includes:")
        print(
            "  1. Click 'Continue with Google' (or 'Log In' then 'Continue with Google')"
        )
        print("  2. Select your Google account or enter credentials")
        print("  3. Complete any 2FA if required")
        print("  4. Wait until you're on the main Coursera page")
        print("\nWaiting for you to complete login (up to 180 seconds)...\n")

        self.driver.get("https://www.coursera.org/?authMode=login")
        time.sleep(3)

        try:
            WebDriverWait(self.driver, 180).until(
                lambda d: (
                    "coursera.org" in d.current_url
                    and all(
                        x not in d.current_url
                        for x in ["authMode=login", "authMode=signup"]
                    )
                )
                or self._check_logged_in()
            )

            time.sleep(3)
            print("  Login successful!")

            self._save_cookies()
            self._sync_session_cookies()

        except TimeoutException:
            print("\n⚠ Login timeout. Please try again and complete the login process.")
            print("If you're having trouble, make sure you:")
            print("  - Click through the entire Google login flow")
            print("  - Wait until you see the main Coursera homepage")
            raise

    def _check_logged_in(self) -> bool:
        """Check if a user is logged in by looking for authenticated elements."""
        selectors = [
            "//button[contains(@aria-label, 'Profile')]",
            "//a[contains(@href, '/my-courses')]",
        ]
        for sel in selectors:
            try:
                if self.driver.find_element(By.XPATH, sel):
                    return True
            except NoSuchElementException:
                continue
        return False

    def _sync_session_cookies(self):
        """Sync Selenium cookies to the requests Session."""
        for cookie in self.driver.get_cookies():
            self.session.cookies.set(cookie["name"], cookie["value"])

    def _save_cookies(self):
        """Save browser cookies to a file for persistent login."""
        try:
            cookies = self.driver.get_cookies()
            with open(self.cookies_file, "wb") as f:
                pickle.dump(cookies, f)
            print(f"  Cookies saved to {self.cookies_file}")
        except (OSError, pickle.PickleError, WebDriverException) as e:
            print(f"⚠ Error saving cookies: {e}")

    def _load_cookies(self) -> bool:
        """Load cookies from a file and add them to the browser session."""
        if not self.cookies_file.exists():
            print("ℹ No saved cookies found")
            return False

        try:
            with open(self.cookies_file, "rb") as f:
                cookies = pickle.load(f)

            self.driver.get("https://www.coursera.org")
            time.sleep(2)

            for cookie in cookies:
                try:
                    if "domain" in cookie and cookie["domain"].startswith("."):
                        cookie["domain"] = cookie["domain"][1:]
                    self.driver.add_cookie(cookie)
                except WebDriverException:
                    continue

            print("  Cookies loaded successfully")
            return True
        except (OSError, pickle.PickleError, WebDriverException) as e:
            print(f"⚠ Error loading cookies: {e}")
            return False

    def _verify_login(self) -> bool:
        """Verify if the current session is logged in."""
        try:
            self.driver.get("https://www.coursera.org/my-learning")
            time.sleep(3)

            if "my-learning" in self.driver.current_url or self._check_logged_in():
                print("  Already logged in")
                return True

            print("ℹ Not logged in (redirected or login elements not found)")
            return False
        except WebDriverException as e:
            print(f"⚠ Error verifying login: {e}")
            return False

    def login_with_persistence(self):
        """Attempt to log in using saved cookies, fall back to manual login if needed."""
        print(f"Attempting login for: {self.email}")

        if self._load_cookies():
            self._sync_session_cookies()
            if self._verify_login():
                return

            print("\nℹ Saved cookies are expired or invalid")
            print("  Proceeding with manual login...\n")

        self.login_with_google()
