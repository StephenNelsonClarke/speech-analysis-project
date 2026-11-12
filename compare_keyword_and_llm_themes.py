from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from analyze_mpc_speeches import THEMES

THEME_LABEL_TO_KEY = {meta['label']: key for key, meta in THEMES.items()}
THEME_KEYS = set(THEMES.keys())


def load_llm_results(path: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    if path.is_dir():
        files = sorted(path.glob('*.json')) + sorted(path.glob('*.jsonl'))
    else:
        files = [path]

    for file in files:
        if file.suffix.lower() == '.jsonl':
            with file.open('r', encoding='utf-8') as handle:
                for line in handle:
                    raw = line.strip()
                    if not raw:
                        continue
                    record = json.loads(raw)
                    speech_id = record.get('speech_id') or record.get('file_name') or record.get('source_path')
                    if speech_id:
                        results[speech_id] = record
        else:
            with file.open('r', encoding='utf-8') as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                speech_id = payload.get('speech_id') or payload.get('file_name') or payload.get('source_path')
                if speech_id:
                    results[speech_id] = payload
            elif isinstance(payload, list):
                for item in payload:
                    speech_id = item.get('speech_id') or item.get('file_name') or item.get('source_path')
                    if speech_id:
                        results[speech_id] = item
    return results


def parse_theme_list(value: str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    cleaned = value.strip()
    if not cleaned:
        return []
    if cleaned.startswith('[') and cleaned.endswith(']'):
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except json.JSONDecodeError:
            pass
    return [part.strip(" '\"") for part in cleaned.split(',') if part.strip()]


def normalise_theme(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if cleaned in THEME_KEYS:
        return cleaned
    if cleaned in THEME_LABEL_TO_KEY:
        return THEME_LABEL_TO_KEY[cleaned]
    lowered = cleaned.lower().replace(' ', '_').replace('-', '_')
    lowered = lowered.replace('&', 'and')
    lowered = ''.join(ch for ch in lowered if ch.isalnum() or ch == '_')
    if lowered in THEME_KEYS:
        return lowered
    for key, meta in THEMES.items():
        if meta['label'].lower() == cleaned.lower():
            return key
    return None


def normalize_theme_sequence(values: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for value in values:
        key = normalise_theme(value)
        if key and key not in seen:
            normalized.append(key)
            seen.add(key)
    return normalized


def build_disagreement_rows(csv_path: Path, llm_path: Path) -> list[dict[str, Any]]:
    csv.field_size_limit(2**31 - 1)
    with csv_path.open('r', encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))

    llm_results = load_llm_results(llm_path)
    disagreements: list[dict[str, Any]] = []

    for row in rows:
        speech_id = row.get('speech_id')
        if not speech_id:
            continue

        keyword_primary_label = row.get('primary_theme_label') or row.get('primary_theme') or ''
        keyword_primary_key = normalise_theme(keyword_primary_label)
        keyword_top_labels = parse_theme_list(row.get('top_themes'))
        keyword_top_keys = normalize_theme_sequence(keyword_top_labels)
        keyword_theme_keys = normalize_theme_sequence([keyword_primary_label] + keyword_top_labels)

        llm = llm_results.get(speech_id)
        if llm is None:
            continue

        llm_primary_key = normalise_theme(llm.get('primary_theme'))
        llm_secondary_keys = normalize_theme_sequence(llm.get('secondary_themes', []))
        llm_theme_keys = normalize_theme_sequence([llm_primary_key] + llm_secondary_keys)
        confidence = llm.get('confidence', 0.0)

        if not keyword_theme_keys or not llm_theme_keys:
            continue

        shared_themes = sorted(set(keyword_theme_keys).intersection(llm_theme_keys))
        primary_theme_agrees = bool(keyword_primary_key and llm_primary_key and keyword_primary_key == llm_primary_key)
        any_theme_overlap = bool(shared_themes)

        if primary_theme_agrees and any_theme_overlap:
            continue

        if not any_theme_overlap and not primary_theme_agrees:
            disagreement_type = 'primary_theme_mismatch_and_no_theme_overlap'
        elif not any_theme_overlap:
            disagreement_type = 'no_theme_overlap'
        else:
            disagreement_type = 'primary_theme_mismatch'

        disagreements.append({
            'speech_id': speech_id,
            'speaker': row.get('speaker', ''),
            'year': row.get('year', ''),
            'speech_title': row.get('speech_title', ''),
            'keyword_primary_label': keyword_primary_label,
            'keyword_primary_key': keyword_primary_key or '',
            'keyword_top_labels': '; '.join(keyword_top_labels),
            'keyword_top_keys': '; '.join(keyword_top_keys),
            'keyword_theme_keys': '; '.join(keyword_theme_keys),
            'llm_primary_key': llm_primary_key or '',
            'llm_secondary_keys': '; '.join(llm_secondary_keys),
            'llm_theme_keys': '; '.join(llm_theme_keys),
            'llm_confidence': confidence,
            'primary_theme_agrees': primary_theme_agrees,
            'any_theme_overlap': any_theme_overlap,
            'shared_themes': '; '.join(shared_themes),
            'disagreement_type': disagreement_type,
        })

    return disagreements


def main() -> None:
    parser = argparse.ArgumentParser(description='Compare keyword-based theme labels to LLM theme labels and flag disagreements.')
    parser.add_argument('--csv', type=Path, required=True, help='Path to the keyword-based speech database CSV.')
    parser.add_argument('--llm-results', type=Path, required=True, help='Path to a JSON/JSONL LLM results file or folder.')
    parser.add_argument('--output-csv', type=Path, default=Path('theme_disagreements.csv'), help='Output CSV for disagreements.')
    args = parser.parse_args()

    rows = build_disagreement_rows(args.csv, args.llm_results)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        'speech_id',
        'speaker',
        'year',
        'speech_title',
        'keyword_primary_label',
        'keyword_primary_key',
        'keyword_top_labels',
        'keyword_top_keys',
        'keyword_theme_keys',
        'llm_primary_key',
        'llm_secondary_keys',
        'llm_theme_keys',
        'llm_confidence',
        'primary_theme_agrees',
        'any_theme_overlap',
        'shared_themes',
        'disagreement_type',
    ]

    with args.output_csv.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f'Found {len(rows)} disagreements. Saved to {args.output_csv}')


if __name__ == '__main__':
    main()
