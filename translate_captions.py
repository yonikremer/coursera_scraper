import os
import time
import json
import argparse
import requests
import concurrent.futures
from typing import List, Optional

# Configuration
ROOT_DIR = "coursera_downloads"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3-translator:4b"
BATCH_SIZE = 15  # Gemma 3 is more capable, we can try slightly larger batches
RETRY_ATTEMPTS = 3

def get_vtt_files(root_dir: str) -> List[str]:
    """
    Recursively finds all *_en.vtt files in the directory.
    """
    vtt_files = []
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith("_en.vtt"):
                vtt_files.append(os.path.join(root, file))
    return sorted(vtt_files)

def is_timestamp(line: str) -> bool:
    """
    Checks if a line looks like a VTT timestamp: '00:00:00.000 --> 00:00:05.000'
    """
    return '-->' in line and any(c.isdigit() for c in line)

def is_metadata(line: str) -> bool:
    """
    Checks for VTT header or metadata/IDs.
    """
    line = line.strip()
    if not line:
        return False
    if line == "WEBVTT":
        return True
    if line.startswith("NOTE"):
        return True
    # If it's a number only (sometimes used as IDs in subtitles), treat as metadata
    if line.isdigit():
        return True
    return False

def translate_batch_ollama(batch: List[str]) -> Optional[List[str]]:
    """
    Translates a batch of text using Ollama (Gemma 3).
    Expects a JSON array input and returns a JSON array output.
    """
    # Prompt is simplified because system message handles instructions
    prompt = json.dumps(batch)

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }

    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = requests.post(OLLAMA_URL, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()
            response_text = result.get("response", "").strip()

            # cleanup markdown if present (e.g. ```json ... ```)
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
            
            translated_batch = json.loads(response_text)

            if not isinstance(translated_batch, list):
                print(f"    [Warning] Ollama returned non-list JSON: {type(translated_batch)}")
                continue

            if len(translated_batch) != len(batch):
                print(f"    [Warning] Mismatch in translation count (Attempt {attempt + 1}). "
                      f"Sent: {len(batch)}, Got: {len(translated_batch)}")
                continue

            return translated_batch

        except json.JSONDecodeError as e:
            print(f"    [Warning] Failed to parse JSON from Ollama (Attempt {attempt + 1}): {e}")
            # print(f"    Response was: {response_text[:100]}...")
        except Exception as e:
            print(f"    [Error] Ollama request failed (Attempt {attempt + 1}): {e}")
            time.sleep(2)

    print("    [Error] Failed to translate batch after retries.")
    return None

def process_vtt_file(file_path: str):
    """
    Parses, translates, and saves a VTT file.
    """
    output_path = file_path.replace("_en.vtt", "_heb.vtt")
    
    if os.path.exists(output_path):
        # Optional: Skip if already exists
        # print(f"Skipping {os.path.basename(file_path)} (Target exists)")
        return

    print(f"Processing: {os.path.basename(file_path)}")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"    [Error] Could not read file: {e}")
        return

    # 1. Identify text lines to translate
    # We will store indices to put translated text back later
    text_lines_indices = []
    text_to_translate = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if is_metadata(stripped):
            continue
        if is_timestamp(stripped):
            continue
        
        # It's likely text
        # Only translate if it has letters
        if any(c.isalpha() for c in stripped):
            text_lines_indices.append(i)
            text_to_translate.append(stripped)

    if not text_to_translate:
        print("    No text content found to translate.")
        return

    # 2. Translate in batches
    translated_texts = []
    total_batches = (len(text_to_translate) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(text_to_translate), BATCH_SIZE):
        batch = text_to_translate[i : i + BATCH_SIZE]
        
        translated_batch = translate_batch_ollama(batch)
        if translated_batch is None:
            print(f"    [Error] Aborting {os.path.basename(file_path)} due to translation failure.")
            return

        translated_texts.extend(translated_batch)
        # No sleep needed for local LLM usually, but small breath doesn't hurt
        # time.sleep(0.1)

    # 3. Reconstruct content
    new_lines = list(lines)
    
    # Verify alignment (double check)
    if len(text_lines_indices) != len(translated_texts):
        print(f"    [Error] Final mismatch. Orig: {len(text_lines_indices)}, Trans: {len(translated_texts)}")
        return

    for idx_in_original, translated_text in zip(text_lines_indices, translated_texts):
        new_lines[idx_in_original] = str(translated_text) + "\n"

    # 4. Write to new file
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print(f"    Saved: {os.path.basename(output_path)}")
    except Exception as e:
        print(f"    [Error] Could not write file: {e}")

def main():
    parser = argparse.ArgumentParser(description="Translate VTT files from English to Hebrew using Ollama.")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of files to process.")
    # Since we are using local GPU, we can probably do 2-3 parallel requests if VRAM allows, 
    # but sequential is safer for 4050 (6GB VRAM) running Llama 3 (4GB+).
    # Let's default to 1 worker to avoid OOM.
    parser.add_argument("--workers", type=int, default=1, help="Number of parallel threads.")
    args = parser.parse_args()

    files = get_vtt_files(ROOT_DIR)
    
    if not files:
        print(f"No '_en.vtt' files found in {ROOT_DIR}")
        return

    print(f"Found {len(files)} files to process.")
    if args.limit:
        print(f"Limiting to first {args.limit} files.")
        files = files[:args.limit]

    print(f"Starting translation with {args.workers} threads using {OLLAMA_MODEL}...")

    # Verify Ollama is running
    try:
        requests.get(OLLAMA_URL.replace("/api/generate", "/"))
    except Exception:
        print(f"Error: Could not connect to Ollama at {OLLAMA_URL}. Is it running?")
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(process_vtt_file, file_path) for file_path in files]
        
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"Thread generated an exception: {e}")

    print("\nAll tasks completed.")

if __name__ == "__main__":
    main()
