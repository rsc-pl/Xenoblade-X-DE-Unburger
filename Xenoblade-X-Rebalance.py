import os
import json
import argparse
import re
from collections import Counter

# ==========================================
#               CONFIGURATION
# ==========================================
CONFIG = {
    "root_directory": "UnpackedBDAT",
    "target_key": "name",
    "log_file": "text_balancing_log.txt",

    # Do NOT scan every JSON purely by style. style 0 also appears in menus/UI.
    # These are the dialogue/event families observed in the supplied UnpackedBDAT.
    "dialogue_file_prefixes": ("xs", "qev", "tev"),

    # Extra non-qev/tev/xs dialogue-like files observed with style 1 balloon text.
    "dialogue_file_exact_names": (
        "fld_meslock.json",
    ),

    "profiles": {
        "event": {
            "name": "Event/Cinematic subtitle",
            "max_lines": 2,
            "split_threshold_for_2": 45,
            "split_threshold_for_3": 999999
        },
        "npc": {
            "name": "NPC/Quest/Balloon dialogue",
            "max_lines": 3,
            "split_threshold_for_2": 40,
            "split_threshold_for_3": 80
        },
        "choice": {
            "name": "Choice/Selection text",
            "max_lines": 1,
            "split_threshold_for_2": 999999,
            "split_threshold_for_3": 999999
        }
    }
}

# ==========================================
#            PROFILE SELECTION
# ==========================================

def is_dialogue_file(filename):
    name_lower = filename.lower()
    return (
        name_lower.startswith(CONFIG["dialogue_file_prefixes"])
        or name_lower in CONFIG["dialogue_file_exact_names"]
    )


def get_profile_for_filename(filename):
    """
    File-level hard gate only. This prevents UI/menu/system JSONs from being
    touched just because they also contain a numeric "style" field.
    """
    if is_dialogue_file(filename):
        return True
    return None


def get_profile_for_row(filename, row):
    """
    Row-level selector. In the supplied XCX UnpackedBDAT:
      style 0 = event/cinematic subtitle window -> max 2 lines
      style 1 = NPC/quest/field balloon dialogue -> max 3 lines
      style 3 = selection description / player action text -> 1 line
      style 4 = short choice label -> 1 line

    Unknown styles are skipped. This is intentionally safer than defaulting
    unknown rows to any profile.
    """
    if not is_dialogue_file(filename):
        return None

    style = row.get("style")

    if style == 0:
        return CONFIG["profiles"]["event"]
    if style == 1:
        return CONFIG["profiles"]["npc"]
    if style in (3, 4):
        return CONFIG["profiles"]["choice"]

    return None

# ==========================================
#            CORE LOGIC
# ==========================================

def clean_and_flatten(text):
    if not text:
        return ""
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

    total_visual_len = sum(get_visual_length(w) for w in words) + max(0, len(words) - 1)
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
        if not current_words:
            break

    if current_words:
        lines.append(" ".join(current_words))
    return lines


def process_text(text_content, profile):
    if not isinstance(text_content, str) or not text_content.strip():
        return text_content

    clean_text = clean_and_flatten(text_content)
    words = tokenize_keeping_tags_intact(clean_text)

    max_lines = int(profile.get("max_lines", 1))
    if max_lines <= 1:
        return " ".join(words)

    total_len = sum(get_visual_length(w) for w in words) + max(0, len(words) - 1)

    if total_len <= profile["split_threshold_for_2"]:
        target_lines = 1
    elif max_lines >= 3 and total_len > profile["split_threshold_for_3"]:
        target_lines = 3
    else:
        target_lines = 2

    target_lines = min(target_lines, max_lines)
    final_lines = force_split(words, target_lines)
    return "\n".join(final_lines)

# ==========================================
#           FILE PROCESSING
# ==========================================

def get_text_key(row):
    target_key = CONFIG["target_key"]
    if target_key in row:
        return target_key
    if "<DBAF43F0>" in row:
        return "<DBAF43F0>"
    return None


def process_single_file(file_path, log, stats):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        modified = False
        filename = os.path.basename(file_path)

        if "rows" in data:
            for row in data["rows"]:
                if not isinstance(row, dict):
                    continue

                row_profile = get_profile_for_row(filename, row)
                if row_profile is None:
                    stats['rows_skipped_unknown_style'] += 1 if is_dialogue_file(filename) and 'style' in row else 0
                    continue

                target_key = get_text_key(row)
                if target_key is None:
                    continue

                original_text = row[target_key]
                if not original_text:
                    continue

                new_text = process_text(original_text, row_profile)

                if original_text != new_text:
                    row[target_key] = new_text
                    log_change(log, file_path, row.get("$id", "?"), row.get("style"), row_profile["name"], original_text, new_text)
                    modified = True
                    stats['changes'] += 1
                    stats['changes_by_style'][row.get('style')] += 1

        if modified:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            stats['files_processed'] += 1

    except Exception as e:
        print(f"Error processing {file_path}: {e}")


def log_change(logfile, filename, row_id, style, profile_name, old_text, new_text):
    logfile.write(f"FILE: {filename} | ID: {row_id} | STYLE: {style} | PROFILE: {profile_name}\n")
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
        description="Xenoblade X Text Auto-Balancer Tool - row style aware",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-single", metavar="FILE_PATH", help="Process only this specific JSON file.")
    parser.add_argument("--no-pause", action="store_true", help="Do not wait for Enter before closing.")
    args, unknown = parser.parse_known_args()

    stats = {
        'files_processed': 0,
        'changes': 0,
        'skipped_files': 0,
        'rows_skipped_unknown_style': 0,
        'changes_by_style': Counter(),
    }

    print("\nStarting Xenoblade X Text Balancer - row style aware...\n")

    with open(CONFIG["log_file"], "w", encoding="utf-8") as log:

        if args.single:
            print(f"Targeting Single File: {args.single}")
            if os.path.exists(args.single):
                if get_profile_for_filename(os.path.basename(args.single)):
                    process_single_file(args.single, log, stats)
                else:
                    print("Skipped: file is not on the dialogue whitelist.")
            else:
                print(f"ERROR: File not found -> {args.single}")
        else:
            if not os.path.exists(CONFIG["root_directory"]):
                print(f"ERROR: Could not find the directory '{CONFIG['root_directory']}'.")
            else:
                print(f"Scanning Directory: {CONFIG['root_directory']}")

                for root, dirs, files in os.walk(CONFIG["root_directory"]):
                    for file in files:
                        if file.lower().endswith(".json"):
                            if get_profile_for_filename(file):
                                process_single_file(os.path.join(root, file), log, stats)
                            else:
                                stats['skipped_files'] += 1

                print(f"\nIgnored {stats['skipped_files']} non-dialogue files (UI, Arts, menus, etc.).")

    print("\n" + "=" * 40)
    print("Processing Complete.")
    print(f"Files Modified:    {stats['files_processed']}")
    print(f"Text Rows Updated: {stats['changes']}")
    print(f"Changes by style:  {dict(stats['changes_by_style'])}")
    print(f"Logs saved to:     {CONFIG['log_file']}")
    print("=" * 40 + "\n")

    if not args.no_pause:
        input("Press Enter to close this window...")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nA critical error occurred: {e}")
        try:
            input("Press Enter to close this window...")
        except EOFError:
            pass
