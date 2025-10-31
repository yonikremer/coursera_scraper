# Coursera Material Downloader

Automated script to download all course materials from your enrolled Coursera courses and professional certificates.

## Features

- Downloads videos, PDFs, readings, and other course materials
- Supports Professional Certificates (multiple courses)
- Google account authentication
- Organized folder structure by course and week
- Progress tracking

## Prerequisites

1. **Python 3.12+**
2. **Chrome browser** installed
3. **ChromeDriver** - Download from https://chromedriver.chromium.org/ and ensure it's in your PATH

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

Or using uv:
```bash
uv pip install -r requirements.txt
```

## Usage

### Basic Usage (with defaults)

The script is pre-configured for your Google Advanced Data Analytics certificate:

```bash
python coursera_scraper.py
```

This will:
- Use email: `yoni.kremer@gmail.com`
- Download from: `https://www.coursera.org/professional-certificates/google-advanced-data-analytics`
- Save to: `coursera_downloads/` directory

### Custom Usage

```bash
python coursera_scraper.py --email your.email@gmail.com --cert-url "https://www.coursera.org/professional-certificates/your-certificate" --output-dir "my_courses"
```

### Command Line Options

- `--email`: Your Google account email (default: yoni.kremer@gmail.com)
- `--cert-url`: Professional certificate URL (default: Google Advanced Data Analytics)
- `--output-dir`: Output directory for downloads (default: coursera_downloads)
- `--headless`: Run browser in headless mode (not recommended for first login)

## How It Works

1. **Authentication**: Opens Chrome browser and navigates to Coursera login
2. **Google Login**: You manually complete the entire Google login flow in the browser
3. **Certificate Navigation**: Extracts all course URLs from the professional certificate
4. **Course Download**: For each course:
   - Iterates through modules (Module 1, 2, 3, etc.)
   - Extracts all item links from each module page
   - Downloads each item sequentially:
     - Videos (MP4)
     - PDFs and resources
     - Reading materials (saved as HTML)
5. **Organization**: Creates folder structure with numbered files:
   ```
   coursera_downloads/
   ├── course-name-1/
   │   ├── 001_Introduction_to_Course.mp4
   │   ├── 002_Helpful_Resources.html
   │   ├── 003_Course_Overview.html
   │   ├── 004_Welcome_to_Module_1.mp4
   │   └── ...
   ├── course-name-2/
   └── ...
   ```

## Important Notes

- **Manual Login**: You'll need to manually enter your password and complete any 2FA
- **Time**: Downloading all 8 courses may take several hours depending on content size
- **Browser Window**: Don't close the Chrome window during the process
- **Enrollment Required**: You must be enrolled in the courses to download materials
- **Network**: Ensure stable internet connection
- **Disk Space**: Make sure you have enough disk space (several GB)

## Troubleshooting

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
If login times out, increase the timeout in line 99 of coursera_scraper.py:
```python
WebDriverWait(self.driver, 120)  # Change 120 to higher value
```

### Video Download Fails
- Ensure yt-dlp is up to date: `pip install --upgrade yt-dlp`
- Some videos may be protected and cannot be downloaded

## Legal Notice

This tool is for personal use only. Ensure you comply with Coursera's Terms of Service. Downloaded materials should only be used for your personal educational purposes and not redistributed.

## Example Run

```
$ python coursera_scraper.py

============================================================
Coursera Material Downloader
============================================================
Email: yoni.kremer@gmail.com
Certificate: https://www.coursera.org/professional-certificates/google-advanced-data-analytics
Output directory: coursera_downloads
============================================================

Logging in with Google account: yoni.kremer@gmail.com

Please complete the login process in the browser window...
Note: You may need to complete 2FA if enabled on your account.

Please enter your password in the browser window...
Waiting for manual login completion (up to 120 seconds)...
✓ Login successful!

Fetching courses from: https://www.coursera.org/professional-certificates/google-advanced-data-analytics
✓ Found 8 courses in the certificate
  1. foundations-data
  2. get-started-with-python
  3. go-beyond-the-numbers-translate-data-into-insight
  ...

############################################################
Course 1/8
############################################################
============================================================
Processing course: foundations-data
============================================================

📂 Week 1
  📄 Introduction to Data Analytics
    ⬇ Downloading video...
    ✓ Video saved
  📄 What is data analytics?
    ✓ Reading saved as HTML
...
```
