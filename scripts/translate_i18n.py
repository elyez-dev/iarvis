"""Translate only missing keys in i18n JSON files using the EXISTING NLLB-200.

Reuses the model already loaded by translation_service.py — no extra RAM.
Compares each locale file against en.json and translates only keys that are
absent (or still have their English fallback value). Preserves en.json/es.json.

Saves after each file so it can survive interruption without losing progress.

Usage:
    docker cp frontend/i18n iarvis_backend:/tmp/i18n
    docker cp scripts/translate_i18n.py iarvis_backend:/tmp/t.py
    docker exec -w /app iarvis_backend python /tmp/t.py
    docker cp iarvis_backend:/tmp/i18n/. frontend/i18n/
"""

import json
import os
import sys


I18N_DIR = "/tmp/i18n"
EN_PATH = os.path.join(I18N_DIR, "en.json")
LANG_MAP_PATH = "/app/config/languages.json"  # backend bind mount

PRESERVE = {"en", "es"}

# Keys where English word alone is ambiguous — translate with context
# then strip the context word so the result is still just "light"/"dark".
CONTEXT_MAP = {
    "theme.light": ("light mode", lambda s: s.replace(" mode", "").replace(" Mode", "").strip()),
    "theme.dark": ("dark mode", lambda s: s.replace(" mode", "").replace(" Mode", "").strip()),
}

BATCH_SIZE = 25  # strings per .generate() call


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def missing_keys(target_data, en_data):
    """Return keys from en_data whose value in target_data is still English."""
    missing = []
    for key, en_value in en_data.items():
        if key == "language_names":
            continue
        tv = target_data.get(key, None)
        if tv is None or tv == en_value:
            missing.append(key)
    return missing


def translate_batch(tokenizer, model, strings, src_lang, tgt_lang):
    """Translate a list of strings en -> target_lang in one .generate() call."""
    tokenizer.src_lang = src_lang
    tgt_lang_id = tokenizer.lang_code_to_id[tgt_lang]

    inputs = tokenizer(strings, return_tensors="pt", padding=True)
    out = model.generate(
        **inputs,
        forced_bos_token_id=tgt_lang_id,
        max_length=512,
    )
    return tokenizer.batch_decode(out, skip_special_tokens=True)


def main(dry_run=False):
    en_data = load_json(EN_PATH)
    lang_map = load_json(LANG_MAP_PATH)

    # Reuse the EXISTING NLLB model from the translation service —
    # no new model loaded, no extra RAM pressure.
    print("Connecting to existing NLLB-200 model...")
    sys.path.insert(0, "/app")
    from services.translation_service import translator

    tokenizer = translator.tokenizer
    model = translator.model
    print("Using already-loaded model.\n")

    src_code = "eng_Latn"
    files = sorted(os.listdir(I18N_DIR))
    files = [f for f in files if f.endswith(".json")]
    total_batches = 0
    total_translated = 0
    total_files = 0

    for idx, filename in enumerate(files):
        locale_code = filename[:-5]
        if locale_code in PRESERVE:
            continue

        nllb_code = lang_map.get(locale_code)
        if nllb_code is None:
            nllb_code = locale_code

        if nllb_code not in tokenizer.lang_code_to_id:
            print(f"  {filename}  SKIP (NLLB code '{nllb_code}' unknown)")
            continue

        filepath = os.path.join(I18N_DIR, filename)
        target_data = load_json(filepath)

        missing = missing_keys(target_data, en_data)
        if not missing:
            print(f"  [{idx+1}/{len(files)}] {filename}  up-to-date")
            continue

        total_files += 1
        print(f"  [{idx+1}/{len(files)}] {filename}  {len(missing)} keys ({nllb_code})")

        sources = []
        for key in missing:
            if key in CONTEXT_MAP:
                sources.append(CONTEXT_MAP[key][0])
            else:
                sources.append(en_data[key])

        translations = []
        for i in range(0, len(sources), BATCH_SIZE):
            batch_src = sources[i : i + BATCH_SIZE]
            batch_tgt = translate_batch(
                tokenizer, model, batch_src, src_code, nllb_code
            )
            translations.extend(batch_tgt)
            total_batches += 1

        for j, key in enumerate(missing):
            trans = translations[j]
            if key in CONTEXT_MAP:
                _, postproc = CONTEXT_MAP[key]
                trans = postproc(trans)
            target_data[key] = trans

        if dry_run:
            print(f"    [DRY RUN] would write {len(missing)} keys")
        else:
            save_json(target_data, filepath)
            print(f"    saved")

        total_translated += len(missing)

    print(
        f"\nDone. {total_batches} batches, {total_translated} keys "
        f"across {total_files} files."
    )


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    main(dry_run=dry)
