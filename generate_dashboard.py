import os
import json
import re
from pathlib import Path
from collections import defaultdict
import urllib.parse

ROOT_DIR = Path("coursera_downloads")
OUTPUT_FILE = ROOT_DIR / "dashboard.html"

TEMPLATE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Offline Learning Dashboard</title>
    <style>
        :root {
            --bg-color: #f5f5f5;
            --sidebar-bg: #fff;
            --text-color: #333;
            --accent-color: #0056D2; /* Coursera Blue */
            --item-hover: #f0f6ff;
            --border-color: #e0e0e0;
        }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; display: flex; height: 100vh; background: var(--bg-color); color: var(--text-color); }
        
        /* Sidebar */
        #sidebar { width: 350px; background: var(--sidebar-bg); border-right: 1px solid var(--border-color); display: flex; flex-direction: column; height: 100%; overflow: hidden; box-shadow: 2px 0 5px rgba(0,0,0,0.05); }
        .sidebar-header { padding: 20px; border-bottom: 1px solid var(--border-color); background: #fff; z-index: 10; }
        .sidebar-header h2 { margin: 0; font-size: 1.2rem; color: var(--accent-color); }
        .search-box { margin-top: 10px; width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        
        #course-list { overflow-y: auto; flex: 1; padding: 0; margin: 0; list-style: none; }
        
        /* Course Items */
        .course-item { border-bottom: 1px solid var(--border-color); }
        .course-title { padding: 15px 20px; cursor: pointer; font-weight: 600; background: #fafafa; display: flex; justify-content: space-between; align-items: center; }
        .course-title:hover { background: #f0f0f0; }
        .course-title .toggle-icon { font-size: 0.8em; transition: transform 0.2s; }
        .course-item.open .toggle-icon { transform: rotate(180deg); }
        
        /* Modules */
        .module-list { display: none; padding: 0; margin: 0; list-style: none; background: #fff; }
        .course-item.open .module-list { display: block; }
        .module-title { padding: 10px 20px 10px 30px; font-size: 0.95rem; font-weight: 600; color: #555; background: #fcfcfc; border-bottom: 1px solid #eee; }
        
        /* Content Items */
        .content-item { padding: 8px 20px 8px 40px; cursor: pointer; display: flex; align-items: center; font-size: 0.9rem; border-bottom: 1px solid #f5f5f5; transition: background 0.2s; }
        .content-item:hover { background: var(--item-hover); }
        .content-item.active { background: #e3effd; border-left: 4px solid var(--accent-color); padding-left: 36px; }
        .item-icon { margin-right: 10px; width: 16px; text-align: center; }
        
        /* Main Content */
        #main-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; }
        #content-header { padding: 15px 25px; background: #fff; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center; }
        #content-title { margin: 0; font-size: 1.2rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 60%; }
        
        .nav-controls { display: flex; gap: 10px; align-items: center; }
        .nav-btn { padding: 8px 15px; border: 1px solid var(--accent-color); background: #fff; color: var(--accent-color); border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 0.85rem; transition: all 0.2s; }
        .nav-btn:hover { background: var(--accent-color); color: #fff; }
        .nav-btn:disabled { border-color: #ccc; color: #ccc; cursor: not-allowed; }
        .nav-btn:disabled:hover { background: #fff; color: #ccc; }

        .complete-btn { display: flex; align-items: center; gap: 5px; cursor: pointer; font-size: 0.85rem; color: #666; }
        .complete-btn input { cursor: pointer; width: 18px; height: 18px; }

        #content-viewer { flex: 1; overflow: auto; padding: 0; background: #fcfcfc; position: relative; }
        
        iframe { width: 100%; height: 100%; border: none; display: block; background: #fff; }
        video { max-width: 100%; max-height: 100%; width: 100%; height: auto; outline: none; background: #000; box-shadow: 0 10px 30px rgba(0,0,0,0.3); }
        .video-container { display: flex; justify-content: center; align-items: center; height: 100%; background: #111; padding: 20px; box-sizing: border-box; }
        
        .placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #888; text-align: center; padding: 40px; }
        .placeholder svg { width: 80px; height: 80px; margin-bottom: 20px; opacity: 0.2; color: var(--accent-color); }
        .placeholder h2 { color: #444; margin-bottom: 10px; }
        
        /* Progress Indicators */
        .content-item.completed::after { content: '✓'; margin-left: auto; color: #28a745; font-weight: bold; }
        
        /* Scrollbar */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: #f1f1f1; }
        ::-webkit-scrollbar-thumb { background: #ccc; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #aaa; }
    </style>
</head>
<body>
    <div id="sidebar">
        <div class="sidebar-header">
            <h2>📚 Course Library</h2>
            <input type="text" class="search-box" placeholder="Search lessons..." id="search-input">
        </div>
        <ul id="course-list">
            <!-- Courses injected here -->
        </ul>
    </div>
    
    <div id="main-content">
        <div id="content-header" style="display:none;">
            <h1 id="content-title">Select a Lesson</h1>
            <div class="nav-controls">
                <label class="complete-btn">
                    <input type="checkbox" id="mark-complete"> Mark Complete
                </label>
                <button class="nav-btn" id="prev-btn">← Previous</button>
                <button class="nav-btn" id="next-btn">Next →</button>
            </div>
        </div>
        <div id="content-viewer">
            <div class="placeholder">
                <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v6h-2zm0 8h2v2h-2z"/></svg>
                <h2>Ready to Start Learning?</h2>
                <p>Pick a course and lesson from the sidebar to begin your offline journey.</p>
                <p style="font-size: 0.8rem; margin-top: 20px;">Your progress is saved automatically on this computer.</p>
            </div>
        </div>
    </div>

    <script>
        const courses = __COURSE_DATA__;
        let currentItemIndex = -1;
        let flatItems = [];

        // Flatten items for navigation
        courses.forEach(course => {
            course.modules.forEach(mod => {
                mod.items.forEach(item => {
                    flatItems.push(item);
                });
            });
        });

        function getProgress() {
            const saved = localStorage.getItem('coursera_progress');
            return saved ? JSON.parse(saved) : {};
        }

        function toggleComplete(path) {
            const progress = getProgress();
            progress[path] = !progress[path];
            localStorage.setItem('coursera_progress', JSON.stringify(progress));
            renderSidebar(document.getElementById('search-input').value);
        }
        
        function renderSidebar(filterText = '') {
            const list = document.getElementById('course-list');
            list.innerHTML = '';
            const progress = getProgress();
            
            filterText = filterText.toLowerCase();
            
            courses.forEach(course => {
                let hasVisibleItems = false;
                
                const courseLi = document.createElement('li');
                courseLi.className = 'course-item open';
                
                const titleDiv = document.createElement('div');
                titleDiv.className = 'course-title';
                titleDiv.innerHTML = `<span>${course.name}</span> <span class="toggle-icon">▼</span>`;
                titleDiv.onclick = () => courseLi.classList.toggle('open');
                
                const modulesUl = document.createElement('ul');
                modulesUl.className = 'module-list';
                
                course.modules.forEach(mod => {
                    const modLi = document.createElement('li');
                    const modTitle = document.createElement('div');
                    modTitle.className = 'module-title';
                    modTitle.textContent = mod.name;
                    modLi.appendChild(modTitle);
                    
                    const itemsUl = document.createElement('ul');
                    itemsUl.style.listStyle = 'none';
                    itemsUl.style.padding = '0';
                    
                    let modHasVisible = false;
                    mod.items.forEach(item => {
                        if (filterText && !item.title.toLowerCase().includes(filterText)) return;
                        
                        modHasVisible = true;
                        hasVisibleItems = true;
                        
                        const itemLi = document.createElement('li');
                        const isCompleted = progress[item.path];
                        itemLi.className = 'content-item' + (isCompleted ? ' completed' : '');
                        if (flatItems[currentItemIndex] && flatItems[currentItemIndex].path === item.path) {
                            itemLi.classList.add('active');
                        }
                        
                        let icon = '📄';
                        if (item.type === 'video') icon = '🎥';
                        if (item.type === 'quiz') icon = '📝';
                        if (item.type === 'lab') icon = '🧪';
                        
                        itemLi.innerHTML = `<span class="item-icon">${icon}</span> <span>${item.title}</span>`;
                        itemLi.onclick = () => loadContentByPath(item.path);
                        
                        itemsUl.appendChild(itemLi);
                    });
                    
                    if (modHasVisible) {
                        modLi.appendChild(itemsUl);
                        modulesUl.appendChild(modLi);
                    }
                });
                
                if (hasVisibleItems) {
                    courseLi.appendChild(titleDiv);
                    courseLi.appendChild(modulesUl);
                    list.appendChild(courseLi);
                }
            });
        }
        
        function loadContentByPath(path) {
            const index = flatItems.findIndex(i => i.path === path);
            if (index !== -1) {
                currentItemIndex = index;
                const item = flatItems[index];
                
                document.getElementById('content-header').style.display = 'flex';
                document.getElementById('content-title').textContent = item.title;
                
                const progress = getProgress();
                const checkbox = document.getElementById('mark-complete');
                checkbox.checked = !!progress[item.path];
                checkbox.onclick = () => toggleComplete(item.path);

                const viewer = document.getElementById('content-viewer');
                viewer.innerHTML = '';
                
                if (item.type === 'video') {
                    const container = document.createElement('div');
                    container.className = 'video-container';
                    const video = document.createElement('video');
                    video.controls = true;
                    video.src = item.path;
                    
                    if (item.subtitles) {
                        if (item.subtitles.he) {
                            const track = document.createElement('track');
                            track.kind = 'subtitles'; track.label = 'Hebrew'; track.srclang = 'he';
                            track.src = item.subtitles.he; track.default = true;
                            video.appendChild(track);
                        }
                        if (item.subtitles.en) {
                            const track = document.createElement('track');
                            track.kind = 'subtitles'; track.label = 'English'; track.srclang = 'en';
                            track.src = item.subtitles.en;
                            video.appendChild(track);
                        }
                    }
                    container.appendChild(video);
                    viewer.appendChild(container);
                } else {
                    const iframe = document.createElement('iframe');
                    iframe.src = item.path;
                    viewer.appendChild(iframe);
                }

                // Update nav buttons
                document.getElementById('prev-btn').disabled = currentItemIndex <= 0;
                document.getElementById('next-btn').disabled = currentItemIndex >= flatItems.length - 1;
                
                renderSidebar(document.getElementById('search-input').value);
                viewer.scrollTop = 0;
            }
        }
        
        document.getElementById('prev-btn').onclick = () => {
            if (currentItemIndex > 0) loadContentByPath(flatItems[currentItemIndex - 1].path);
        };
        
        document.getElementById('next-btn').onclick = () => {
            if (currentItemIndex < flatItems.length - 1) loadContentByPath(flatItems[currentItemIndex + 1].path);
        };

        document.getElementById('search-input').addEventListener('input', (e) => renderSidebar(e.target.value));
        
        renderSidebar();
    </script>
</body>
</html>
""";

def scan_directory(root_dir):
    courses = []
    
    # Sort folders naturally
    course_dirs = sorted([d for d in root_dir.iterdir() if d.is_dir() and not d.name.startswith('.')])
    
    for course_dir in course_dirs:
        if course_dir.name == 'shared_assets': continue
        
        course_data = {
            "name": course_dir.name.replace('_', ' ').title(),
            "path": str(course_dir.relative_to(root_dir)),
            "modules": []
        }
        
        module_dirs = sorted([d for d in course_dir.iterdir() if d.is_dir()], key=lambda x: x.name)
        
        for module_dir in module_dirs:
            module_data = {
                "name": module_dir.name.replace('_', ' ').title(),
                "items": []
            }
            
            # Group files by their prefix ID
            files = sorted([f for f in module_dir.iterdir() if f.is_file()])
            grouped_items = defaultdict(dict)
            
            for f in files:
                # Regex to match 001_filename.ext
                match = re.match(r"(\d+)_", f.name)
                if match:
                    prefix = match.group(1)
                    key = prefix # Group key
                    
                    if f.suffix == '.mp4':
                        grouped_items[key]['video'] = f
                    elif f.suffix == '.vtt':
                        if '_en.vtt' in f.name:
                            grouped_items[key]['sub_en'] = f
                        elif '_heb.vtt' in f.name:
                            grouped_items[key]['sub_he'] = f
                    elif f.suffix == '.html':
                         grouped_items[key]['html'] = f
                    elif '_attachment_' in f.name:
                        # Handle attachments separately? For now maybe ignore or list?
                        # Let's attach them to the main item if possible or separate
                        pass

            # Convert groups to items
            sorted_keys = sorted(grouped_items.keys())
            for key in sorted_keys:
                group = grouped_items[key]
                item = {
                    "title": "",
                    "type": "unknown",
                    "path": "",
                    "subtitles": {}
                }
                
                # Determine primary file
                if 'video' in group:
                    main_file = group['video']
                    item['type'] = 'video'
                    item['path'] = urllib.parse.quote(str(main_file.relative_to(root_dir)).replace('\\', '/'))
                    
                    # Clean title
                    name = main_file.stem
                    name = re.sub(r"^\d+_", "", name)
                    name = name.replace('_', ' ').title()
                    item['title'] = name
                    
                    # Subtitles
                    if 'sub_en' in group:
                        item['subtitles']['en'] = urllib.parse.quote(str(group['sub_en'].relative_to(root_dir)).replace('\\', '/'))
                    if 'sub_he' in group:
                        item['subtitles']['he'] = urllib.parse.quote(str(group['sub_he'].relative_to(root_dir)).replace('\\', '/'))
                        
                elif 'html' in group:
                    main_file = group['html']
                    item['path'] = urllib.parse.quote(str(main_file.relative_to(root_dir)).replace('\\', '/'))
                    
                    # Heuristic for type
                    lower_name = main_file.name.lower()
                    if 'quiz' in lower_name or 'assignment' in lower_name:
                        item['type'] = 'quiz'
                    elif 'lab' in lower_name:
                        item['type'] = 'lab'
                    else:
                        item['type'] = 'html'
                        
                    name = main_file.stem
                    name = re.sub(r"^\d+_", "", name)
                    name = name.replace('_', ' ').title()
                    item['title'] = name
                
                if item['path']:
                    module_data['items'].append(item)
            
            if module_data['items']:
                course_data['modules'].append(module_data)
        
        if course_data['modules']:
            courses.append(course_data)
            
    return courses

def generate_dashboard():
    print(f"Scanning {ROOT_DIR}...")
    if not ROOT_DIR.exists():
        print(f"Directory {ROOT_DIR} does not exist.")
        return

    courses = scan_directory(ROOT_DIR)
    
    json_data = json.dumps(courses)
    html_content = TEMPLATE_HEAD.replace('__COURSE_DATA__', json_data)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)
        
    print(f"Dashboard generated at: {OUTPUT_FILE.absolute()}")
    print("Open this file in your browser to view your offline courses.")

if __name__ == "__main__":
    generate_dashboard()
