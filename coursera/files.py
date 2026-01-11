import shutil
import time
from pathlib import Path
from typing import Set, List, Optional
import requests
import yt_dlp
import yt_dlp.utils
from .utils import extract_slug


def cleanup_stale_modules(course_dir: Path, valid_modules: Set[int]):
    """Delete module folders that are not in the valid_modules set."""
    if not course_dir.exists():
        return

    for item in course_dir.iterdir():
        if item.is_dir() and item.name.startswith("module_"):
            try:
                # Extract number.
                num_part = item.name.replace("module_", "")
                if num_part.isdigit():
                    module_num = int(num_part)
                    if module_num not in valid_modules:
                        print(f"  ♲ Deleting stale module directory: {item.name}")
                        shutil.rmtree(item)
            except OSError as e:
                print(f"  ⚠ Error cleaning up {item.name}: {e}")


def get_unique_search_dirs(course_dir: Path, module_dir: Path) -> List[Path]:
    """Get a list of unique directories to search for items (course root, current module, other modules)."""
    search_dirs = [course_dir, module_dir]
    if course_dir.exists():
        search_dirs.extend([d for d in course_dir.glob("module_*") if d.is_dir()])

    unique_search_dirs = []
    seen_resolved = set()
    for sd in search_dirs:
        if sd.exists():
            res = sd.resolve()
            if res not in seen_resolved:
                unique_search_dirs.append(sd)
                seen_resolved.add(res)
    return unique_search_dirs


def get_or_move_path(course_dir: Path, module_dir: Path, target_name: str) -> Path:
    """
    Check if a file or directory exists in the course directory (from old runs),
    move it to the module directory.
    Also handles fixing numbering prefixes and moving between modules.
    """
    target_path = module_dir / target_name

    # Ensure module directory exists.
    module_dir.mkdir(exist_ok=True, parents=True)

    # 1. If an item already exists in the module directory with the exact name, return it.
    if target_path.exists():
        return target_path

    # 2. Search for the item in all possible locations.
    unique_search_dirs = get_unique_search_dirs(course_dir, module_dir)

    # 2.1. Check for the exact name match in other directories.
    for sd in unique_search_dirs:
        if sd.resolve() == module_dir.resolve():
            continue
        source_path = sd / target_name
        if source_path.exists():
            print(
                f"  💾 Moving existing item to module directory: {target_name} (from {sd.name})"
            )
            try:
                shutil.move(str(source_path), str(target_path))
                return target_path
            except OSError as e:
                print(f"  ⚠ Error moving item: {e}")

    # 3. Fix numbering: check if an item exists with a different number prefix.
    # target_name is expected to be like "035_title.ext" or "035_title_assets".
    if len(target_name) > 4 and target_name[3] == "_":
        suffix = target_name[4:]
        for sd in unique_search_dirs:
            # Skip cross-module fuzzy matching (different prefix) to avoid collisions
            # where items in different modules have the same name (e.g. "Final Quiz").
            if sd.name.startswith("module_") and sd.resolve() != module_dir.resolve():
                continue

            # Look for items with any 3-digit prefix and the same suffix.
            for existing in sd.glob(f"[0-9][0-9][0-9]_{suffix}"):
                if existing.exists() and existing.resolve() != target_path.resolve():
                    print(
                        f"  ↗️ Correcting item number/location: {existing.name} (in {sd.name}) → {target_name}"
                    )
                    try:
                        shutil.move(str(existing), str(target_path))
                        return target_path
                    except OSError as e:
                        print(
                            f"  ⚠ Error correcting item number for {existing.name}: {e}"
                        )

    return target_path


def find_items(course_dir: Path, module_dir: Path, item_url: str = None) -> List[Path]:
    """
    Check if an item's materials already exist across any module or course directory.
    Relies on slug-based matching to handle re-ordering accurately and avoid prefix hijacking.
    """
    all_found = []

    # Get all directories to search (all modules + course root).
    unique_search_dirs = get_unique_search_dirs(course_dir, module_dir)

    # 1. Primary Search: Match by slug (best for identifying moved items).
    if item_url:
        slug = extract_slug(item_url)
        if slug:
            for directory in unique_search_dirs:
                # Match any 3-digit prefix followed by our slug.
                slug_matches = list(directory.glob(f"[0-9][0-9][0-9]_{slug}*"))
                all_found.extend(slug_matches)

    # Remove duplicates and resolve to actual paths.
    unique_found = []
    seen_paths = set()
    for p in all_found:
        resolved_p = str(p.resolve())
        if resolved_p not in seen_paths:
            unique_found.append(p)
            seen_paths.add(resolved_p)

    return unique_found


def download_file(url: str, filepath: Path, session: requests.Session) -> bool:
    """Download a file from URL."""
    try:
        if filepath.exists() and filepath.stat().st_size > 0:
            print(f"  ℹ File already exists, skipping: {filepath.name}")
            return True

        response = session.get(url, stream=True, timeout=30)
        response.raise_for_status()

        filepath.parent.mkdir(parents=True, exist_ok=True)

        # For small files (not videos), we can just use response.content to ensure proper decompression.
        if filepath.suffix.lower() not in [".mp4", ".zip"]:
            with open(filepath, "wb") as f:
                f.write(response.content)
        else:
            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

        return True
    except (requests.RequestException, OSError) as e:
        print(f"  ⚠ Error downloading {url}: {e}")
        return False


def download_video(
    video_url: str, filepath: Path, cookies: list = None, download_dir: Path = None
) -> bool:
    """Download video using yt-dlp."""
    try:
        cookies_file_path = None
        if cookies and download_dir:
            cookies_dict = {}
            for cookie in cookies:
                cookies_dict[cookie["name"]] = cookie["value"]

            cookies_file_path = download_dir / "cookies.txt"
            with open(cookies_file_path, "w") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for name, value in cookies_dict.items():
                    f.write(f".coursera.org\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")

        ydl_opts = {
            "outtmpl": str(filepath),
            "format": "best[height<=720]",
            "quiet": True,
            "no_warnings": True,
        }

        if cookies_file_path:
            ydl_opts["cookiefile"] = str(cookies_file_path)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        if cookies_file_path:
            cookies_file_path.unlink(missing_ok=True)
        return True

    except (yt_dlp.utils.DownloadError, OSError) as e:
        print(f"  ⚠ Error downloading video: {e}")
        return False
    except Exception as e:
        # Fallback for unexpected yt-dlp errors
        print(f"  ⚠ Unexpected video download error: {e}")
        return False
