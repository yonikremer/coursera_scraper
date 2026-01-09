import time
import zipfile
import shutil
from pathlib import Path
from typing import Optional, Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException, WebDriverException
from ..files import get_or_move_path
from ..utils import extract_slug, sanitize_filename

class LabExtractor:
    def __init__(self, driver, download_dir: Path):
        self.driver = driver
        self.download_dir = download_dir

    def _sanitize_and_rename_files(self, directory: Path) -> int:
        """
        Recursively normalize filenames in the directory.
        Returns the number of files processed.
        """
        count = 0
        # Walk bottom-up so we don't rename parent directories before their children
        for item in list(directory.rglob("*")):
            if item.is_file():
                # Sanitize the name
                safe_name = sanitize_filename(item.stem)
                # Keep extension
                suffix = item.suffix
                new_filename = f"{safe_name}{suffix}"
                
                if new_filename != item.name:
                    new_path = item.parent / new_filename
                    try:
                        # Handle collision
                        if new_path.exists():
                             timestamp = int(time.time())
                             new_path = item.parent / f"{safe_name}_{timestamp}{suffix}"
                        
                        item.rename(new_path)
                        count += 1
                    except OSError as e:
                        print(f"    ⚠ Error renaming {item.name}: {e}")
                else:
                    count += 1
        return count

    def _download_individual_files(self, lab_dir: Path) -> int:
        """Fallback: Download files one by one from the side panel."""
        print("  ⚠ 'Download all files' failed or timed out. Attempting individual downloads...")
        downloaded_count = 0
        
        try:
            # Find the file list container. 
            # It's usually a list of items above the "Download all files" button.
            # We look for 'a' tags that link to files.
            
            # Common selectors for file links in Coursera/Jupyter sidebars
            # They often have 'download' attribute or href pointing to /files/
            file_links = self.driver.find_elements(By.XPATH, 
                "//div[contains(@class, 'rc-LabFile')]//a | " +
                "//a[contains(@class, 'file-link')] | " +
                "//li//a[contains(@href, '/files/')]"
            )
            
            if not file_links:
                # Fallback: find ANY link in the sidebar that isn't the "Download all files" button
                # Assuming the sidebar is the parent of the "Download all files" button
                try:
                    download_all_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Download all files')] ")
                    sidebar = download_all_btn.find_element(By.XPATH, "./ancestor::div[contains(@class, 'rc-LabFiles')] | ./ancestor::div[contains(@class, 'c-modal-content')]")
                    file_links = sidebar.find_elements(By.TAG_NAME, "a")
                except NoSuchElementException:
                    pass

            unique_links = []
            seen_hrefs = set()
            for link in file_links:
                try:
                    href = link.get_attribute('href')
                    text = link.text.strip()
                    if href and href not in seen_hrefs and 'download_all' not in href:
                        # Filter out navigation links if possible
                        if '/tree/' in href or '/lab' in href: 
                            continue # likely a folder navigation or lab link
                            
                        unique_links.append(link)
                        seen_hrefs.add(href)
                except StaleElementReferenceException:
                    continue

            print(f"  Found {len(unique_links)} potential file links.")
            
            for link in unique_links:
                try:
                    # Get filename
                    href = link.get_attribute('href')
                    filename = href.split('/')[-1].split('?')[0]
                    if not filename:
                        filename = link.text.strip() or "untitled_file"
                    
                    # Sanitize
                    filename = sanitize_filename(Path(filename).stem) + Path(filename).suffix
                    target_path = lab_dir / filename
                    
                    if target_path.exists():
                        continue
                        
                    print(f"    ⬇ Clicking file: {filename}")
                    link.click()
                    
                    # Wait a bit for download to start/finish
                    time.sleep(2)
                    
                    # Check if file appeared in downloads
                    downloaded_file = None
                    for attempt in range(10):
                        # It might be in user's Downloads folder
                        user_downloads = Path.home() / "Downloads" / filename
                        # Or generic name
                        
                        if user_downloads.exists():
                            shutil.move(str(user_downloads), str(target_path))
                            downloaded_count += 1
                            print(f"    ✓ Downloaded: {filename}")
                            break
                        time.sleep(1)
                        
                except Exception as e:
                    print(f"    ⚠ Failed to download link: {e}")
                    
        except Exception as e:
            print(f"  ⚠ Error during individual download: {e}")
            
        return downloaded_count

    def process(self, course_dir: Path, module_dir: Path, item_counter: int,
                         title: str, item_url: str) -> Tuple[bool, int]:
        """Process and download Jupyter lab notebooks and data files."""
        downloaded_count = 0
        downloaded_something = False
        original_window = None
        lab_window = None

        try:
            print(f"  Processing lab...")

            # 1. Determine target directory name using slug (for consistency with find_items)
            slug = extract_slug(item_url)
            # Use slug if available, otherwise fall back to title
            base_name = slug if slug else sanitize_filename(title)
            target_dir_name = f"{item_counter:03d}_{base_name}_lab"
            
            # 2. Check for existing directory with different name (e.g. based on title) and rename it
            # This fixes the issue where find_items (using slug) fails but folder exists (using title)
            if module_dir.exists():
                for item in module_dir.iterdir():
                    if item.is_dir() and item.name.startswith(f"{item_counter:03d}_") and item.name.endswith("_lab"):
                        if item.name != target_dir_name:
                            print(f"  ↗️ Renaming existing lab directory: {item.name} -> {target_dir_name}")
                            try:
                                item.rename(module_dir / target_dir_name)
                            except OSError as e:
                                print(f"  ⚠ Error renaming directory: {e}")
            
            # 3. Get path (now possibly renamed)
            lab_dir = get_or_move_path(course_dir, module_dir, target_dir_name)
            
            # 4. Check if already completed (lab_info.txt exists)
            lab_info_file = lab_dir / "lab_info.txt"
            if lab_info_file.exists():
                print(f"  ℹ Lab already processed (found lab_info.txt).")
                return False, 0

            # Remember the original window handle.
            original_window = self.driver.current_window_handle
            print(f"  Original window: {original_window}")

            # Launch lab.
            launch_clicked = False
            for btn_text in ["Launch Lab", "Open Tool", "Launch", "Continue"]:
                try:
                    launch_btn = self.driver.find_element(By.XPATH,
                        f"//button[contains(., '{btn_text}')] | //a[contains(., '{btn_text}')]"
                    )
                    if launch_btn.is_displayed() and launch_btn.is_enabled():
                        print(f"  ✓ Clicking '{btn_text}'...")
                        launch_btn.click()
                        launch_clicked = True
                        break
                except (NoSuchElementException, StaleElementReferenceException):
                    continue

            if not launch_clicked:
                print(f"  ℹ Could not launch lab")
                return downloaded_something, downloaded_count

            # Wait for a new tab / window to open
            print(f"  ⏳ Waiting for new tab to open...")
            time.sleep(5)  # Give time for a new tab to open

            # Check if a new window/tab was opened
            all_windows = self.driver.window_handles
            print(f"  Windows open: {len(all_windows)}")

            if len(all_windows) > 1:
                # New tab opened - switch to it
                for window in all_windows:
                    if window != original_window:
                        lab_window = window
                        break

                if lab_window:
                    print(f"  Switching to lab tab: {lab_window}")
                    self.driver.switch_to.window(lab_window)
                    time.sleep(2)

            # Wait for a lab to load (either in new tab or same window)
            print(f"  ⏳ Waiting for lab environment to load (up to 60 seconds)...")
            try:
                WebDriverWait(self.driver, 60).until(
                    lambda d: '/lab' in d.current_url and 'path=' in d.current_url
                )
                print(f"  ✓ Lab loaded: {self.driver.current_url}")
                time.sleep(5)
            except TimeoutException:
                print(f"  ⚠ Timeout waiting for lab to load")
                print(f"  Current URL: {self.driver.current_url}")
                # Switch back to the original window before returning
                if original_window and lab_window:
                    print(f"  Switching back to original window")
                    self.driver.switch_to.window(original_window)
                return downloaded_something, downloaded_count

            # Check if lab directory exists in old location or with different numbering
            # We already defined lab_dir and target_dir_name at the start of the function
            # lab_dir = get_or_move_path(course_dir, module_dir, lab_dir_name)

            # Create lab directory if it still doesn't exist
            lab_dir.mkdir(exist_ok=True)

            # Download all lab files using the "Download all files" button
            current_url = self.driver.current_url
            print(f"  Lab URL: {current_url}")

            # Click "Lab files" button to show the file panel.
            print(f"  Looking for 'Lab files' button...")
            lab_files_btn = None
            for btn_selector in [
                "//button[contains(., 'Lab files')]",
                "//button[contains(@aria-label, 'Lab files')]",
                "//*[contains(text(), 'Lab files')]//ancestor::button",
            ]:
                try:
                    lab_files_btn = self.driver.find_element(By.XPATH, btn_selector)
                    if lab_files_btn.is_displayed():
                        break
                except (NoSuchElementException, StaleElementReferenceException):
                    continue

            if lab_files_btn and lab_files_btn.is_displayed():
                print(f"  ✓ Clicking 'Lab files' button...")
                lab_files_btn.click()
                time.sleep(2)
            else:
                error_msg = f"❌ CRITICAL ERROR: 'Lab files' button not found!\n"
                print(f"  {error_msg}")
                # Don't raise, just return, maybe manual intervention needed
                return downloaded_something, downloaded_count

            # Click "Download all files" button.
            print(f"  Looking for 'Download all files' button...")
            download_all_btn = None
            for btn_selector in [
                "//button[contains(., 'Download all files')]",
                "//span[contains(text(), 'Download all files')]//ancestor::button",
                "//button[contains(@aria-label, 'Download all files')]",
            ]:
                try:
                    download_all_btn = self.driver.find_element(By.XPATH, btn_selector)
                    if download_all_btn.is_displayed() and download_all_btn.is_enabled():
                        break
                except (NoSuchElementException, StaleElementReferenceException):
                    continue

            zip_downloaded = False
            if download_all_btn and download_all_btn.is_displayed() and download_all_btn.is_enabled():
                print(f"  ✓ Clicking 'Download all files' button...")
                # Use JavaScript click to avoid interception.
                self.driver.execute_script("arguments[0].click();", download_all_btn)
                time.sleep(3)  # Give time for download to start.

                # Wait for Files.zip to be downloaded.
                print(f"  ⏳ Waiting for Files.zip to download (30s timeout)...")
                zip_file = None
                for attempt in range(30):  # Wait up to 30 seconds.
                    # Check in download directory.
                    potential_zip = self.download_dir / "Files.zip"
                    if potential_zip.exists():
                        zip_file = potential_zip
                        break
                    # Also check in user's Downloads folder.
                    downloads_folder = Path.home() / "Downloads" / "Files.zip"
                    if downloads_folder.exists():
                        zip_file = downloads_folder
                        break
                    time.sleep(1)

                if zip_file and zip_file.exists():
                    print(f"  ✓ Files.zip downloaded: {zip_file}")
                    
                    try:
                        # Extract the zip file.
                        print(f"  📦 Extracting Files.zip...")
                        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                            zip_ref.extractall(lab_dir)

                        # The zip contains: Files/home/jovyan/work/
                        # Move files from work directory to lab_dir root.
                        work_dir = lab_dir / "Files" / "home" / "jovyan" / "work"
                        if work_dir.exists():
                            print(f"  📁 Moving files from work directory to lab directory...")
                            for item in work_dir.iterdir():
                                # Skip Jupyter checkpoints.
                                if item.name == '.ipynb_checkpoints':
                                    continue

                                dest = lab_dir / item.name
                                if dest.exists():
                                    print(f"    ℹ Skipping existing: {item.name}")
                                else:
                                    shutil.move(str(item), str(dest))
                                    downloaded_count += 1

                            # Clean up the Files directory structure.
                            files_dir = lab_dir / "Files"
                            if files_dir.exists():
                                shutil.rmtree(files_dir)
                                print(f"  ✓ Cleaned up temporary Files directory")
                        else:
                            # Fallback: extract all files directly if structure is different
                            pass

                        # Delete the zip file.
                        zip_file.unlink()
                        print(f"  ✓ Deleted Files.zip")
                        zip_downloaded = True
                        downloaded_something = True
                        
                    except zipfile.BadZipFile:
                        print(f"  ⚠ Files.zip is corrupted. Ignoring.")
                        zip_file.unlink(missing_ok=True)

            # Fallback to individual files if zip failed
            if not zip_downloaded:
                print(f"  ⚠ Zip download failed or skipped. Trying individual files...")
                count = self._download_individual_files(lab_dir)
                downloaded_count += count
                if count > 0:
                    downloaded_something = True

            # Normalize filenames (requested by user)
            # This applies to files from zip OR individual downloads
            print(f"  🧹 Normalizing filenames...")
            renamed_count = self._sanitize_and_rename_files(lab_dir)
            if renamed_count > 0:
                print(f"  ✓ Normalized {renamed_count} files.")

            # Recursive cleanup of any .ipynb_checkpoints
            for checkpoint_dir in lab_dir.rglob(".ipynb_checkpoints"):
                if checkpoint_dir.is_dir():
                    try:
                        shutil.rmtree(checkpoint_dir)
                    except Exception:
                        pass

            # Save lab info.
            lab_info_file = lab_dir / "lab_info.txt"
            with open(lab_info_file, 'w', encoding='utf-8') as f:
                f.write(f"Lab: {title}\n")
                f.write(f"URL: {current_url}\n")
                f.write(f"Zip Downloaded: {zip_downloaded}\n")
                f.write(f"Files downloaded: {downloaded_count}\n")

            if downloaded_something:
                print(f"  ✓ Lab processing complete")
            else:
                print(f"  ⚠ No files downloaded for this lab.")

        except Exception as e:
            print(f"  ⚠ Error processing lab: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Clean up: close the lab tab and switch back to the original window.
            if lab_window and original_window:
                try:
                    # Check if the lab window is still open.
                    if lab_window in self.driver.window_handles:
                        print(f"  Closing lab tab...")
                        self.driver.switch_to.window(lab_window)
                        self.driver.close()
                        print(f"  ✓ Lab tab closed")

                    # Switch back to the original window.
                    if original_window in self.driver.window_handles:
                        print(f"  Switching back to original window...")
                        self.driver.switch_to.window(original_window)
                        print(f"  ✓ Back to course page")
                except Exception as e:
                    print(f"  ⚠ Error during cleanup: {e}")
                    try:
                        if len(self.driver.window_handles) > 0:
                            self.driver.switch_to.window(self.driver.window_handles[0])
                    except WebDriverException:
                        pass
        return downloaded_something, downloaded_count