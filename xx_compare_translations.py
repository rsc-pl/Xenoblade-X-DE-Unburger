#!/usr/bin/env python3
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
# No type flags = compare everything.
FILE_TYPE_PREFIXES = {
    "story": ("xs",),
    "quest": ("qev", "tev", "qst"),
}
FILE_TYPE_EXACT_NAMES = {
    "field": ("fld_meslock.json",),
}
TYPE_FLAG_ORDER = ("story", "quest", "field", "other")
TYPE_FLAG_BY_CLI_NAME = {
    "-story": "story",
    "--story": "story",
    "-quest": "quest",
    "--quest": "quest",
    "-field": "field",
    "--field": "field",
    "-other": "other",
    "--other": "other",
}

REQUIRED_CONFIG_KEYS = ("original_dir", "fan_dir", "localized_dir")
DEFAULT_OUTPUT_FILE = "translation_differences.json"
SCRIPT_VERSION = "2026-06-28-flag-order-output-v6"

# ==========================================
#              CONFIG HELPERS
# ==========================================

def default_config_path():
    """Config lives next to this script: script.py -> script.json."""
    return Path(__file__).resolve().with_suffix(".json")


def normalize_config_path(path_value):
    return str(Path(path_value).expanduser()) if path_value else ""


def validate_config(config):
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
    prompt = f"{label} [{default}]: " if default else f"{label}: "
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
        return config["original_dir"], config["fan_dir"], config["localized_dir"], config["output_file"], config_path

    if loaded_config is None:
        if config_status == "missing":
            print(f"Config not found: {config_path}")
        else:
            print(f"Config invalid: {config_path}")
            print(f"Reason: {config_status}")
        runtime_config = prompt_for_config(config_path)
    else:
        runtime_config = loaded_config

    original_dir = normalize_config_path(args.original_dir or runtime_config["original_dir"])
    fan_dir = normalize_config_path(args.fan_dir or runtime_config["fan_dir"])
    localized_dir = normalize_config_path(args.localized_dir or runtime_config["localized_dir"])
    output_file = normalize_config_path(args.output or runtime_config.get("output_file", DEFAULT_OUTPUT_FILE))

    if (args.original_dir or args.fan_dir or args.localized_dir or args.output) and not args.no_save_config:
        updated_config = {
            "original_dir": original_dir,
            "fan_dir": fan_dir,
            "localized_dir": localized_dir,
            "output_file": output_file,
        }
        save_config(config_path, updated_config)
        print(f"Updated config: {config_path}")

    return original_dir, fan_dir, localized_dir, output_file, config_path

# ==========================================
#              TEXT / FILTER HELPERS
# ==========================================

def normalize_text(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    if not value:
        return ""
    return unicodedata.normalize("NFKC", value)


def strip_invisible_and_whitespace(value):
    """Remove whitespace plus control/format/separator chars for blank checks."""
    value = normalize_text(value)
    return "".join(
        ch for ch in value
        if not ch.isspace() and unicodedata.category(ch) not in {"Cc", "Cf", "Zs", "Zl", "Zp"}
    )


def is_empty_text(value):
    return strip_invisible_and_whitespace(value) == ""


def empty_count_from_values(original_name, fan_name, localized_name):
    return sum(1 for value in (original_name, fan_name, localized_name) if is_empty_text(value))


def should_skip_mostly_empty_values(original_name, fan_name, localized_name):
    # User wanted rows skipped when 2+ of the compared fields are empty.
    return empty_count_from_values(original_name, fan_name, localized_name) >= 2


def should_skip_mostly_empty_record(record):
    return should_skip_mostly_empty_values(
        record.get("Original Japanese line", ""),
        record.get("fan translation", ""),
        record.get("localized version", ""),
    )


def renumber_results(records):
    for idx, record in enumerate(records, start=1):
        record["number"] = idx
    return records


def sanitize_mostly_empty_records(records):
    """Return (cleaned_records, removed_records) using the global 2+ empty-fields rule."""
    cleaned = []
    removed = []
    for record in records:
        if should_skip_mostly_empty_record(record):
            removed.append(record)
        else:
            cleaned.append(record)
    return cleaned, removed

# ==========================================
#              FILE HELPERS
# ==========================================

def classify_file(filename):
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
    # selected_types None = ALL MODE. This still keeps the empty-row filter active.
    if selected_types is None:
        return True
    return bool(classify_file(filename) & selected_types)


def sort_label_key(value):
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def resolve_output_path(output_file):
    # Keep old behavior for relative paths: relative to current working directory.
    return str(Path(output_file).expanduser().resolve())

# ==========================================
#              CORE LOGIC
# ==========================================

def file_output_sort_key(filename, selected_types=None, selected_type_order=None):
    """Sort files by the user's type-flag order, then by filename.

    Examples:
      -quest -story  => quest files first, then story files
      -story -quest  => story files first, then quest files
    No type flags / -all keeps a stable default order.
    """
    name_lower = filename.lower()
    file_types = classify_file(name_lower)

    if selected_types is None:
        # All mode: stable, predictable grouping instead of raw os.walk order.
        order = TYPE_FLAG_ORDER
        selected = set(order)
    else:
        order = selected_type_order or tuple(TYPE_FLAG_ORDER)
        selected = selected_types

    rank_by_type = {type_name: idx for idx, type_name in enumerate(order)}
    matching_ranks = [rank_by_type[t] for t in file_types if t in selected and t in rank_by_type]
    rank = min(matching_ranks) if matching_ranks else len(rank_by_type)

    # Secondary type list makes ties deterministic for files that match more than one type.
    type_key = ",".join(sorted(file_types))
    return (rank, type_key, name_lower)


def load_json_files(directory, selected_types=None, stats=None):
    """Return {lowercase_filename: {label_or_id: name}}."""
    json_data = {}
    directory = str(Path(directory).expanduser())

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


def compare_json_files(original_dir, fan_dir, localized_dir, output_file, selected_types=None, selected_type_order=None, skip_mostly_empty=True):
    results = []
    stats = {
        "seen_by_type": Counter(),
        "loaded_by_type": Counter(),
        "loaded_files": 0,
        "skipped_files": 0,
        "errors": 0,
        "missing_original": 0,
        "missing_localized": 0,
        "skipped_mostly_empty": 0,
        "final_safety_skipped": 0,
        "postwrite_safety_skipped": 0,
        "skipped_examples": [],
    }

    print("Loading original files...")
    original_data = load_json_files(original_dir, selected_types, stats)
    print("Loading fan translation files...")
    fan_data = load_json_files(fan_dir, selected_types, stats)
    print("Loading localized files...")
    localized_data = load_json_files(localized_dir, selected_types, stats)

    for fan_file_name, fan_names in sorted(
        fan_data.items(),
        key=lambda item: file_output_sort_key(item[0], selected_types, selected_type_order),
    ):
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
            original_name = normalize_text(original_names.get(label_key, ""))
            fan_name = normalize_text(fan_names.get(label_key, ""))
            localized_name = normalize_text(localized_names.get(label_key, ""))

            # Build the exact output candidate FIRST, then run the global skip on it.
            # This avoids separate behavior between -quest/-story and no-flag/all mode.
            candidate = {
                "number": 0,
                "file_name": fan_file_name,
                "file_type": sorted(classify_file(fan_file_name)),
                "ID": label_key,
                "Original Japanese line": original_name,
                "fan translation": fan_name,
                "localized version": localized_name,
            }

            if skip_mostly_empty and should_skip_mostly_empty_record(candidate):
                stats["skipped_mostly_empty"] += 1
                if len(stats["skipped_examples"]) < 10:
                    stats["skipped_examples"].append({
                        "file_name": fan_file_name,
                        "ID": label_key,
                        "empty_fields": empty_count_from_values(original_name, fan_name, localized_name),
                        "file_type": sorted(classify_file(fan_file_name)),
                    })
                continue

            if not fan_name or not localized_name or fan_name != localized_name:
                results.append(candidate)

    # Final hard cleanup for ALL MODE and all file categories, including "other".
    if skip_mostly_empty:
        results, removed = sanitize_mostly_empty_records(results)
        stats["final_safety_skipped"] += len(removed)

    renumber_results(results)

    output_path = Path(resolve_output_path(output_file))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)
        f.write("\n")

    # Post-write verification: reopen exactly the file that was written and purge again.
    # This makes the empty-row filter impossible to bypass in default/all mode.
    if skip_mostly_empty:
        try:
            with output_path.open("r", encoding="utf-8") as f:
                written_results = json.load(f)
            if isinstance(written_results, list):
                cleaned_written, postwrite_removed = sanitize_mostly_empty_records(written_results)
                if postwrite_removed:
                    stats["postwrite_safety_skipped"] += len(postwrite_removed)
                    renumber_results(cleaned_written)
                    with output_path.open("w", encoding="utf-8") as f:
                        json.dump(cleaned_written, f, indent=4, ensure_ascii=False)
                        f.write("\n")
                    results = cleaned_written
        except Exception as e:
            print(f"WARNING: post-write empty-row verification failed: {e}")

    return results, stats, str(output_path)

# ==========================================
#              CLI
# ==========================================

def build_selected_types(args):
    selected_order = []
    for arg in sys.argv[1:]:
        # Accept compact forms only for these boolean type flags. Value-taking
        # options such as --config or --output are intentionally ignored here.
        type_name = TYPE_FLAG_BY_CLI_NAME.get(arg)
        if type_name and type_name not in selected_order:
            selected_order.append(type_name)

    # Fallback for unusual argparse callers/tests that build args without sys.argv.
    if not selected_order:
        for type_name in TYPE_FLAG_ORDER:
            if getattr(args, type_name, False):
                selected_order.append(type_name)

    if args.all or not selected_order:
        return None, None

    return set(selected_order), selected_order


def main():
    parser = argparse.ArgumentParser(
        description="Compare Xenoblade translation JSON files with optional type filters.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("original_dir", nargs="?", help="Directory with original Japanese JSON files. Overrides config.")
    parser.add_argument("fan_dir", nargs="?", help="Directory with fan translation JSON files. Overrides config.")
    parser.add_argument("localized_dir", nargs="?", help="Directory with localized-version JSON files. Overrides config.")
    parser.add_argument("-o", "--output", default=None, help="Output JSON file. Overrides config.")

    parser.add_argument("-story", action="store_true", help="Compare story/cinematic files only: xs*.json")
    parser.add_argument("-quest", action="store_true", help="Compare quest/event files only: qev*.json, tev*.json, qst*.json")
    parser.add_argument("-field", action="store_true", help="Compare known field-dialogue files only: FLD_MesLock.json")
    parser.add_argument("-other", action="store_true", help="Compare files not classified as story/quest/field.")
    parser.add_argument("-all", action="store_true", help="Compare all JSON files. Default when no type flag is passed.")

    parser.add_argument("--config", default=None, help="Custom config path. Default: same name as script, .json extension.")
    parser.add_argument("--reset-config", action="store_true", help="Delete config first and ask for paths again.")
    parser.add_argument("--no-save-config", action="store_true", help="Do not write/update config.")
    parser.add_argument(
        "--include-mostly-empty",
        action="store_true",
        help="Include rows where at least 2 of JP/fan/localized are empty. Default: skip them.",
    )

    args = parser.parse_args()
    print(f"compare_translations_filtered.py version: {SCRIPT_VERSION}")

    selected_types, selected_type_order = build_selected_types(args)
    original_dir, fan_dir, localized_dir, output_file, config_path = build_runtime_paths(args)

    active_filter = "all" if selected_types is None else ", ".join(selected_type_order)
    print(f"Active filter: {active_filter}")
    if selected_type_order:
        print(f"Output type order: {', '.join(selected_type_order)}")
    print(f"Mostly-empty filter: {'OFF' if args.include_mostly_empty else 'ON'}")
    print(f"Config path: {config_path}")

    results, stats, output_path = compare_json_files(
        original_dir=original_dir,
        fan_dir=fan_dir,
        localized_dir=localized_dir,
        output_file=output_file,
        selected_types=selected_types,
        selected_type_order=selected_type_order,
        skip_mostly_empty=not args.include_mostly_empty,
    )

    print("\n" + "=" * 60)
    print(f"Comparison completed. Results saved to: {output_path}")
    print(f"Active filter: {active_filter}")
    if selected_type_order:
        print(f"Output type order: {', '.join(selected_type_order)}")
    print(f"Differences written: {len(results)}")
    print(f"Mostly-empty rows skipped: {stats['skipped_mostly_empty']}")
    print(f"Final safety skipped: {stats['final_safety_skipped']}")
    print(f"Post-write safety skipped: {stats['postwrite_safety_skipped']}")
    if stats.get("skipped_examples"):
        print("Skipped examples:")
        for ex in stats["skipped_examples"][:5]:
            print(f"  - {ex['file_name']} | {ex['ID']} | empty_fields={ex['empty_fields']} | type={ex['file_type']}")
    print(f"Files loaded total: {stats['loaded_files']}")
    print(f"Files skipped by filter: {stats['skipped_files']}")
    print(f"Loaded by type: {dict(stats['loaded_by_type'])}")
    print(f"Missing original files: {stats['missing_original']}")
    print(f"Missing localized files: {stats['missing_localized']}")
    print(f"Load errors: {stats['errors']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
