import os
import re
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup
from coursera.utils import sanitize_filename

def fix_attachment_links(root_dir):
    """
    Scans HTML files in root_dir and replaces external attachment links 
    with relative links to local files.
    """
    root_path = Path(root_dir)
    html_files = list(root_path.rglob("*.html"))
    
    print(f"Found {len(html_files)} HTML files to process.")
    
    links_fixed = 0
    files_changed = 0

    for html_file in html_files:
        # We look for files in the same directory that look like attachments
        # Pattern: XXX_attachment_filename.ext
        parent_dir = html_file.parent
        local_files = [f for f in parent_dir.iterdir() if f.is_file() and "_attachment_" in f.name]
        
        if not local_files:
            continue

        try:
            with open(html_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            soup = BeautifulSoup(content, 'html.parser')
            modified = False
            
            # Find all links that look like downloads
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                
                # Skip already local links or empty ones
                if not href or not href.startswith(('http://', 'https://')):
                    continue
                
                # Logic to find matching local file
                # 1. Try to match by data-name if present (check on <a> and children)
                matched_file = None
                
                # Check data-name on <a> tag
                data_name = a_tag.get('data-name')
                
                # Check data-name on children (e.g. div inside a)
                if not data_name:
                    child_with_data = a_tag.find(attrs={"data-name": True})
                    if child_with_data:
                        data_name = child_with_data.get('data-name')
                
                if data_name:
                    clean_name = sanitize_filename(data_name)
                    # The local file should contain this clean name
                    for lf in local_files:
                        if f"_attachment_{clean_name}" in lf.name:
                            matched_file = lf
                            break
                
                # Strategy B: Check filename in URL (fallback)
                if not matched_file:
                    try:
                        parsed_url = urllib.parse.urlparse(href)
                        url_path = parsed_url.path
                        url_filename = os.path.basename(url_path)
                        if url_filename:
                            url_filename = urllib.parse.unquote(url_filename)
                            clean_url_name = sanitize_filename(url_filename)
                            
                            for lf in local_files:
                                if clean_url_name in lf.name:
                                    matched_file = lf
                                    break
                                if Path(clean_url_name).stem in lf.stem and lf.suffix == Path(clean_url_name).suffix:
                                    matched_file = lf
                                    break
                    except Exception:
                        pass

                if matched_file:
                    new_href = matched_file.name
                    a_tag['href'] = new_href
                    a_tag['target'] = "_self"
                    if 'rel' in a_tag.attrs: del a_tag.attrs['rel']
                    
                    print(f"  [FIX] {html_file.name}: Link to '{href[:30]}...' -> '{new_href}'")
                    modified = True
                    links_fixed += 1

            if modified:
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(str(soup))
                files_changed += 1

        except Exception as e:
            print(f"Error processing {html_file}: {e}")

    print(f"\nSummary: Fixed {links_fixed} links in {files_changed} files.")

if __name__ == "__main__":
    download_dir = "coursera_downloads"
    if os.path.exists(download_dir):
        fix_attachment_links(download_dir)
    else:
        print(f"Directory {download_dir} not found.")