import time
import pickle
import requests
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
)


class Authenticator:
    def __init__(
        self, driver, session: requests.Session, email: str, download_dir: Path
    ):
        self.driver = driver
        self.session = session
        self.email = email
        self.cookies_file = download_dir / "coursera_cookies.pkl"

    def login_with_google(self):
        """Login to Coursera using a Google account."""
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
                lambda driver: (
                    "coursera.org" in driver.current_url
                    and "authMode=login" not in driver.current_url
                    and "authMode=signup" not in driver.current_url
                )
                or self._check_logged_in()
            )

            time.sleep(3)
            print("  Login successful!")

            # Save cookies for future sessions.
            self._save_cookies()

            for cookie in self.driver.get_cookies():
                self.session.cookies.set(cookie["name"], cookie["value"])

        except TimeoutException:
            print("\n⚠ Login timeout. Please try again and complete the login process.")
            print("If you're having trouble, make sure you:")
            print("  - Click through the entire Google login flow")
            print("  - Wait until you see the main Coursera homepage")
            raise

    def _check_logged_in(self) -> bool:
        """Check if a user is logged in by looking for commonly authenticated elements."""
        try:
            self.driver.find_element(
                By.XPATH, "//button[contains(@aria-label, 'Profile')]"
            )
            return True
        except NoSuchElementException:
            pass

        try:
            self.driver.find_element(By.XPATH, "//a[contains(@href, '/my-courses')]")
            return True
        except NoSuchElementException:
            pass

        return False

    def _save_cookies(self):
        """Save browser cookies to a file for persistent login."""
        try:
            cookies = self.driver.get_cookies()
            with open(self.cookies_file, "wb") as f:
                pickle.dump(cookies, f)
            print(f"  Cookies saved to {self.cookies_file}")
        except (OSError, pickle.PickleError) as e:
            print(f"⚠ Error saving cookies to file: {e}")
        except WebDriverException as e:
            print(f"⚠ Browser error while getting cookies: {e}")

    def _load_cookies(self) -> bool:
        """Load cookies from a file and add them to the browser session."""
        if not self.cookies_file.exists():
            print("ℹ No saved cookies found")
            return False

        try:
            with open(self.cookies_file, "rb") as f:
                cookies = pickle.load(f)

            # Navigate to Coursera first (required to set cookies for the domain).
            self.driver.get("https://www.coursera.org")
            time.sleep(2)

            # Add each cookie to the browser.
            for cookie in cookies:
                try:
                    # Remove the domain if it starts with a dot (compatibility fix).
                    if "domain" in cookie and cookie["domain"].startswith("."):
                        cookie["domain"] = cookie["domain"][1:]
                    self.driver.add_cookie(cookie)
                except WebDriverException:
                    # Skip cookies that can't be added (e.g., invalid domain).
                    continue

            print("  Cookies loaded successfully")
            return True
        except (OSError, pickle.PickleError) as e:
            print(f"⚠ Error loading cookies from file: {e}")
            return False
        except WebDriverException as e:
            print(f"⚠ Browser error while loading cookies: {e}")
            return False

    def _verify_login(self) -> bool:
        """Verify if the current session is logged in."""
        try:
            # Navigate to a protected page to check login status.
            self.driver.get("https://www.coursera.org/my-learning")
            time.sleep(3)

            # Check if we're still on the my-learning page (logged in).
            if "my-learning" in self.driver.current_url or self._check_logged_in():
                print("  Already logged in")
                return True
            else:
                print("ℹ Not logged in (redirected or login elements not found)")
                return False
        except WebDriverException as e:
            print(f"⚠ Browser error while verifying login: {e}")
            return False

    def login_with_persistence(self):
        """
        Attempt to log in using saved cookies, fall back to manual login if needed.
        This allows users to stay logged in between script runs.
        """
        print(f"Attempting to login for: {self.email}")

        # Try to load saved cookies first.
        if self._load_cookies():
            # Sync cookies to the requests session.
            for cookie in self.driver.get_cookies():
                self.session.cookies.set(cookie["name"], cookie["value"])

            # Verify the login is still valid.
            if self._verify_login():
                # Login successful with saved cookies.
                return
            else:
                print("\nℹ Saved cookies are expired or invalid")
                print("  Proceeding with manual login...\n")

        # if no saved cookies, or they expired - do manual login.
        self.login_with_google()
