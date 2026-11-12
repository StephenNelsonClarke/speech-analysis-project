from __future__ import annotations

import argparse
import ast
import json
import re
import warnings
from dataclasses import dataclass
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from analyze_mpc_speeches import THEMES
from compare_keyword_and_llm_themes import normalise_theme

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_MEMBERSHIP = PROJECT_ROOT / 'mpc_membership.csv'
MEMBER_TYPES = ['internal', 'external', 'outside_recorded_tenure', 'unresolved']
THEME_COLUMNS = ['method', 'theme_role', 'theme_key', 'theme_label', 'speech_count']
ANNOTATION_COLUMNS = {
    'input_row', 'analysis_year', 'canonical_speaker', 'mpc_member_type', 'mpc_role',
    'mpc_membership_reason', 'mpc_membership_source', 'analysis_keyword_primary',
    'analysis_llm_primary', 'analysis_keyword_secondary', 'analysis_llm_secondary',
}


@dataclass(frozen=True)
class Membership:
    speaker: str
    member_type: str
    start: date
    end: date
    source_url: str
    date_basis: str = 'appointment'
    role: str = ''


def name_key(value: str) -> str:
    value = re.sub(r'^(?:(?:sir|dame|dr|professor|prof)\.?\s+)+', '', value.strip(), flags=re.I)
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


def iso_date(value: str) -> date:
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return date.fromisoformat(value)
    if re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}', value):
        return datetime.strptime(value, '%d/%m/%Y').date()
    raise ValueError(f'Expected an ISO date (YYYY-MM-DD) or day/month/year date, got {value!r}')


def membership_endpoint(value: str, end_of_month: bool, monthly: bool) -> date:
    if monthly and re.fullmatch(r'\d{4}-\d{2}', value):
        year, month = map(int, value.split('-'))
        day = monthrange(year, month)[1] if end_of_month else 1
        return date(year, month, day)
    parsed = iso_date(value)
    if monthly:
        day = monthrange(parsed.year, parsed.month)[1] if end_of_month else 1
        return date(parsed.year, parsed.month, day)
    return parsed


def load_membership(path: Path) -> tuple[dict[str, str], dict[str, list[Membership]]]:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    required = {'speaker', 'member_type', 'start_date', 'end_date', 'aliases', 'source_url'}
    if not required.issubset(frame.columns):
        raise ValueError(f'Membership reference is missing columns: {sorted(required - set(frame.columns))}')
    if frame.empty:
        raise ValueError('Membership reference contains no records.')
    aliases: dict[str, str] = {}
    periods: dict[str, list[Membership]] = {}
    for row in frame.to_dict('records'):
        speaker = row['speaker'].strip()
        if not speaker or row['member_type'] not in {'internal', 'external'} or not row['source_url'].strip():
            raise ValueError(f'Invalid membership record: {row}')
        date_basis = row.get('date_basis', 'appointment')
        if date_basis not in {'appointment', 'appointment_month', 'voting_window'}:
            raise ValueError(f'Invalid membership date basis for {speaker}: {date_basis!r}')
        start = membership_endpoint(row['start_date'], False, date_basis == 'appointment_month')
        end = membership_endpoint(row['end_date'], True, date_basis == 'appointment_month')
        if start > end:
            raise ValueError(f'Membership start is after end for {speaker}')
        role = row.get('mpc_role', '')
        if role == 'Internal members':
            role = 'Internal member'
        if role not in {'', 'Governor', 'Deputy Governor', 'Chief Economist',
                        'External member', 'Internal member'}:
            raise ValueError(f'Invalid MPC role for {speaker}: {role!r}')
        if row['member_type'] == 'external' and role not in {'', 'External member'}:
            raise ValueError(f'External membership must have the External member role for {speaker}.')
        period = Membership(speaker, row['member_type'], start, end, row['source_url'], date_basis, role)
        periods.setdefault(speaker, []).append(period)
        for alias in [speaker, *row['aliases'].split(';')]:
            key = name_key(alias)
            if not key:
                continue
            if key in aliases and aliases[key] != speaker:
                raise ValueError(f'Ambiguous membership alias: {alias!r}')
            aliases[key] = speaker
    for speaker, entries in periods.items():
        entries.sort(key=lambda entry: entry.start)
        for left, right in zip(entries, entries[1:]):
            if left.end >= right.start:
                raise ValueError(f'Overlapping membership periods for {speaker}')
    return aliases, periods


def theme_key(value: str, context: str) -> str:
    if not value.strip():
        return ''
    key = normalise_theme(value)
    if key is None:
        raise ValueError(f'{context}: unknown theme {value!r}')
    return key


def theme_list(value: str, context: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    if value.startswith('['):
        # pandas CSV exports Python list literals; the merged LLM column uses semicolons.
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError) as exc:
            raise ValueError(f'{context}: malformed theme list {value!r}') from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError(f'{context}: expected a list of theme strings')
        values = parsed
    else:
        values = re.split(r'[;,]', value)
    keys = [theme_key(item, context) for item in values]
    return list(dict.fromkeys(key for key in keys if key))


def count_rows(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return frame.groupby(columns, dropna=False, sort=True).size().reset_index(name='speech_count')


def build_reports(database: pd.DataFrame, membership_csv: Path) -> tuple[dict[str, pd.DataFrame], dict]:
    required = {'speech_id', 'speaker', 'year', 'date', 'top_themes',
                'llm_primary_theme', 'llm_secondary_themes'}
    if not required.issubset(database.columns):
        raise ValueError(f'Database is missing columns: {sorted(required - set(database.columns))}')
    if not {'primary_theme', 'primary_theme_label'}.intersection(database.columns):
        raise ValueError('Database needs primary_theme or primary_theme_label.')
    if database.empty:
        raise ValueError('Database contains no speech rows.')
    existing_annotations = ANNOTATION_COLUMNS.intersection(database.columns)
    if 'speech_date' in database.columns:
        existing_annotations -= {'mpc_member_type', 'mpc_role'}
    if existing_annotations:
        raise ValueError('Input already contains quantitative annotations. Use the original merged database.')
    aliases, periods = load_membership(membership_csv)
    frame = database.fillna('').astype(str).copy().reset_index(drop=True)
    issues: list[dict] = []
    annotations: list[dict] = []
    assignments: list[dict] = []
    duplicate_ids = set(frame.loc[frame['speech_id'].duplicated(keep=False), 'speech_id']) - {''}

    for index, row in frame.iterrows():
        row_number = index + 1

        def flag(issue: str, detail: str) -> None:
            issues.append({'input_row': row_number, 'speech_id': row['speech_id'],
                           'issue': issue, 'detail': detail})

        if not row['speech_id'].strip():
            flag('missing_speech_id', 'Row is counted, but has no speech identifier.')
        if row['speech_id'] in duplicate_ids:
            flag('duplicate_speech_id', 'Each input row is counted; no automatic deduplication.')
        raw_speaker = row['speaker'].strip()
        key = name_key(raw_speaker)
        canonical = aliases.get(key)
        speaker = canonical or raw_speaker or 'Unknown speaker'
        if not key or key in {'unknown', 'unknown speaker'}:
            speaker = 'Unknown speaker'
            flag('missing_speaker', 'Speaker is blank or unknown.')
        elif canonical is None:
            flag('unrecognised_speaker', f'No membership reference entry for {raw_speaker!r}.')

        year_value = row['year'].strip()
        year = 'Unknown'
        if re.fullmatch(r'\d{4}(?:\.0)?', year_value) and 1 <= int(float(year_value)) <= 9999:
            year = str(int(float(year_value)))
        else:
            flag('missing_or_invalid_year', f'Year {year_value!r} is reported in the Unknown bucket.')
        date_value = row.get('speech_date', row['date']).strip()
        speech_date = None
        if not date_value:
            flag('missing_date', 'Date-specific MPC membership cannot be determined.')
        else:
            try:
                speech_date = iso_date(date_value)
            except ValueError as exc:
                flag('invalid_date', str(exc))
        date_year_conflict = speech_date is not None and year != 'Unknown' and str(speech_date.year) != year
        if date_year_conflict:
            flag('date_year_conflict', 'Speech date and supplied year disagree; membership is unresolved.')

        member_type, role, reason, source = 'unresolved', '', '', ''
        if canonical is None:
            reason = 'missing_or_unrecognised_speaker'
        elif speech_date is None:
            reason = 'missing_or_invalid_date'
        elif date_year_conflict:
            reason = 'date_year_conflict'
        else:
            match = next((entry for entry in periods[canonical]
                          if entry.start <= speech_date <= entry.end), None)
            if match:
                member_type, reason, source = match.member_type, 'matched_dated_membership', match.source_url
                role = match.role or ('External member' if match.member_type == 'external' else '')
                if match.date_basis == 'appointment_month':
                    reason = 'matched_monthly_appointment'
                elif match.date_basis == 'voting_window':
                    reason = 'matched_confirmed_voting_window'
                    flag('membership_appointment_dates_unverified',
                         'Membership confirmed within voting window; exact appointment dates remain unverified.')
                if match.member_type == 'internal' and not role:
                    flag('mpc_role_unassigned', 'Internal MPC role is blank for review.')
            else:
                member_type, reason = 'outside_recorded_tenure', 'date_outside_reference_periods'
                flag('outside_recorded_tenure', 'Date is outside the recorded MPC terms; check reference coverage.')

        supplied_member_type = row.get('mpc_member_type', '')
        if 'mpc_status' in frame.columns and not supplied_member_type:
            supplied_member_type = row['mpc_status']
        if 'mpc_member_type' in frame.columns and supplied_member_type != member_type:
            raise ValueError(f'Input row {row_number}: enriched MPC membership disagrees with '
                             'the dated reference. Re-enrich the dataset before reporting.')
        if 'mpc_role' in frame.columns and row['mpc_role'] != role:
            raise ValueError(f'Input row {row_number}: enriched MPC role disagrees with '
                             'the dated reference. Re-enrich the dataset before reporting.')

        context = f'Input row {row_number} ({row["speech_id"]})'
        primary = theme_key(row.get('primary_theme', ''), context)
        label_primary = theme_key(row.get('primary_theme_label', ''), context)
        if primary and label_primary and primary != label_primary:
            raise ValueError(f'{context}: keyword primary_theme and primary_theme_label disagree.')
        keyword_primary = primary or label_primary
        llm_primary = theme_key(row['llm_primary_theme'], context)
        keyword_top = theme_list(row['top_themes'], context)
        llm_secondary = theme_list(row['llm_secondary_themes'], context)
        annotation = {
            'input_row': row_number, 'analysis_year': year, 'canonical_speaker': speaker,
            'mpc_member_type': member_type, 'mpc_role': role, 'mpc_membership_reason': reason,
            'mpc_membership_source': source,
            'analysis_keyword_primary': keyword_primary, 'analysis_llm_primary': llm_primary,
            'analysis_keyword_secondary': json.dumps([key for key in keyword_top if key != keyword_primary]),
            'analysis_llm_secondary': json.dumps([key for key in llm_secondary if key != llm_primary]),
        }
        annotations.append(annotation)
        for method, main, additional in [
            ('keyword', keyword_primary, keyword_top), ('llm', llm_primary, llm_secondary)
        ]:
            base = {'input_row': row_number, 'year': year, 'speaker': speaker,
                    'mpc_member_type': member_type, 'mpc_role': role, 'method': method}
            assignments.append({**base, 'theme_role': 'primary', 'theme_key': main or 'unclassified'})
            if not main:
                flag(f'missing_{method}_primary', 'Reported as unclassified; secondary counts excluded.')
                continue
            for secondary in additional:
                if secondary != main:
                    assignments.append({**base, 'theme_role': 'secondary', 'theme_key': secondary})
        if keyword_primary and not keyword_top:
            flag('missing_keyword_top_themes', 'No keyword secondary themes available.')

    annotated = pd.concat([frame.drop(columns=['mpc_member_type', 'mpc_role'], errors='ignore'),
                           pd.DataFrame(annotations)], axis=1)
    theme_rows = pd.DataFrame(assignments)
    overall = count_rows(theme_rows, ['method', 'theme_role', 'theme_key'])
    grid = pd.MultiIndex.from_product(
        [['keyword', 'llm'], ['primary', 'secondary'], list(THEMES)],
        names=['method', 'theme_role', 'theme_key'],
    )
    zeros = pd.DataFrame(index=grid).reset_index()
    overall = zeros.merge(overall, how='outer', on=['method', 'theme_role', 'theme_key']).fillna({'speech_count': 0})
    overall['speech_count'] = overall['speech_count'].astype(int)
    overall['theme_label'] = overall['theme_key'].map(
        {**{key: meta['label'] for key, meta in THEMES.items()}, 'unclassified': 'Unclassified'}
    )
    overall = overall[THEME_COLUMNS]
    overall['share_of_all_speeches_pct'] = (100 * overall['speech_count'] / len(frame)).round(2)
    reports = {
        'annotated_speeches': annotated,
        'speeches_by_year': count_rows(annotated, ['analysis_year']).rename(columns={'analysis_year': 'year'}),
        'speeches_by_speaker': count_rows(annotated, ['canonical_speaker']).rename(columns={'canonical_speaker': 'speaker'}),
        'speeches_by_speaker_year': count_rows(annotated, ['canonical_speaker', 'analysis_year']).rename(
            columns={'canonical_speaker': 'speaker', 'analysis_year': 'year'}),
        'theme_counts': overall,
        'speeches_by_mpc_member_type': count_rows(annotated, ['mpc_member_type']).set_index('mpc_member_type')
            .reindex(MEMBER_TYPES, fill_value=0).reset_index(),
        'speeches_by_mpc_member_type_year': count_rows(annotated, ['mpc_member_type', 'analysis_year'])
            .rename(columns={'analysis_year': 'year'}),
        'speeches_by_mpc_role': count_rows(annotated, ['mpc_role']),
        'theme_counts_by_mpc_role': count_rows(theme_rows, ['mpc_role', 'method', 'theme_role', 'theme_key']),
        'data_quality_issues': pd.DataFrame(issues, columns=['input_row', 'speech_id', 'issue', 'detail']),
    }
    for dimension in ['year', 'speaker', 'mpc_member_type', 'mpc_role']:
        table = count_rows(theme_rows, [dimension, 'method', 'theme_role', 'theme_key'])
        table['theme_label'] = table['theme_key'].map(
            {**{key: meta['label'] for key, meta in THEMES.items()}, 'unclassified': 'Unclassified'}
        )
        reports[f'theme_counts_by_{dimension}'] = table[[dimension, *THEME_COLUMNS]]
    coverage = {}
    for method in ['keyword', 'llm']:
        primary = annotated[f'analysis_{method}_primary'].ne('')
        secondary = annotated[f'analysis_{method}_secondary'].map(json.loads).map(bool)
        coverage[method] = {
            'classified_primary_rows': int(primary.sum()),
            'unclassified_primary_rows': int((~primary).sum()),
            'rows_with_secondary_themes': int((primary & secondary).sum()),
        }
    summary = {
        'speech_rows': len(frame),
        'counting_unit': 'One input CSV row; duplicates are flagged, not removed.',
        'duplicate_id_groups': len(duplicate_ids),
        'rows_with_quality_issues': len({item['input_row'] for item in issues}),
        'quality_issue_counts': reports['data_quality_issues']['issue'].value_counts().to_dict(),
        'theme_coverage': coverage,
        'mpc_member_type_counts': dict(zip(
            reports['speeches_by_mpc_member_type']['mpc_member_type'],
            reports['speeches_by_mpc_member_type']['speech_count'],
        )),
        'membership_reference': str(membership_csv.resolve()),
        'secondary_counting': 'Each non-primary theme counted at most once per row and method. '
                              'Rows without a valid primary classification are excluded from secondary counts.',
    }
    return reports, summary


def run_analysis(database_csv: Path, output_root: Path, membership_csv: Path = DEFAULT_MEMBERSHIP) -> dict:
    database_csv, output_root, membership_csv = (
        database_csv.resolve(), output_root.resolve(), membership_csv.resolve()
    )
    output_paths = {output_root / f'{name}.csv' for name in [
        'annotated_speeches', 'speeches_by_year', 'speeches_by_speaker', 'speeches_by_speaker_year',
        'theme_counts', 'speeches_by_mpc_member_type', 'speeches_by_mpc_member_type_year',
        'speeches_by_mpc_role', 'data_quality_issues', 'theme_counts_by_mpc_role',
        'theme_counts_by_year', 'theme_counts_by_speaker',
        'theme_counts_by_mpc_member_type', 'membership_reference_used',
    ]}
    if {database_csv, membership_csv}.intersection(output_paths | {output_root / 'quantitative_summary.json'}):
        raise ValueError('Output paths would overwrite an input file. Choose a separate output folder.')
    database = pd.read_csv(database_csv, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    reports, summary = build_reports(database, membership_csv)
    summary['database_csv'] = str(database_csv)
    summary['output_root'] = str(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    for name, report in reports.items():
        report.to_csv(output_root / f'{name}.csv', index=False)
    pd.read_csv(membership_csv, dtype=str, keep_default_na=False).to_csv(
        output_root / 'membership_reference_used.csv', index=False
    )
    (output_root / 'quantitative_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    if summary['rows_with_quality_issues']:
        warnings.warn(
            f'{summary["rows_with_quality_issues"]} of {summary["speech_rows"]} speech rows have quality flags. '
            f'See {output_root / "data_quality_issues.csv"}.', stacklevel=2
        )
    print(f'Quantified {len(database)} speech rows. Reports saved to {output_root}')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Quantify speeches by year, themes, speaker and dated MPC membership.')
    parser.add_argument('--database-csv', type=Path, required=True, help='Explicit merged speech database with LLM columns.')
    parser.add_argument('--output-root', type=Path, required=True, help='Separate directory for quantitative reports.')
    parser.add_argument('--membership-csv', type=Path, default=DEFAULT_MEMBERSHIP,
                        help='Dated membership reference, with inclusive ISO start/end dates.')
    args = parser.parse_args()
    run_analysis(args.database_csv, args.output_root, args.membership_csv)


if __name__ == '__main__':
    main()
