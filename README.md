# Coursera Material Downloader

Automated script to download all course materials from your enrolled Coursera courses and professional certificates.

## Features

- Downloads videos (720p quality), PDFs, readings, and other course materials
- Downloads assignments and quizzes (saves content as HTML)
- Downloads Jupyter notebook labs including:
  - Notebook files (.ipynb)
  - All referenced data files (CSV, JSON, Excel, Parquet, etc.)
- Supports Professional Certificates (multiple courses)
- Google account authentication
- Organized folder structure by course and module
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
python main.py
```

This will:
- Use email: `yoni.kremer@gmail.com`
- Download from: `https://www.coursera.org/professional-certificates/google-advanced-data-analytics`
- Save to: `coursera_downloads/` directory

### Custom Usage

```bash
python main.py --email your.email@gmail.com --cert-url "https://www.coursera.org/professional-certificates/your-certificate" --output-dir "my_courses"
```

### Command Line Options

- `--email`: Your Google account email (default: yoni.kremer@gmail.com)
- `--cert-url`: Professional certificate URL (default: Google Advanced Data Analytics)
- `--output-dir`: Output directory for downloads (default: coursera_downloads)
- `--headless`: Run browser in headless mode (not recommended for first login)

## AI Reading Summarization

The project includes an optional tool to generate AI-powered summaries of downloaded reading materials using a **local LLM (Ollama)**. This ensures privacy, costs nothing, and runs entirely on your own hardware (GPU recommended).

### Prerequisites

1. **Install Ollama**: Download and install from [ollama.com](https://ollama.com).
2. **Pull the Model**: Open your terminal and run:
   ```bash
   ollama pull llama3.1
   ```
   *Note: This downloads the Llama 3.1 8B model (~4.7GB). If you have limited VRAM (<6GB), you can try a smaller model like `ollama pull llama3.2`.*

### Usage

After downloading your course materials, run:

```bash
python summarize_readings.py
```

This script will:
1. **Auto-start Ollama**: It automatically checks if the Ollama server is running and starts it in the background if needed.
2. **Scan Files**: Finds all HTML reading files in your `coursera_downloads` directory.
3. **Generate Summaries**: Uses the local Llama 3.1 model to read the content and generate a concise summary in **Hebrew**.
   - It maintains a "global context" of what has been read so far to avoid repeating known concepts in subsequent files.
4. **Inject Content**: The summary is injected into the top of the HTML file as a styled box.

### Configuration

You can modify `summarize_readings.py` to change settings:

- **Model**: Change `MODEL_NAME = "llama3.1"` to use a different model (e.g., "llama3.2" or "mistral").
- **Context Window**: Default is `num_ctx: 4096` to fit comfortably in 6GB VRAM. If you have a powerful GPU (12GB+), you can increase this to `8192` for larger files.

### Troubleshooting

- **"First file takes longer"**: The first time the script runs, Ollama loads the 5GB model from disk into your GPU VRAM. This can take 10-60 seconds depending on your drive speed. Subsequent files will be processed much faster.
- **CPU vs GPU**: If the script is slow, check Task Manager to see if your GPU is being used. If not, ensure your NVIDIA drivers are up to date. The script forces a smaller context window (4096) to help models fit on smaller cards (like RTX 3050/4050).

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

## Important Notes

- **Manual Login**: You'll need to manually enter your password and complete any 2FA.
- **Persistent Login**: Cookies are saved after the first successful login, so you won't need to log in manually every time unless they expire.
- **Time**: Downloading all courses in a certificate may take several hours depending on content size.
- **Browser Window**: Don't close the Chrome window during the process.
- **Enrollment Required**: You must be enrolled in the courses to download materials.
- **Network**: Ensure stable internet connection.
- **Disk Space**: Make sure you have enough disk space (several GB).

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
If login times out, increase the timeout in `coursera/auth.py` (line 35):
```python
WebDriverWait(self.driver, 180)  # Change 180 to higher value
```

### Video Download Fails
- Ensure yt-dlp is up to date: `pip install --upgrade yt-dlp`
- Some videos may be protected and cannot be downloaded.

## Legal Notice

This tool is for personal use only. Ensure you comply with Coursera's Terms of Service. Downloaded materials should only be used for your personal educational purposes and not redistributed.

## Example Run

```
$ python main.py

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
