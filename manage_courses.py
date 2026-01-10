import sys
import subprocess
import os

def run_script(script_name, args=None):
    """Runs a python script using subprocess."""
    cmd = [sys.executable, script_name]
    if args:
        cmd.extend(args)
    
    print(f"\n[Running {script_name}...]")
    try:
        subprocess.check_call(cmd)
        print(f"[Finished {script_name}]")
    except subprocess.CalledProcessError as e:
        print(f"[Error running {script_name}: {e}]")
    except KeyboardInterrupt:
        print(f"\n[Interrupted {script_name}]")

def main_menu():
    while True:
        print("\n" + "="*40)
        print("   🎓 COURSERA OFFLINE MANAGER")
        print("="*40)
        print("1. 📥 Download Courses (main.py)")
        print("2. 🤖 Translate Subtitles (Ollama required)")
        print("3. 📝 Summarize Readings (Ollama required)")
        print("4. 🎥 Apply Subtitles for VLC (Rename .vtt)")
        print("6. 🎵 Generate Video Playlists (.wpl)")
        print("7. 🧭 Update Course Navigation (Sidebar)")
        print("8. 🛠️  Fix Links (Legacy)")
        print("0. ❌ Exit")
        print("="*40)
        
        choice = input("Select an option (0-8): ").strip()
        
        if choice == '1':
            # ...
            pass
        elif choice == '2':
            # ...
            pass
        # (Replacing the logic block for cleaner insertion)
        
        if choice == '1':
            print("\n-- Download Courses --")
            email = input("Enter email (press Enter for default): ").strip()
            args = []
            if email:
                args.extend(["--email", email])
            run_script("main.py", args=args)

        elif choice == '2':
            print("\n-- Translate Subtitles --")
            print("Ensure Ollama is running with 'gemma3-translator:4b'.")
            run_script("translate_captions.py")

        elif choice == '3':
            print("\n-- Summarize Readings --")
            print("Ensure Ollama is running with 'llama3.1'.")
            run_script("summarize_readings.py")

        elif choice == '4':
            print("\n-- Apply Subtitles for VLC --")
            run_script("apply_subtitles.py")

        elif choice == '6':
            print("\n-- Generating Playlists --")
            run_script("create_playlists.py")

        elif choice == '7':
            print("\n-- Updating Course Navigation --")
            run_script("create_course_navigator.py")
            
        elif choice == '8':
            print("\n-- Fix Links --")
            run_script("fix_links.py")
            
        elif choice == '0':
            print("Goodbye!")
            break
        else:
            print("Invalid option. Please try again.")

if __name__ == "__main__":
    main_menu()
