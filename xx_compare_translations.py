import argparse
import json
import os
import sys
import unicodedata
from collections import Counter
from pathlib import Path


# ==========================================
#              TYPE FILTERS
# ==========================================
# These filters are intentionally filename-based, because the comparison script
# should be able to decide which files to load before parsing every row.
#
# XCX/Xeno-style conventions used here:
#   story  -> xs*.json
#   quest  -> qev*.json, tev*.json, qst*.json
#   field  -> known field/dialogue exceptions such as FLD_MesLock.json
#
# No flags = compare everything, matching the original script behavior.
FILE_TYPE_PREFIXES = {
    "story": ("xs",),
    "quest": ("qev", "tev", "qst"),
}

FILE_TYPE_EXACT_NAMES = {
    "field": ("fld_meslock.json",),
}

REQUIRED_CONFIG_KEYS = ("original_dir", "fan_dir", "localized_dir")
DEFAULT_OUTPUT_FILE = "translation_differences.json"


# ==========================================
#              CONFIG HELPERS
# ==========================================

def default_config_path():
    """Config lives next to this script and uses the same base name: script.py -> script.json."""
    script_path = Path(__file__).resolve()
    return script_path.with_suffix(".json")


def normalize_config_path(path_value):
    return str(Path(path_value).expanduser()) if path_value else ""


def validate_config(config):
    """
    Validate only format and required keys. Missing/non-string values are bad format.
    Directory existence is checked separately so the user gets a clearer prompt.
    """
    if not isinstance(config, dict):
        return False, "config root must be a JSON object"

    for key in REQUIRED_CONFIG_KEYS:
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            return False, f"missing or invalid string value for '{key}'"

    output_value = config.get("output_file", DEFAULT_OUTPUT_FILE)
    if not isinstance(output_value, str) or not output_value.strip():
        return False, "'output_file' must be a non-empty string when present"

    return True, "ok"


def load_config(config_path):
    if not config_path.exists():
        return None, "missing"

    try:
        with config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        return None, f"bad JSON formatting: {e}"
    except OSError as e:
        return None, f"cannot read config: {e}"

    ok, reason = validate_config(config)
    if not ok:
        return None, reason

    return config, "ok"


def save_config(config_path, config):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")

    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
        f.write("\n")

    tmp_path.replace(config_path)


def prompt_path(label, default=None):
    if default:
        prompt = f"{label} [{default}]: "
    else:
        prompt = f"{label}: "

    value = input(prompt).strip()
    return value or (default or "")


def prompt_for_config(config_path, existing_config=None):
    print(f"\nConfig file will be saved as: {config_path}")
    print("Enter paths once; next runs will reuse this config.\n")

    existing_config = existing_config or {}

    config = {
        "original_dir": normalize_config_path(prompt_path(
            "Enter the path to the original Japanese text directory",
            existing_config.get("original_dir"),
        )),
        "fan_dir": normalize_config_path(prompt_path(
            "Enter the path to the fan translation directory",
            existing_config.get("fan_dir"),
        )),
        "localized_dir": normalize_config_path(prompt_path(
            "Enter the path to the localized version directory",
            existing_config.get("localized_dir"),
        )),
        "output_file": normalize_config_path(prompt_path(
            "Enter output JSON file",
            existing_config.get("output_file", DEFAULT_OUTPUT_FILE),
        )),
    }

    ok, reason = validate_config(config)
    if not ok:
        print(f"Invalid config input: {reason}")
        sys.exit(1)

    save_config(config_path, config)
    print(f"Saved config: {config_path}\n")
    return config


def build_runtime_paths(args):
    config_path = Path(args.config).expanduser() if args.config else default_config_path()

    if args.reset_config and config_path.exists():
        config_path.unlink()
        print(f"Deleted config: {config_path}")

    loaded_config, config_status = load_config(config_path)

    # CLI paths override config when provided. This also allows one-off runs.
    cli_has_all_required_paths = bool(args.original_dir and args.fan_dir and args.localized_dir)

    if cli_has_all_required_paths:
        config = loaded_config or {}
        config.update({
            "original_dir": normalize_config_path(args.original_dir),
            "fan_dir": normalize_config_path(args.fan_dir),
            "localized_dir": normalize_config_path(args.localized_dir),
            "output_file": normalize_config_path(args.output or config.get("output_file", DEFAULT_OUTPUT_FILE)),
        })

        if not args.no_save_config:
            save_config(config_path, config)
            print(f"Saved config: {config_path}")

        return config["original_dir"], config["fan_dir"], config["localized_dir"], config["output_file"]

    if loaded_config is None:
        if config_status == "missing":
            print(f"Config not found: {config_path}")
            return_paths = prompt_for_config(config_path)
        else:
            print(f"Config invalid: {config_path}")
            print(f"Reason: {config_status}")
            # Try to preserve any readable partial JSON is intentionally skipped here;
            # malformed JSON cannot be safely reused.
            return_paths = prompt_for_config(config_path)
    else:
        return_paths = loaded_config

    # Partial CLI overrides are allowed, but missing values come from config.
    original_dir = normalize_config_path(args.original_dir or return_paths["original_dir"])
    fan_dir = normalize_config_path(args.fan_dir or return_paths["fan_dir"])
    localized_dir = normalize_config_path(args.localized_dir or return_paths["localized_dir"])
    output_file = normalize_config_path(args.output or return_paths.get("output_file", DEFAULT_OUTPUT_FILE))

    # If the user passed only some paths, refresh the config so next run is consistent.
    if (args.original_dir or args.fan_dir or args.localized_dir or args.output) and not args.no_save_config:
        updated_config = {
            "original_dir": original_dir,
            "fan_dir": fan_dir,
            "localized_dir": localized_dir,
            "output_file": output_file,
        }
        save_config(config_path, updated_config)
        print(f"Updated config: {config_path}")

    return original_dir, fan_dir, localized_dir, output_file


# ==========================================
#              HELPERS
# ==========================================

def normalize_text(value):
    if not isinstance(value, str):
        return ""
    if not value:
        return ""
    return unicodedata.normalize("NFKC", value).encode("utf-8").decode("utf-8")


def classify_file(filename):
    """Return a set of logical types matching this filename."""
    name_lower = filename.lower()
    matched = set()

    for type_name, prefixes in FILE_TYPE_PREFIXES.items():
        if name_lower.startswith(prefixes):
            matched.add(type_name)

    for type_name, exact_names in FILE_TYPE_EXACT_NAMES.items():
        if name_lower in exact_names:
            matched.add(type_name)

    if not matched:
        matched.add("other")

    return matched


def should_include_file(filename, selected_types):
    """
    selected_types:
      None -> include everything
      set  -> include if file matches at least one selected type
    """
    if selected_types is None:
        return True
    return bool(classify_file(filename) & selected_types)


def sort_label_key(value):
    """Sort numeric IDs numerically, labels lexically."""
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


# ==========================================
#              CORE LOGIC
# ==========================================

def load_json_files(directory, selected_types=None, stats=None):
    """
    Recursively search for JSON files in a directory and extract the 'name'
    field from each row. Returns:
        {lowercase_filename: {label_or_id: name}}
    """
    json_data = {}

    for root, _, files in os.walk(directory):
        for file in files:
            if not file.lower().endswith(".json"):
                continue

            file_lower = file.lower()
            file_types = classify_file(file_lower)

            if stats is not None:
                for file_type in file_types:
                    stats["seen_by_type"][file_type] += 1

            if not should_include_file(file_lower, selected_types):
                if stats is not None:
                    stats["skipped_files"] += 1
                continue

            file_path = os.path.join(root, file)

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                names = {}
                for item in data.get("rows", []):
                    if not isinstance(item, dict):
                        continue

                    label = item.get("label")
                    if isinstance(label, str) and label.strip():
                        key = label
                    else:
                        id_val = item.get("$id")
                        if id_val is None:
                            continue
                        key = str(id_val)

                    names[key] = item.get("name", "")

                json_data[file_lower] = names

                if stats is not None:
                    stats["loaded_files"] += 1
                    for file_type in file_types:
                        stats["loaded_by_type"][file_type] += 1

            except Exception as e:
                print(f"Error loading {file_path}: {e}")
                if stats is not None:
                    stats["errors"] += 1

    return json_data


def compare_json_files(original_dir, fan_dir, localized_dir, output_file, selected_types=None):
    """
    Compare JSON files from three directories and output differences.

    Args:
        original_dir: directory with original Japanese text JSON files.
        fan_dir: directory with fan translation JSON files.
        localized_dir: directory with localized-version JSON files.
        output_file: output JSON path.
        selected_types: None for all files, or a set such as {'quest', 'story'}.
    """
    results = []
    stats = {
        "seen_by_type": Counter(),
        "loaded_by_type": Counter(),
        "loaded_files": 0,
        "skipped_files": 0,
        "errors": 0,
        "missing_original": 0,
        "missing_localized": 0,
    }

    print("Loading original files...")
    original_data = load_json_files(original_dir, selected_types, stats)
    print("Loading fan translation files...")
    fan_data = load_json_files(fan_dir, selected_types, stats)
    print("Loading localized files...")
    localized_data = load_json_files(localized_dir, selected_types, stats)

    result_counter = 1

    for fan_file_name, fan_names in sorted(fan_data.items()):
        original_names = original_data.get(fan_file_name, {})
        localized_names = localized_data.get(fan_file_name, {})

        if not original_names or not localized_names:
            print(f"Missing corresponding files for {fan_file_name} in original or localized directories.")
            if not original_names:
                print(f"  Missing in original: {os.path.join(original_dir, fan_file_name)}")
                stats["missing_original"] += 1
            if not localized_names:
                print(f"  Missing in localized: {os.path.join(localized_dir, fan_file_name)}")
                stats["missing_localized"] += 1
            continue

        all_labels = sorted(set(fan_names.keys()).union(localized_names.keys()), key=sort_label_key)

        for label_key in all_labels:
            fan_name = normalize_text(fan_names.get(label_key, ""))
            localized_name = normalize_text(localized_names.get(label_key, ""))

            if not fan_name or not localized_name or fan_name != localized_name:
                results.append({
                    "number": result_counter,
                    "file_name": fan_file_name,
                    "file_type": sorted(classify_file(fan_file_name)),
                    "ID": label_key,
                    "Original Japanese line": original_names.get(label_key, ""),
                    "fan translation": fan_name,
                    "localized version": localized_name,
                })
                result_counter += 1

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)

    return results, stats


# ==========================================
#              CLI
# ==========================================

def build_selected_types(args):
    selected = set()

    if args.story:
        selected.add("story")
    if args.quest:
        selected.add("quest")
    if args.field:
        selected.add("field")
    if args.other:
        selected.add("other")

    if args.all or not selected:
        return None

    return selected


def main():
    parser = argparse.ArgumentParser(
        description="Compare Xenoblade translation JSON files with optional type filters.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument("original_dir", nargs="?", help="Directory with original Japanese JSON files. Overrides config.")
    parser.add_argument("fan_dir", nargs="?", help="Directory with fan translation JSON files. Overrides config.")
    parser.add_argument("localized_dir", nargs="?", help="Directory with localized-version JSON files. Overrides config.")
    parser.add_argument("-o", "--output", default=None, help="Output JSON file. Overrides config. Default in config: translation_differences.json")

    parser.add_argument("-story", action="store_true", help="Compare story/cinematic files only: xs*.json")
    parser.add_argument("-quest", action="store_true", help="Compare quest/event files only: qev*.json, tev*.json, qst*.json")
    parser.add_argument("-field", action="store_true", help="Compare known field-dialogue files only: FLD_MesLock.json")
    parser.add_argument("-other", action="store_true", help="Compare files not classified as story/quest/field.")
    parser.add_argument("-all", action="store_true", help="Compare all JSON files. This is also the default when no type flag is passed.")

    parser.add_argument("--config", default=None, help="Custom config path. Default: same name as script, .json extension.")
    parser.add_argument("--reset-config", action="store_true", help="Delete config first and ask for paths again.")
    parser.add_argument("--no-save-config", action="store_true", help="Do not write/update config when paths are entered via CLI or prompt.")

    args = parser.parse_args()
    selected_types = build_selected_types(args)

    original_dir, fan_dir, localized_dir, output_file = build_runtime_paths(args)

    results, stats = compare_json_files(
        original_dir=original_dir,
        fan_dir=fan_dir,
        localized_dir=localized_dir,
        output_file=output_file,
        selected_types=selected_types,
    )

    active_filter = "all" if selected_types is None else ", ".join(sorted(selected_types))
    print("\n" + "=" * 60)
    print(f"Comparison completed. Results saved to: {output_file}")
    print(f"Active filter: {active_filter}")
    print(f"Differences written: {len(results)}")
    print(f"Files loaded total: {stats['loaded_files']}")
    print(f"Files skipped by filter: {stats['skipped_files']}")
    print(f"Loaded by type: {dict(stats['loaded_by_type'])}")
    print(f"Missing original files: {stats['missing_original']}")
    print(f"Missing localized files: {stats['missing_localized']}")
    print(f"Load errors: {stats['errors']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
