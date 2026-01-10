import re
import time
import zipfile
import shutil
import json
import os
import hashlib
from pathlib import Path
from typing import Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from ..files import get_or_move_path
from ..utils import extract_slug, sanitize_filename


class LabExtractor:
    def __init__(self, driver, download_dir: Path, shared_assets_dir: Path):
        self.driver = driver
        self.download_dir = download_dir
        self.shared_assets_dir = shared_assets_dir
        self.labs_shared_assets_dir = self.shared_assets_dir / "labs"
        self.labs_shared_assets_dir.mkdir(exist_ok=True, parents=True)
        # Candidate directories to search for downloaded files
        self.search_dirs = [self.download_dir, Path.home() / "Downloads", Path.cwd()]

    def _update_ipynb_references(self, ipynb_path: Path, replacements: dict):
        """Update file references in .ipynb files to point to shared assets."""
        if not ipynb_path.exists() or not replacements:
            return

        try:
            # Calculate depth from coursera_downloads root
            # ipynb_path is coursera_downloads/course/module_n/lab_dir/file.ipynb
            depth = len(ipynb_path.parent.relative_to(self.download_dir).parts)
            dots = "../" * depth

            with open(ipynb_path, "r", encoding="utf-8") as f:
                notebook_content = json.load(f)

            # Pre-calculate replacement values to avoid repeated string concatenation
            final_replacements = {}
            for old_name, target_shared_name in replacements.items():
                new_rel_path = f"{dots}shared_assets/labs/{target_shared_name}"
                # Add variations for matching
                final_replacements[old_name] = new_rel_path
                # Add variation with backslashes for JSON/Windows context
                final_replacements[old_name.replace("/", "\\\\")] = (
                    new_rel_path.replace("/", "\\\\")
                )

            updated = False
            for cell in notebook_content.get("cells", []):
                if "source" in cell and isinstance(cell["source"], list):
                    source_lines = cell["source"]
                    new_source_lines = []
                    for line in source_lines:
                        original_line = line
                        for old_path, new_rel_path in final_replacements.items():
                            escaped_old_path = re.escape(old_path)

                            # 1. Match src attributes in HTML tags: src="old_path" or src='old_path'
                            # This handles the user's specific example: <img src="images/Plan.png" ...>
                            pattern_html_src = (
                                rf'(src\s*=\s*)(["\']){escaped_old_path}(["\'])'
                            )
                            line = re.sub(
                                pattern_html_src,
                                rf"\1\2{new_rel_path}\3",
                                line,
                                flags=re.IGNORECASE,
                            )

                            # 2. Match standard Markdown image/link syntax: [text](old_path)
                            pattern_markdown = rf"(\!\[.*?\]\()({escaped_old_path})(\))"
                            line = re.sub(
                                pattern_markdown,
                                rf"\1{new_rel_path}\3",
                                line,
                                flags=re.IGNORECASE,
                            )

                            # 3. Fallback: Match quoted strings that look like the path
                            pattern_quoted = rf'(["\']){escaped_old_path}(["\'])'
                            line = re.sub(
                                pattern_quoted,
                                rf"\1{new_rel_path}\2",
                                line,
                                flags=re.IGNORECASE,
                            )

                        if original_line != line:
                            updated = True
                        new_source_lines.append(line)
                    cell["source"] = new_source_lines

            if updated:
                with open(ipynb_path, "w", encoding="utf-8") as f:
                    json.dump(notebook_content, f, indent=4)
                print(f"    Updated references in {ipynb_path.name}")
        except (IOError, UnicodeDecodeError, json.JSONDecodeError) as e:
            print(f"    Error updating references in {ipynb_path.name}: {e}")

    def _download_individual_files(self, lab_dir: Path) -> list[Path]:
        """Fallback: Download files one by one from the side panel."""
        print(
            "  ⚠ 'Download all files' failed or timed out. Attempting individual downloads..."
        )
        downloaded_files_paths = []

        try:
            # Find the file list container.
            # It's usually a list of items above the "Download all files" button.
            # We look for 'a' tags that link to files.

            # Common selectors for file links in Coursera/Jupyter sidebars
            # They often have 'download' attribute or href pointing to /files/
            file_links = self.driver.find_elements(
                By.XPATH,
                "//div[contains(@class, 'rc-LabFile')]//a | "
                + "//a[contains(@class, 'file-link')] | "
                + "//li//a[contains(@href, '/files/')]",
            )

            if not file_links:
                # Fallback: find ANY link in the sidebar that isn't the "Download all files" button
                # Assuming the sidebar is the parent of the "Download all files" button
                try:
                    download_all_btn = self.driver.find_element(
                        By.XPATH, "//button[contains(., 'Download all files')] "
                    )
                    sidebar = download_all_btn.find_element(
                        By.XPATH,
                        "./ancestor::div[contains(@class, 'rc-LabFiles')] | ./ancestor::div[contains(@class, 'c-modal-content')]",
                    )
                    file_links = sidebar.find_elements(By.TAG_NAME, "a")
                except NoSuchElementException:
                    pass

            unique_links = []
            seen_hrefs = set()
            for link in file_links:
                try:
                    href = link.get_attribute("href")
                    if href and href not in seen_hrefs and "download_all" not in href:
                        # Filter out navigation links if possible
                        if "/tree/" in href or "/lab" in href:
                            continue  # likely a folder navigation or lab link

                        unique_links.append(link)
                        seen_hrefs.add(href)
                except StaleElementReferenceException:
                    continue

            print(f"  Found {len(unique_links)} potential file links.")

            for link in unique_links:
                try:
                    # Get filename
                    href = link.get_attribute("href")
                    filename = href.split("/")[-1].split("?")[0]
                    if not filename:
                        filename = link.text.strip() or "untitled_file"

                    # Sanitize
                    filename = (
                        sanitize_filename(Path(filename).stem) + Path(filename).suffix
                    )
                    target_path = lab_dir / filename

                    if target_path.exists():
                        continue

                    print(f"    Clicking file: {filename}")
                    link.click()

                    # Wait a bit for download to start/finish
                    time.sleep(2)

                    # Check if file appeared in any candidate download directory
                    for attempt in range(10):
                        found = False
                        for dir_path in self.search_dirs:
                            potential_file = dir_path / filename
                            if potential_file.exists():
                                shutil.move(str(potential_file), str(target_path))
                                downloaded_files_paths.append(target_path)
                                print(
                                    f"    Downloaded (from {dir_path.name}): {filename}"
                                )
                                found = True
                                break
                        if found:
                            break
                        time.sleep(1)

                except (WebDriverException, OSError) as e:
                    print(f"    Failed to download link: {e}")

        except WebDriverException as e:
            print(f"  Error during individual download: {e}")

        return downloaded_files_paths

    def _download_via_selection(self, lab_dir: Path) -> list[Path]:
        """
        Downloads files one by one by selecting them individually and clicking Download.
        Returns a list of paths to the downloaded files.
        """
        print("  Attempting download via individual file selection...")
        downloaded_files_paths = []

        try:
            # Initial find of checkboxes
            checkboxes = self.driver.find_elements(
                By.XPATH, "//input[@type='checkbox']"
            )
            if not checkboxes:
                print("  ℹ No checkboxes found.")
                return []

            # We need to re-find elements in the loop to avoid staleness,
            # so we'll just loop by index.
            # First, count how many valid checkboxes there are roughly
            count = len(checkboxes)

            for i in range(count):
                try:
                    # Re-find checkboxes to avoid StaleElementReferenceException
                    checkboxes = self.driver.find_elements(
                        By.XPATH, "//input[@type='checkbox']"
                    )
                    if i >= len(checkboxes):
                        break

                    checkbox = checkboxes[i]

                    # Find parent label and check name
                    try:
                        label = checkbox.find_element(By.XPATH, "./parent::label")
                        aria_label = label.get_attribute("aria-labelledby") or ""

                        # Skip checkpoints
                        if ".ipynb_checkpoints" in aria_label:
                            continue
                    except NoSuchElementException:
                        continue

                    # Determine filename from aria-label or associated link
                    # aria-label is often like "/home/jovyan/work/Filename.ipynb"
                    # We want just "Filename.ipynb"
                    filename_raw = Path(aria_label).name
                    if not filename_raw:
                        filename_raw = f"file_{i}.dat"  # Fallback

                    filename_sanitized = (
                        sanitize_filename(Path(filename_raw).stem)
                        + Path(filename_raw).suffix
                    )
                    target_path = lab_dir / filename_sanitized

                    if target_path.exists():
                        print(f"    Skipping existing: {target_path.name}")
                        continue

                    # 1. Select the checkbox
                    if not checkbox.is_selected():
                        label.click()
                        time.sleep(0.2)

                    # 2. Click Download
                    download_btns = self.driver.find_elements(
                        By.XPATH, "//button[contains(., 'Download')]"
                    )
                    valid_btns = [
                        b for b in download_btns if b.is_displayed() and b.is_enabled()
                    ]

                    target_btn = None
                    # Prefer "Download" over "Download all files"
                    for btn in valid_btns:
                        if "all files" not in btn.text.lower():
                            target_btn = btn
                            break
                    if not target_btn and valid_btns:
                        target_btn = valid_btns[0]

                    if target_btn:
                        # print(f"    ⬇ Downloading: {filename_raw}")
                        self.driver.execute_script("arguments[0].click();", target_btn)

                        # 3. Wait for download
                        # Check in any candidate download directory
                        file_downloaded = False
                        for attempt in range(15):  # Wait up to 15s
                            for dir_path in self.search_dirs:
                                potential_file = dir_path / filename_raw
                                if potential_file.exists():
                                    shutil.move(str(potential_file), str(target_path))
                                    downloaded_files_paths.append(target_path)
                                    print(
                                        f"    Downloaded (from {dir_path.name}): {filename_raw}"
                                    )
                                    file_downloaded = True
                                    break
                            if file_downloaded:
                                break
                            time.sleep(1)

                        if not file_downloaded:
                            print(f"    Timeout waiting for: {filename_raw}")

                    # 4. Deselect
                    # Re-find checkbox again just in case
                    checkboxes = self.driver.find_elements(
                        By.XPATH, "//input[@type='checkbox']"
                    )
                    if i < len(checkboxes):
                        checkbox = checkboxes[i]
                        if checkbox.is_selected():
                            # Re-find label
                            label = checkbox.find_element(By.XPATH, "./parent::label")
                            label.click()
                            time.sleep(0.1)

                except (WebDriverException, OSError) as e:
                    print(f"    Error downloading file index {i}: {e}")
                    continue

            if len(downloaded_files_paths) > 0:
                print(
                    f"  Downloaded {len(downloaded_files_paths)} files via selection."
                )
            else:
                print("  No files downloaded via selection.")

            return downloaded_files_paths

        except WebDriverException as e:
            print(f"  Error in _download_via_selection: {e}")
            return downloaded_files_paths

    def _handle_barriers(self):
        """Handle 'Continue' or 'Agree' buttons that might appear before the launch button."""
        # Handle "Continue Learning" specifically by closing it if possible
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
                closed = False
                for sel in close_selectors:
                    close_btns = self.driver.find_elements(By.XPATH, sel)
                    for c_btn in close_btns:
                        if c_btn.is_displayed():
                            self.driver.execute_script("arguments[0].click();", c_btn)
                            print("  Closed 'Continue Learning' popup")
                            time.sleep(2)
                            closed = True
                            break
                    if closed:
                        break
        except Exception:
            pass

        barriers = ["Continue", "I agree", "Agree", "Accept", "Confirm", "I understand"]
        clicked = False
        for b_text in barriers:
            xpath = f"//button[contains(., '{b_text}')] | //a[contains(., '{b_text}')] | //span[text()='{b_text}']/ancestor::button"
            btns = self.driver.find_elements(By.XPATH, xpath)
            for btn in btns:
                if btn.is_displayed() and btn.is_enabled():
                    # Avoid search buttons
                    if "rc-InCourseSearchBar" in btn.get_attribute("outerHTML"):
                        continue
                    btn_label = btn.text.strip() or b_text
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});", btn
                    )
                    time.sleep(1)
                    self.driver.execute_script("arguments[0].click();", btn)
                    print(f"  Clicked lab barrier: '{btn_label}'")
                    time.sleep(3)
                    clicked = True
                    break

    def process(
        self,
        course_dir: Path,
        module_dir: Path,
        item_counter: int,
        title: str,
        item_url: str,
    ) -> Tuple[bool, int]:
        """Process and download Jupyter lab notebooks and data files."""
        downloaded_count = 0
        downloaded_something = False
        original_window = None
        lab_window = None

        print(f"  Processing lab...")

        # 1. Determine target directory name using slug (for consistency with find_items)
        slug = extract_slug(item_url)
        # Use slug if available, otherwise fall back to title
        base_name = slug if slug else sanitize_filename(title)

        # Avoid double _lab suffix
        if base_name.endswith("_lab"):
            target_dir_name = f"{item_counter:03d}_{base_name}"
        else:
            target_dir_name = f"{item_counter:03d}_{base_name}_lab"

        # 2. Check for existing directory with different name (e.g. based on title) and rename it
        # This fixes the issue where find_items (using slug) fails but folder exists (using title)
        if module_dir.exists():
            for item in module_dir.iterdir():
                if (
                    item.is_dir()
                    and item.name.startswith(f"{item_counter:03d}_")
                    and item.name.endswith("_lab")
                ):
                    if item.name != target_dir_name:
                        print(
                            f"  Renaming existing lab directory: {item.name} -> {target_dir_name}"
                        )
                        item.rename(module_dir / target_dir_name)

        # 3. Get path (now possibly renamed)
        lab_dir = get_or_move_path(course_dir, module_dir, target_dir_name)

        # 4. Check if already completed (any .ipynb file exists)
        if any(lab_dir.rglob("*.ipynb")):
            print(f"  Lab already processed (found notebook files).")
            return False, 0

        # Remember the original window handle.
        original_window = self.driver.current_window_handle
        print(f"  Original window: {original_window}")

        # Try to remove messy elements before launching.
        try:
            self.driver.execute_script("""
                const messySelectors = [
                    '[data-ai-instructions="true"]',
                    '[data-testid="content-integrity-instructions"]',
                    '[data-testid="visually-hidden"]',
                    '[data-testid="like-button"]',
                    '[data-testid="dislike-button"]',
                    '[data-testid="part-points"]',
                    '[aria-label="Text Formatting"]',
                    '.rc-A11yScreenReaderOnly'
                ];
                messySelectors.forEach(selector => {
                    document.querySelectorAll(selector).forEach(el => el.remove());
                });
            """)
        except:
            pass

        # Handle barriers (Honor Code etc.) before launching
        url_before_barriers = self.driver.current_url
        self._handle_barriers()

        # If barrier clicking took us away from the lab page (e.g. to home), go back
        if "/home/" in self.driver.current_url or "/home?" in self.driver.current_url:
            print(f"  ℹ Redirected to home, returning to: {url_before_barriers}")
            self.driver.get(url_before_barriers)
            time.sleep(2)
        elif (
            self.driver.current_url != url_before_barriers
            and "/learn/" in self.driver.current_url
        ):
            print(f"  ℹ URL changed to: {self.driver.current_url}")

        # Launch lab.
        launch_clicked = False
        for btn_text in ["Launch Lab", "Open Tool", "Launch", "Continue"]:
            try:
                launch_btn = self.driver.find_element(
                    By.XPATH,
                    f"//button[contains(., '{btn_text}')] | //a[contains(., '{btn_text}')]",
                )
                if launch_btn.is_displayed() and launch_btn.is_enabled():
                    print(f"  ✓ Clicking '{btn_text}'...")
                    launch_btn.click()
                    launch_clicked = True
                    break
            except (NoSuchElementException, StaleElementReferenceException):
                continue

        if not launch_clicked:
            print(f"  Could not launch lab")
            return downloaded_something, downloaded_count

        # Wait for a new tab / window to open
        print(f"  Waiting for new tab to open...")
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
        print(f"  Waiting for lab environment to load (up to 60 seconds)...")
        WebDriverWait(self.driver, 60).until(
            lambda d: "/lab" in d.current_url and "path=" in d.current_url
        )
        print(f"  Lab loaded: {self.driver.current_url}")
        time.sleep(5)

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
            print(f"  Clicking 'Lab files' button...")
            lab_files_btn.click()
            time.sleep(2)
        else:
            error_msg = f"  CRITICAL ERROR: 'Lab files' button not found!\n"
            print(f"  {error_msg}")
            # Don't raise, just return, maybe manual intervention needed
            return downloaded_something, downloaded_count

        downloaded_files_in_lab = []  # Collect all downloaded files

        # Try to download via selection first (User preference)
        files_downloaded_via_selection_paths = self._download_via_selection(lab_dir)
        if files_downloaded_via_selection_paths:
            downloaded_files_in_lab.extend(files_downloaded_via_selection_paths)
            downloaded_something = True

        zip_downloaded = False
        if not files_downloaded_via_selection_paths:  # Only try zip if selection failed
            # Fallback: Download all files button
            print(f"  Looking for 'Download all files' button (Fallback)...")
            download_all_btn = None
            for btn_selector in [
                "//button[contains(., 'Download all files')]",
                "//span[contains(text(), 'Download all files')]//ancestor::button",
                "//button[contains(@aria-label, 'Download all files')]",
            ]:
                try:
                    download_all_btn = self.driver.find_element(By.XPATH, btn_selector)
                    if (
                        download_all_btn.is_displayed()
                        and download_all_btn.is_enabled()
                    ):
                        break
                except (NoSuchElementException, StaleElementReferenceException):
                    continue

            if (
                download_all_btn
                and download_all_btn.is_displayed()
                and download_all_btn.is_enabled()
            ):
                print(f"  Clicking 'Download all files' button...")
                # Use JavaScript click to avoid interception.
                self.driver.execute_script("arguments[0].click();", download_all_btn)

                time.sleep(3)  # Give time for download to start.

                # Wait for ANY zip file to be downloaded and identify the correct one.
                print(f"  Waiting for zip file to download (30s timeout)...")
                downloaded_zip_file = None
                start_time = time.time()

                while time.time() - start_time < 30:
                    potential_zips = []
                    for dir_path in self.search_dirs:
                        for p in dir_path.glob("Files*.zip"):
                            potential_zips.append(p)

                    if potential_zips:
                        # Sort by modification time (most recent first)
                        potential_zips.sort(
                            key=lambda x: x.stat().st_mtime, reverse=True
                        )
                        # Pick the most recently modified one
                        downloaded_zip_file = potential_zips[0]
                        # Ensure it's not a partial download
                        if downloaded_zip_file.stat().st_size > 0:
                            break
                    time.sleep(1)

                    if downloaded_zip_file and downloaded_zip_file.exists():
                        print(f"  Zip file downloaded: {downloaded_zip_file.name}")

                        # Extract the zip file.
                        print(f"  Extracting {downloaded_zip_file.name}...")
                        with zipfile.ZipFile(downloaded_zip_file, "r") as zip_ref:
                            zip_ref.extractall(lab_dir)

                        # Identify the deepest directory that contains actual files
                        # Often it's Files/home/jovyan/work/
                        def find_content_root(current_path: Path):
                            children = list(current_path.iterdir())
                            visible_children = [
                                c for c in children if not c.name.startswith(".")
                            ]
                            if (
                                len(visible_children) == 1
                                and visible_children[0].is_dir()
                            ):
                                return find_content_root(visible_children[0])
                            return current_path

                        try:
                            content_root = find_content_root(lab_dir)
                            if content_root != lab_dir:
                                print(
                                    f"  📁 Flattening directory structure from: {content_root.relative_to(lab_dir)}"
                                )
                                for item in content_root.iterdir():
                                    dest = lab_dir / item.name
                                    if not dest.exists():
                                        shutil.move(str(item), str(dest))

                                # Clean up the now redundant top-level "Files" or similar
                                if not list(content_root.iterdir()):
                                    shutil.rmtree(content_root)

                        except Exception as e:
                            print(f"    Error while flattening: {e}")

                        # Always attempt to delete the zip file
                        if downloaded_zip_file and downloaded_zip_file.exists():
                            try:
                                downloaded_zip_file.unlink()
                                print(f"  Deleted {downloaded_zip_file.name}")
                            except OSError as e:
                                print(
                                    f"  Could not delete {downloaded_zip_file.name}: {e}"
                                )

                        # Proactive cleanup: remove any other Files*.zip
                        for dir_path in self.search_dirs:
                            try:
                                for junk_zip in dir_path.glob("Files*.zip"):
                                    if junk_zip.exists():
                                        junk_zip.unlink()
                                        print(f"  Cleaned up junk zip: {junk_zip.name}")
                            except (OSError, PermissionError):
                                pass
                    else:
                        print(f"  Zip file not found after download attempt.")

            # Identify all files currently in lab_dir for migration (from zip OR individual downloads)
            # We do this AFTER flattening to get correct paths.
            downloaded_files_in_lab = [f for f in lab_dir.rglob("*") if f.is_file()]
            if downloaded_files_in_lab:
                downloaded_something = True
            # --- Shared Assets Migration ---
        print(f"  Migrating shared assets...")
        replacements = {}
        ipynb_files = []

        # Iterate through all files that were downloaded into the lab_dir or extracted there.
        # We iterate a copy because items might be unlinked during the loop.
        for item in list(downloaded_files_in_lab):
            if not item.is_file():
                continue
            if item.name == "lab_info.txt":
                continue  # Skip internal files
            if item.suffix.lower() == ".ipynb":
                ipynb_files.append(item)
            else:
                # Move to shared assets
                # Combine original name with hash for descriptive uniqueness
                try:
                    item_hash = hashlib.md5(item.read_bytes()).hexdigest()[:8]
                except IOError as e:
                    print(f"    Could not read file {item.name} for hashing: {e}")
                    continue

                # Truncate the original stem to prevent excessively long filenames.
                MAX_BASENAME_LEN = 60
                stem = sanitize_filename(item.stem)
                if len(stem) > MAX_BASENAME_LEN:
                    stem = stem[:MAX_BASENAME_LEN]

                target_shared_name = f"{stem}_{item_hash}{item.suffix}"
                target_shared_path = self.labs_shared_assets_dir / target_shared_name

                try:
                    # Only copy if it doesn't already exist in shared assets
                    if not target_shared_path.exists():
                        shutil.copy2(item, target_shared_path)
                        downloaded_count += (
                            1  # Count actual new downloads to shared assets
                        )

                    # Store replacement mapping for ipynb files
                    # The key should be the path relative to the ipynb file's original location
                    # The value is the new shared asset filename

                    # Add relative path from lab_dir
                    try:
                        rel_path_in_lab = str(item.relative_to(lab_dir)).replace(
                            "\\", "/"
                        )
                        replacements[rel_path_in_lab] = target_shared_name
                    except ValueError:
                        # If item is not relative to lab_dir (e.g., already moved by flatten)
                        pass

                    # Also add simple filename
                    replacements[item.name] = target_shared_name

                    # Delete original to save space
                    item.unlink()
                except OSError as e:
                    print(f"    Error migrating {item.name}: {e}")

        # 2. Update references in notebooks
        for ipynb in ipynb_files:
            self._update_ipynb_references(ipynb, replacements)

        # 3. Clean up empty subdirectories
        # This needs to be done AFTER all files have potentially been moved out.
        # The existing logic should work for this.
        for root, dirs, files in os.walk(lab_dir, topdown=False):
            for name in dirs:
                dir_path = Path(root) / name
                try:
                    if not any(dir_path.iterdir()):
                        dir_path.rmdir()
                except OSError:
                    pass
        # -------------------------------

        # Recursive cleanup of any .ipynb_checkpoints
        for checkpoint_dir in lab_dir.rglob(".ipynb_checkpoints"):
            if checkpoint_dir.is_dir():
                try:
                    shutil.rmtree(checkpoint_dir)
                except OSError:
                    pass

        if len(downloaded_files_in_lab) > 0:
            downloaded_something = True

        if downloaded_something:
            print(f"  Lab processing complete")
        else:
            print(f"  No files downloaded for this lab.")

        # Clean up: close the lab tab and switch back to the original window.
        if lab_window and original_window:
            try:
                # Check if the lab window is still open.
                if lab_window in self.driver.window_handles:
                    print(f"  Closing lab tab...")
                    self.driver.switch_to.window(lab_window)
                    self.driver.close()
                    print(f"  Lab tab closed")

                # Switch back to the original window.
                if original_window in self.driver.window_handles:
                    print(f"  Switching back to original window...")
                    self.driver.switch_to.window(original_window)
                    print(f"  Back to course page")
            except WebDriverException as e:
                print(f"  Error during cleanup: {e}")
                try:
                    if len(self.driver.window_handles) > 0:
                        self.driver.switch_to.window(self.driver.window_handles[0])
                except WebDriverException:
                    pass
        return downloaded_something, downloaded_count
