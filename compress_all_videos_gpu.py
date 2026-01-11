import os
import subprocess
import time
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


def compress_video_gpu(input_path):
    # Skip if it looks like a temp file
    if "temp_compressed_" in input_path:
        return False

    basename = os.path.basename(input_path)
    dirname = os.path.dirname(input_path)
    temp_output = os.path.join(dirname, f"temp_compressed_{basename}")

    # NVENC command
    # -cq 32: Increased from 28 to target smaller file sizes.
    # -rc vbr: Variable Bit Rate.
    # -preset p6: Start with p6.
    ffmpeg_path = (
        r"C:\Users\yonik\AppData\Local\Microsoft\WinGet\Packages"
        r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build"
        r"\bin\ffmpeg.exe"
    )
    cmd = [
        ffmpeg_path,
        "-i",
        input_path,
        "-c:v",
        "hevc_nvenc",
        "-rc",
        "vbr",
        "-cq",
        "32",
        "-preset",
        "p6",
        "-c:a",
        "copy",
        "-y",
        "-loglevel",
        "error",
        temp_output,
    ]

    try:
        start_time = time.time()
        subprocess.run(cmd, check=True)
        duration = time.time() - start_time

        if os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            orig_size = os.path.getsize(input_path)
            new_size = os.path.getsize(temp_output)

            # STRICT CHECK: Only replace if newer is smaller
            if new_size < orig_size:
                os.remove(input_path)
                os.rename(temp_output, input_path)
                reduction = (1 - new_size / orig_size) * 100
                logging.info(
                    f"GPU Compressed {basename}: "
                    f"{orig_size / 1024 / 1024:.1f}MB -> "
                    f"{new_size / 1024 / 1024:.1f}MB "
                    f"(-{reduction:.1f}%) in {duration:.1f}s"
                )
                return True
            else:
                logging.info(
                    f"Skipped {basename}: Compressed size "
                    f"({new_size / 1024 / 1024:.1f}MB) >= Original "
                    f"({orig_size / 1024 / 1024:.1f}MB)"
                )
                os.remove(temp_output)
                return False
        else:
            logging.error(f"Compression failed for {basename}: Output invalid")
            if os.path.exists(temp_output):
                os.remove(temp_output)
            return False

    except Exception as e:
        logging.error(f"Error compressing {basename}: {e}")
        if os.path.exists(temp_output):
            os.remove(temp_output)
        return False


def batch_compress_gpu(root_dir):
    videos = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.lower().endswith(".mp4"):
                videos.append(os.path.join(dirpath, filename))

    total_videos = len(videos)
    print(f"Found {total_videos} videos to compress with GPU.")

    success_count = 0
    start_total = time.time()

    for i, video_path in enumerate(videos, 1):
        # Optional: Print every file to stdout or just keep it clean?
        # User requested speed, print slows down slightly but gives feedback.
        # I'll print.
        print(f"Processing {i}/{total_videos}: {os.path.basename(video_path)}")
        if compress_video_gpu(video_path):
            success_count += 1

    total_time = time.time() - start_total
    print("\nGPU Batch processing complete.")
    print(f"Successfully compressed {success_count}/{total_videos} videos.")
    print(f"Total time: {total_time / 60:.1f} minutes")


if __name__ == "__main__":
    root = r"C:\Users\yonik\PycharmProjects\coursera_scraper\coursera_downloads"
    if os.path.exists(root):
        batch_compress_gpu(root)
    else:
        print(f"Directory not found: {root}")
