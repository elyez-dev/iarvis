"""Translate missing i18n keys by calling the backend's /frontend/translate.

Runs on the HOST — no NLLB loaded here, just lightweight HTTP calls to
the backend which already has the model in RAM. 0 extra RAM pressure.

Usage:
    python3 scripts/translate_i18n_via_api.py
    python3 scripts/translate_i18n_via_api.py --dry-run
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

I18N_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "i18n")
EN_PATH = os.path.join(I18N_DIR, "en.json")
BACKEND_URL = "http://localhost:8000"

PRESERVE = {"en", "es"}
API_TIMEOUT = int(os.environ.get("TRANSLATE_TIMEOUT", "300"))

# Keys whose English value is a single ambiguous word — the backend
# endpoint handles the "mode" context when is_light_or_dark=True.
AMBIGUOUS = {"theme.light": "light", "theme.dark": "dark"}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def missing_keys(target_data, en_data):
    missing = []
    for key, en_value in en_data.items():
        if key == "language_names":
            continue
        tv = target_data.get(key, None)
        if tv is None or tv == en_value:
            missing.append(key)
    return missing


def call_translate(text, tgt_lang, is_ambig=False, retries=3):
    """POST /frontend/translate, returns translated string. Retries on timeout."""
    payload = json.dumps({
        "text": text,
        "tgt_lang": tgt_lang,
        "is_light_or_dark": is_ambig,
    }).encode("utf-8")
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"{BACKEND_URL}/frontend/translate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
                return json.loads(resp.read())["translation"]
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if attempt < retries - 1:
                wait = 2 ** attempt
                sys.stdout.write(f"!{wait}")
                sys.stdout.flush()
                time.sleep(wait)
    errored = str(last_err)[:80]
    raise RuntimeError(f"translate failed after {retries} retries: {errored}")


def main(dry_run=False):
    en_data = load_json(EN_PATH)

    # Load NLLB code map from the backend
    with urllib.request.urlopen(f"{BACKEND_URL}/frontend/languages") as resp:
        lang_map = json.loads(resp.read())

    files = sorted([f for f in os.listdir(I18N_DIR) if f.endswith(".json")])
    total_keys = 0
    total_files = 0
    start = time.time()

    for idx, filename in enumerate(files):
        locale_code = filename[:-5]
        if locale_code in PRESERVE:
            continue

        nllb_code = lang_map.get(locale_code)
        if nllb_code is None:
            nllb_code = locale_code

        filepath = os.path.join(I18N_DIR, filename)
        target_data = load_json(filepath)

        missing = missing_keys(target_data, en_data)
        if not missing:
            print(f"  [{idx+1}/{len(files)}] {filename}  up-to-date")
            continue

        total_files += 1
        elapsed = time.time() - start
        print(
            f"  [{idx+1}/{len(files)}] {filename}  {len(missing)} keys  "
            f"({locale_code} -> {nllb_code})  [{elapsed:.0f}s]"
        )

        for key in missing:
            en_value = en_data[key]
            is_ambig = key in AMBIGUOUS
            if dry_run:
                trans = f"[would translate '{en_value}']"
            else:
                try:
                    trans = call_translate(en_value, nllb_code, is_ambig=is_ambig)
                except Exception as e:
                    # Skip file on persistent failure — will be retried next run
                    print(f"\n    SKIPPED ({len(missing)} keys pending): {e}")
                    break
                sys.stdout.write(".")
                sys.stdout.flush()
            target_data[key] = trans

        if dry_run:
            print(f"\n    [DRY RUN] would translate {len(missing)} keys")
        else:
            save_json(target_data, filepath)
            print(f" saved")

        total_keys += len(missing)

    elapsed = time.time() - start
    print(
        f"\nDone. {total_keys} keys in {total_files} files. "
        f"Took {elapsed:.0f}s ({elapsed/60:.1f} min)."
    )


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    main(dry_run=dry)
