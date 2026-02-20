import os
import json
import argparse
import re

# ==========================================
#               CONFIGURATION
# ==========================================
CONFIG = {
    "root_directory": "UnpackedBDAT",
    "target_key": "name",
    "log_file": "text_balancing_log.txt",

    "profiles": {
        "event": {
            "name": "Event (Cinematic)",
            "max_lines": 2,
            "split_threshold_for_2": 45,
            "split_threshold_for_3": 999999
        },
        "npc": {
            "name": "NPC/Quest/Dialogue",
            "max_lines": 3,
            "split_threshold_for_2": 40,
            "split_threshold_for_3": 80
        }
    }
}

# ==========================================
#            CORE LOGIC
# ==========================================

def get_profile_for_filename(filename):
    """
    Hard-checks the filename. If it doesn't start with xs, qev, or tev,
    it returns None, and the scanner will completely skip the file.
    """
    name_lower = filename.lower()
    if name_lower.startswith("xs"):
        return CONFIG["profiles"]["event"]
    elif name_lower.startswith("qev") or name_lower.startswith("tev"):
        return CONFIG["profiles"]["npc"]

    return None

def clean_and_flatten(text):
    if not text: return ""
    flat = text.replace('\\n', ' ').replace('\n', ' ')
    flat = flat.replace('\r', '')
    return " ".join(flat.split())

def get_visual_length(text):
    clean_text = re.sub(r'\[.*?\]', '', text)
    clean_text = clean_text.replace('\u200B', '')
    return len(clean_text)

def tokenize_keeping_tags_intact(text):
    def protect_match(match):
        return match.group(0).replace(' ', '<<SPACE>>')
    protected_text = re.sub(r'\[.*?\]', protect_match, text)
    raw_words = protected_text.split(' ')
    return [w.replace('<<SPACE>>', ' ') for w in raw_words if w]

def force_split(words, num_lines):
    if num_lines <= 1:
        return [" ".join(words)]

    total_visual_len = sum(get_visual_length(w) for w in words) + (len(words) - 1)
    target_visual_len = total_visual_len / num_lines

    lines = []
    current_words = words[:]

    for _ in range(num_lines - 1):
        best_split = 0
        best_diff = float('inf')
        current_visual_len = 0

        for i, w in enumerate(current_words):
            w_vis_len = get_visual_length(w)
            len_with = current_visual_len + w_vis_len + (1 if current_visual_len > 0 else 0)
            diff = abs(len_with - target_visual_len)

            if diff <= best_diff:
                best_diff = diff
                best_split = i + 1
                current_visual_len = len_with
            else:
                break

        if best_split == 0 and current_words:
            best_split = 1

        lines.append(" ".join(current_words[:best_split]))
        current_words = current_words[best_split:]
        if not current_words: break

    if current_words:
        lines.append(" ".join(current_words))
    return lines

def process_text(text_content, profile):
    if not isinstance(text_content, str) or not text_content.strip():
        return text_content

    clean_text = clean_and_flatten(text_content)
    words = tokenize_keeping_tags_intact(clean_text)

    total_len = sum(get_visual_length(w) for w in words) + (len(words) - 1)

    if total_len <= profile["split_threshold_for_2"]:
        target_lines = 1
    elif total_len <= profile["split_threshold_for_3"] and profile["max_lines"] >= 2:
        target_lines = 2
    else:
        target_lines = 3 if profile["max_lines"] >= 3 else 2

    final_lines = force_split(words, target_lines)
    return "\n".join(final_lines)

# ==========================================
#           FILE PROCESSING
# ==========================================

def process_single_file(file_path, log, stats, profile):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        modified = False

        if "rows" in data:
            for row in data["rows"]:
                target_key = CONFIG["target_key"]

                if target_key not in row and "<DBAF43F0>" in row:
                     target_key = "<DBAF43F0>"

                if target_key in row:
                    original_text = row[target_key]
                    if not original_text or original_text == "":
                        continue

                    new_text = process_text(original_text, profile)

                    # Only log and update if the text was ACTUALLY changed
                    if original_text != new_text:
                        row[target_key] = new_text
                        log_change(log, file_path, row.get("$id", "?"), original_text, new_text)
                        modified = True
                        stats['changes'] += 1

        if modified:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            stats['files_processed'] += 1

    except Exception as e:
        print(f"Error processing {file_path}: {e}")

def log_change(logfile, filename, row_id, old_text, new_text):
    logfile.write(f"FILE: {filename} | ID: {row_id}\n")
    logfile.write("-" * 60 + "\n")
    vis_len = get_visual_length(clean_and_flatten(old_text))
    logfile.write(f"OLD (Vis Len: {vis_len}):\n{old_text}\n")
    logfile.write(f"\nNEW ({new_text.count(chr(10)) + 1} lines):\n{new_text}\n")
    logfile.write("-" * 60 + "\n\n")

# ==========================================
#               MAIN ENTRY
# ==========================================

def main():
    parser = argparse.ArgumentParser(
        description="Xenoblade X Text Auto-Balancer Tool",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-single", metavar="FILE_PATH", help="Process only this specific JSON file.")
    args, unknown = parser.parse_known_args()

    stats = {'files_processed': 0, 'changes': 0, 'skipped_files': 0}

    print("\nStarting Xenoblade X Text Balancer...\n")

    with open(CONFIG["log_file"], "w", encoding="utf-8") as log:

        if args.single:
            print(f"Targeting Single File: {args.single}")
            if os.path.exists(args.single):
                profile = get_profile_for_filename(os.path.basename(args.single))
                if profile:
                    process_single_file(args.single, log, stats, profile)
                else:
                    print("Skipped: File does not start with xs, qev, or tev.")
            else:
                print(f"ERROR: File not found -> {args.single}")
        else:
            if not os.path.exists(CONFIG["root_directory"]):
                print(f"ERROR: Could not find the directory '{CONFIG['root_directory']}'.")
            else:
                print(f"Scanning Directory: {CONFIG['root_directory']}")

                # Recursive walk through all folders
                for root, dirs, files in os.walk(CONFIG["root_directory"]):
                    for file in files:
                        if file.lower().endswith(".json"):

                            # Hard-block: ONLY process if it starts with the correct prefix
                            profile = get_profile_for_filename(file)

                            if profile is not None:
                                process_single_file(os.path.join(root, file), log, stats, profile)
                            else:
                                stats['skipped_files'] += 1

                print(f"\nIgnored {stats['skipped_files']} non-dialogue files (UI, Arts, etc).")

    print("\n" + "="*40)
    print(f"Processing Complete.")
    print(f"Files Modified:    {stats['files_processed']}")
    print(f"Text Rows Updated: {stats['changes']}")
    print(f"Logs saved to:     {CONFIG['log_file']}")
    print("="*40 + "\n")

    input("Press Enter to close this window...")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nA critical error occurred: {e}")
        input("Press Enter to close this window...")
