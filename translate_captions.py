import os
import time
from typing import List
from deep_translator import GoogleTranslator

# Configuration
ROOT_DIR = "coursera_downloads"
SOURCE_LANG = 'en'
TARGET_LANG = 'iw'
BATCH_SIZE = 30  # Number of lines to translate in one request
DELAY_BETWEEN_CHUNKS = 0.5  # Seconds to sleep between API calls to avoid blocking
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

def translate_batch_with_retry(translator: GoogleTranslator, batch: List[str]) -> List[str]:
    """
    Translates a batch of text with retry logic.
    """
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return translator.translate_batch(batch)
        except Exception as e:
            print(f"    [Warning] Batch translation failed (Attempt {attempt + 1}/{RETRY_ATTEMPTS}): {e}")
            time.sleep(2 * (attempt + 1))  # Exponential backoff
    
    print("    [Error] Failed to translate batch after retries. Returning original text.")
    return batch

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
    translator = GoogleTranslator(source=SOURCE_LANG, target=TARGET_LANG)
    translated_texts = []

    for i in range(0, len(text_to_translate), BATCH_SIZE):
        batch = text_to_translate[i : i + BATCH_SIZE]
        # print(f"    Translating batch {i//BATCH_SIZE + 1}/{total_batches}...")
        
        translated_batch = translate_batch_with_retry(translator, batch)
        translated_texts.extend(translated_batch)
        
        if i + BATCH_SIZE < len(text_to_translate):
            time.sleep(DELAY_BETWEEN_CHUNKS)

    # 3. Reconstruct content
    # Make a copy of lines
    new_lines = list(lines)
    
    # Verify alignment
    if len(text_lines_indices) != len(translated_texts):
        print(f"    [Error] Mismatch in translation count. Orig: {len(text_lines_indices)}, Trans: {len(translated_texts)}")
        # Fallback: Just save original to avoid corruption, or save partial
        return

    for idx_in_original, translated_text in zip(text_lines_indices, translated_texts):
        # Preserve original indentation/newlines if possible, though VTT is usually plain
        # VTT text usually doesn't have leading indentation
        new_lines[idx_in_original] = translated_text + "\n"

    # 4. Write to new file
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print(f"    Saved: {os.path.basename(output_path)}")
    except Exception as e:
        print(f"    [Error] Could not write file: {e}")

import argparse

import concurrent.futures

def main():
    parser = argparse.ArgumentParser(description="Translate VTT files from English to Hebrew.")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of files to process.")
    parser.add_argument("--workers", type=int, default=10, help="Number of parallel threads.")
    args = parser.parse_args()

    files = get_vtt_files(ROOT_DIR)
    
    if not files:
        print(f"No '_en.vtt' files found in {ROOT_DIR}")
        return

    print(f"Found {len(files)} files to process.")
    if args.limit:
        print(f"Limiting to first {args.limit} files.")
        files = files[:args.limit]

    print(f"Starting translation with {args.workers} threads...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        # Submit all tasks
        futures = [executor.submit(process_vtt_file, file_path) for file_path in files]
        
        # Wait for completion (optional progress tracking could be added here)
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"Thread generated an exception: {e}")

    print("\nAll tasks completed.")

if __name__ == "__main__":
    main()
