import os
import asyncio
import argparse
import httpx
import re
from typing import List, Optional
from tqdm.asyncio import tqdm

# Configuration
ROOT_DIR = "coursera_downloads"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3-translator:4b"
RETRY_ATTEMPTS = 3
DEFAULT_CONCURRENCY = 64  # Total parallel requests across all files

def get_vtt_files(root_dir: str) -> List[str]:
    vtt_files = []
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.endswith("_en.vtt"):
                vtt_files.append(os.path.join(root, file))
    return sorted(vtt_files)

def is_timestamp(line: str) -> bool:
    return '-->' in line and any(c.isdigit() for c in line)

def is_metadata(line: str) -> bool:
    line = line.strip()
    if not line: return False
    if line == "WEBVTT": return True
    if line.startswith("NOTE"):
        return True
    if line.isdigit():
        return True
    return False

def clean_translation(text: str) -> str:
    """
    Strips markdown, JSON brackets, and extra quotes.
    """
    text = text.strip()
    # Remove markdown code blocks
    text = re.sub(r'```(?:json|html|text)?\s*(.*?)\s*```', r'\1', text, flags=re.DOTALL)
    # Remove simple [ "text" ] if model wraps it
    text = re.sub(r'^\[\s*"(.*?)"\s*\]$', r'\1', text)
    # Remove wrapping quotes
    if (text.startswith('"') and text.endswith('"')) or \
       (text.startswith("'" ) and text.endswith("'" )):
        text = text[1:-1].strip()
    return text.strip()

async def translate_line_async(client: httpx.AsyncClient, text: str, semaphore: asyncio.Semaphore) -> Optional[str]:
    prompt = f"Translate to Hebrew. Return ONLY the translation.\nText: {text}"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 128}
    }

    async with semaphore:
        for attempt in range(RETRY_ATTEMPTS):
            try:
                response = await client.post(OLLAMA_URL, json=payload, timeout=60.0)
                response.raise_for_status()
                result = response.json()
                translated = result.get("response", "")
                
                cleaned = clean_translation(translated)
                if cleaned:
                    return cleaned
            except Exception:
                await asyncio.sleep(0.5)
    return None

async def process_vtt_file(file_path: str, client: httpx.AsyncClient, semaphore: asyncio.Semaphore, pbar: tqdm):
    output_path = file_path.replace("_en.vtt", "_heb.vtt")
    if os.path.exists(output_path):
        pbar.update(1)
        return True

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception:
        pbar.update(1)
        return False

    text_indices = []
    texts = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or is_metadata(stripped) or is_timestamp(stripped):
            continue
        if any(c.isalpha() for c in stripped):
            text_indices.append(i)
            texts.append(stripped)

    if not texts:
        translated_texts = []
    else:
        tasks = [translate_line_async(client, text, semaphore) for text in texts]
        translated_texts = await asyncio.gather(*tasks)

        if any(t is None for t in translated_texts):
            pbar.update(1)
            return False

    new_lines = list(lines)
    for idx, translated in zip(text_indices, translated_texts):
        new_lines[idx] = translated + "\n"

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        pbar.update(1)
        return True
    except Exception:
        pbar.update(1)
        return False

async def run_translation(root_dir: str, concurrency: int = DEFAULT_CONCURRENCY, limit: Optional[int] = None):
    all_vtt = get_vtt_files(root_dir)
    files_to_process = [f for f in all_vtt if not os.path.exists(f.replace("_en.vtt", "_heb.vtt"))]
    
    if limit:
        files_to_process = files_to_process[:limit]

    if not files_to_process:
        print("Everything is up to date.")
        return

    semaphore = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_keepalive_connections=concurrency, max_connections=concurrency)
    
    async with httpx.AsyncClient(limits=limits) as client:
        with tqdm(total=len(files_to_process), desc="Translating Videos", unit="video") as pbar:
            # We process files one by one to keep semaphore focused on line level 
            # while still providing a nice file-level progress bar.
            for file_path in files_to_process:
                await process_vtt_file(file_path, client, semaphore, pbar)

    print("\nProcessing complete.")

def translate_all_captions(root_dir: str, concurrency: int = DEFAULT_CONCURRENCY):
    asyncio.run(run_translation(root_dir, concurrency))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Translate VTT files with parallel processing.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    args = parser.parse_args()

    asyncio.run(run_translation(ROOT_DIR, args.concurrency, args.limit))