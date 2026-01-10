import os
import re
import json
from pathlib import Path

def sanitize_filename(filename: str) -> str:
    """Exact same logic as coursera/utils.py"""
    if not filename:
        return "untitled"
    # Replace invalid characters and punctuation with underscores.
    sanitized = re.sub(r'[<>:"/\\|?*,!]', '_', filename)
    # Handle ellipsis and multiple dots (replace with single underscore).
    sanitized = re.sub(r'\.{2,}', '_', sanitized)
    # Replace spaces and hyphens with underscores.
    sanitized = sanitized.replace(' ', '_').replace('-', '_')
    # Convert to lowercase.
    sanitized = sanitized.lower()
    # Remove multiple consecutive underscores.
    sanitized = re.sub(r'_+', '_', sanitized)
    # Strip leading/trailing underscores.
    sanitized = sanitized.strip('_')
    return sanitized or "untitled"

def fix_notebooks(download_dir: Path):
    shared_labs_dir = download_dir / "shared_assets" / "labs"
    if not shared_labs_dir.exists():
        print(f"Error: Shared assets directory not found at {shared_labs_dir.absolute()}")
        return

    # 1. Index shared assets: sanitized_stem -> hashed_filename
    # Migration naming scheme: {truncated_sanitized_stem}_{hash}{suffix}
    shared_assets_index = {}
    # Regex to extract the stem part before the 8-char hash
    pattern_hash = re.compile(r"(.+)_([0-9a-f]{8})(\.[^.]+)$")
    
    print(f"Indexing shared assets in {shared_labs_dir}...")
    for f in shared_labs_dir.iterdir():
        if f.is_file():
            match = pattern_hash.match(f.name)
            if match:
                stem = match.group(1)
                # Store using the stem as key (already sanitized/truncated during migration)
                shared_assets_index[stem.lower()] = f.name
            else:
                # Fallback for any files that might not follow the exact pattern
                shared_assets_index[sanitize_filename(f.stem).lower()] = f.name

    print(f"✓ Indexed {len(shared_assets_index)} shared assets.")

    # 2. Walk through all .ipynb files
    notebook_count = 0
    fixed_count = 0
    
    # We walk the parent directory of coursera_downloads or current dir
    search_root = download_dir.parent if download_dir.name == "coursera_downloads" else download_dir
    
    print(f"Searching for notebooks in {search_root.absolute()}...")
    for root, dirs, files in os.walk(search_root):
        # Skip the shared_assets folder itself to avoid infinite loops or fixing assets
        if "shared_assets" in root:
            continue
            
        for file in files:
            if file.endswith(".ipynb"):
                notebook_path = Path(root) / file
                # Ensure we are inside a course directory (relative to download_dir)
                try:
                    notebook_path.relative_to(download_dir)
                except ValueError:
                    continue
                    
                notebook_count += 1
                if fix_single_notebook(notebook_path, download_dir, shared_assets_index):
                    fixed_count += 1

    print(f"\nProcessing complete.")
    print(f"Total notebooks analyzed: {notebook_count}")
    print(f"Notebooks updated: {fixed_count}")

def fix_single_notebook(ipynb_path: Path, download_dir: Path, shared_assets_index: dict) -> bool:
    try:
        # Calculate depth to construct correct relative path (e.g. ../../shared_assets)
        # notebook is at coursera_downloads/course/module_n/lab_dir/notebook.ipynb
        rel_path = ipynb_path.parent.relative_to(download_dir)
        depth = len(rel_path.parts)
        dots = "../" * depth
        
        with open(ipynb_path, 'r', encoding='utf-8') as f:
            notebook_content = json.load(f)
            
        updated = False
        
        # Regex patterns to find potential paths
        # 1. HTML src attribute: src="path"
        pattern_html_src = re.compile(r'(src\s*=\s*)(["\'])(.*?)(["\'])', re.IGNORECASE)
        # 2. Markdown image syntax: ![alt](path)
        pattern_markdown = re.compile(r'(!\[.*?\]\()(.*?)(\))', re.IGNORECASE)

        for cell in notebook_content.get("cells", []):
            if "source" in cell and isinstance(cell["source"], list):
                new_source = []
                for line in cell["source"]:
                    new_line = line
                    
                    def replace_match(match):
                        nonlocal updated
                        groups = match.groups()
                        num_groups = len(groups)
                        
                        if num_groups == 4: # Likely HTML src=(quote)(path)(quote)
                            prefix, quote, old_path, suffix = groups
                        elif num_groups == 3: # Likely Markdown (prefix)(path)(suffix)
                            prefix, old_path, suffix = groups
                            quote = ""
                        else:
                            return match.group(0) # Unknown format, return unchanged
                        
                        # Normalize path for comparison
                        old_path_clean = old_path.strip().replace("\\", "/")
                        
                        # Skip if already points to shared assets
                        if "shared_assets/labs" in old_path_clean:
                            return match.group(0)
                            
                        # Extract the filename part
                        # e.g., "images/Plan.png" -> "Plan.png"
                        try:
                            filename_part = old_path_clean.split("/")[-1]
                            stem = filename_part.rsplit(".", 1)[0] if "." in filename_part else filename_part
                            
                            # Apply migration sanitization logic
                            sanitized_stem = sanitize_filename(stem)
                            if len(sanitized_stem) > 60:
                                sanitized_stem = sanitized_stem[:60]
                            
                            if sanitized_stem in shared_assets_index:
                                target_name = shared_assets_index[sanitized_stem]
                                # Construct the new relative path
                                new_rel_path = f"{dots}shared_assets/labs/{target_name}"
                                
                                # Convert to Windows style backslashes if the original had them
                                if "\\" in old_path:
                                    new_rel_path = new_rel_path.replace("/", "\\")
                                
                                updated = True
                                if quote: # HTML
                                    return f"{prefix}{quote}{new_rel_path}{suffix}"
                                else: # Markdown
                                    return f"{prefix}{new_rel_path}{suffix}"
                        except Exception:
                            pass
                            
                        return match.group(0)

                    # Apply replacements
                    new_line = pattern_html_src.sub(replace_match, new_line)
                    new_line = pattern_markdown.sub(replace_match, new_line)
                    
                    new_source.append(new_line)
                
                cell["source"] = new_source

        if updated:
            with open(ipynb_path, 'w', encoding='utf-8') as f:
                json.dump(notebook_content, f, indent=4)
            print(f"  [FIXED] {ipynb_path.relative_to(download_dir)}")
            return True
            
    except (json.JSONDecodeError, IOError, ValueError) as e:
        print(f"  [SKIP] {ipynb_path.name}: {e}")
        
    return False

if __name__ == "__main__":
    # Locate coursera_downloads relative to this script
    script_dir = Path(__file__).parent
    download_dir = script_dir / "coursera_downloads"
    
    if not download_dir.exists():
        # Try current working directory
        download_dir = Path("coursera_downloads")
        
    if not download_dir.exists():
        print("Could not find 'coursera_downloads' directory in script folder or CWD.")
    else:
        fix_notebooks(download_dir)
