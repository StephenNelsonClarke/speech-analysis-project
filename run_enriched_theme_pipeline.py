from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests

from analyze_mpc_speeches import THEMES, score_speech
from compare_keyword_and_llm_themes import build_disagreement_rows
from llm_theme_classifier import (
    choose_provider, classify_speech, load_prompt_template, load_schema, validate_response,
)
from quantify_mpc_speeches import DEFAULT_MEMBERSHIP, run_analysis
from llm_report_charts import write_llm_charts

PROJECT_ROOT = Path(__file__).resolve().parent
LLM_COLUMNS = [
    'llm_primary_theme', 'llm_secondary_themes', 'llm_confidence',
    'llm_evidence_excerpt', 'llm_rationale',
]
GENERATED_COLUMNS = [
    'speech_id', 'speech_title', 'word_count', 'primary_theme', 'primary_theme_label',
    'top_themes', *[f'{key}_score' for key in THEMES], *LLM_COLUMNS,
]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def classify_with_retries(text: str, prompt: str, schema: dict, provider: str) -> dict:
    for attempt in range(3):
        try:
            return validate_response(classify_speech(text, prompt, schema, provider))
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            if attempt == 2:
                raise
            delay = 10 * (attempt + 1)
            print(f'Transient LLM connection failure ({type(exc).__name__}); '
                  f'retrying in {delay}s (attempt {attempt + 2}/3).', flush=True)
            time.sleep(delay)


def classify_keywords(source: pd.DataFrame) -> pd.DataFrame:
    required = {'hyperlink', 'text', 'title', 'date', 'speaker', 'year',
                'speech_date', 'mpc_member_type'}
    if not required.issubset(source.columns):
        raise ValueError(f'Enriched dataset is missing columns: {sorted(required - set(source.columns))}')
    overlap = set(source.columns).intersection(GENERATED_COLUMNS)
    if overlap:
        raise ValueError(f'Input already has classification columns: {sorted(overlap)}')
    if source.empty or not source['hyperlink'].is_unique or source['hyperlink'].str.strip().eq('').any():
        raise ValueError('Input must contain speeches with nonblank, unique URLs.')
    if source['text'].str.strip().str.lower().isin(
        ['', 'na', 'n/a', 'no text extracted']
    ).any():
        raise ValueError('Input contains missing speech text; repair it before classifying.')
    result = source.copy().reset_index(drop=True)
    result['speech_id'] = result['hyperlink'].map(lambda url: 'url_' + digest(url))
    result['speech_title'] = result['title']
    result['word_count'] = result['text'].map(lambda text: len(re.findall(r'\b\w+\b', text)))
    scores = pd.DataFrame([score_speech(text) for text in result['text']])
    ranked = [sorted(THEMES, key=lambda key: row[key], reverse=True)
              for row in scores.to_dict('records')]
    result['primary_theme'] = [keys[0] if scores.iloc[index].max() > 0 else ''
                               for index, keys in enumerate(ranked)]
    result['primary_theme_label'] = result['primary_theme'].map(
        {key: meta['label'] for key, meta in THEMES.items()}
    ).fillna('')
    result['top_themes'] = [
        json.dumps([THEMES[key]['label'] for key in keys[:3]]) if primary else '[]'
        for keys, primary in zip(ranked, result['primary_theme'])
    ]
    for key in THEMES:
        result[f'{key}_score'] = scores[key]
    return result


def cache_key(text: str, prompt: str, schema: dict, provider: str) -> str:
    config = {
        'text': text, 'prompt': prompt, 'schema': schema, 'provider': provider,
        'model': os.getenv('OPENAI_MODEL', 'gpt-4o-mini') if provider == 'openai'
                 else os.getenv('COPILOT_MODEL_HINT', ''),
        'endpoint': (os.getenv('OPENAI_BASE_URL') or os.getenv('OPENAI_API_BASE')
                     or 'https://api.openai.com/v1') if provider == 'openai' else 'copilot-api',
        'classifier_sha256': digest(Path(__file__).with_name('llm_theme_classifier.py')
                                    .read_text(encoding='utf-8-sig')),
    }
    return digest(json.dumps(config, sort_keys=True))


def load_cache(path: Path) -> dict[tuple[str, str], dict]:
    records = {}
    if path.exists():
        for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                classification = validate_response(record)
                key = (record['speech_id'], record['classification_key'])
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ValueError(f'Invalid LLM cache at {path.name}, line {line_number}.') from exc
            records[key] = {**record, **classification}
    return records


def write_charts(output_root: Path) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(output_root / f'{name}.png', dpi=150, bbox_inches='tight')
        plt.close(fig)

    for name, column, title in [
        ('speeches_by_year', 'year', 'Speeches per year'),
        ('speeches_by_speaker', 'speaker', 'Speeches by speaker'),
        ('speeches_by_mpc_member_type', 'mpc_member_type', 'MPC membership at speech date'),
    ]:
        table = pd.read_csv(output_root / f'{name}.csv', keep_default_na=False)
        if column == 'speaker':
            table = table.sort_values('speech_count')
        fig, ax = plt.subplots(figsize=(10, max(4, len(table) * 0.35)))
        if column == 'year':
            ax.bar(table[column].astype(str), table['speech_count'])
            ax.set(ylabel='Speech count', xlabel='Year')
        else:
            ax.barh(table[column].str.replace('_', ' '), table['speech_count'])
            ax.set(xlabel='Speech count')
        ax.set_title(title)
        save(fig, name)
    themes = pd.read_csv(output_root / 'theme_counts.csv')
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for role, ax in zip(['primary', 'secondary'], axes):
        table = themes.loc[themes.theme_role.eq(role)].pivot(
            index='theme_label', columns='method', values='speech_count').fillna(0)
        table.plot.barh(ax=ax)
        ax.set(title=f'{role.title()} themes', xlabel='Speech count', ylabel='')
    save(fig, 'theme_counts')
    write_llm_charts(output_root)


def run(
    input_csv: Path, output_root: Path, provider: str = 'auto',
    membership_csv: Path = DEFAULT_MEMBERSHIP, max_new_classifications: int | None = None,
    exclude_urls: tuple[str, ...] = (),
    skip_charts: bool = False,
    skip_analysis: bool = False,
) -> dict:
    if max_new_classifications is not None and max_new_classifications < 1:
        raise ValueError('max_new_classifications must be positive.')
    input_csv, output_root = input_csv.resolve(), output_root.resolve()
    if input_csv.is_relative_to(output_root) or membership_csv.resolve().is_relative_to(output_root):
        raise ValueError('Choose an output folder separate from the input and membership reference.')
    source = pd.read_csv(input_csv, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    missing_exclusions = set(exclude_urls) - set(source['hyperlink'])
    if missing_exclusions:
        raise ValueError(f'Excluded URLs not found in source: {sorted(missing_exclusions)}')
    source = source.loc[~source['hyperlink'].isin(exclude_urls)].reset_index(drop=True)
    if exclude_urls:
        print(f'Excluded {len(set(exclude_urls))} explicitly selected row(s) from analysis.', flush=True)
    keyword = classify_keywords(source)
    provider = choose_provider(provider)
    prompt, schema = load_prompt_template(), load_schema()
    output_root.mkdir(parents=True, exist_ok=True)
    keyword_path = output_root / 'mpc_speech_database.csv'
    keyword.to_csv(keyword_path, index=False, encoding='utf-8')
    cache_path = output_root / 'llm_classification_cache.jsonl'
    cached = load_cache(cache_path)
    records = []
    new_count = 0
    print(f'Keyword-classified {len(keyword)} speeches from text. LLM provider: {provider}', flush=True)
    with cache_path.open('a', encoding='utf-8') as handle:
        for index, row in keyword.iterrows():
            fingerprint = cache_key(row['text'], prompt, schema, provider)
            record = cached.get((row['speech_id'], fingerprint))
            if record is None:
                if max_new_classifications is not None and new_count >= max_new_classifications:
                    print(f'Paused after {new_count} new classifications. Re-run to resume; '
                          'full reports are only produced after every speech is classified.', flush=True)
                    return {'complete': False, 'new_classifications': new_count,
                            'classified_rows': len(records), 'speech_rows': len(keyword)}
                print(f'Classifying {index + 1}/{len(keyword)}: {row["title"]}', flush=True)
                try:
                    classification = classify_with_retries(row['text'], prompt, schema, provider)
                except Exception as exc:
                    raise RuntimeError(f'LLM classification failed at row {index + 1} '
                                       f'({row["hyperlink"]}); saved results can be resumed.') from exc
                record = {
                    'speech_id': row['speech_id'], 'hyperlink': row['hyperlink'],
                    'provider': provider, 'classification_key': fingerprint, **classification,
                }
                handle.write(json.dumps(record, ensure_ascii=False) + '\n')
                handle.flush()
                new_count += 1
                print(f'  Saved: {record["primary_theme"]}', flush=True)
            records.append(record)
    llm_path = output_root / 'llm_theme_results.jsonl'
    llm_path.write_text(''.join(json.dumps(record, ensure_ascii=False) + '\n'
                                for record in records), encoding='utf-8')
    merged = keyword.copy()
    merged['llm_primary_theme'] = [r['primary_theme'] for r in records]
    merged['llm_secondary_themes'] = ['; '.join(r['secondary_themes']) for r in records]
    merged['llm_confidence'] = [r['confidence'] for r in records]
    merged['llm_evidence_excerpt'] = [r['evidence_excerpt'] for r in records]
    merged['llm_rationale'] = [r['rationale'] for r in records]
    merged_path = output_root / 'mpc_speech_database_with_llm.csv'
    merged.to_csv(merged_path, index=False, encoding='utf-8')
    pd.testing.assert_frame_equal(
        pd.read_csv(merged_path, dtype=str, keep_default_na=False)[source.columns], source)
    if skip_analysis:
        summary = {
            'input_csv': str(input_csv),
            'input_sha256': hashlib.sha256(input_csv.read_bytes()).hexdigest(),
            'speech_rows': len(source), 'complete': True, 'provider': provider,
            'new_classifications': new_count,
            'excluded_urls': sorted(set(exclude_urls)),
            'analysis_generated': False, 'charts_generated': False,
            'llm_prompt_sha256': digest(prompt), 'llm_schema': schema,
        }
        (output_root / 'classification_summary.json').write_text(
            json.dumps(summary, indent=2), encoding='utf-8')
        print(f'Complete: {len(source)} speeches classified. '
              'Quantitative analysis and charts explicitly skipped.', flush=True)
        return summary
    disagreements = build_disagreement_rows(keyword_path, llm_path)
    pd.DataFrame(disagreements, columns=[
        'speech_id', 'speaker', 'year', 'speech_title', 'keyword_primary_label',
        'keyword_primary_key', 'keyword_top_labels', 'keyword_top_keys', 'keyword_theme_keys',
        'llm_primary_key', 'llm_secondary_keys', 'llm_theme_keys', 'llm_confidence',
        'primary_theme_agrees', 'any_theme_overlap', 'shared_themes', 'disagreement_type',
    ]).to_csv(output_root / 'theme_disagreements.csv', index=False)
    reports_root = output_root / 'quantitative'
    summary = run_analysis(merged_path, reports_root, membership_csv)
    if skip_charts:
        print('Chart generation explicitly skipped; classification and CSV reports are saved.', flush=True)
    else:
        write_charts(reports_root)
    provenance = {
        'input_csv': str(input_csv), 'input_sha256': hashlib.sha256(input_csv.read_bytes()).hexdigest(),
        'speech_rows': len(source), 'complete': True, 'provider': provider,
        'excluded_urls': sorted(set(exclude_urls)),
        'charts_generated': not skip_charts,
        'keyword_method': 'analyze_mpc_speeches.score_speech applied only to text',
        'colleague_keyword_columns': 'Preserved unchanged; not used for classification or reports.',
        'keyword_zero_hit_rule': 'Unclassified if every theme score is zero.',
        'llm_text_limit_characters': 200000,
        'llm_prompt_sha256': digest(prompt), 'llm_schema': schema,
        'disagreement_rows': len(disagreements),
    }
    (output_root / 'classification_summary.json').write_text(
        json.dumps(provenance, indent=2), encoding='utf-8')
    print(f'Complete: {len(source)} speeches, {len(disagreements)} primary-theme disagreements.',
          flush=True)
    return {**summary, 'complete': True}


def main() -> None:
    parser = argparse.ArgumentParser(description='Classify enriched speech text and produce quantitative reports.')
    parser.add_argument('--input-csv', type=Path, default=PROJECT_ROOT / 'speeches_enriched.csv')
    parser.add_argument('--output-root', type=Path, default=PROJECT_ROOT / 'outputs' / 'enriched_run')
    parser.add_argument('--provider', choices=['auto', 'copilot-api', 'openai'], default='auto')
    parser.add_argument('--membership-csv', type=Path, default=DEFAULT_MEMBERSHIP)
    parser.add_argument('--max-new-classifications', type=int,
                        help='Optional pilot-run limit; cached results resume on the next run.')
    parser.add_argument('--exclude-url', action='append', default=[],
                        help='Exact URL to exclude from this analysis only; can be repeated.')
    parser.add_argument('--skip-charts', action='store_true',
                        help='Save classifications and CSV reports without charts (e.g. unverified tenure).')
    parser.add_argument('--skip-analysis', action='store_true',
                        help='Stop after saving classifications; do not generate diagnostics, reports or charts.')
    args = parser.parse_args()
    run(args.input_csv, args.output_root, args.provider, args.membership_csv,
        args.max_new_classifications, tuple(args.exclude_url), args.skip_charts, args.skip_analysis)


if __name__ == '__main__':
    main()
