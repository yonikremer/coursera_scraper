# Technical Details & Developer Guide

## How It Works

1. **Authentication**: Opens Chrome browser and navigates to Coursera login.
2. **Google Login**: You manually complete the entire Google login flow in the browser. Cookies are saved to `coursera_downloads/coursera_cookies.pkl` for persistent login.
3. **Certificate Navigation**: Extracts all course URLs from the professional certificate.
4. **Course Download**: For each course:
   - Iterates through modules (Module 1, 2, 3, etc.).
   - Extracts all item links from each module page.
   - Downloads each item sequentially:
     - Videos (MP4 in 720p quality)
     - PDFs and resources
     - Reading materials with attachments (saved as HTML)
     - Assignments and quizzes (saves content to HTML)
     - Jupyter Labs (downloads .ipynb notebook + all data files)
5. **Organization**: Creates folder structure with numbered files organized by module:
   ```
   coursera_downloads/
   ├── course-name-1/
   │   ├── Module_1/
   │   │   ├── 001_Introduction_to_Course.mp4
   │   │   ├── 002_Helpful_Resources.html
   │   │   ├── 003_Course_Overview_quiz.html
   │   │   └── 004_Python_Lab_lab/
   │   │       ├── notebook.ipynb
   │   │       ├── data.csv
   │   │       └── lab_info.txt
   │   ├── Module_2/
   │   └── ...
   ├── course-name-2/
   └── ...
   ```

## Advanced Troubleshooting

### ChromeDriver Issues
```bash
# Linux/WSL
sudo apt-get install chromium-chromedriver

# macOS
brew install chromedriver

# Windows
Download from https://chromedriver.chromium.org/
```

### Login Timeout
If login times out, increase the timeout in `coursera/auth.py` (line 35):
```python
WebDriverWait(self.driver, 180)  # Change 180 to higher value
```

### Video Download Fails
- Ensure yt-dlp is up to date: `pip install --upgrade yt-dlp`
- Some videos may be protected and cannot be downloaded.

## Legal Notice

This tool is for personal use only. Ensure you comply with Coursera's Terms of Service. Downloaded materials should only be used for your personal educational purposes and not redistributed.
