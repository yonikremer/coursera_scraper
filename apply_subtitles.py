import os
import shutil

ROOT_DIR = "coursera_downloads"


def apply_subtitles():
    """
    Scans for *_heb.vtt files and creates a copy named *.vtt (matching the video filename).
    This forces most players (VLC, Windows Media Player) to load the Hebrew subtitles by default.
    """
    count = 0
    print(f"Scanning {ROOT_DIR} for Hebrew subtitles...")

    for root, dirs, files in os.walk(ROOT_DIR):
        for file in files:
            if file.endswith("_heb.vtt"):
                # Source: video_name_heb.vtt
                source_path = os.path.join(root, file)

                # Target: video_name.vtt
                # We assume the format ends in _heb.vtt, so we strip that suffix
                base_name = file.replace("_heb.vtt", "")
                target_filename = f"{base_name}.vtt"
                target_path = os.path.join(root, target_filename)

                # Verify that a corresponding video file actually exists
                # (Common extensions: .mp4, .mkv, .webm)
                video_exists = False
                for ext in [".mp4", ".mkv", ".webm"]:
                    video_path = os.path.join(root, f"{base_name}{ext}")
                    if os.path.exists(video_path):
                        video_exists = True
                        break

                if not video_exists:
                    # It might be that the video name is slightly different or the _heb logic is off
                    # Let's try to verify against the _en.vtt if video not found
                    if not os.path.exists(os.path.join(root, f"{base_name}_en.vtt")):
                        # Only skip if we can't find a video OR the original English sub
                        # (which confirms the naming convention)
                        continue

                if not os.path.exists(target_path):
                    try:
                        shutil.copy2(source_path, target_path)
                        print(f"Applied: {target_filename}")
                        count += 1
                    except Exception as e:
                        print(f"Error copying {file}: {e}")
                else:
                    # print(f"Skipping: {target_filename} (Already exists)")
                    pass

    print(f"\nSuccess! Applied subtitles to {count} videos.")
    print("These videos will now play with Hebrew subtitles automatically.")


if __name__ == "__main__":
    apply_subtitles()
