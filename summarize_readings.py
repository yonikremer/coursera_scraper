"""
Script to summarize Coursera reading materials using Ollama.
Supports sequential processing within courses to maintain context.
"""
import os
import re
import time
import signal
import subprocess
import sys
import threading
from collections import defaultdict
from typing import List, Tuple, Optional
from pathlib import Path
import concurrent.futures

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# Configuration
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3.1"
ROOT_DIR = "coursera_downloads"

print_lock = threading.Lock()


class OllamaManager:
    """Manages the Ollama server process."""

    def __init__(self):
        self.process = None

    def start(self) -> bool:
        """Starts 'ollama serve' in the background if it's not already running."""
        try:
            if requests.get("http://localhost:11434/", timeout=5).status_code == 200:
                print("Ollama server is already running.")
                return True
        except requests.exceptions.ConnectionError:
            pass

        print("Starting Ollama server...")
        try:
            # pylint: disable=consider-using-with
            self.process = subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )

            print("Waiting for Ollama to initialize...", end="", flush=True)
            for _ in range(30):
                try:
                    if (
                        requests.get("http://localhost:11434/", timeout=5).status_code
                        == 200
                    ):
                        print(" Ready!")
                        return True
                except requests.exceptions.ConnectionError:
                    time.sleep(1)
                    print(".", end="", flush=True)

            print("\nError: Timed out waiting for Ollama to start.")
            return False

        except OSError as e:
            print(f"\nError starting Ollama: {e}.")
            return False

    def stop(self):
        """Stops the background Ollama process."""
        if self.process:
            print("Stopping Ollama server...")
            self.process.terminate()
            self.process = None


SERVER = OllamaManager()


def start_ollama_server() -> bool:
    """Wrapper for backward compatibility."""
    return SERVER.start()


def stop_ollama_server():
    """Wrapper for backward compatibility."""
    SERVER.stop()


def check_ollama_model() -> bool:
    """Verifies that the required model is available."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=10)
        if response.status_code == 200:
            models = [m["name"] for m in response.json().get("models", [])]
            if not any(MODEL_NAME in m for m in models):
                print(
                    f"Warning: Model '{MODEL_NAME}' not found. Please run: ollama pull {MODEL_NAME}"
                )
                return False
        return True
    except requests.exceptions.ConnectionError:
        return False


def get_html_files(root_dir: str) -> List[str]:
    """Recursively finds all candidate .html reading files."""
    html_files = []
    skip_keywords = ["quiz", "assignment", "submit", "peer_review", "exam"]

    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".html"):
                lower_name = file.lower()
                if not any(keyword in lower_name for keyword in skip_keywords):
                    html_files.append(os.path.join(root, file))

    return sorted(html_files)


def has_summary(file_path: str) -> bool:
    """Checks if the file already contains an AI summary box."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")
        return bool(soup.find("div", class_="ai-summary-box"))
    except (OSError, UnicodeDecodeError):
        return False


def extract_text_from_html(file_path: str) -> Optional[str]:
    """Extracts cleaner text from the HTML, skipping interactive content."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")

        # Check for interactive quiz content
        checks = [
            soup.find("input", {"type": "radio"}),
            soup.find("input", {"type": "checkbox"}),
            soup.find("textarea"),
            soup.find(class_=re.compile(r"rc-FormPartsQuestion|rc-Option")),
        ]
        if any(checks):
            return None

        content_div = soup.find("div", class_="content-wrapper") or soup.body
        if not content_div:
            return ""

        text = content_div.get_text(separator="\n\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", text)
    except (OSError, UnicodeDecodeError) as e:
        with print_lock:
            print(f"Error reading {file_path}: {e}")
        return ""


def inject_summary_into_file(file_path: str, summary_html: str):
    """Injects the AI-generated Hebrew summary into the HTML file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")

        if soup.find("div", class_="ai-summary-box"):
            return

        box = soup.new_tag("div")
        box["class"] = "ai-summary-box"
        box["style"] = (
            "background-color: #f0f8ff; border: 1px solid #007bff; "
            "border-radius: 8px; padding: 20px; margin-bottom: 25px; font-family: sans-serif;"
        )

        box.append(BeautifulSoup(summary_html, "html.parser"))

        target = soup.find("div", class_="content-wrapper") or soup.body
        if target:
            target.insert(0, box)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(str(soup))
        else:
            with print_lock:
                print(f"No insertion point found in {file_path}.")

    except (OSError, UnicodeDecodeError) as e:
        with print_lock:
            print(f"File system error for {file_path}: {e}")


def generate_content_updates(
    current_context: str, new_text: str, file_name: str
) -> Tuple[str, str]:
    """Asks the AI to generate a Hebrew summary and update current English context."""
    if len(new_text) < 100:
        return "", current_context

    prompt = f"""
    Context: {current_context}
    Material ({file_name}): {new_text}
    Instructions:
    1. Summary in Hebrew (HTML tags only).
    2. Updated context in English for next file.
    Format: [HEBREW_HTML_START]...[HEBREW_HTML_END] |||SEPARATOR||| (English Context)
    """
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0.3},
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=600)
        response.raise_for_status()
        text = response.json().get("response", "")

        if "|||SEPARATOR|||" not in text:
            with print_lock:
                print(f"Invalid AI format for {file_name}")
            return "", current_context

        parts = text.split("|||SEPARATOR|||")
        raw_sum = parts[0].strip()
        new_ctx = parts[1].strip()

        if "[HEBREW_HTML_START]" in raw_sum:
            raw_sum = raw_sum.split("[HEBREW_HTML_START]")[1]
        if "[HEBREW_HTML_END]" in raw_sum:
            raw_sum = raw_sum.split("[HEBREW_HTML_END]")[0]

        cleaned = raw_sum.replace("```html", "").replace("```", "").strip()
        return cleaned, new_ctx

    except (requests.RequestException, ValueError) as e:
        with print_lock:
            print(f"API error for {file_name}: {e}")
        return "", current_context


def summarize_file(file_path: str, context: str = "") -> Tuple[bool, str]:
    """Summarizes a single file (used for real-time processing)."""
    if not os.path.exists(file_path) or has_summary(file_path):
        return True, context

    text = extract_text_from_html(file_path)
    if text is None or not text:
        return False, context

    summary_html, new_ctx = generate_content_updates(
        context, text, os.path.basename(file_path)
    )
    if summary_html:
        inject_summary_into_file(file_path, summary_html)
        return True, new_ctx
    return False, context


def process_course(_course_name: str, files: List[str], pbar: tqdm):
    """Processes course files sequentially to preserve learning context."""
    ctx = ""
    for f in files:
        text = extract_text_from_html(f)
        if text:
            summary_html, ctx = generate_content_updates(ctx, text, os.path.basename(f))
            if summary_html:
                inject_summary_into_file(f, summary_html)
        pbar.update(1)


def signal_handler(_sig, _frame):
    """Handles termination signals."""
    print("\nExiting gracefully...")
    stop_ollama_server()
    sys.exit(0)


def is_video(filename: str) -> bool:
    """Checks if an HTML file is actually a video item companion."""
    return os.path.exists(filename.replace(".html", ".mp4"))


def summarize_all_readings(root_dir: str = ROOT_DIR):
    """Batch processes all reading materials found in the root directory."""
    signal.signal(signal.SIGINT, signal_handler)

    if not start_ollama_server():
        return

    if not check_ollama_model():
        stop_ollama_server()
        return

    print(f"Scanning {root_dir}...")
    files = get_html_files(root_dir)
    files = [f for f in files if not is_video(f)]

    courses = defaultdict(list)
    for f in files:
        course_name = Path(f).relative_to(ROOT_DIR).parts[0]
        courses[course_name].append(f)

    to_process = {
        c: f_list
        for c, f_list in courses.items()
        if any(not has_summary(f) for f in f_list)
    }

    if not to_process:
        print("Everything is up to date.")
        stop_ollama_server()
        return

    total = sum(len(f) for f in to_process.values())
    print(f"Found {len(to_process)} courses with {total} pending readings.")

    with tqdm(total=total, desc="Summarizing Readings") as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(process_course, c, f, pbar)
                for c, f in to_process.items()
            ]
            concurrent.futures.wait(futures)

    print("\nSummarization complete.")
    stop_ollama_server()


if __name__ == "__main__":
    summarize_all_readings()
