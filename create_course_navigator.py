import os
import re
from pathlib import Path
from bs4 import BeautifulSoup

ROOT_DIR = Path("coursera_downloads")

# CSS for the navigator
NAV_CSS = """
<style>
    /* Basic Layout */
    body { margin: 0; padding: 0; display: flex; font-family: "Open Sans", Arial, sans-serif; height: 100vh; overflow: hidden; }
    #app-container { display: flex; width: 100%; height: 100%; }
    
    /* Sidebar */
    #sidebar {
        width: 350px;
        background: #f7f7f7;
        border-right: 1px solid #ddd;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        flex-shrink: 0;
    }
    
    .sidebar-header { padding: 16px; background: #fff; border-bottom: 1px solid #eee; }
    .sidebar-header h2 { margin: 0; font-size: 16px; color: #333; }
    
    /* Module Accordion */
    .module-group { border-bottom: 1px solid #eee; background: #fff; }
    .module-header {
        padding: 12px 16px;
        cursor: pointer;
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #fff;
        font-weight: 600;
        font-size: 14px;
        color: #333;
    }
    .module-header:hover { background: #f0f0f0; }
    .module-content { display: none; }
    .module-group.open .module-content { display: block; }
    .module-arrow { transition: transform 0.2s; }
    .module-group.open .module-arrow { transform: rotate(180deg); }

    /* Items */
    .nav-item {
        display: block;
        padding: 10px 16px 10px 40px;
        text-decoration: none;
        color: #555;
        font-size: 13px;
        border-left: 3px solid transparent;
    }
    .nav-item:hover { background: #f5f5f5; color: #0056D2; }
    .nav-item.active {
        background: #e6f0fa;
        color: #0056D2;
        border-left-color: #0056D2;
        font-weight: 600;
    }
    .item-icon { margin-right: 8px; font-size: 14px; }

    /* Main Content Area */
    #main-content {
        flex: 1;
        width: 100%;
        min-width: 0;
        overflow-y: auto;
        padding: 0;
        position: relative;
        background: #fff;
    }
    
    /* Video Player */
    .video-container {
        display: flex;
        justify-content: center;
        align-items: center;
        height: 100%;
        background: #000;
    }
    video { max-width: 100%; max-height: 100%; }

    /* Original Content Styling Preservation */
    .content-wrapper { width: 100%; max-width: none; margin: 0; padding: 20px; box-sizing: border-box; }
    .content-wrapper img { max-width: 100%; height: auto; object-fit: contain; }
    
    /* AI Summary RTL support */
    .ai-summary-box { 
        direction: rtl !important; 
        text-align: right !important; 
        font-family: "Segoe UI", "David", "Arial", sans-serif; 
        line-height: 1.6;
    }
    .ai-summary-box h1, .ai-summary-box h2, .ai-summary-box h3 { text-align: right !important; }
    .ai-summary-box ul { padding-right: 40px; padding-left: 0; }
</style>
"""

NAV_JS = """
<script>
    function toggleModule(header) {
        header.parentElement.classList.toggle('open');
    }
    
    document.addEventListener('DOMContentLoaded', () => {
        const active = document.querySelector('.nav-item.active');
        if (active) {
            active.closest('.module-group').classList.add('open');
            active.scrollIntoView({ block: 'center' });
        }
    });
</script>
"""


def generate_sidebar_html(course_tree, current_file_path):
    sidebar_html = (
        '<div id="sidebar"><div class="sidebar-header"><h2>Course Outline</h2></div>'
    )

    current_path_obj = Path(current_file_path)

    for module in course_tree["modules"]:
        # Check if active
        is_module_active = False
        for item in module["items"]:
            # Compare resolved paths or just filenames if unique enough?
            # We used absolute paths in the tree construction, let's stick to that.
            if Path(item["nav_path"]).resolve() == current_path_obj.resolve():
                is_module_active = True
                break

        active_class = " open" if is_module_active else ""

        sidebar_html += f"""
        <div class="module-group{active_class}">
            <div class="module-header" onclick="toggleModule(this)">
                <span>{module["name"]}</span>
                <span class="module-arrow">▼</span>
            </div>
            <div class="module-content">
        """

        for item in module["items"]:
            # Create relative link
            target_path = Path(item["nav_path"]).resolve()
            current_parent = current_path_obj.parent.resolve()
            try:
                rel_link = os.path.relpath(target_path, current_parent)
            except ValueError:
                # Fallback if on different drives on Windows, but should not happen in standalone folder
                rel_link = target_path.name

            is_item_active = (
                " active" if target_path == current_path_obj.resolve() else ""
            )
            icon = "🎥" if item["type"] == "video" else "📄"

            sidebar_html += f'<a href="{rel_link}" class="nav-item{is_item_active}"><span class="item-icon">{icon}</span>{item["title"]}</a>'

        sidebar_html += "</div></div>"

    sidebar_html += "</div>"
    return sidebar_html


def process_html_file(file_path, course_tree):
    """
    Injects sidebar into existing HTML file.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")

        # 1. Clean up previous injections to prevent duplication
        # We look for styles that contain our signature or common layout IDs
        for style in soup.find_all("style"):
            if (
                "#app-container" in style.string
                or "#sidebar" in style.string
                or ".content-wrapper" in style.string
            ):
                style.decompose()

        for script in soup.find_all("script"):
            if "toggleModule" in script.string or "auto-advance" in script.string:
                script.decompose()

        # 2. Extract original content
        existing_wrapper = soup.find(class_="content-wrapper")
        if existing_wrapper:
            original_body = existing_wrapper.decode_contents()
        else:
            original_body = soup.body.decode_contents() if soup.body else str(soup)

        # 3. Handle the Head - remove conflicting body styles from the scraper if possible
        # Some scrapers put styles in a <style> block that target 'body'
        if soup.head:
            for style in soup.head.find_all("style"):
                # If a style block only contains the body max-width rule, we can be aggressive
                if "body" in style.string and "max-width" in style.string:
                    # We'll just override it in our NAV_CSS instead of deleting it,
                    # as it might contain other useful styles.
                    pass
            original_head = soup.head.decode_contents()
        else:
            original_head = ""

        sidebar = generate_sidebar_html(course_tree, file_path)

        # 4. Construct new HTML with aggressive overrides
        new_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    {original_head}
    {NAV_CSS}
    <style>
        /* Aggressive Overrides to force full width */
        body {{ 
            display: flex !important; 
            max-width: none !important; 
            width: 100% !important; 
            margin: 0 !important; 
            padding: 0 !important; 
        }}
        #app-container {{ 
            width: 100% !important; 
            height: 100vh !important; 
        }}
    </style>
</head>
<body>
    <div id="app-container">
        {sidebar}
        <div id="main-content">
            <div class="content-wrapper">
                {original_body}
            </div>
        </div>
    </div>
    {NAV_JS}
</body>
</html>"""

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_html)

    except Exception as e:
        print(f"Error processing {file_path}: {e}")


def create_video_html(video_path, html_path, course_tree):
    """
    Creates a new HTML file for the video player.
    """
    sidebar = generate_sidebar_html(course_tree, html_path)
    video_rel = video_path.name

    # Check for subtitles
    sub_tracks = ""
    base_name = video_path.stem
    parent = video_path.parent

    # Check en/he vtt
    vtt_en = parent / f"{base_name}_en.vtt"
    vtt_he = parent / f"{base_name}_heb.vtt"

    if vtt_he.exists():
        sub_tracks += f'<track kind="subtitles" label="Hebrew" srclang="he" src="{vtt_he.name}" default>'
    if vtt_en.exists():
        default_attr = "" if vtt_he.exists() else "default"
        sub_tracks += f'<track kind="subtitles" label="English" srclang="en" src="{vtt_en.name}" {default_attr}>'

    # Add video features script (Auto-advance + Preferences)
    video_script = """
    <script>
        const video = document.querySelector('video');

        // --- Preferences Persistence ---
        function loadPreferences() {
            const savedSpeed = localStorage.getItem('coursera_video_speed');
            const savedVolume = localStorage.getItem('coursera_video_volume');
            
            if (savedSpeed) {
                video.playbackRate = parseFloat(savedSpeed);
            }
            if (savedVolume) {
                video.volume = parseFloat(savedVolume);
            }
        }

        video.addEventListener('loadedmetadata', loadPreferences);
        
        video.addEventListener('ratechange', () => {
            localStorage.setItem('coursera_video_speed', video.playbackRate);
        });

        video.addEventListener('volumechange', () => {
            localStorage.setItem('coursera_video_volume', video.volume);
        });

        // --- Auto-advance ---
        video.addEventListener('ended', () => {
            const activeItem = document.querySelector('.nav-item.active');
            if (activeItem) {
                const navItems = Array.from(document.querySelectorAll('.nav-item'));
                const currentIndex = navItems.indexOf(activeItem);
                if (currentIndex >= 0 && currentIndex < navItems.length - 1) {
                    const nextItem = navItems[currentIndex + 1];
                    window.location.href = nextItem.href;
                }
            }
        });
    </script>
    """

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{video_path.stem.replace("_", " ").title()}</title>
    {NAV_CSS}
</head>
<body>
    <div id="app-container">
        {sidebar}
        <div id="main-content" style="padding:0; overflow:hidden;">
            <div class="video-container">
                <video controls autoplay>
                    <source src="{video_rel}" type="video/mp4">
                    {sub_tracks}
                    Your browser does not support the video tag.
                </video>
            </div>
        </div>
    </div>
    {NAV_JS}
    {video_script}
</body>
</html>"""

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def create_lab_html(lab_dir_path, html_path, course_tree):
    """
    Creates a new HTML file for the lab, listing Jupyter notebooks.
    """
    sidebar = generate_sidebar_html(course_tree, html_path)

    lab_content = '<div class="content-wrapper"><h1>Lab Resources</h1>'
    lab_content += """
    <div class="ai-summary-box" style="direction: ltr !important; text-align: left !important; background: #f8f9fa; border: 1px solid #e9ecef; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
        <h3 style="margin-top: 0;">How to view these notebooks</h3>
        <p>These links will open the notebooks in your local Jupyter Lab instance.</p>
        <ol>
            <li>Open a terminal in the root of your project folder (e.g., <code>coursera_scraper</code>)</li>
            <li>Run the command: <code>jupyter lab</code></li>
            <li>Keep the terminal open and click the links below</li>
        </ol>
        <p><strong>Note:</strong> If you haven't installed Jupyter Lab, run: <code>pip install jupyterlab</code></p>
    </div>
    <ul>
    """

    # Find notebooks
    notebooks = sorted(list(lab_dir_path.glob("*.ipynb")))

    if not notebooks:
        lab_content += "<li>No notebooks found in this lab directory.</li>"
    else:
        for nb in notebooks:
            # Construct localhost URL for Jupyter Lab
            # Assumes running from project root
            # Path must be relative to project root
            # lab_dir_path is already relative to project root in this context

            # nb is a Path object fully qualified or relative?
            # In previous steps, it seemed `notebooks` list contains Paths relative to CWD if globbed from there?
            # Actually `lab_dir_path.glob` yields paths relative to `lab_dir_path`'s base? No, it yields paths relative to CWD if `lab_dir_path` is relative to CWD.
            # `lab_dir_path` comes from `module_dir`, which comes from `course_dir`.
            # `course_dir` comes from `ROOT_DIR` which is `Path("coursera_downloads")`.
            # So `nb` is e.g. `coursera_downloads/course/module/lab/notebook.ipynb`.

            project_rel_path = nb
            # Convert backslashes to forward slashes for URL
            url_path = project_rel_path.as_posix()

            link = f"http://localhost:8888/lab/tree/{url_path}"

            lab_content += f'<li><a href="{link}" target="_blank">Open {nb.name} in Jupyter Lab</a></li>'

    lab_content += "</ul></div>"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{lab_dir_path.stem.replace("_", " ").title()}</title>
    {NAV_CSS}
</head>
<body>
    <div id="app-container">
        {sidebar}
        <div id="main-content">
            {lab_content}
        </div>
    </div>
    {NAV_JS}
</body>
</html>"""

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def generate_course_navigation(course_dir: Path):
    """
    Generates navigation wrappers for a single course directory.
    """
    if course_dir.name.startswith(".") or course_dir.name == "shared_assets":
        return

    print(f"Indexing course content for {course_dir.name}...")

    course_struct = {"name": course_dir.name, "modules": []}

    for module_dir in sorted(
        [d for d in course_dir.iterdir() if d.is_dir()], key=lambda x: x.name
    ):
        module_name = module_dir.name.replace("_", " ").lower()
        module_struct = {"name": module_name, "items": []}

        # Find groups
        # We need to look at both files and directories (for labs)
        all_items = sorted([x for x in module_dir.iterdir()], key=lambda x: x.name)
        processed_prefixes = set()

        for f in all_items:
            if f.suffix == ".html" and f.name.endswith("_view.html"):
                continue  # Skip old wrappers

            # Identify labs (directories)
            is_lab = f.is_dir()

            match = re.match(r"(\d+)_", f.name)
            if not match:
                continue
            prefix = match.group(1)
            if prefix in processed_prefixes:
                continue

            base_name = f.stem
            title = base_name.replace(f"{prefix}_", "").replace("_", " ").title()

            mp4_file = list(module_dir.glob(f"{prefix}_*.mp4"))
            html_file = list(module_dir.glob(f"{prefix}_*.html"))
            # Filter out _view.html from candidates
            html_file = [h for h in html_file if not h.name.endswith("_view.html")]

            # Check for lab directory if current item isn't it (though we are iterating all items)
            # Actually, if 'f' is a directory and matches prefix, it IS the lab.
            # But we might have processed it already if we hit a file with same prefix first?
            # Sorted order usually puts files before directories or similar?
            # Actually standard alphanumeric sort: '001_...' file vs '001_...' dir
            # Let's just trust processed_prefixes.

            item = None
            if is_lab and (list(f.glob("*.ipynb")) or "_lab" in f.name):
                # It is a lab directory
                lab_html_name = f.name + ".html"
                # We want the HTML to be in the module dir, outside the lab dir?
                # Or we can put it inside? The request implies "pages for the labs".
                # Let's put the generated HTML in the module directory, named after the lab directory.
                nav_path = module_dir / lab_html_name

                item = {
                    "title": title + " (Lab)",
                    "type": "lab",
                    "asset_path": f,  # The directory
                    "nav_path": nav_path,
                    "is_video": False,
                    "is_lab": True,
                }

            elif mp4_file:
                # Target is the new HTML wrapper we WILL create
                vid_path = mp4_file[0]
                # New HTML name: same as video but .html
                nav_path = vid_path.with_suffix(".html")

                item = {
                    "title": title,
                    "type": "video",
                    "asset_path": vid_path,
                    "nav_path": nav_path,
                    "is_video": True,
                    "is_lab": False,
                }
            elif html_file:
                # Target is the existing HTML file we WILL modify
                h_path = html_file[0]
                item = {
                    "title": title,
                    "type": "reading",
                    "asset_path": h_path,
                    "nav_path": h_path,
                    "is_video": False,
                    "is_lab": False,
                }

            if item:
                module_struct["items"].append(item)
                processed_prefixes.add(prefix)

        if module_struct["items"]:
            course_struct["modules"].append(module_struct)

    if not course_struct["modules"]:
        print(f"  No modules found in {course_dir.name}")
        return

    # Generation Phase
    print(f"Injecting navigation for {course_dir.name}...")
    for module in course_struct["modules"]:
        for item in module["items"]:
            if item.get("is_lab"):
                create_lab_html(item["asset_path"], item["nav_path"], course_struct)
            elif item["is_video"]:
                create_video_html(item["asset_path"], item["nav_path"], course_struct)
            else:
                process_html_file(item["nav_path"], course_struct)


def scan_and_generate(root_dir):
    print("Scanning for courses...")
    for course_dir in sorted([d for d in root_dir.iterdir() if d.is_dir()]):
        if course_dir.name.startswith(".") or course_dir.name == "shared_assets":
            continue
        generate_course_navigation(course_dir)
    print("Done! Navigation injected.")


if __name__ == "__main__":
    scan_and_generate(ROOT_DIR)
