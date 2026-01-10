# Playlist Generation Updates

## Overview
The playlist generation system has been overhauled to improve compatibility with Windows media players (specifically "Movies & TV" and Windows Media Player).

## Key Changes

### 1. Format Change
- **Old Format:** `.m3u` / `.pls`
- **New Format:** `.wpl` (Windows Media Player Playlist)
- **Reason:** Native XML-based format supported by Windows apps, which often struggle with simple text-based playlists.

### 2. Path Handling
- **Strategy:** Relative Paths
- **Format:** `module_1\video.mp4` (Windows backslashes)
- **Reason:** 
  - Absolute paths caused portability issues.
  - Standard relative paths often failed in sandboxed Windows apps due to security/permission contexts.
  - The new implementation uses strictly formatted relative paths within the XML `src` attribute, which bypasses these issues.

### 3. Playlist Structure
- **Module Level:** Each module folder (e.g., `module_1/`) contains a `module_1.wpl` playlist with only that module's videos.
- **Course Level:** The course root folder contains a `Full_Course_[Name].wpl` master playlist containing all videos from all modules.

### 4. Integration
- The `process_all_courses` function now accepts a dynamic root directory argument.
- `main.py` passes the user-defined output directory to the playlist generator, ensuring correct execution regardless of CLI arguments.

## Usage
Playlists are automatically generated at the end of the `main.py` execution. To run manually:
```bash
python create_playlists.py
```
