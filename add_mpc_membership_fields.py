from __future__ import annotations

import argparse
import csv
import io
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pandas as pd

from quantify_mpc_speeches import DEFAULT_MEMBERSHIP, Membership, load_membership, name_key

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = PROJECT_ROOT / 'speeches.csv'
DEFAULT_OUTPUT = PROJECT_ROOT / 'speeches_enriched.csv'
SOURCE_COLUMNS = ['hyperlink', 'text', 'title', 'date']
NEW_COLUMNS = [
    'speaker', 'speaker_source', 'speech_date', 'year', 'mpc_status', 'mpc_member_type', 'mpc_role',
    'mpc_service_start', 'years_on_mpc', 'completed_years_on_mpc',
    'completed_months_on_mpc', 'review_flag',
]
TEXT_HEAD_CHARS = 600
DAYS_PER_YEAR = 365.25


def read_speeches(path: Path) -> tuple[pd.DataFrame, int]:
    """Read the speeches CSV by header name, tolerating empty trailing columns.

    A speech is a row with a hyperlink. Rows without one are continuation
    fragments (e.g. text that spilled over Excel's 32,767-character cell limit)
    and are skipped; their number is returned so the caller can report it.
    """
    csv.field_size_limit(2**31 - 1)
    raw = path.read_bytes()
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        # Excel's plain "CSV" save is Windows-1252, not UTF-8
        print(f'Warning: {path.name} is not UTF-8; reading as Windows-1252.')
        content = raw.decode('cp1252')
    with io.StringIO(content, newline='') as handle:
        reader = csv.reader(handle)
        header = [cell.strip().lower() for cell in next(reader, [])]
        missing = [column for column in SOURCE_COLUMNS if column not in header]
        if missing:
            raise ValueError(f'{path.name} is missing required columns: {missing}')
        columns = [column for column in header if column]
        if len(set(columns)) != len(columns):
            raise ValueError(f'{path.name} contains duplicate column names.')
        index = {column: header.index(column) for column in columns}
        records, skipped = [], 0
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            record = {column: (row[i] if i < len(row) else '') for column, i in index.items()}
            if not record['hyperlink'].strip().lower().startswith('http'):
                skipped += 1
                continue
            records.append(record)
    return pd.DataFrame(records, columns=columns), skipped


def apply_updates(speeches: pd.DataFrame, updates: pd.DataFrame) -> pd.DataFrame:
    """Replace complete rows by exact URL, without changing row order or either input."""
    if set(speeches.columns) != set(updates.columns):
        raise ValueError('Update columns must match the source columns for complete row replacement.')
    for label, frame in [('Source', speeches), ('Updates', updates)]:
        urls = frame['hyperlink']
        if urls.map(lambda value: not value.strip() or value != value.strip()).any():
            raise ValueError(f'{label} contains blank URLs or URLs with surrounding whitespace.')
        if urls.duplicated().any():
            raise ValueError(f'{label} contains duplicate URLs; updates require unique URLs.')
    unmatched = updates.loc[~updates['hyperlink'].isin(speeches['hyperlink']), 'hyperlink']
    if not unmatched.empty:
        raise ValueError(f'Update URLs not found in source: {unmatched.tolist()}')
    result = speeches.copy()
    replacement = updates.set_index('hyperlink')
    mask = result['hyperlink'].isin(replacement.index)
    columns = [column for column in result.columns if column != 'hyperlink']
    result.loc[mask, columns] = replacement.loc[result.loc[mask, 'hyperlink'], columns].to_numpy()
    return result


MISSING_TOKENS = {'', 'na', 'n/a', 'nan', 'none', 'null', '-'}
BY_MARKER = re.compile(
    r'\b(?:speech|remarks|slides|lecture|statement|presentation|given)\s+(?:given\s+)?by\s+(.{0,80})',
    re.I | re.S)


def is_missing(value: str) -> bool:
    return value.strip().lower() in MISSING_TOKENS


def parse_speech_date(value: str) -> date | None:
    value = value.strip()
    for pattern in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def speakers_in(text: str, aliases: dict[str, str]) -> set[str]:
    padded = f' {name_key(text)} '
    found = set()
    for key, speaker in aliases.items():
        if f' {key} ' in padded:
            found.add(speaker)
    return found


def identify_speaker(
    title: str, text: str, aliases: dict[str, str], hyperlink: str = '',
) -> tuple[str, str, str]:
    """Return (speaker, source, problem). Only known MPC-reference names are recognised."""
    head = text[:TEXT_HEAD_CHARS]
    marker = BY_MARKER.search(head)
    candidates = [('title', title)]
    if marker:
        candidates.append(('text', marker.group(1)))
    candidates.append(('text', head))
    for source, candidate in candidates:
        if is_missing(candidate):
            continue
        found = speakers_in(candidate, aliases)
        if len(found) == 1:
            return next(iter(found)), source, ''
        if len(found) > 1:
            return '', source, 'ambiguous_speaker'
    found = speakers_in(unquote(urlsplit(hyperlink).path.rsplit('/', 1)[-1]), aliases)
    if len(found) == 1:
        return next(iter(found)), 'url', ''
    if len(found) > 1:
        return '', 'url', 'ambiguous_speaker'
    return '', '', 'speaker_not_identified'


def service_start(periods: list[Membership], on: date) -> tuple[Membership, date] | None:
    """Find the period covering `on` and the start of the unbroken MPC service it belongs to."""
    ordered = sorted(periods, key=lambda period: period.start)
    chain_start = None
    previous = None
    for period in ordered:
        if previous is None or period.start > previous.end + timedelta(days=1):
            chain_start = period.start
        if period.start <= on <= period.end:
            return period, chain_start
        previous = period
    return None


def classify(speaker: str, speech_date: date | None, periods: dict[str, list[Membership]]) -> dict:
    result = {'mpc_status': 'unresolved', 'mpc_member_type': '', 'mpc_role': '', 'mpc_service_start': '',
              'years_on_mpc': '', 'completed_years_on_mpc': '',
              'completed_months_on_mpc': '', 'problem': ''}
    if not speaker:
        return result
    if speech_date is None:
        result['problem'] = 'missing_or_invalid_date'
        return result
    match = service_start(periods[speaker], speech_date)
    if match is None:
        result['mpc_status'] = 'outside_recorded_tenure'
        result['problem'] = 'speech_date_outside_mpc_tenure'
        return result
    period, start = match
    chain = [entry for entry in periods[speaker] if start <= entry.start <= period.start]
    if any(entry.date_basis == 'voting_window' for entry in chain):
        result.update(mpc_status=period.member_type, mpc_member_type=period.member_type,
                      mpc_role=period.role or ('External member' if period.member_type == 'external' else ''),
                      problem='membership_appointment_dates_unverified')
        return result
    completed_months = ((speech_date.year - start.year) * 12
                        + speech_date.month - start.month)
    if period.date_basis != 'appointment_month' and speech_date.day < start.day:
        completed_months -= 1
    if period.date_basis == 'appointment_month':
        years = completed_months / 12
        completed = completed_months // 12
    else:
        years = (speech_date - start).days / DAYS_PER_YEAR
        completed = speech_date.year - start.year - (
            (speech_date.month, speech_date.day) < (start.month, start.day))
    result.update(mpc_status=period.member_type, mpc_member_type=period.member_type,
                  mpc_role=period.role or ('External member' if period.member_type == 'external' else ''),
                  mpc_service_start=start.isoformat(), years_on_mpc=round(years, 2),
                  completed_years_on_mpc=completed, completed_months_on_mpc=completed_months)
    return result


def enrich(speeches: pd.DataFrame, membership_csv: Path = DEFAULT_MEMBERSHIP) -> pd.DataFrame:
    overlap = set(speeches.columns).intersection(NEW_COLUMNS)
    if overlap:
        raise ValueError(f'Input already contains enrichment columns: {sorted(overlap)}')
    aliases, periods = load_membership(membership_csv)
    rows = []
    for record in speeches.to_dict('records'):
        title = '' if is_missing(record['title']) else record['title']
        speaker, source, speaker_problem = identify_speaker(
            title, record['text'], aliases, record['hyperlink'])
        speech_date = parse_speech_date(record['date'])
        info = classify(speaker, speech_date, periods)
        problems = []
        if is_missing(record['text']):
            problems.append('missing_text')
        if is_missing(record['title']):
            problems.append('missing_title')
        if is_missing(record['date']):
            problems.append('missing_date')
        elif speech_date is None:
            problems.append('unparseable_date')
        if speaker_problem:
            problems.append(speaker_problem)
        if info['problem'] and info['problem'] != 'missing_or_invalid_date':
            problems.append(info['problem'])
        if info['mpc_member_type'] == 'internal' and not info['mpc_role']:
            problems.append('mpc_role_unassigned')
        rows.append({
            'speaker': speaker,
            'speaker_source': source,
            'speech_date': speech_date.isoformat() if speech_date else '',
            'year': speech_date.year if speech_date else '',
            **{key: info[key] for key in ('mpc_status', 'mpc_member_type', 'mpc_role', 'mpc_service_start',
                                           'years_on_mpc', 'completed_years_on_mpc',
                                           'completed_months_on_mpc')},
            'review_flag': ';'.join(dict.fromkeys(problems)),
        })
    new = pd.DataFrame(rows, columns=NEW_COLUMNS, index=speeches.index)
    return pd.concat([speeches, new], axis=1)


def run(
    input_csv: Path, output_csv: Path, membership_csv: Path = DEFAULT_MEMBERSHIP,
    updates_csv: Path | None = None,
) -> pd.DataFrame:
    protected = [input_csv, membership_csv]
    if updates_csv is not None:
        protected.append(updates_csv)
    if output_csv.resolve() in {path.resolve() for path in protected}:
        raise ValueError('Output path must differ from all input paths; inputs are never overwritten.')
    speeches, skipped = read_speeches(input_csv)
    if skipped:
        print(f'Warning: ignored {skipped} continuation row(s) with no hyperlink (likely text '
              f'that overflowed a spreadsheet cell).')
    if updates_csv is not None:
        updates, skipped_updates = read_speeches(updates_csv)
        if skipped or skipped_updates:
            raise ValueError('Cannot apply updates to malformed CSVs with skipped rows.')
        speeches = apply_updates(speeches, updates)
        print(f'Replaced {len(updates)} speech row(s) by exact URL.')
    enriched = enrich(speeches, membership_csv)
    enriched.to_csv(output_csv, index=False, encoding='utf-8-sig')
    print(f'Speeches: {len(enriched)}')
    print('mpc_status:', enriched['mpc_status'].value_counts().to_dict())
    flagged = enriched['review_flag'].ne('')
    print(f'Rows needing review: {int(flagged.sum())}')
    for flag, count in enriched.loc[flagged, 'review_flag'].value_counts().items():
        print(f'  {flag}: {count}')
    print(f'Wrote {output_csv}')
    return enriched


def main() -> None:
    parser = argparse.ArgumentParser(description='Add MPC membership fields to a speeches CSV.')
    parser.add_argument('--input-csv', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--output-csv', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--membership-csv', type=Path, default=DEFAULT_MEMBERSHIP)
    parser.add_argument('--updates-csv', type=Path,
                        help='Replace complete source rows using matching hyperlink values.')
    args = parser.parse_args()
    run(args.input_csv, args.output_csv, args.membership_csv, args.updates_csv)


if __name__ == '__main__':
    main()
