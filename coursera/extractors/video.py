"""
Extractor for video content from Coursera.
"""
import time
import re
from pathlib import Path
from typing import Tuple, List, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)
import yt_dlp
from ..files import get_or_move_path, download_file, download_video
from ..browser import BrowserManager
from .base import BaseExtractor


class VideoExtractor(BaseExtractor):
    """Extractor for Coursera video items."""

    def __init__(self, driver, download_dir: Path, session):
        super().__init__(driver)
        self.download_dir = download_dir
        self.session = session

    def process(self, context: dict) -> Tuple[bool, int, List[Tuple[Path, str]]]:
        """Process and download video items."""
        print("  Processing video...")
        new_files = []

        course_dir = context["course_dir"]
        module_dir = context["module_dir"]
        item_counter = context["item_counter"]
        title = context["title"]
        item_url = context["item_url"]
        browser_manager = context["browser_manager"]

        self._cleanup_ui()
        main_video_file = get_or_move_path(
            course_dir, module_dir, f"{item_counter:03d}_{title}.mp4"
        )

        # Always try subtitles
        subs = self._download_subtitles(item_counter, title, course_dir, module_dir)
        for sub in subs:
            new_files.append((sub, "subtitle"))

        if main_video_file.exists() and main_video_file.stat().st_size > 0:
            print(f"  ℹ Video already exists: {main_video_file.name}")
            return True, 1, new_files

        # Strategies
        strategies = [
            lambda: self._try_download_from_buttons(main_video_file),
            lambda: self._try_download_from_video_tag(main_video_file),
            lambda: self._try_download_from_manifest(main_video_file, browser_manager),
            lambda: self._try_download_yt_dlp(item_url, main_video_file),
        ]

        for strategy in strategies:
            if strategy():
                new_files.append((main_video_file, "video"))
                return True, 1, new_files

        return len(new_files) > 0, 1 if main_video_file.exists() else 0, new_files

    def _cleanup_ui(self):
        """Remove messy elements."""
        try:
            self.driver.execute_script(
                """
                const selectors = ['[data-ai-instructions="true"]', '[data-testid="like-button"]', '[data-testid="dislike-button"]'];
                selectors.forEach(s => document.querySelectorAll(s).forEach(el => el.remove()));
            """
            )
        except WebDriverException:
            pass

    def _try_download_from_buttons(self, target: Path) -> bool:
        """Strategy: Check 'Download' section buttons."""
        try:
            btns = self.driver.find_elements(
                By.XPATH,
                "//a[contains(text(), 'Download') and (contains(@href, '.mp4') or contains(@href, 'video'))]",
            )
            if not btns:
                return False

            best_href = None
            for btn in btns:
                href = btn.get_attribute("href")
                if not href:
                    continue
                txt = btn.text.lower()
                if any(x in txt or x in href for x in ["720p", "1080p"]):
                    best_href = href
                    break

            if best_href and download_file(best_href, target, self.session):
                print(f"  ✓ Video saved from button: {target.name}")
                return True
        except (WebDriverException, StaleElementReferenceException):
            pass
        return False

    def _try_download_from_video_tag(self, target: Path) -> bool:
        """Strategy: Extract from <video> element."""
        self._switch_video_quality_to_hd()
        time.sleep(3)
        try:
            video = self.driver.find_element(By.TAG_NAME, "video")
            src = video.get_attribute("src")
            if (
                src
                and not src.startswith("blob:")
                and download_file(src, target, self.session)
            ):
                print(f"  ✓ Video saved from direct source: {target.name}")
                return True
        except WebDriverException:
            pass
        return False

    def _try_download_from_manifest(
        self, target: Path, browser_manager: BrowserManager
    ) -> bool:
        """Strategy: Network logs or DOM manifests."""
        if not browser_manager:
            return False
        url = browser_manager.get_network_m3u8() or self._find_manifest_in_dom()
        if url:
            try:
                if download_video(
                    url,
                    target,
                    cookies=self.driver.get_cookies(),
                    download_dir=self.download_dir,
                ):
                    print(f"  ✓ Video saved from manifest: {target.name}")
                    return True
            except (yt_dlp.utils.DownloadError, OSError):
                pass
        return False

    def _find_manifest_in_dom(self) -> Optional[str]:
        """Look for .m3u8 or .mpd in page content."""
        try:
            for v in self.driver.find_elements(By.TAG_NAME, "video"):
                srcs = [v.get_attribute("src")] + [
                    s.get_attribute("src")
                    for s in v.find_elements(By.TAG_NAME, "source")
                ]
                for s in srcs:
                    if s and (".m3u8" in s or ".mpd" in s):
                        return s

            matches = re.findall(
                r'(https?://[^"\\]+\.m3u8[^"\\]*)', self.driver.page_source
            )
            for m in matches:
                if "coursera" in m or "cloudfront" in m:
                    return m
        except WebDriverException:
            pass
        return None

    def _try_download_yt_dlp(self, item_url: str, target: Path) -> bool:
        """Strategy: yt-dlp on page URL."""
        if not item_url:
            return False
        try:
            if download_video(
                item_url,
                target,
                cookies=self.driver.get_cookies(),
                download_dir=self.download_dir,
            ):
                print(f"  ✓ Video saved with yt-dlp: {target.name}")
                return True
        except (yt_dlp.utils.DownloadError, OSError):
            pass
        return False

    def _switch_video_quality_to_hd(self):
        """Switch video player quality to HD."""
        try:
            player, controls = self._find_player_elements()
            if not self._open_settings_menu(player, controls):
                return

            quality_menu = self._find_quality_menu()
            if quality_menu:
                self.driver.execute_script("arguments[0].click();", quality_menu)
                time.sleep(1)
                self._click_highest_resolution()
        except WebDriverException as e:
            print(f"  ⚠ HD switch error: {e}")

    def _find_player_elements(self):
        """Find video player components."""
        player = None
        controls = None
        try:
            player = self.driver.find_element(
                By.CSS_SELECTOR,
                "[data-testid='playerContainer'], .rc-VideoPlayer, .c-video-player",
            )
        except NoSuchElementException:
            pass
        try:
            controls = self.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='video-control-bar'], .vjs-control-bar"
            )
        except NoSuchElementException:
            pass
        return player, controls

    def _open_settings_menu(self, player, controls) -> bool:
        """Hover and click settings."""
        if player:
            try:
                actions = ActionChains(self.driver).move_to_element(player)
                if controls:
                    actions.move_to_element(controls)
                actions.perform()
                time.sleep(1)
            except WebDriverException:
                pass

        selectors = [
            "button[data-testid='videoSettingsMenuButton']",
            "button[aria-label='Settings']",
            ".rc-VideoSettingsMenu button",
        ]
        for sel in selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                if btn:
                    self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1)
                    return True
            except (NoSuchElementException, WebDriverException):
                continue
        return False

    def _find_quality_menu(self):
        """Locate 'Quality' in settings menu."""
        selectors = [
            "button[data-testid='menuitem-Quality']",
            "button[aria-label='Quality']",
            ".rc-VideoSettingsMenu li",
        ]
        for sel in selectors:
            try:
                items = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for item in items:
                    if (
                        "Quality" in item.text
                        or item.get_attribute("aria-label") == "Quality"
                    ):
                        return item
            except (NoSuchElementException, StaleElementReferenceException):
                continue
        return None

    def _click_highest_resolution(self):
        """Find and click the highest 'p' resolution."""
        opts = self.driver.find_elements(
            By.CSS_SELECTOR,
            "button[role='option'], li[role='menuitemradio'], .c-player-settings-menu-item",
        )
        res_map = {}
        for opt in opts:
            try:
                text = opt.text or opt.get_attribute("aria-label") or ""
                match = re.search(r"(\d+)p", text)
                if match:
                    res_map[int(match.group(1))] = opt
            except StaleElementReferenceException:
                continue

        if res_map:
            target = res_map[max(res_map.keys())]
            self.driver.execute_script("arguments[0].click();", target)
            time.sleep(3)

    def _download_subtitles(
        self, counter: int, title: str, cdir: Path, mdir: Path
    ) -> List[Path]:
        """Download English subtitles."""
        downloaded = []
        try:
            tracks = self.driver.find_elements(
                By.CSS_SELECTOR,
                "track[kind='captions'][srclang='en'], track[kind='subtitles'][srclang='en']",
            )
            for track in tracks:
                src = track.get_attribute("src")
                if src:
                    path = get_or_move_path(cdir, mdir, f"{counter:03d}_{title}_en.vtt")
                    if path.exists() and path.stat().st_size > 0:
                        return [path]
                    if download_file(src, path, self.session):
                        print(f"  ✓ Subtitles saved: {path.name}")
                        downloaded.append(path)
                        break
        except WebDriverException as e:
            print(f"  ⚠ Subtitle error: {e}")
        return downloaded
