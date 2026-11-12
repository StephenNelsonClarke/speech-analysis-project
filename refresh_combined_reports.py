from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from add_mpc_membership_fields import classify, parse_speech_date
from membership_activity_charts import write_activity_charts
from quantify_mpc_speeches import DEFAULT_MEMBERSHIP, load_membership, name_key, run_analysis
from run_enriched_theme_pipeline import GENERATED_COLUMNS, write_charts

PROJECT_ROOT = Path(__file__).resolve().parent
EXCLUDED_SLIDES_URL = (
    'https://www.bankofengland.co.uk/speech/2016/'
    'slides-from-andy-haldanes-speech-given-at-the-deans-lecture-at-cass-business-school'
)
MEMBERSHIP_FIELDS = [
    'mpc_status', 'mpc_member_type', 'mpc_role', 'mpc_service_start',
    'years_on_mpc', 'completed_years_on_mpc', 'completed_months_on_mpc',
]
REFRESH_FLAGS = {
    'membership_appointment_dates_unverified', 'mpc_role_unassigned',
    'speech_date_outside_mpc_tenure', 'speaker_not_identified', 'ambiguous_speaker',
    'unrecognised_speaker',
}


def refresh_membership(source: pd.DataFrame, membership_csv: Path) -> pd.DataFrame:
    aliases, periods = load_membership(membership_csv)
    refreshed = source.copy().reset_index(drop=True)
    for field in MEMBERSHIP_FIELDS:
        refreshed[field] = ''
    for index, row in source.reset_index(drop=True).iterrows():
        speaker = aliases.get(name_key(row['speaker']))
        if not speaker:
            raise ValueError(f'Cannot refresh unidentified speaker for {row["hyperlink"]}.')
        speech_date = parse_speech_date(row['speech_date'])
        if speech_date is None:
            raise ValueError(f'Cannot refresh invalid speech date for {row["hyperlink"]}.')
        info = classify(speaker, speech_date, periods)
        refreshed.loc[index, 'speaker'] = speaker
        for field in MEMBERSHIP_FIELDS:
            refreshed.loc[index, field] = str(info[field])
        flags = [flag for flag in row['review_flag'].split(';') if flag and flag not in REFRESH_FLAGS]
        if info['problem']:
            flags.append(info['problem'])
        if info['mpc_member_type'] == 'internal' and not info['mpc_role']:
            flags.append('mpc_role_unassigned')
        refreshed.loc[index, 'review_flag'] = ';'.join(dict.fromkeys(flags))
    return refreshed


def combine_classifications(
    enriched: pd.DataFrame, databases: list[pd.DataFrame], exclude_urls: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not enriched.hyperlink.is_unique:
        raise ValueError('Combined enriched corpus has duplicate URLs.')
    if not set(exclude_urls).issubset(set(enriched.hyperlink)):
        raise ValueError('Requested exclusion is absent from the enriched corpus.')
    excluded = enriched.loc[enriched.hyperlink.isin(exclude_urls)].copy()
    selected = enriched.loc[~enriched.hyperlink.isin(exclude_urls)].copy().reset_index(drop=True)
    saved = pd.concat(databases, ignore_index=True)
    if not saved.hyperlink.is_unique:
        raise ValueError('Saved classification sources have duplicate URLs.')
    if set(saved.hyperlink) != set(selected.hyperlink):
        raise ValueError('Saved classifications do not exactly cover the selected corpus.')
    saved = saved.set_index('hyperlink').loc[selected.hyperlink].reset_index()
    if saved.text.tolist() != selected.text.tolist():
        raise ValueError('Speech text has changed; existing classifications cannot be reused.')
    if selected.text.str.strip().str.lower().isin(['', 'no text extracted', 'na', 'n/a']).any():
        raise ValueError('Selected corpus contains missing speech text.')
    if saved.llm_primary_theme.eq('').any():
        raise ValueError('Saved LLM classifications are incomplete.')
    for column in GENERATED_COLUMNS:
        selected[column] = saved[column].to_numpy()
    return selected, excluded


def run(candidate_csv: Path, classification_csvs: list[Path], output_root: Path,
        membership_csv: Path = DEFAULT_MEMBERSHIP) -> dict:
    output_root = output_root.resolve()
    inputs = [candidate_csv, membership_csv, *classification_csvs]
    if any(path.resolve().is_relative_to(output_root) for path in inputs):
        raise ValueError('Output directory must be separate from source inputs.')
    source = pd.read_csv(candidate_csv, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    refreshed = refresh_membership(source, membership_csv)
    databases = [pd.read_csv(path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
                 for path in classification_csvs]
    combined, excluded = combine_classifications(refreshed, databases, (EXCLUDED_SLIDES_URL,))
    if not combined.mpc_member_type.isin(['internal', 'external']).all():
        raise ValueError('Some analysed speeches remain outside recorded MPC membership; review before charts.')
    output_root.mkdir(parents=True, exist_ok=True)
    enriched_path = output_root / 'speeches_enriched.csv'
    database_path = output_root / 'mpc_speech_database_with_llm.csv'
    refreshed.to_csv(enriched_path, index=False, encoding='utf-8-sig')
    combined.to_csv(database_path, index=False, encoding='utf-8-sig')
    excluded[['hyperlink', 'title']].assign(reason='Previously confirmed slides-only; no speech text.').to_csv(
        output_root / 'excluded_speeches.csv', index=False)
    saved = pd.read_csv(database_path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    pd.testing.assert_frame_equal(saved[refreshed.columns], combined[refreshed.columns].astype(str))
    unchanged = [c for c in source.columns
                 if c not in {*MEMBERSHIP_FIELDS, 'review_flag', 'speaker'}]
    pd.testing.assert_frame_equal(
        pd.read_csv(enriched_path, dtype=str, keep_default_na=False)[unchanged], source[unchanged])
    reports_root = output_root / 'quantitative'
    summary = run_analysis(database_path, reports_root, membership_csv)
    write_charts(reports_root)
    _, periods = load_membership(membership_csv)
    annotated = pd.read_csv(reports_root / 'annotated_speeches.csv', dtype=str, keep_default_na=False)
    write_activity_charts(reports_root, annotated, periods)
    summary.update(
        enriched_rows=len(refreshed), analysed_rows=len(combined), excluded_rows=len(excluded),
        llm_calls=0, chart_count=len(list(reports_root.glob('*.png'))),
        sources=[{'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                 for path in inputs],
        tenure_basis='Calendar month of continuous MPC service; joining month is month 0.',
        averages='Speech counts / inclusive service months within corpus calendar-year range, through latest speech month, * 12.',
        cohort_average='Unweighted mean of member annualised speech rates; members with zero speeches included.',
    )
    (output_root / 'refresh_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Refresh and report combined saved speech classifications without LLM calls.')
    parser.add_argument('--candidate-csv', type=Path,
                        default=PROJECT_ROOT / 'outputs' / 'url_import_full' / 'speeches_enriched_candidate.csv')
    parser.add_argument('--classification-csv', type=Path, action='append')
    parser.add_argument('--membership-csv', type=Path, default=DEFAULT_MEMBERSHIP)
    parser.add_argument('--output-root', type=Path, default=PROJECT_ROOT / 'outputs' / 'combined_run')
    args = parser.parse_args()
    classification_csvs = args.classification_csv or [
        PROJECT_ROOT / 'outputs' / folder / 'mpc_speech_database_with_llm.csv'
        for folder in ('enriched_run', 'imported_speeches_run')]
    run(args.candidate_csv, classification_csvs, args.output_root, args.membership_csv)


if __name__ == '__main__':
    main()
