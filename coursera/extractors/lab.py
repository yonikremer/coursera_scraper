import time
import zipfile
import shutil
from pathlib import Path
from typing import Optional, Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException, WebDriverException
from ..files import get_or_move_path

class LabExtractor:
    def __init__(self, driver, download_dir: Path):
        self.driver = driver
        self.download_dir = download_dir

    def process(self, course_dir: Path, module_dir: Path, item_counter: int,
                         title: str) -> Tuple[bool, int]:
        """Process and download Jupyter lab notebooks and data files."""
        downloaded_count = 0
        downloaded_something = False
        original_window = None
        lab_window = None

        try:
            print(f"  Processing lab...")

            # Remember the original window handle.
            original_window = self.driver.current_window_handle
            print(f"  Original window: {original_window}")

            # Launch lab.
            launch_clicked = False
            for btn_text in ["Launch Lab", "Open Tool", "Launch", "Continue"]:
                try:
                    launch_btn = self.driver.find_element(By.XPATH,
                        f"//button[contains(., '{btn_text}')] | //a[contains(., '{btn_text}')]")
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
            lab_dir_name = f"{item_counter:03d}_{title}_lab"
            lab_dir = get_or_move_path(course_dir, module_dir, lab_dir_name)

            # Create lab directory if it still doesn't exist
            lab_dir.mkdir(exist_ok=True)

            # Download all lab files using the "Download all files" button
            current_url = self.driver.current_url
            print(f"  Lab URL: {current_url}")

            try:
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
                    error_msg += f"  Lab: {title}\n"
                    error_msg += f"  URL: {current_url}\n"
                    error_msg += f"  Cannot proceed with downloading lab files.\n"
                    print(f"  {error_msg}")
                    raise RuntimeError(error_msg)

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

                if download_all_btn and download_all_btn.is_displayed() and download_all_btn.is_enabled():
                    print(f"  ✓ Clicking 'Download all files' button...")
                    # Use JavaScript click to avoid interception.
                    self.driver.execute_script("arguments[0].click();", download_all_btn)
                    time.sleep(3)  # Give time for download to start.
                else:
                    error_msg = f"❌ CRITICAL ERROR: 'Download all files' button not found!\n"
                    error_msg += f"  Lab: {title}\n"
                    error_msg += f"  URL: {current_url}\n"
                    error_msg += f"  Cannot proceed with downloading lab files.\n"
                    print(f"  {error_msg}")
                    raise RuntimeError(error_msg)

                # Wait for Files.zip to be downloaded.
                print(f"  ⏳ Waiting for Files.zip to download...")
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
                                print(f"    ✓ Moved: {item.name}")
                                downloaded_count += 1

                        # Clean up the Files directory structure.
                        files_dir = lab_dir / "Files"
                        if files_dir.exists():
                            shutil.rmtree(files_dir)
                            print(f"  ✓ Cleaned up temporary Files directory")
                    else:
                        # Fallback: extract all files directly.
                        print(f"  ℹ Work directory not found, extracting all files from zip...")
                        for item in lab_dir.iterdir():
                            if item.is_file() and item.suffix in ['.ipynb', '.csv', '.txt', '.json', '.xlsx', '.py']:
                                print(f"    ✓ Found: {item.name}")
                                downloaded_count += 1

                    # Delete the zip file.
                    zip_file.unlink()
                    print(f"  ✓ Deleted Files.zip")

                    # Recursive cleanup of any .ipynb_checkpoints that might have been extracted.
                    for checkpoint_dir in lab_dir.rglob(".ipynb_checkpoints"):
                        if checkpoint_dir.is_dir():
                            try:
                                shutil.rmtree(checkpoint_dir)
                                print(f"  ✓ Removed checkpoint directory: {checkpoint_dir.name}")
                            except Exception as e:
                                print(f"  ⚠ Could not remove checkpoint directory {checkpoint_dir}: {e}")

                    # Save lab info.
                    lab_info_file = lab_dir / "lab_info.txt"
                    with open(lab_info_file, 'w', encoding='utf-8') as f:
                        f.write(f"Lab: {title}\n")
                        f.write(f"URL: {current_url}\n")
                        f.write(f"\nFiles downloaded from Lab files → Download all files\n")
                        f.write(f"Check the lab directory for all downloaded files.\n")

                    print(f"  ✓ Lab processing complete")
                else:
                    # CRITICAL: If lab files were not downloaded, raise an error and stop.
                    error_msg = f"❌ CRITICAL ERROR: Lab files were NOT downloaded!\n"
                    error_msg += f"  Lab: {title}\n"
                    error_msg += f"  URL: {current_url}\n"
                    error_msg += f"  Expected: Files.zip in {self.download_dir}\n"
                    error_msg += f"  This is a critical failure - the script must stop.\n"
                    print(f"  {error_msg}")
                    raise RuntimeError(error_msg)

            except Exception as e:
                print(f"  ⚠ Error downloading lab files: {e}")
                import traceback
                traceback.print_exc()

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
                    # Try to switch back to any available window.
                    try:
                        if len(self.driver.window_handles) > 0:
                            self.driver.switch_to.window(self.driver.window_handles[0])
                    except WebDriverException:
                        pass
        return downloaded_something, downloaded_count
