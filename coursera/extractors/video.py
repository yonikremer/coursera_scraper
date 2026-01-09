import time
import re
from pathlib import Path
from typing import Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, JavascriptException, TimeoutException, WebDriverException
import yt_dlp
from ..files import get_or_move_path, download_file, download_video
from ..browser import BrowserManager

class VideoExtractor:
    def __init__(self, driver, download_dir: Path, session):
        self.driver = driver
        self.download_dir = download_dir
        self.session = session

    def _switch_video_quality_to_hd(self):
        """Attempt to switch the video player quality to HD via UI interaction."""
        try:
            # 1. Find video player components
            video_player = None
            control_bar = None
            
            try:
                # Try finding the main player container
                video_player = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='playerContainer']")
            except NoSuchElementException:
                try:
                    video_player = self.driver.find_element(By.CSS_SELECTOR, ".rc-VideoPlayer, .c-video-player, .vjs-react")
                except NoSuchElementException:
                    pass

            try:
                # Try finding the control bar specifically
                control_bar = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='video-control-bar'], .vjs-control-bar")
            except NoSuchElementException:
                pass

            # 2. Perform hover action
            if video_player:
                try:
                    actions = ActionChains(self.driver)
                    actions.move_to_element(video_player)
                    # If we found the control bar, move to it as well to be safe
                    if control_bar:
                        actions.move_to_element(control_bar)
                    actions.perform()
                    time.sleep(1) # Wait for UI to react
                except WebDriverException:
                    pass

            # 3. Click Settings (Gear Icon).
            print("  ⚙ Opening video settings...")
            settings_btn = None
            settings_selectors = [
                "button[data-testid='videoSettingsMenuButton']",
                "button[aria-label='Settings']",
                "button.c-player-settings-button",
                ".rc-VideoSettingsMenu button"
            ]
            
            for selector in settings_selectors:
                try:
                    buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    # First try to find a visible button
                    for btn in buttons:
                        if btn.is_displayed():
                            settings_btn = btn
                            break
                    
                    # If no visible button, take the first present one (and force click it later)
                    if not settings_btn and buttons:
                        print("  ⚠ Settings button found but hidden, attempting force click...")
                        settings_btn = buttons[0]
                        
                    if settings_btn: break
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
            
            if not settings_btn:
                print("  ⚠ Settings button not found in DOM")
                return

            # Re-hover if needed before clicking
            if video_player and not settings_btn.is_displayed():
                 try:
                    ActionChains(self.driver).move_to_element(video_player).perform()
                    time.sleep(0.5)
                 except WebDriverException:
                    pass  # Ignore hover errors if player disappeared

            try:
                self.driver.execute_script("arguments[0].click();", settings_btn)
            except JavascriptException:
                try:
                    settings_btn.click()
                except WebDriverException as e:
                    print(f"  ⚠ Failed to click settings button: {e}")
                    return
            time.sleep(1)
            
            # 4. Find the "Quality" menu item.
            print("  ⚙ Finding Quality menu...")
            quality_menu = None
            quality_selectors = [
                "button[data-testid='menuitem-Quality']",
                "button[aria-label='Quality']",
                ".rc-VideoSettingsMenu li", 
                ".c-player-settings-menu-item"
            ]
            
            for selector in quality_selectors:
                try:
                    items = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for item in items:
                        if "Quality" in item.text or item.get_attribute("aria-label") == "Quality":
                            quality_menu = item
                            break
                    if quality_menu: break
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
            
            if quality_menu:
                try:
                    self.driver.execute_script("arguments[0].click();", quality_menu)
                except JavascriptException:
                    quality_menu.click()
                time.sleep(1)
                
                # 4. Select Highest Resolution.
                resolutions = self.driver.find_elements(By.CSS_SELECTOR, "button[role='option'], li[role='menuitemradio'], .c-player-settings-menu-item")
                target_res = None
                
                # Parse resolutions to find the max available.
                res_map = {}
                for res in resolutions:
                    try:
                        text = res.text or res.get_attribute("aria-label") or ""
                        # Extract number from "720p", "1080p", etc.
                        match = re.search(r'(\d+)p', text)
                        if match:
                            val = int(match.group(1))
                            res_map[val] = res
                    except StaleElementReferenceException:
                        continue
                
                if res_map:
                    max_res = max(res_map.keys())
                    target_res = res_map[max_res]
                    print(f"  ✓ Switching player quality to: {max_res}p")
                
                if target_res:
                    try:
                        self.driver.execute_script("arguments[0].click();", target_res)
                    except JavascriptException:
                        target_res.click()
                    time.sleep(3)  # Wait for the buffer switch.
            else:
                print("  ⚠ Quality menu not found")
        except (NoSuchElementException, TimeoutException, StaleElementReferenceException) as e:
            print(f"  ⚠ Navigation error during HD switch: {e}")

    def _download_subtitles(self, item_counter: int, title: str, course_dir: Path, module_dir: Path):
        """Find and download English subtitles."""
        try:
            # Look for track elements in the video tag
            tracks = self.driver.find_elements(By.CSS_SELECTOR, "track[kind='captions'][srclang='en'], track[kind='subtitles'][srclang='en']")
            
            if not tracks:
                return

            print(f"  Found {len(tracks)} subtitle track(s).")
            
            for track in tracks:
                src = track.get_attribute('src')
                label = track.get_attribute('label')
                
                if src:
                    # Construct filename: 001_Title.en.vtt
                    subtitle_filename = f"{item_counter:03d}_{title}.en.vtt"
                    subtitle_file = get_or_move_path(course_dir, module_dir, subtitle_filename)
                    
                    if subtitle_file.exists() and subtitle_file.stat().st_size > 0:
                        continue
                        
                    print(f"  ⬇ Downloading subtitles ({label})...")
                    if download_file(src, subtitle_file, self.session):
                        print(f"  ✓ Subtitles saved: {subtitle_file.name}")
                        # Only download one English track
                        break

        except Exception as e:
            print(f"  ⚠ Error downloading subtitles: {e}")

    def process(self, course_dir: Path, module_dir: Path, item_counter: int,
                           title: str, item_url: str, browser_manager: BrowserManager) -> Tuple[bool, int]:
        """Process and download video items."""
        downloaded_count = 0
        downloaded_something = False

        # 1. Determine the target filename for the main video
        main_filename = f"{item_counter:03d}_{title}.mp4"
        main_video_file = get_or_move_path(course_dir, module_dir, main_filename)
        
        # Always try to download subtitles, even if video exists
        self._download_subtitles(item_counter, title, course_dir, module_dir)

        if main_video_file.exists() and main_video_file.stat().st_size > 0:
             print(f"  ℹ Video already exists: {main_video_file.name}")
             return True, 1

        # 2. Strategy: Check the "Downloads" section buttons first (often the clearest source)
        download_buttons = []
        best_href = None
        try:
            download_buttons = self.driver.find_elements(By.XPATH,
                "//a[contains(text(), 'Download') and (contains(@href, '.mp4') or contains(@href, 'video'))]")
            
            if download_buttons:
                print(f"  Found {len(download_buttons)} download button(s)")
                best_href = None
                
                # Priority: 720p/1080p > 540p > others
                for btn in download_buttons:
                    href = btn.get_attribute('href')
                    if not href: continue
                    text = btn.text.lower()
                    
                    if '720p' in text or '720p' in href or '1080p' in text or '1080p' in href:
                        best_href = href
                        print(f"  ✓ Found HD download link")
                        break
                    
                if best_href:
                    print(f"  ⬇ Downloading from button...")
                    if download_file(best_href, main_video_file, self.session):
                        print(f"  ✓ Video saved: {main_video_file.name}")
                        return True, 1

        except (NoSuchElementException, StaleElementReferenceException) as e:
            print(f"  ⚠ Error checking download buttons: {e}")

        # Try to force HD quality in player UI before checking sources
        # This updates the <video src=\"...\"> attribute
        self._switch_video_quality_to_hd()
        time.sleep(3) # Wait for player to re-load source

        # 3. Strategy: Extract direct URL from Video Element (Best for direct MP4)
        try:
            video_element = self.driver.find_element(By.TAG_NAME, "video")
            current_src = video_element.get_attribute('src')
            if current_src and not current_src.startswith('blob:'):
                print(f"  ✓ Found direct video source: {current_src[:60]}...")
                if download_file(current_src, main_video_file, self.session):
                    print(f"  ✓ Video saved from direct source: {main_video_file.name}")
                    return True, 1
        except (NoSuchElementException, StaleElementReferenceException) as e:
            print(f"  ⚠ Error checking direct video source: {e}")

        # 4. Strategy: Check Network Logs for Manifest
        manifest_url = browser_manager.get_network_m3u8()
        if manifest_url:
            print(f"  ✓ Found manifest URL in network logs")

        # 5. Strategy: Check for HLS/DASH Manifests in DOM (Fallback)
        best_dom_src = None
        if not manifest_url:
            try:
                # Check video element sources for manifests
                video_elements = self.driver.find_elements(By.TAG_NAME, "video")
                print(f"  Found {len(video_elements)} video element(s)")

                for video in video_elements:
                    sources = [
                        video.get_attribute('src'),
                        *[source.get_attribute('src') for source in video.find_elements(By.TAG_NAME, 'source')]
                    ]
                    sources = [s for s in sources if s]

                    if sources:
                        best_dom_src = sources[0] # Default fallback

                    for s in sources:
                        if '.m3u8' in s or '.mpd' in s:
                            manifest_url = s
                            print(f"  ✓ Found manifest URL in DOM: {s[:60]}...")
                            break
                    if manifest_url: break
                
                # If not in video tag, check the page source for m3u8 regex (Coursera often embeds it in JS)
                if not manifest_url:
                    m3u8_matches = re.findall(r'(https?://[^"\\]+\.m3u8[^"\\]*)', self.driver.page_source)
                    if m3u8_matches:
                        # Filter for likely video manifests
                        valid_matches = [m for m in m3u8_matches if 'coursera' in m or 'cloudfront' in m]
                        if valid_matches:
                            manifest_url = valid_matches[0]
                            print(f"  ✓ Found manifest URL in page source")

            except (NoSuchElementException, StaleElementReferenceException, JavascriptException) as e:
                print(f"  ⚠ Error inspecting for manifests: {e}")

        # 6. Strategy: yt-dlp with Manifest (High Success for HD)
        if manifest_url:
            print(f"  ⬇ Downloading from manifest with yt-dlp (Best Quality)...")
            try:
                # We need to pass cookies to yt-dlp
                cookies = self.driver.get_cookies()
                if download_video(manifest_url, main_video_file, cookies=cookies, download_dir=self.download_dir):
                    print(f"  ✓ Video saved with yt-dlp: {main_video_file.name}")
                    return True, 1
            except (yt_dlp.utils.DownloadError, OSError) as e:
                 print(f"  ⚠ yt-dlp manifest download failed: {e}")
        
        # 7. Strategy: yt-dlp on Page URL (Retry, might work if extractor updated)
        # Skip this if we already tried the manifest, and it failed; it likely won't work either.
        if not manifest_url:
            print(f"  ⬇ Trying high-quality download with yt-dlp (Page URL)...")
            try:
                cookies = self.driver.get_cookies()
                # Use --ignore-errors to prevent crash
                if download_video(item_url, main_video_file, cookies=cookies, download_dir=self.download_dir):
                    print(f"  ✓ Video saved with yt-dlp: {main_video_file.name}")
                    return True, 1
            except (yt_dlp.utils.DownloadError, OSError) as e:
                print(f"  ⚠ yt-dlp failed: {e}")

        # 8. Fallback: Use the best available DOM source (likely 540p)
        if best_dom_src:
            print(f"  ⚠ Falling back to standard quality source (DOM)...")
            if download_file(best_dom_src, main_video_file, self.session):
                print(f"  ✓ Video saved: {main_video_file.name}")
                return True, 1
                
        # 9. Final Fallback: Any download button
        try:
            if download_buttons:
                for btn in download_buttons:
                    href = btn.get_attribute('href')
                    if href:
                        print(f"  ⚠ Falling back to download button (SD)...")
                        if download_file(href, main_video_file, self.session):
                            print(f"  ✓ Video saved: {main_video_file.name}")
                            return True, 1
        except WebDriverException as e:
            print(f"  ⚠ Error in fallback download: {e}")

        return downloaded_something, downloaded_count
