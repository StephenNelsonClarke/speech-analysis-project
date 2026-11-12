from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pandas as pd
from bs4 import BeautifulSoup
from pypdf import PdfReader

from add_mpc_membership_fields import classify, enrich, is_missing, parse_speech_date
from quantify_mpc_speeches import DEFAULT_MEMBERSHIP, load_membership, name_key

PROJECT_ROOT = Path(__file__).resolve().parent


def validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'www.bankofengland.co.uk'
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError(f'Expected an HTTPS www.bankofengland.co.uk URL, got {url!r}')


def download(url: str, destination: Path) -> None:
    validate_url(url)
    result = subprocess.run(
        ['curl.exe', '--fail', '--location', '--max-time', '120', '--output',
         str(destination.resolve()), url], capture_output=True, text=True, timeout=150)
    if result.returncode:
        raise RuntimeError(f'Download failed for {url}: {result.stderr.strip()}')
    if not destination.exists() or not destination.stat().st_size:
        raise ValueError(f'Download produced an empty file for {url}')


def page_metadata(soup: BeautifulSoup) -> tuple[str, str]:
    title_tag = soup.find('title')
    title = re.sub(r'\s*\|\s*Bank of England.*$', '',
                   title_tag.get_text(' ', strip=True) if title_tag else '', flags=re.I)
    published = soup.select_one('.published-date')
    raw_date = published.get_text(' ', strip=True) if published else ''
    match = re.search(r'\b(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b', raw_date)
    date = ''
    if match:
        for fmt in ('%d %B %Y', '%d %b %Y'):
            try:
                date = datetime.strptime(match.group(1), fmt).date().isoformat()
                break
            except ValueError:
                continue
    # Restrict fallback to the speech main content: navigation includes dates of other speeches.
    if not date:
        main = soup.select_one('main')
        time = main.select_one('time[datetime]') if main else None
        if time:
            candidate = str(time.get('datetime', ''))[:10]
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', candidate) and parse_speech_date(candidate):
                date = candidate
    return title, date


def html_speech_text(soup: BeautifulSoup) -> str:
    body = soup.select_one('#output')
    if body is None:
        return ''
    for unwanted in body.select(
        'script, style, nav, form, button, input, select, textarea, '
        '[role="navigation"], [role="toolbar"], .modal__close'
    ):
        unwanted.decompose()
    dialogs = body.select('[role="dialog"], .modal')
    outside = BeautifulSoup(str(body), 'html.parser')
    for dialog in outside.select('[role="dialog"], .modal'):
        dialog.decompose()
    outside_blocks = {' '.join(block.get_text(' ', strip=True).split())
                      for block in outside.select('p, li')}
    for dialog in dialogs:
        if dialog.parent is None:
            continue
        blocks = dialog.select('p, li')
        if blocks and all(' '.join(block.get_text(' ', strip=True).split()) in outside_blocks
                          for block in blocks):
            dialog.decompose()
    for block in body.select('p, li, h1, h2, h3, h4, h5, h6, tr'):
        block.insert_before('\n')
        block.insert_after('\n')
    for br in body.select('br'):
        br.replace_with('\n')
    text = body.get_text(' ', strip=False)
    text = '\n'.join(' '.join(line.split()) for line in text.splitlines())
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def clean_pdf_pages(pages: list[str]) -> str:
    """Remove repeated edge lines, not matching passages in the body."""
    lines = [[line.strip() for line in page.splitlines() if line.strip()] for page in pages]
    normalise = lambda line: ' '.join(line.split()).casefold()
    occurrences: Counter[str] = Counter()
    for page in lines:
        occurrences.update({normalise(line) for line in page[:3] + page[-3:]
                            if len(line) >= 12 and not re.fullmatch(r'[\d\s.,%+-]+', line)})
    repeated = {line for line, count in occurrences.items()
                if count >= max(2, (len(pages) + 1) // 2)}
    cleaned = []
    for page_number, page in enumerate(lines, 1):
        edge_indices = set(range(min(3, len(page)))) | set(range(max(0, len(page)-3), len(page)))
        remove = {i for i, line in enumerate(page)
                  if (i in edge_indices and normalise(line) in repeated)
                  or re.fullmatch(r'all speeches are available online at\s+www\.bankofengland\.co\.uk/\S+',
                                  normalise(line))}
        for i, line in enumerate(page):
            explicit_page = re.fullmatch(r'page\s+\d+\s*(?:of\s+\d+)?', line, flags=re.I)
            adjacent_header = any(abs(i - removed) <= 2 for removed in remove)
            if (i in edge_indices and explicit_page) or (line == str(page_number) and adjacent_header):
                remove.add(i)
        cleaned.append('\n'.join(line for i, line in enumerate(page) if i not in remove))
    return '\n\n'.join(page for page in cleaned if page).strip()


def extract_clean_pdf_text(path: Path) -> str:
    reader = PdfReader(path)
    return clean_pdf_pages([page.extract_text() or '' for page in reader.pages])


def speech_pdf(soup: BeautifulSoup, url: str) -> str:
    parsed = urlsplit(url)
    parts = parsed.path.strip('/').split('/')
    year_scope = '/files/speech/' + parts[1] + '/' if len(parts) >= 2 else '/files/speech/'
    scope = '/files/speech/' + '/'.join(parts[1:3]) + '/' if len(parts) >= 4 else year_scope
    title, _ = page_metadata(soup)
    def title_key(value: str) -> str:
        return name_key(re.split(r'\s*[-\u2212\u2013]\s*(?:speech|remarks|slides|presentation)\b',
                                value, flags=re.I)[0])

    page_title_key = title_key(title)
    candidates = []
    for anchor in soup.select('a[href]'):
        href = urljoin(url, str(anchor['href']))
        attachment_path = urlsplit(href).path.lower()
        if (not attachment_path.endswith('.pdf')
                or not any(f'/files/{kind}/{parts[1]}/' in attachment_path
                           for kind in ('speech', 'paper'))):
            continue
        label = anchor.get_text(' ', strip=True)
        if re.search(r'slides?|\bcharts?\b|appendix|annex|transcript|q\s*&\s*a', label, re.I):
            continue
        if re.search(r'slides?|\bcharts?\b|appendix|annex|transcript', urlsplit(href).path, re.I):
            continue
        matches_title = bool(page_title_key) and title_key(label) == page_title_key
        matches_slug = urlsplit(href).path.rsplit('/', 1)[-1] == parts[-1] + '.pdf'
        if matches_title or matches_slug or (
            year_scope in href and re.search(r'\b(download speech|speech|remarks|full text|pdf)\b', label, re.I)
        ) or (scope in href and re.search(r'\bdownload\b', label, re.I)):
            validate_url(href)
            candidates.append(href)
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) > 1:
        raise ValueError('Multiple candidate speech PDFs; attachment requires manual review.')
    if not candidates:
        raise ValueError('No substantive HTML speech text or unambiguous speech PDF; may be slides-only.')
    return candidates[0]


def extract_url(row: dict[str, str], raw_root: Path, reuse_downloads: bool = False) -> dict[str, str]:
    url = row['hyperlink'].strip()
    validate_url(url)
    key = hashlib.sha256(url.encode()).hexdigest()
    path = raw_root / f'{key}.html'
    if not reuse_downloads or not path.exists():
        download(url, path)
    soup = BeautifulSoup(path.read_bytes(), 'html.parser')
    title, date = page_metadata(soup)
    text = html_speech_text(soup)
    text_url, text_type, text_path = url, 'html', path
    if len(re.findall(r'\b\w+\b', text)) < 80:
        text_url = speech_pdf(soup, url)
        text_path = raw_root / f'{key}.pdf'
        if not reuse_downloads or not text_path.exists():
            download(text_url, text_path)
        text = extract_clean_pdf_text(text_path)
        text_type = 'pdf'
    if len(re.findall(r'\b\w+\b', text)) < 80:
        raise ValueError('Extracted fewer than 80 words; review for scanned PDF or non-speech material.')
    flags = []
    supplied_title = row.get('title', '')
    supplied_date = row.get('date', '')
    if not is_missing(supplied_title):
        title = supplied_title
    if not is_missing(supplied_date):
        parsed = parse_speech_date(supplied_date)
        if parsed is None:
            raise ValueError(f'Invalid supplied speech date: {supplied_date!r}')
        if date and date != parsed.isoformat():
            flags.append('supplied_date_differs_from_page')
        date = parsed.isoformat()
    return {
        'hyperlink': url, 'text': text, 'title': title, 'date': date,
        'import_page_path': str(path.resolve()), 'import_text_path': str(text_path.resolve()),
        'import_text_url': text_url, 'import_text_type': text_type,
        'import_review_flag': ';'.join(flags),
    }


def run(
    urls_csv: Path, base_csv: Path, output_root: Path, sample_size: int = 10,
    reuse_downloads: bool = False,
) -> dict:
    if sample_size < 1:
        raise ValueError('Sample size must be positive.')
    output_root = output_root.resolve()
    if any(path.resolve().is_relative_to(output_root) for path in (urls_csv, base_csv, DEFAULT_MEMBERSHIP)):
        raise ValueError('Output directory must be separate from input files.')
    urls = pd.read_csv(urls_csv, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    base = pd.read_csv(base_csv, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    if 'hyperlink' not in urls or 'hyperlink' not in base:
        raise ValueError('Both input CSVs require a hyperlink column.')
    urls['hyperlink'] = urls.hyperlink.str.strip()
    for url in urls.hyperlink:
        validate_url(url)
    if not base.hyperlink.is_unique:
        raise ValueError('Curated input has duplicate URLs; resolve them before importing.')
    duplicate_rows = int(urls.hyperlink.duplicated().sum())
    urls = urls.drop_duplicates('hyperlink')
    new = urls.loc[~urls.hyperlink.isin(base.hyperlink)].reset_index(drop=True)
    count = min(sample_size, len(new))
    positions = [round(i * (len(new) - 1) / (count - 1)) for i in range(count)] if count > 1 else [0][:count]
    selected = new.iloc[positions]
    raw_root = output_root / 'raw'
    raw_root.mkdir(parents=True, exist_ok=True)
    selected.to_csv(output_root / 'selected_urls.csv', index=False, encoding='utf-8-sig')
    aliases, periods = load_membership(DEFAULT_MEMBERSHIP)
    imported, diagnostics = [], []
    for row in selected.to_dict('records'):
        url = row['hyperlink']
        print(f'Importing {len(diagnostics) + 1}/{count}: {url}', flush=True)
        try:
            extracted = extract_url(row, raw_root, reuse_downloads=reuse_downloads)
            enriched = enrich(pd.DataFrame([extracted])).iloc[0].to_dict()
            supplied_speaker = row.get('speaker', '')
            if not is_missing(supplied_speaker):
                canonical = aliases.get(name_key(supplied_speaker))
                if enriched['speaker'] and canonical and enriched['speaker'] != canonical:
                    enriched['import_review_flag'] += ';supplied_speaker_differs_from_extraction'
                enriched['speaker'] = canonical or supplied_speaker
                enriched['speaker_source'] = 'supplied'
                info = classify(canonical or '', parse_speech_date(enriched['date']), periods)
                enriched.update({key: value for key, value in info.items() if key != 'problem'})
                flags = [flag for flag in enriched['review_flag'].split(';')
                         if flag and flag not in {'speaker_not_identified', 'ambiguous_speaker',
                                                 'speech_date_outside_mpc_tenure'}]
                if not canonical:
                    flags.append('unrecognised_speaker')
                elif info['problem']:
                    flags.append(info['problem'])
                if info['mpc_member_type'] == 'internal' and not info['mpc_role']:
                    flags.append('mpc_role_unassigned')
                enriched['review_flag'] = ';'.join(dict.fromkeys(flags))
            enriched['import_review_flag'] = enriched['import_review_flag'].strip(';')
            imported.append(enriched)
            diagnostics.append({'hyperlink': url, 'status': 'extracted',
                                'text_characters': len(enriched['text']),
                                'text_type': enriched['import_text_type'],
                                'detail': ';'.join(filter(None, [enriched['review_flag'],
                                                                enriched['import_review_flag']]))})
            print(f'  {len(enriched["text"])} characters; {enriched["import_text_type"]}; '
                  f'{enriched["speaker"]}; flags: {diagnostics[-1]["detail"]}', flush=True)
        except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            diagnostics.append({'hyperlink': url, 'status': 'failed', 'text_characters': 0,
                                'text_type': '', 'detail': str(exc)})
            print(f'  FAILED: {exc}', flush=True)
    new_frame = pd.DataFrame(imported)
    candidate = pd.concat([base, new_frame], ignore_index=True).fillna('')
    candidate_path = output_root / 'speeches_enriched_candidate.csv'
    candidate.to_csv(candidate_path, index=False, encoding='utf-8-sig')
    pd.testing.assert_frame_equal(
        pd.read_csv(candidate_path, dtype=str, keep_default_na=False).iloc[:len(base)][base.columns], base)
    pd.DataFrame(diagnostics, columns=['hyperlink', 'status', 'text_characters', 'text_type', 'detail']).to_csv(
        output_root / 'import_diagnostics.csv', index=False, encoding='utf-8-sig')
    summary = {'selected': count, 'extracted': len(imported), 'failed': count-len(imported),
               'base_rows': len(base), 'candidate_rows': len(candidate),
               'existing_urls_skipped': len(urls)-len(new), 'duplicate_urls_skipped': duplicate_rows,
               'input_urls': str(urls_csv.resolve()), 'curated_input': str(base_csv.resolve()),
               'candidate_csv': str(candidate_path),
               'classification': 'No keyword or LLM classification performed.'}
    (output_root / 'import_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Trial import of speech URLs into a separate enriched candidate CSV.')
    parser.add_argument('--urls-csv', type=Path, required=True)
    parser.add_argument('--base-csv', type=Path, default=PROJECT_ROOT / 'speeches_enriched.csv')
    parser.add_argument('--output-root', type=Path, default=PROJECT_ROOT / 'outputs' / 'url_import_trial')
    parser.add_argument('--sample-size', type=int, default=10)
    parser.add_argument('--reuse-downloads', action='store_true',
                        help='Re-extract existing saved downloads without fetching them again.')
    args = parser.parse_args()
    run(args.urls_csv, args.base_csv, args.output_root, args.sample_size, args.reuse_downloads)


if __name__ == '__main__':
    main()
