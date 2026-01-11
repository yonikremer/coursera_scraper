#!/usr/bin/env python3
"""
Coursera Material Downloader
Downloads all course materials from enrolled Coursera courses/professional certificates.
"""
import argparse
import os
import queue
import threading
import asyncio
import httpx
from pathlib import Path
from coursera.scraper import CourseraScraper
from create_playlists import process_all_courses
from create_course_navigator import scan_and_generate
from compress_all_videos_gpu import batch_compress_gpu, compress_video_gpu
from summarize_readings import (
    summarize_all_readings,
    summarize_file,
    start_ollama_server,
    stop_ollama_server,
)
from translate_captions import translate_all_captions, process_vtt_file


class DummyPbar:
    def update(self, n):
        pass


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
        except Exception as e:
            print(f"  [GPU Worker] Error: {e}")


async def ai_worker_async(job_queue: queue.Queue, stop_event: threading.Event):
    """Async worker logic for AI tasks."""
    if not start_ollama_server():
        print("  [AI Worker] Failed to start Ollama.")
        return

    print("  [AI Worker] Started/Connected to Ollama.")

    # Serialize AI tasks to avoid VRAM overload or conflicts
    semaphore = asyncio.Semaphore(1)

    # Fake progress bar for process_vtt_file
    dummy_pbar = DummyPbar()

    async with httpx.AsyncClient(timeout=600) as client:
        while not stop_event.is_set() or not job_queue.empty():
            try:
                # Non-blocking check to allow yielding
                try:
                    item = job_queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(1)
                    continue

                file_path, type_ = item

                if type_ == "subtitle":
                    # print(f"  [AI Worker] Translating {file_path.name}...")
                    await process_vtt_file(
                        str(file_path), client, semaphore, dummy_pbar
                    )

                elif type_ == "reading":
                    # print(f"  [AI Worker] Summarizing {file_path.name}...")
                    # summarize_file is synchronous, so we just call it.
                    # Ideally we'd run in executor, but since we are serializing anyway,
                    # it's ok.
                    summarize_file(str(file_path))

                job_queue.task_done()
            except Exception as e:
                print(f"  [AI Worker] Error: {e}")


def ai_worker_runner(job_queue: queue.Queue, stop_event: threading.Event):
    """Thread entry point for AI worker."""
    asyncio.run(ai_worker_async(job_queue, stop_event))


def main():
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
        default="https://www.coursera.org/professional-certificates/"
        "google-advanced-data-analytics",
        help="Professional certificate URL",
    )
    parser.add_argument(
        "--output-dir",
        default="coursera_downloads",
        help="Output directory for downloads (default: coursera_downloads)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (not recommended for login)",
    )

    # New flags for controlling steps
    parser.add_argument(
        "--skip-download", action="store_true", help="Skip the downloading phase"
    )
    parser.add_argument(
        "--skip-compress", action="store_true", help="Skip video compression"
    )
    parser.add_argument(
        "--skip-translate", action="store_true", help="Skip caption translation"
    )
    parser.add_argument(
        "--skip-summary", action="store_true", help="Skip reading summarization"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Coursera Material Downloader")
    print("=" * 60)
    print(f"Email: {args.email}")
    print(f"Cert:  {args.cert_url}")
    print(f"Out:   {args.output_dir}")
    print("=" * 60)

    # Queue and Event for parallel workers
    post_process_queue = queue.Queue()
    stop_workers_event = threading.Event()
    workers = []

    # 1. Download Phase
    if not args.skip_download:
        # Start Workers if not skipping their respective tasks
        if not args.skip_compress:
            t_gpu = threading.Thread(
                target=gpu_worker,
                args=(post_process_queue, stop_workers_event),
                daemon=True,
            )
            t_gpu.start()
            workers.append(t_gpu)

        if not args.skip_translate and not args.skip_summary:
            t_ai = threading.Thread(
                target=ai_worker_runner,
                args=(post_process_queue, stop_workers_event),
                daemon=True,
            )
            t_ai.start()
            workers.append(t_ai)

        def on_content(path, type_):
            # Callback to add items to queue
            # Filter based on args
            if type_ == "video" and not args.skip_compress:
                post_process_queue.put((path, type_))
            elif type_ == "subtitle" and not args.skip_translate:
                post_process_queue.put((path, type_))
            elif type_ == "reading" and not args.skip_summary:
                post_process_queue.put((path, type_))

        print("\nStarting Download Phase (with Parallel Post-Processing)...")
        scraper = CourseraScraper(
            email=args.email,
            download_dir=args.output_dir,
            headless=args.headless,
            on_content_downloaded=on_content,
        )

        try:
            scraper.download_certificate(cert_url=args.cert_url)
        except Exception as e:
            print(f"\nDownload phase error: {e}")
        finally:
            # Stop workers
            print("\nStopping workers and waiting for queue to empty...")
            stop_workers_event.set()
            for w in workers:
                w.join()

            # Stop Ollama if we started it here (though script manages its own,
            # ai_worker logic might leave it running if process was shared,
            # but stop_ollama_server() kills the global process variable).
            stop_ollama_server()

    else:
        print("\nSkipping Download Phase.")

    # Ensure output directory exists for post-processing
    if not os.path.exists(args.output_dir):
        print(f"Error: Output directory '{args.output_dir}' does not exist.")
        return

    # 2-4. Sequential / Clean-up Passes
    # These verify everything is done or process anything showing up from
    # skip_download=True. They automatically skip already processed files.

    if not args.skip_compress:
        print("\n" + "-" * 60)
        print("Finalizing Video Compression...")
        batch_compress_gpu(args.output_dir)

    if not args.skip_translate:
        print("\n" + "-" * 60)
        print("Finalizing Caption Translation...")
        translate_all_captions(args.output_dir)

    if not args.skip_summary:
        print("\n" + "-" * 60)
        print("Finalizing Reading Summarization...")
        summarize_all_readings(args.output_dir)

    # 5. Generate Playlists
    print("\n" + "=" * 60)
    print("Generating Course Playlists...")
    process_all_courses(args.output_dir)

    # 6. Generate Navigation
    print("Updating Course Navigation...")
    scan_and_generate(Path(args.output_dir))


if __name__ == "__main__":
    main()
