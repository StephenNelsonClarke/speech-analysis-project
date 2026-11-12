"""Run the keyword + LLM theme pipeline with the alternative (v2) taxonomy.

The existing modules bind the original taxonomy at import time. ``use_taxonomy_v2`` swaps
those bindings for the duration of a run and restores them afterwards, so the original files,
taxonomy and outputs are unchanged.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

import analyze_mpc_speeches
import compare_keyword_and_llm_themes
import llm_report_charts
import llm_theme_classifier
import quantify_mpc_speeches
import run_enriched_theme_pipeline
import theme_taxonomy_v2
from membership_activity_charts import write_activity_charts
from quantify_mpc_speeches import DEFAULT_MEMBERSHIP, load_membership
from refresh_combined_reports import EXCLUDED_SLIDES_URL

PROJECT_ROOT = Path(__file__).resolve().parent
PROMPT_PATH = PROJECT_ROOT / 'llm_theme_prompt_v2.txt'
SCHEMA_PATH = PROJECT_ROOT / 'llm_theme_schema_v2.json'
DEFAULT_INPUT = PROJECT_ROOT / 'outputs' / 'combined_run' / 'speeches_enriched.csv'
DEFAULT_OUTPUT = PROJECT_ROOT / 'outputs' / 'combined_run_taxonomy_v2'
DEFAULT_EXCLUSIONS = PROJECT_ROOT / 'outputs' / 'speech_format_audit' / 'slides_only_in_analysis.csv'


def apply_reviewed_exclusions(
    frame: pd.DataFrame, review_csv: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    review = pd.read_csv(review_csv, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    required = {'hyperlink', 'exclude_from_analysis'}
    if not required.issubset(review.columns) or not review.hyperlink.is_unique:
        raise ValueError('Exclusion review requires unique hyperlinks and exclude_from_analysis.')
    decisions = review.exclude_from_analysis.str.strip().str.lower()
    if not decisions.isin(['yes', 'no', '']).all():
        raise ValueError('Exclusion decisions must be yes, no, or blank (retain).')
    for url in review.loc[decisions.eq(''), 'hyperlink']:
        print(f'Retaining reviewed item with blank exclusion decision: {url}', flush=True)
    missing = set(review.hyperlink) - set(frame.hyperlink)
    if missing:
        raise ValueError(f'Reviewed URLs absent from classified dataset: {sorted(missing)}')
    excluded_urls = set(review.loc[decisions.eq('yes'), 'hyperlink'])
    selected = frame.loc[~frame.hyperlink.isin(excluded_urls)].copy().reset_index(drop=True)
    excluded = frame.loc[frame.hyperlink.isin(excluded_urls)].copy()
    if selected.empty:
        raise ValueError('Exclusions would leave no speeches to analyse.')
    excluded['exclusion_reason'] = 'User-reviewed slide-only item.'
    return selected, excluded


def _patches() -> dict:
    themes = theme_taxonomy_v2.THEMES
    labels = {key: meta['label'] for key, meta in themes.items()}
    pipeline = run_enriched_theme_pipeline
    return {
        analyze_mpc_speeches: {'THEMES': themes, 'THEME_ORDER': list(themes)},
        llm_theme_classifier: {'THEMES': themes, 'THEME_KEYS': list(themes),
                               'PROMPT_PATH': PROMPT_PATH, 'SCHEMA_PATH': SCHEMA_PATH},
        compare_keyword_and_llm_themes: {
            'THEMES': themes, 'THEME_KEYS': set(themes),
            'THEME_LABEL_TO_KEY': {label: key for key, label in labels.items()}},
        llm_report_charts: {'THEMES': themes,
                            'THEME_LABELS': {**labels, 'unclassified': 'Unclassified'}},
        quantify_mpc_speeches: {'THEMES': themes},
        pipeline: {'THEMES': themes, 'GENERATED_COLUMNS': [
            'speech_id', 'speech_title', 'word_count', 'primary_theme', 'primary_theme_label',
            'top_themes', *[f'{key}_score' for key in themes], *pipeline.LLM_COLUMNS]},
    }


@contextmanager
def use_taxonomy_v2():
    originals = []
    try:
        for module, values in _patches().items():
            for name, value in values.items():
                originals.append((module, name, getattr(module, name)))
                setattr(module, name, value)
        yield theme_taxonomy_v2.THEMES
    finally:
        for module, name, value in reversed(originals):
            setattr(module, name, value)


def check_prompt_and_schema() -> None:
    keys = list(theme_taxonomy_v2.THEMES)
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    props = schema['properties']
    if props['primary_theme']['enum'] != keys or props['secondary_themes']['items']['enum'] != keys:
        raise ValueError('v2 schema theme keys do not match theme_taxonomy_v2.THEMES.')
    prompt = PROMPT_PATH.read_text(encoding='utf-8')
    for key, meta in theme_taxonomy_v2.THEMES.items():
        if f'- {key} = "{meta["label"]}"' not in prompt:
            raise ValueError(f'v2 prompt is missing theme {key}.')
    if 'fiscal_policy_public_finances' in prompt or 'monetary_policy_rates' in prompt:
        raise ValueError('v2 prompt still lists a removed theme.')


def run_keyword_only(input_csv: Path, output_root: Path, exclude_urls: tuple[str, ...]) -> dict:
    source = pd.read_csv(input_csv, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    source = source.loc[~source['hyperlink'].isin(exclude_urls)].reset_index(drop=True)
    with use_taxonomy_v2():
        keyword = run_enriched_theme_pipeline.classify_keywords(source)
    output_root.mkdir(parents=True, exist_ok=True)
    keyword.to_csv(output_root / 'mpc_speech_database_keyword_v2.csv', index=False, encoding='utf-8')
    counts = Counter(keyword['primary_theme'].replace('', 'unclassified'))
    summary = {'taxonomy': theme_taxonomy_v2.TAXONOMY_VERSION, 'speech_rows': len(keyword),
               'keyword_primary_counts': dict(counts.most_common())}
    (output_root / 'keyword_v2_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def run(input_csv: Path, output_root: Path, provider: str = 'auto',
        membership_csv: Path = DEFAULT_MEMBERSHIP, max_new_classifications: int | None = None,
        exclude_urls: tuple[str, ...] = (EXCLUDED_SLIDES_URL,), skip_charts: bool = False,
        skip_analysis: bool = False) -> dict:
    check_prompt_and_schema()
    with use_taxonomy_v2():
        summary = run_enriched_theme_pipeline.run(
            input_csv, output_root, provider, membership_csv, max_new_classifications,
            exclude_urls, skip_charts, skip_analysis)
        if summary.get('complete') and not skip_charts and not skip_analysis:
            reports_root = output_root.resolve() / 'quantitative'
            annotated = pd.read_csv(reports_root / 'annotated_speeches.csv', dtype=str,
                                    keep_default_na=False)
            write_activity_charts(reports_root, annotated, load_membership(membership_csv)[1])
    if summary.get('complete'):
        (output_root / 'taxonomy_v2.json').write_text(json.dumps({
            'version': theme_taxonomy_v2.TAXONOMY_VERSION,
            'removed': list(theme_taxonomy_v2.REMOVED_THEMES),
            'themes': theme_taxonomy_v2.THEMES,
        }, indent=2), encoding='utf-8')
    return summary


def run_saved_reports(output_root: Path, membership_csv: Path = DEFAULT_MEMBERSHIP,
                      exclusion_csv: Path | None = None, dataset_csv: Path | None = None) -> dict:
    check_prompt_and_schema()
    database = dataset_csv if dataset_csv is not None else output_root / 'mpc_speech_database_with_llm.csv'
    frame = pd.read_csv(database, dtype=str, keep_default_na=False)
    if frame.empty or not frame.hyperlink.is_unique:
        raise ValueError('Saved classifications must contain unique speeches.')
    with use_taxonomy_v2():
        if dataset_csv is None:
            provenance = json.loads((output_root / 'classification_summary.json').read_text(encoding='utf-8'))
            prompt = llm_theme_classifier.load_prompt_template()
            schema = llm_theme_classifier.load_schema()
            cache = run_enriched_theme_pipeline.load_cache(output_root / 'llm_classification_cache.jsonl')
            for row in frame.itertuples():
                fingerprint = run_enriched_theme_pipeline.cache_key(
                    row.text, prompt, schema, provenance['provider'])
                record = cache.get((row.speech_id, fingerprint))
                if record is None or any([
                    row.llm_primary_theme != record['primary_theme'],
                    row.llm_secondary_themes != '; '.join(record['secondary_themes']),
                    float(row.llm_confidence) != record['confidence'],
                    row.llm_evidence_excerpt != record['evidence_excerpt'],
                    row.llm_rationale != record['rationale'],
                ]):
                    raise ValueError(f'Saved classification does not match current cache: {row.hyperlink}')
        else:
            for row in frame.itertuples():
                secondary = [key.strip() for key in row.llm_secondary_themes.split(';') if key.strip()]
                if (any(key not in theme_taxonomy_v2.THEMES for key in secondary)
                        or len(secondary) > 3 or len(set(secondary)) != len(secondary)
                        or row.llm_primary_theme in secondary):
                    raise ValueError(f'Invalid saved secondary themes: {row.hyperlink}')
                llm_theme_classifier.validate_response({
                    'primary_theme': row.llm_primary_theme,
                    'secondary_themes': secondary,
                    'confidence': row.llm_confidence, 'evidence_excerpt': row.llm_evidence_excerpt,
                    'rationale': row.llm_rationale,
                })
        reports_root = output_root / 'quantitative'
        source_rows = len(frame)
        if exclusion_csv is not None:
            frame, excluded = apply_reviewed_exclusions(frame, exclusion_csv)
            reports_root.mkdir(parents=True, exist_ok=True)
            excluded.to_csv(reports_root / 'excluded_speeches.csv', index=False)
            database = reports_root / 'analysis_speech_database.csv'
            frame.to_csv(database, index=False, encoding='utf-8')
        summary = quantify_mpc_speeches.run_analysis(database, reports_root, membership_csv)
        run_enriched_theme_pipeline.write_charts(reports_root)
        annotated = pd.read_csv(reports_root / 'annotated_speeches.csv', dtype=str,
                                keep_default_na=False)
        write_activity_charts(reports_root, annotated, load_membership(membership_csv)[1])
    summary.update(llm_calls=0, chart_count=len(list(reports_root.glob('*.png'))),
                   classified_source_rows=source_rows, excluded_rows=source_rows - len(frame),
                   exclusion_review=str(exclusion_csv.resolve()) if exclusion_csv else '',
                   percentage_denominator='All speeches within each corresponding group.')
    (reports_root / 'report_refresh_summary.json').write_text(
        json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Classify speeches with the v2 taxonomy '
                                     '(no fiscal theme; monetary policy split into conventional/unconventional).')
    parser.add_argument('--input-csv', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--output-root', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--provider', choices=['auto', 'copilot-api', 'openai'], default='auto')
    parser.add_argument('--membership-csv', type=Path, default=DEFAULT_MEMBERSHIP)
    parser.add_argument('--exclusion-csv', type=Path,
                        help='Reviewed yes/no exclusions for reports-only mode.')
    parser.add_argument('--dataset-csv', type=Path,
                        help='Already classified analysis dataset for reports-only; no API cache required.')
    parser.add_argument('--max-new-classifications', type=int,
                        help='Optional pilot-run limit; cached results resume on the next run.')
    parser.add_argument('--skip-charts', action='store_true')
    parser.add_argument('--skip-analysis', action='store_true',
                        help='Save classifications only, without diagnostics, quantitative reports or charts.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--keyword-only', action='store_true',
                      help='Only run v2 keyword scoring (no LLM calls).')
    mode.add_argument('--reports-only', action='store_true',
                      help='Generate reports and charts from saved v2 classifications; no LLM calls.')
    args = parser.parse_args()
    exclude = (EXCLUDED_SLIDES_URL,)
    if args.reports_only:
        exclusion_csv = args.exclusion_csv
        if exclusion_csv is None and args.dataset_csv is None and DEFAULT_EXCLUSIONS.exists():
            columns = pd.read_csv(DEFAULT_EXCLUSIONS, nrows=0).columns
            if 'exclude_from_analysis' in columns:
                exclusion_csv = DEFAULT_EXCLUSIONS
        run_saved_reports(args.output_root, args.membership_csv, exclusion_csv, args.dataset_csv)
    elif args.keyword_only:
        run_keyword_only(args.input_csv, args.output_root, exclude)
    else:
        run(args.input_csv, args.output_root, args.provider, args.membership_csv,
            args.max_new_classifications, exclude, args.skip_charts, args.skip_analysis)


if __name__ == '__main__':
    main()
