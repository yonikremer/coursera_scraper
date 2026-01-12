"""
Main entry point for the Coursera Material Downloader.
Integrated with parallel compression and AI post-processing.
"""
import argparse
import asyncio
import os
import queue
import threading
from pathlib import Path

# pylint: disable=import-error,no-name-in-module
import httpx
from selenium.common.exceptions import WebDriverException

from coursera.scraper import CourseraScraper
from coursera.video_utils import batch_compress_gpu, compress_video_gpu
from coursera.playlist_generator import process_all_courses
from coursera.navigator import scan_and_generate
from summarize_readings import (
    summarize_all_readings,
    summarize_file,
    start_ollama_server,
    stop_ollama_server,
)
from translate_captions import translate_all_captions, process_vtt_file


class DummyPbar:  # pylint: disable=too-few-public-methods
    """A dummy progress bar to replace tqdm when not needed."""

    def update(self, n: int):
        """No-op update."""


def gpu_worker(job_queue: queue.Queue, stop_event: threading.Event):
    """Worker thread for GPU video compression."""
    print("  [GPU Worker] Started.")
    while not stop_event.is_set() or not job_queue.empty():
        try:
            item = job_queue.get(timeout=1)
            file_path, type_ = item

            if type_ == "video":
                # print(f"  [GPU Worker] Compressing {file_path.name}...")
                compress_video_gpu(str(file_path))

            job_queue.task_done()
        except queue.Empty:
            continue
        except (RuntimeError, OSError) as e:
            print(f"  [GPU Worker] Error: {e}")


async def ai_worker_async(job_queue: queue.Queue, stop_event: threading.Event):
    """Async worker logic for AI tasks."""
    if not start_ollama_server():
        print("  [AI Worker] Failed to start Ollama.")
        return

    print("  [AI Worker] Started/Connected to Ollama.")
    semaphore = asyncio.Semaphore(1)
    dummy_pbar = DummyPbar()

    async with httpx.AsyncClient(timeout=600) as client:
        while not stop_event.is_set() or not job_queue.empty():
            try:
                try:
                    item = job_queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(1)
                    continue

                file_path, type_ = item
                if type_ == "subtitle":
                    await process_vtt_file(
                        str(file_path), client, semaphore, dummy_pbar
                    )
                elif type_ == "reading":
                    summarize_file(str(file_path))

                job_queue.task_done()
            except (RuntimeError, ValueError, httpx.HTTPError) as e:
                print(f"  [AI Worker] Error: {e}")


def ai_worker_runner(job_queue: queue.Queue, stop_event: threading.Event):
    """Thread entry point for AI worker."""
    asyncio.run(ai_worker_async(job_queue, stop_event))


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Download all materials from Coursera,\n"
        "integrated with parallel compression and AI post-processing."
    )
    parser.add_argument(
        "--email",
        default="yoni.kremer@gmail.com",
        help="Google account email (default: yoni.kremer@gmail.com)",
    )
    parser.add_argument(
        "--cert-url",
        default="https://www.coursera.org/professional-certificates/google-advanced-data-analytics",
        help="Professional certificate URL",
    )
    parser.add_argument(
        "--output-dir",
        default="coursera_downloads",
        help="Output directory (default: coursera_downloads)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode",
    )
    parser.add_argument(
        "--skip-download", action="store_true", help="Skip download phase"
    )
    parser.add_argument("--skip-compress", action="store_true", help="Skip compression")
    parser.add_argument(
        "--skip-translate", action="store_true", help="Skip translation"
    )
    parser.add_argument(
        "--skip-summary", action="store_true", help="Skip summarization"
    )
    return parser.parse_args()


def run_download_phase(args, post_process_queue, stop_workers_event, workers):
    """Execute the download phase with background workers."""
    if args.skip_download:
        print("\nSkipping Download Phase.")
        return

    if not args.skip_compress:
        t_gpu = threading.Thread(
            target=gpu_worker,
            args=(post_process_queue, stop_workers_event),
            daemon=True,
        )
        t_gpu.start()
        workers.append(t_gpu)

    if not args.skip_translate or not args.skip_summary:
        t_ai = threading.Thread(
            target=ai_worker_runner,
            args=(post_process_queue, stop_workers_event),
            daemon=True,
        )
        t_ai.start()
        workers.append(t_ai)

    def on_content(path, type_):
        if type_ == "video" and not args.skip_compress:
            post_process_queue.put((path, type_))
        elif type_ == "subtitle" and not args.skip_translate:
            post_process_queue.put((path, type_))
        elif type_ == "reading" and not args.skip_summary:
            post_process_queue.put((path, type_))

    print("\nStarting Download Phase...")
    scraper = CourseraScraper(
        email=args.email,
        download_dir=args.output_dir,
        headless=args.headless,
        on_content_downloaded=on_content,
    )

    try:
        scraper.download_certificate(cert_url=args.cert_url)
    except (RuntimeError, WebDriverException) as e:
        print(f"\nDownload phase error: {e}")
    finally:
        print("\nStopping workers...")
        stop_workers_event.set()
        for worker in workers:
            worker.join()
        stop_ollama_server()


def run_finalization_phase(args):
    """Execute sequential finalization steps."""
    if not os.path.exists(args.output_dir):
        print(f"Error: Output directory '{args.output_dir}' does not exist.")
        return

    if not args.skip_compress:
        print("\n" + "-" * 60 + "\nFinalizing Video Compression...")
        batch_compress_gpu(args.output_dir)

    if not args.skip_translate:
        print("\n" + "-" * 60 + "\nFinalizing Caption Translation...")
        translate_all_captions(args.output_dir)

    if not args.skip_summary:
        print("\n" + "-" * 60 + "\nFinalizing Reading Summarization...")
        summarize_all_readings(args.output_dir)

    print("\n" + "=" * 60 + "\nGenerating Course Playlists...")
    process_all_courses(args.output_dir)
    print("Updating Course Navigation...")
    scan_and_generate(Path(args.output_dir))


def main():
    """Main execution flow."""
    args = parse_args()
    print("=" * 60 + "\nCoursera Material Downloader\n" + "=" * 60)
    print(
        f"Email: {args.email}\nCert:  {args.cert_url}\nOut:   {args.output_dir}\n"
        + "=" * 60
    )

    queue_inst = queue.Queue()
    stop_event = threading.Event()
    workers_list = []

    run_download_phase(args, queue_inst, stop_event, workers_list)
    run_finalization_phase(args)


if __name__ == "__main__":
    main()
