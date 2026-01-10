import os
import re
import time
import requests
import subprocess
import signal
import sys
from bs4 import BeautifulSoup
from typing import List, Tuple, Dict, Optional
from collections import defaultdict
import concurrent.futures
import threading

from tqdm import tqdm

# Configuration
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3.1"  # Ensure you have run: ollama pull llama3.1
ROOT_DIR = "coursera_downloads"

# Global variable to track the Ollama process
ollama_process = None
print_lock = threading.Lock()

def start_ollama_server():
    """
    Starts 'ollama serve' in the background if it's not already running.
    """
    global ollama_process
    
    # Check if already running
    try:
        if requests.get("http://localhost:11434/").status_code == 200:
            print("Ollama server is already running.")
            return True
    except requests.exceptions.ConnectionError:
        pass

    print("Starting Ollama server...")
    try:
        # Start ollama serve in background
        # We redirect stdout/stderr to DEVNULL to avoid cluttering the script output,
        # but you could redirect to a file for debugging.
        ollama_process = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_CONSOLE  # Windows specific: runs in new window/hidden
        )
        
        # Wait for it to become ready
        print("Waiting for Ollama to initialize...", end="", flush=True)
        retries = 30 # Wait up to 30 seconds
        for _ in range(retries):
            try:
                if requests.get("http://localhost:11434/").status_code == 200:
                    print(" Ready!")
                    return True
            except requests.exceptions.ConnectionError:
                time.sleep(1)
                print(".", end="", flush=True)
        
        print("\nError: Timed out waiting for Ollama to start.")
        return False

    except FileNotFoundError:
        print("\nError: 'ollama' command not found. Please install Ollama from ollama.com")
        return False


def stop_ollama_server():
    """
    Stops the background Ollama process if we started it.
    """
    global ollama_process
    if ollama_process:
        print("Stopping Ollama server...")
        ollama_process.terminate()
        ollama_process = None


def check_ollama_model():
    """
    Verifies that the required model is available.
    """
    try:
        # Check if model exists
        tags_response = requests.get("http://localhost:11434/api/tags")
        if tags_response.status_code == 200:
            models = [m['name'] for m in tags_response.json().get('models', [])]
            if not any(MODEL_NAME in m for m in models):
                print(f"Warning: Model '{MODEL_NAME}' not found in Ollama library.")
                print(f"Available models: {models}")
                print(f"Please run: ollama pull {MODEL_NAME}")
                return False
        return True
    except requests.exceptions.ConnectionError:
        return False


def get_html_files(root_dir: str) -> List[str]:
    """
    Recursively finds all .html files in the directory, filtering out obvious quizzes/assignments by name.
    """
    html_files = []
    # Keywords to skip based on filename
    skip_keywords = ["quiz", "assignment", "submit", "peer_review", "exam"]
    
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".html"):
                lower_name = file.lower()
                if not any(keyword in lower_name for keyword in skip_keywords):
                    html_files.append(os.path.join(root, file))
                # else:
                #     # Optional: Debug print for skipped files
                #     # print(f"Skipping (by name): {file}")
                #     pass

    return sorted(html_files)


def has_summary(file_path: str) -> bool:
    """
    Checks if the file already contains the AI summary div.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
        return bool(soup.find('div', class_='ai-summary-box'))
    except Exception:
        return False


def extract_text_from_html(file_path: str) -> Optional[str]:
    """
    Extracts user-readable text from the Coursera HTML file.
    Returns None if the file looks like a quiz/assignment (has inputs).
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')

        # Check for quiz indicators (interactive elements)
        # Quizzes usually have radio buttons, checkboxes, or text areas for answers.
        # We look for <input type="radio">, <input type="checkbox">, <textarea>, or specific quiz classes.
        
        has_radio = bool(soup.find('input', {'type': 'radio'}))
        has_checkbox = bool(soup.find('input', {'type': 'checkbox'}))
        has_textarea = bool(soup.find('textarea'))
        has_quiz_class = bool(soup.find(class_=re.compile(r'rc-FormPartsQuestion|rc-Option')))

        if has_radio or has_checkbox or has_textarea or has_quiz_class:
            print(f"Skipping (detected quiz/interactive content): {os.path.basename(file_path)}")
            return None

        content_div = soup.find('div', class_='content-wrapper')
        if not content_div:
            content_div = soup.body

        if not content_div:
            return ""

        text = content_div.get_text(separator='\n\n', strip=True)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text
    except (OSError, UnicodeDecodeError) as e:
        with print_lock:
            print(f"Error reading {file_path}: {e}")
        return ""


def inject_summary_into_file(file_path: str, summary_html: str):
    """
    Reads the HTML file, injects the summary_html at the top.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            
        if soup.find('div', class_='ai-summary-box'):
             return

        summary_div = soup.new_tag("div")
        summary_div['class'] = "ai-summary-box"
        summary_div['style'] = (
            "background-color: #f0f8ff; "
            "border: 1px solid #007bff; "
            "border-radius: 8px; "
            "padding: 20px; "
            "margin-bottom: 25px; "
            "font-family: sans-serif;"
        )

        summary_content = BeautifulSoup(summary_html, 'html.parser')
        summary_div.append(summary_content)

        target_div = soup.find('div', class_='content-wrapper')
        if target_div:
            target_div.insert(0, summary_div)
        elif soup.body:
            soup.body.insert(0, summary_div)
        else:
            with print_lock:
                print(f"Could not find a place to insert summary in {file_path}")
            return

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(str(soup))
            
        # with print_lock:
        #     print(f"Successfully injected summary into {os.path.basename(file_path)}")

    except OSError as e:
        with print_lock:
            print(f"File system error while writing to {file_path}: {e}")


def generate_content_updates(current_context: str, new_text: str, file_name: str) -> Tuple[str, str]:
    """
    Asks the local AI to generate summary and update context.
    """

    if len(new_text) < 100:
        # with print_lock:
        #     print(f"Skipping {file_name} (content too short).")
        return "", current_context

    # with print_lock:
    #     print(f"Processing: {file_name} with {MODEL_NAME}...")

    prompt = f"""
    You are an expert tutor creating study aids for a Hebrew speaking student.
    
    PREVIOUS CONTEXT (What the student already learned):
    {current_context}
    
    NEW READING MATERIAL (File: {file_name}):
    {new_text}
    
    *** INSTRUCTIONS ***
    1. Write a concise summary of the "NEW READING MATERIAL" in **HEBREW**.
       - ONLY include new concepts not in the PREVIOUS CONTEXT.
       - Use HTML tags: <h3>, <ul>, <li>, <strong>, <p>.
       - DO NOT use markdown code blocks (```html). Just raw HTML.
    
    2. Write an updated summary of the ENTIRE TOPIC (Previous + New) in **ENGLISH**.
       - This will be used as context for the next file.
       - Keep it compressed and factual.

    *** REQUIRED OUTPUT FORMAT ***
    [HEBREW_HTML_START]
    (Put your Hebrew HTML summary here)
    [HEBREW_HTML_END]
    |||SEPARATOR|||
    (Put your English updated context here)
    """

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": 4096,  # Reduced to fit in 6GB VRAM
            "temperature": 0.3
        }
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=600) 
        response.raise_for_status()
        
        result_json = response.json()
        text_response = result_json.get("response", "")

        if "|||SEPARATOR|||" in text_response:
            parts = text_response.split("|||SEPARATOR|||")
            
            raw_summary = parts[0].strip()
            updated_context = parts[1].strip()
            
            if "[HEBREW_HTML_START]" in raw_summary:
                raw_summary = raw_summary.split("[HEBREW_HTML_START]")[1]
            if "[HEBREW_HTML_END]" in raw_summary:
                raw_summary = raw_summary.split("[HEBREW_HTML_END]")[0]

            local_summary = raw_summary.replace("```html", "").replace("```", "").strip()
            return local_summary, updated_context
        else:
            with print_lock:
                print(f"Warning: AI output format incorrect for {file_name}. Skipping.")
            return "", current_context

    except requests.exceptions.RequestException as e:
        with print_lock:
            print(f"Ollama API error processing {file_name}: {e}")
        return "", current_context


def process_course(course_name: str, files: List[str], pbar: tqdm):
    """
    Process all files for a specific course sequentially to maintain context.
    """
    course_context = ""
    
    for file_path in files:
        file_name = os.path.basename(file_path)
        
        text = extract_text_from_html(file_path)
        
        # If extract_text_from_html returns None, it was a quiz/interactive file.
        if text is None:
            pbar.update(1)
            continue
            
        if not text:
            # Just empty content, skip but count it
            pbar.update(1)
            continue
            
        local_summary_html, course_context = generate_content_updates(course_context, text, file_name)
        
        if local_summary_html:
            inject_summary_into_file(file_path, local_summary_html)
            
        pbar.update(1)
        # Optional: Print progress for this course
        # with print_lock:
        #    print(f"[{course_name}] Processed {file_name}")


def signal_handler(sig, frame):
    print("\nExiting gracefully...")
    stop_ollama_server()
    sys.exit(0)


def is_video(filename: str):
    # if there is a mp4 file with the same name as the HTML file, this is a video
    return os.path.exists(filename.replace(".html", ".mp4"))


def main():
    # Register cleanup on Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    if not start_ollama_server():
        return

    if not check_ollama_model():
        stop_ollama_server()
        return

    print(f"Scanning {ROOT_DIR} for reading materials...")
    files = get_html_files(ROOT_DIR)

    if not files:
        print("No HTML files found.")
        stop_ollama_server()
        return

    files_to_process = [f for f in files if not has_summary(f) and not is_video(f)]
    print(f"Found {len(files)} files. {len(files_to_process)} need processing.")

    # Group files by course
    course_files = defaultdict(list)
    for f in files_to_process:
        # Determine course name from directory structure
        # Assumes structure: coursera_downloads/course_name/...
        rel_path = os.path.relpath(f, ROOT_DIR)
        parts = rel_path.split(os.sep)
        if parts:
            course_name = parts[0]
            course_files[course_name].append(f)
            
    print(f"Identified {len(course_files)} courses to process.")
    print("Starting parallel processing... (Note: The first file per course may take longer)")

    try:
        with tqdm(total=len(files_to_process)) as pbar:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(course_files)) as executor:
                futures = []
                for course_name, files in course_files.items():
                    futures.append(
                        executor.submit(process_course, course_name, files, pbar)
                    )
                
                # Wait for all to complete
                concurrent.futures.wait(futures)
                
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        stop_ollama_server()
        print("\nProcessing complete!")


if __name__ == "__main__":
    main()
