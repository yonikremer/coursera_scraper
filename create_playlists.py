import re
from pathlib import Path

ROOT_DIR = Path("coursera_downloads")


def write_wpl(
    playlist_path: Path, title: str, video_paths: list[Path], relative_to: Path = None
):
    """
    Writes a .wpl playlist file with the given title and video paths.
    If relative_to is provided, uses paths relative to that directory.
    Otherwise, uses absolute paths.
    """
    with open(playlist_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<?wpl version="1.0"?>\n')
        f.write("<smil>\n")
        f.write("    <head>\n")
        f.write('        <meta name="Generator" content="CourseraScraper"/>\n')
        f.write(f"        <title>{title}</title>\n")
        f.write("    </head>\n")
        f.write("    <body>\n")
        f.write("        <seq>\n")

        for vid in video_paths:
            if relative_to:
                try:
                    # Get path relative to the playlist location
                    path_str = str(vid.relative_to(relative_to))
                except ValueError:
                    # Fallback if not on same drive or path
                    path_str = str(vid.resolve())
            else:
                # Use absolute path
                path_str = str(vid.resolve())

            # Ensure backslashes for Windows
            win_path = path_str.replace("/", "\\")

            # Escape path for XML attribute
            xml_path = (
                win_path.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )
            f.write(f'            <media src="{xml_path}"/>\n')

        f.write("        </seq>\n")
        f.write("    </body>\n")
        f.write("</smil>\n")


def module_sort_key(p):
    name = p.name.lower()
    match = re.search(r"module_(\d+)", name)
    if match:
        return int(match.group(1))
    return name


def create_playlists_for_course(course_dir: Path):
    """
    Generates .wpl playlists for the entire course and for each individual module.
    """
    print(f"  Processing course: {course_dir.name}")

    all_course_videos = []

    # Get module directories, sorted
    modules = sorted(
        [d for d in course_dir.iterdir() if d.is_dir()], key=module_sort_key
    )

    for module in modules:
        # Find all mp4 files in the module
        mp4s = sorted(
            [f for f in module.iterdir() if f.is_file() and f.suffix.lower() == ".mp4"]
        )

        if mp4s:
            # Create module-level playlist
            module_playlist_name = f"{module.name}.wpl"
            module_playlist_path = module / module_playlist_name
            module_title = f"{course_dir.name} - {module.name}".replace(
                "_", " "
            ).title()

            # Use relative paths for module playlists (portable within the folder)
            write_wpl(module_playlist_path, module_title, mp4s, relative_to=module)
            print(f"    [Module] Created {module_playlist_name}")

            all_course_videos.extend(mp4s)

    if all_course_videos:
        # Create course-level master playlist
        course_playlist_name = f"Full_Course_{course_dir.name}.wpl"
        course_playlist_path = course_dir / course_playlist_name
        course_title = course_dir.name.replace("_", " ").title()

        # Use relative paths for the full course playlist as well
        write_wpl(
            course_playlist_path,
            course_title,
            all_course_videos,
            relative_to=course_dir,
        )
        print(
            f"    [Course] Created {course_playlist_name} "
            f"({len(all_course_videos)} videos)"
        )
    else:
        print(f"    [Skipping] No videos found in {course_dir.name}")


def process_all_courses(root_dir=None):
    base_dir = Path(root_dir) if root_dir else ROOT_DIR
    print(f"Scanning {base_dir} for courses...")
    if not base_dir.exists():
        print(f"Directory {base_dir} does not exist.")
        return

    # Iterate over immediate subdirectories of coursera_downloads
    for course_dir in base_dir.iterdir():
        if course_dir.is_dir() and not course_dir.name.startswith("."):
            if course_dir.name == "shared_assets":
                continue
            create_playlists_for_course(course_dir)


if __name__ == "__main__":
    process_all_courses()
