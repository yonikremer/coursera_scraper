import os
import re
from bs4 import BeautifulSoup
import google.generativeai as genai
from google.api_core import exceptions as api_exceptions
from typing import List, Tuple

# Configuration
# Expects GEMINI_API_KEY in environment variables
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    print("Warning: GEMINI_API_KEY not found in environment variables.")
    print("Please set it before running the script (e.g., set GEMINI_API_KEY=your_key).")
    exit(1)

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

ROOT_DIR = "coursera_downloads"

def get_html_files(root_dir: str) -> List[str]:
    """
    Recursively finds all .html files in the directory.
    Returns a sorted list of file paths.
    """
    html_files = []
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".html"):
                html_files.append(os.path.join(root, file))
    return sorted(html_files)

def extract_text_from_html(file_path: str) -> str:
    """
    Extracts user-readable text from the Coursera HTML file.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
        
        content_div = soup.find('div', class_='content-wrapper')
        if not content_div:
            content_div = soup.body
            
        if not content_div:
            return ""

        text = content_div.get_text(separator='\n\n', strip=True)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text
    except (OSError, UnicodeDecodeError) as e:
        print(f"Error reading {file_path}: {e}")
        return ""

def inject_summary_into_file(file_path: str, summary_html: str):
    """
    Reads the HTML file, injects the summary_html at the top of the content-wrapper,
    and overwrites the file.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
        
        # Create a new div for the summary.
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
        
        # Parse the AI's HTML snippet and append it to our container.
        summary_content = BeautifulSoup(summary_html, 'html.parser')
        summary_div.append(summary_content)

        # Find where to insert.
        target_div = soup.find('div', class_='content-wrapper')
        if target_div:
            target_div.insert(0, summary_div)
        elif soup.body:
            soup.body.insert(0, summary_div)
        else:
            print(f"Could not find a place to insert summary in {file_path}")
            return

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(str(soup))
            
        print(f"Successfully injected summary into {file_path}")

    except OSError as e:
        print(f"File system error while writing to {file_path}: {e}")

def generate_content_updates(current_context: str, new_text: str, file_name: str) -> Tuple[str, str]:
    """
    Asks the AI to:
    1. Generate an HTML summary for the current file (focusing on NEW info).
    2. Update the global context string.
    
    Returns: (html_summary_for_file, updated_global_context)
    """
    
    if len(new_text) < 100:
        print(f"Skipping {file_name} (content too short).")
        return "", current_context

    print(f"Processing: {file_name}...")

    prompt = f"""
    You are an expert tutor creating study aids.
    
    --- CONTEXT (What the student has already learned from previous files) ---
    {current_context}
    ------------------------------------------------------------------------
    
    --- NEW READING (Current File: {file_name}) ---
    {new_text}
    ---------------------------------------------------------------
    
    **TASK:**
    1. Generate a concise **HTML Summary** of the "NEW READING".
       - Focus ONLY on **new concepts, definitions, or insights** not already in the CONTEXT.
       - If the text is just a generic intro or purely repetitive, provide a very brief 1-sentence summary saying so.
       - Use <h3>, <ul>, <li>, <strong>, <p> tags for the HTML. 
       - Do NOT include <html>, <head>, or <body> tags. Just the content.
    
    2. Create an **Updated Context** summary.
       - This should be a compressed plain-text summary of everything learned so far (CONTEXT + NEW READING).
       - This will be passed to the next step to prevent repetition.
    
    **OUTPUT FORMAT:**
    Separate the two parts with exactly this string: |||SEPARATOR|||
    
    Example Output:
    <h3>Key Concepts in Module 3</h3><p>...</p>
    |||SEPARATOR|||
    (Updated plain text context...)
    """

    try:
        response = model.generate_content(prompt)
        text_response = response.text
        
        if "|||SEPARATOR|||" in text_response:
            parts = text_response.split("|||SEPARATOR|||")
            local_summary = parts[0].strip()
            # Remove markdown code blocks if AI adds them.
            local_summary = local_summary.replace("```html", "").replace("```", "")
            updated_context = parts[1].strip()
            return local_summary, updated_context
        else:
            # Fallback if separator is missing.
            print("Warning: Separator missing in AI response. Using full response as context.")
            return text_response, current_context + "\n" + new_text[:500]

    except (api_exceptions.GoogleAPICallError, api_exceptions.RetryError) as e:
        print(f"API error while processing {file_name}: {e}")
        return "", current_context

def main():
    print(f"Scanning {ROOT_DIR} for reading materials...")
    files = get_html_files(ROOT_DIR)
    
    if not files:
        print("No HTML files found.")
        return

    print(f"Found {len(files)} files.")
    
    # This string tracks what we have learned so far to avoid repetition.
    global_context = ""
    
    for i, file_path in enumerate(files):
        file_name = os.path.basename(file_path)
        
        # 1. Extract text.
        text = extract_text_from_html(file_path)
        if not text:
            continue
            
        # 2. Generate Summary & Update Context.
        local_summary_html, global_context = generate_content_updates(global_context, text, file_name)
        
        # 3. Inject Summary into HTML.
        if local_summary_html:
            inject_summary_into_file(file_path, local_summary_html)

    print(f"\nProcessing complete!")

if __name__ == "__main__":
    main()
