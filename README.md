# Coursera Material Downloader & AI Summarizer

A comprehensive tool to download your Coursera courses (videos, readings, labs) and generate AI-powered summaries in Hebrew using your local GPU.

## 🚀 Quick Start Guide

### 1. Prerequisites
- **Python 3.12+**
- **Chrome Browser** installed
- **Ollama** (for AI summaries) - [Download here](https://ollama.com)

### 2. Installation
1. Clone this repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Prepare the AI Model (Run this in your terminal once):
   ```bash
   ollama pull llama3.1
   ```

### 3. Downloading Courses
Run the main script to start downloading your certificate/course materials:

```bash
python main.py
```

**What to expect:**
- A Chrome window will open. **Log in to Coursera** manually with your Google account.
- Once logged in, the script will automatically take over and start downloading everything to the `coursera_downloads` folder.
- **Do not close** the Chrome window while it's working.

### 4. Generating AI Summaries (Optional)
After your downloads are complete, you can generate Hebrew summaries for all reading materials:

```bash
python summarize_readings.py
```

**Features:**
- **Local & Private:** Runs entirely on your computer (no API keys, no cost).
- **Smart Context:** The AI remembers what you've already read to avoid repeating concepts.
- **Auto-Inject:** Summaries are added to the top of each HTML reading file.

---

## 🛠️ Utility Tools

This repository includes several helper scripts to enhance your offline learning experience:

### 🌍 Subtitle Translation (`translate_captions.py`)
Translates all downloaded English subtitles (`_en.vtt`) to Hebrew (`_heb.vtt`) using the Google Translate API.
```bash
python translate_captions.py --workers 10
```

### 🎬 Apply Subtitles (`apply_subtitles.py`)
Renames the Hebrew subtitles to match your video filenames exactly (e.g., `video.vtt`). This forces players like VLC to load them automatically.
```bash
python apply_subtitles.py
```

---

## ⚙️ Configuration

### Customizing Downloads
You can specify different emails or target directories:
```bash
python main.py --email your@email.com --output-dir "my_courses"
```

### Customizing AI
Edit `summarize_readings.py` to change settings:
- **Model**: Change `MODEL_NAME` (e.g., to "llama3.2" for faster speed on older laptops).
- **Memory**: The script is optimized for 6GB VRAM GPUs (RTX 3050/4050).

---

## ❓ FAQ

**Q: The AI script is slow / taking a long time to start.**
A: The first file takes about 30-60 seconds to process because the 5GB model needs to load into your GPU memory. Subsequent files will be much faster.

**Q: I don't see GPU usage.**
A: Ensure your NVIDIA drivers are up to date. The script is configured to use your GPU automatically if Ollama is installed correctly.

**Q: Can I use a different Certificate?**
A: Yes! Run with the `--cert-url` flag:
```bash
python main.py --cert-url "https://coursera.org/professional-certificates/your-cert"
```

For technical details, architecture, and advanced troubleshooting, see [TECHNICAL_DETAILS.md](TECHNICAL_DETAILS.md).