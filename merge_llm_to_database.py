from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def load_jsonl(path: Path):
    if not path.exists():
        raise FileNotFoundError(f'LLM results file not found: {path}')

    records = []
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def merge_llm_into_database(database_csv: Path, llm_jsonl: Path, output_csv: Path) -> None:
    df = pd.read_csv(database_csv)
    llm = load_jsonl(llm_jsonl)

    llm_lookup = {}
    for item in llm:
        speech_id = item.get('speech_id') or item.get('file_name') or item.get('source_path')
        if speech_id:
            llm_lookup[speech_id] = item

    llm_columns = [
        'llm_primary_theme',
        'llm_secondary_themes',
        'llm_confidence',
        'llm_evidence_excerpt',
        'llm_rationale',
    ]
    for col in llm_columns:
        if col in df.columns:
            df.drop(columns=[col], inplace=True)

    for key, value in {
        'llm_primary_theme': lambda x: llm_lookup.get(x, {}).get('primary_theme', ''),
        'llm_secondary_themes': lambda x: '; '.join(llm_lookup.get(x, {}).get('secondary_themes', [])),
        'llm_confidence': lambda x: llm_lookup.get(x, {}).get('confidence', None),
        'llm_evidence_excerpt': lambda x: llm_lookup.get(x, {}).get('evidence_excerpt', ''),
        'llm_rationale': lambda x: llm_lookup.get(x, {}).get('rationale', ''),
    }.items():
        df[key] = df['speech_id'].map(value)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f'Merged {len(llm)} LLM records into {output_csv}')


def main() -> None:
    parser = argparse.ArgumentParser(description='Merge LLM theme classification results back into the master speech database CSV.')
    parser.add_argument('--database-csv', type=Path, required=True, help='Path to the main speech database CSV.')
    parser.add_argument('--llm-jsonl', type=Path, required=True, help='Path to the LLM JSONL classification file.')
    parser.add_argument('--output-csv', type=Path, required=True, help='Path to write the merged CSV.')
    args = parser.parse_args()

    merge_llm_into_database(args.database_csv, args.llm_jsonl, args.output_csv)


if __name__ == '__main__':
    main()
