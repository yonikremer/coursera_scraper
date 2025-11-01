# File Migration Feature

## Overview

The Coursera scraper now automatically migrates files from the old flat course structure to the new module-based structure. This ensures backward compatibility with previous downloads while organizing new downloads properly.

## How It Works

When downloading course materials, the script now:

1. **Checks module directory first** - If a file already exists in the correct module directory, it uses that file
2. **Checks course root directory** - If a file exists in the old flat structure (course root), it moves it to the appropriate module directory
3. **Downloads if needed** - If the file doesn't exist anywhere, it downloads to the module directory

## Migration Behavior

### For Individual Files

Files are migrated automatically using the `_get_or_move_file()` method:

```python
def _get_or_move_file(self, course_dir: Path, module_dir: Path, filename: str) -> Path:
    """
    Check if file exists in course directory (from old runs), move it to module directory.
    If not found, return the module directory path for saving.
    """
```

**Example:**
```
Before (old structure):
coursera_downloads/
└── foundations-data/
    ├── 001_Introduction.mp4
    ├── 002_Week1_Quiz.html
    └── 003_Reading.html

After migration (new structure):
coursera_downloads/
└── foundations-data/
    ├── Module_1/
    │   ├── 001_Introduction.mp4      # Moved from course root
    │   ├── 002_Week1_Quiz.html       # Moved from course root
    │   └── 003_Reading.html          # Moved from course root
    └── Module_2/
        └── 004_New_Content.mp4       # Newly downloaded
```

### For Lab Directories

Lab directories are handled specially since they contain multiple files:

```python
# Check if lab directory exists in old location (course root)
lab_dirname = f"{item_counter:03d}_{title}_lab"
old_lab_dir = course_dir / lab_dirname
lab_dir = module_dir / lab_dirname

# Move entire directory if it exists
if old_lab_dir.exists() and old_lab_dir.is_dir():
    print(f"  📦 Moving existing lab directory to module directory")
    shutil.move(str(old_lab_dir), str(lab_dir))
```

**Example:**
```
Before:
coursera_downloads/
└── get-started-with-python/
    └── 005_Python_Basics_lab/
        ├── notebook.ipynb
        ├── data.csv
        └── lab_info.txt

After:
coursera_downloads/
└── get-started-with-python/
    └── Module_1/
        └── 005_Python_Basics_lab/    # Entire directory moved
            ├── notebook.ipynb
            ├── data.csv
            └── lab_info.txt
```

## Affected File Types

All material types are migrated automatically:

- ✅ **Videos** (.mp4)
- ✅ **PDFs**
- ✅ **Readings** (.html)
- ✅ **Attachments** (DOCX, PDF, etc.)
- ✅ **Assignments** (.html)
- ✅ **Quizzes** (.html)
- ✅ **Labs** (entire directories with .ipynb and data files)

## User Experience

### Console Output

When files are migrated, you'll see messages like:

```
  📦 Moving existing file to module directory: 001_Introduction.mp4
  ✓ Moved: 001_Introduction.mp4
```

For lab directories:
```
  📦 Moving existing lab directory to module directory
  ✓ Moved lab directory
```

### Error Handling

If migration fails (e.g., due to permissions), the script:
- Logs a warning
- Continues with normal download operations
- Does not crash or stop the download process

Example error output:
```
  ⚠ Error moving file: Permission denied
```

## Migration Safety

### No Data Loss

- Original files are **moved**, not copied
- No duplicate files are created
- Files are only moved once
- If move fails, original files remain untouched

### Idempotent Operations

Running the script multiple times is safe:
- Already-migrated files won't be moved again
- Module directory is checked first
- No unnecessary file operations

### Atomic Operations

File moves are atomic on most filesystems:
- Either the entire file moves or nothing happens
- No partial/corrupted files
- Safe to interrupt with Ctrl+C

## Technical Implementation

### Method Signature

```python
def _get_or_move_file(self, course_dir: Path, module_dir: Path, filename: str) -> Path
```

### Integration Points

The method is called from all material processing functions:

1. **Videos**: `_process_video_item()`
   ```python
   filename = f"{item_counter:03d}_{title}_{idx}.mp4"
   video_file = self._get_or_move_file(course_dir, module_dir, filename)
   ```

2. **PDFs**: `_process_pdf_items()`
   ```python
   filename = f"{item_counter:03d}_{base_filename}"
   pdf_file = self._get_or_move_file(course_dir, module_dir, filename)
   ```

3. **Readings**: `_process_reading_item()`
   ```python
   filename = f"{item_counter:03d}_{title}.html"
   html_file = self._get_or_move_file(course_dir, module_dir, filename)
   ```

4. **Attachments**: `_download_attachments()`
   ```python
   filename = f"{item_counter:03d}_attachment_{attach_name}"
   attach_file = self._get_or_move_file(course_dir, module_dir, filename)
   ```

5. **Assignments/Quizzes**: `_process_assignment_or_quiz()`
   ```python
   filename = f"{item_counter:03d}_{title}_{item_type}.html"
   assignment_file = self._get_or_move_file(course_dir, module_dir, filename)
   ```

6. **Labs**: `_process_lab_item()` (uses `shutil.move` for entire directory)

### Performance Considerations

- **Fast**: File moves are O(1) on the same filesystem
- **Minimal I/O**: Only metadata is updated, data isn't copied
- **One-time cost**: Migration only happens on first run after update

## Migration Timeline

### Automatic Migration

Migration happens automatically when you run the updated script:

1. **First run** - Existing files are migrated to module directories
2. **Subsequent runs** - Files are already in the correct location, no migration needed
3. **Resume capability** - Interrupted downloads can be resumed without re-migration

### Manual Verification

To verify migration completed successfully:

```bash
# Check that course root has only Module_X directories
ls coursera_downloads/foundations-data/

# Should show:
# Module_1/
# Module_2/
# Module_3/
# ...

# Verify files are in modules
ls coursera_downloads/foundations-data/Module_1/

# Should show files like:
# 001_Introduction.mp4
# 002_Reading.html
# etc.
```

## Troubleshooting

### Files Not Migrating

**Issue**: Old files remain in course root

**Solution**:
- Check file naming matches the pattern (e.g., `001_Title.mp4`)
- Ensure you have write permissions
- Check console output for error messages

### Duplicate Files

**Issue**: Files exist in both locations

**Cause**: Migration was interrupted or failed

**Solution**:
```bash
# Manually remove duplicates from course root
rm coursera_downloads/course-name/001_*.mp4
rm coursera_downloads/course-name/002_*.html
# etc.
```

### Permission Errors

**Issue**: `Permission denied` when moving files

**Solution**:
- Run script with appropriate permissions
- Check folder ownership: `ls -la coursera_downloads/`
- On Windows: Run as administrator if needed

## Rollback

If you need to revert to the old flat structure:

1. Restore the backup file:
   ```bash
   mv coursera_scraper_backup.py coursera_scraper.py
   ```

2. Manually flatten directories if needed:
   ```bash
   mv coursera_downloads/course-name/Module_*/* coursera_downloads/course-name/
   rmdir coursera_downloads/course-name/Module_*/
   ```

## Benefits

✅ **Backward Compatible** - Works with existing downloads
✅ **Zero Manual Work** - Automatic migration
✅ **Organized Structure** - Module-based organization
✅ **Resume Downloads** - Can continue interrupted downloads
✅ **Safe Operations** - No data loss, atomic moves
✅ **Clear Feedback** - Console messages show migration progress

## Future Enhancements

Potential improvements:

1. **Progress Bar** - Show migration progress for large course collections
2. **Dry Run Mode** - Preview what would be migrated without actually moving files
3. **Migration Report** - Generate summary of all migrated files
4. **Batch Migration** - Migrate all courses at once before downloading new content
