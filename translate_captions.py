"""
Script to translate VTT subtitle files from English to Hebrew using Ollama.
Supports parallel processing of lines within a file.
"""
import os
import re
import argparse
import asyncio
from typing import List, Optional, Tuple
import httpx
from tqdm.asyncio import tqdm

# Configuration
ROOT_DIR = "coursera_downloads"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3-translator:4b"
RETRY_ATTEMPTS = 3
DEFAULT_CONCURRENCY = 64  # Total parallel requests across all files


def get_vtt_files(root_dir: str) -> List[str]:
    """Recursively find all English VTT files."""
    vtt_files = []
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.endswith("_en.vtt"):
                vtt_files.append(os.path.join(root, file))
    return sorted(vtt_files)


def is_timestamp(line: str) -> bool:
    """Check if a line contains a VTT timestamp."""
    return "-->" in line and any(c.isdigit() for c in line)


def is_metadata(line: str) -> bool:
    """Check if a line is a VTT metadata line."""
    line = line.strip()
    if not line:
        return False
    if line == "WEBVTT":
        return True
    if line.startswith("NOTE"):
        return True
    if line.isdigit():
        return True
    return False


def clean_translation(text: str) -> str:
    """Strips markdown, JSON brackets, and extra quotes from the translation."""
    text = text.strip()
    # Remove markdown code blocks
    text = re.sub(r"```(?:json|html|text)?\s*(.*?)\s*```", r"\1", text, flags=re.DOTALL)
    # Remove simple [ "text" ] if model wraps it
    text = re.sub(r'^\[\s*"(.*?)"\s*\]$', r"\1", text)
    # Remove wrapping quotes
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1].strip()
    return text.strip()


async def translate_line_async(
    client: httpx.AsyncClient, text: str, semaphore: asyncio.Semaphore
) -> Optional[str]:
    """Translate a single line using the Ollama API."""
    prompt = f"Translate to Hebrew. Return ONLY the translation.\nText: {text}"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 128},
    }

    async with semaphore:
        for _ in range(RETRY_ATTEMPTS):
            try:
                response = await client.post(OLLAMA_URL, json=payload, timeout=60.0)
                response.raise_for_status()
                result = response.json()
                translated = result.get("response", "")

                cleaned = clean_translation(translated)
                if cleaned:
                    return cleaned
            except httpx.HTTPError:
                await asyncio.sleep(0.5)
            except (ValueError, KeyError) as e:
                print(f"Error parsing response: {e}.")
                break
    return None


def _extract_translatable_lines(lines: List[str]) -> Tuple[List[int], List[str]]:
    """Helper to extract indices and text of lines that need translation."""
    indices = []
    texts = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or is_metadata(stripped) or is_timestamp(stripped):
            continue
        if any(c.isalpha() for c in stripped):
            indices.append(i)
            texts.append(stripped)
    return indices, texts


async def process_vtt_file(
    file_path: str, client: httpx.AsyncClient, semaphore: asyncio.Semaphore, pbar: tqdm
) -> bool:
    """Process a single VTT file: extract text, translate, and save results."""
    output_path = file_path.replace("_en.vtt", "_heb.vtt")
    if os.path.exists(output_path):
        pbar.update(1)
        return True

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        print(f"Failed to read {file_path}: {e}.")
        pbar.update(1)
        return False

    indices, texts = _extract_translatable_lines(lines)
    if not texts:
        translated_texts = []
    else:
        tasks = [translate_line_async(client, text, semaphore) for text in texts]
        translated_texts = await asyncio.gather(*tasks)

        if any(t is None for t in translated_texts):
            pbar.update(1)
            return False

    new_lines = list(lines)
    for idx, trans in zip(indices, translated_texts):
        if trans is not None:
            new_lines[idx] = trans + "\n"

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        pbar.update(1)
        return True
    except OSError as e:
        print(f"Failed to write {output_path}: {e}.")
        pbar.update(1)
        return False


async def run_translation(
    root_dir: str, concurrency: int = DEFAULT_CONCURRENCY, limit: Optional[int] = None
):
    """Orchestrate the translation of all VTT files in a directory."""
    all_vtt = get_vtt_files(root_dir)
    files_to_process = [
        f for f in all_vtt if not os.path.exists(f.replace("_en.vtt", "_heb.vtt"))
    ]

    if limit:
        files_to_process = files_to_process[:limit]

    if not files_to_process:
        print("Everything is up to date.")
        return

    semaphore = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(
        max_keepalive_connections=concurrency, max_connections=concurrency
    )

    async with httpx.AsyncClient(limits=limits) as client:
        with tqdm(
            total=len(files_to_process), desc="Translating Videos", unit="video"
        ) as pbar:
            for file_path in files_to_process:
                await process_vtt_file(file_path, client, semaphore, pbar)

    print("\nProcessing complete.")


def translate_all_captions(root_dir: str, concurrency: int = DEFAULT_CONCURRENCY):
    """Synchronous wrapper to run the translation process."""
    try:
        asyncio.run(run_translation(root_dir, concurrency))
    except (KeyboardInterrupt, SystemExit):
        print("\nTranslation sequence interrupted.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Translate VTT files with parallel processing."
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    p.add_argument("--dir", default=ROOT_DIR, help="Root directory to scan")
    a = p.parse_args()
    translate_all_captions(a.dir, a.concurrency)
