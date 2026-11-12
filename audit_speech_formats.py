from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pandas as pd
from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from import_speech_urls import download, html_speech_text, page_metadata, validate_url
from refresh_combined_reports import EXCLUDED_SLIDES_URL

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / 'outputs' / 'combined_run_taxonomy_v2' / 'mpc_speech_database_with_llm.csv'
DEFAULT_OUTPUT = ROOT / 'outputs' / 'speech_format_audit'
SLIDES = re.compile(r'\bslides?\b|\bslidepack\b|\bslide deck\b', re.I)


def words(text: str) -> list[str]:
    return re.findall(r'\b[a-z]+\b', text.lower())


def text_match_fraction(candidate: str, saved: str) -> float:
    tokens = words(candidate)
    sample = [' '.join(tokens[i:i + 12]) for i in range(0, len(tokens) - 11, 12)]
    normalised = ' '.join(words(saved))
    return sum(chunk in normalised for chunk in sample) / max(1, len(sample))


def pdf_features(path: Path) -> dict:
    reader = PdfReader(path)
    if not reader.pages:
        raise ValueError('PDF contains no pages.')
    texts = [page.extract_text() or '' for page in reader.pages]
    landscape = sum(float(page.mediabox.width) > float(page.mediabox.height)
                    for page in reader.pages) / len(texts)
    average = sum(len(words(text)) for text in texts) / len(texts)
    prose_pages = sum(
        len(words(text)) >= 180 and text.count('\u2022') < 3
        and sum(len(words(sentence)) >= 18
                for sentence in re.split(r'[.!?]\s+', text)) >= 3
        for text in texts[:8])
    return {'pages': len(texts), 'landscape_fraction': round(landscape, 3),
            'words_per_page': round(average, 1), 'text': '\n'.join(texts),
            'continuous_prose_pages_in_first_eight': prose_pages,
            'slide_like': len(texts) >= 3 and landscape >= 0.8 and average < 350,
            'prose_like': (landscape <= 0.2 and average >= 250)
                          or prose_pages >= (1 if len(texts) <= 2 else 2)}


def cached_download(url: str, cache: Path) -> Path:
    validate_url(url)
    path = cache / hashlib.sha256(url.encode()).hexdigest()
    if not path.exists():
        download(url, path)
    return path


def page_features(content: bytes, url: str) -> dict:
    soup = BeautifulSoup(content, 'html.parser')
    title, _ = page_metadata(soup)
    main = soup.select_one('main') or soup
    attachments = {}
    for anchor in main.select('a[href]'):
        href = urljoin(url, str(anchor['href']))
        parsed = urlsplit(href)
        if (parsed.hostname != 'www.bankofengland.co.uk'
                or not parsed.path.lower().endswith('.pdf')
                or not re.search(r'/files/(speech|paper|working-paper)/', parsed.path, re.I)):
            continue
        label = anchor.get_text(' ', strip=True)
        # References in the speech body are not necessarily accompanying documents.
        if anchor.find_parent(id='output') is not None:
            continue
        hint = label + ' ' + parsed.path.rsplit('/', 1)[-1]
        kind = 'slides' if SLIDES.search(hint) else (
            'other' if re.search(r'appendix|annex|\bcharts?\b', hint, re.I) else 'speech')
        attachments[href] = {'url': href, 'label': label, 'kind': kind}
    text = html_speech_text(BeautifulSoup(content, 'html.parser'))
    if not text:
        fragments = main.select('.page-content')
        if fragments:
            body = BeautifulSoup('<div id="output">' + ''.join(str(tag) for tag in fragments)
                                 + '</div>', 'html.parser')
            text = html_speech_text(body)
    return {'title': title, 'html_text': text, 'attachments': list(attachments.values()),
            'recording': bool(main.select('video, audio, iframe[src*="youtube"], iframe[src*="vimeo"]'))}


def audit_row(row: dict, cache: Path) -> dict:
    result = {key: row.get(key, '') for key in ['hyperlink', 'title', 'speaker', 'speech_date']}
    result.update(in_analysis=row.get('in_analysis', True), document_type='unclear',
                  classified_text_type='uncertain', speech_text_url='', slides_url='',
                  evidence='', review_required=True, error='', attachment_details='[]')
    url = row['hyperlink']
    try:
        page = cached_download(url, cache)
        direct_pdf = page.read_bytes()[:5] == b'%PDF-'
        features = ({'title': row.get('title', ''), 'html_text': '', 'recording': False,
                     'attachments': [{'url': url, 'label': row.get('title', ''), 'kind':
                                      'slides' if SLIDES.search(url + row.get('title', '')) else 'speech'}]}
                    if direct_pdf else page_features(page.read_bytes(), url))
        title = features['title'] or row.get('title', '')
        result['page_title'] = title
        html_text = features['html_text']
        html_words = len(words(html_text))
        has_prose = html_words >= 500
        html_has_prose = has_prose
        has_slides = False
        prose_matches = []
        slide_matches = []
        if html_has_prose:
            prose_matches.append(text_match_fraction(html_text, row.get('text', '')))
        speech_urls = [url] if has_prose else []
        slide_urls = []
        evidence = [f'HTML speech body: {html_words} words.']
        details = []
        for attachment in features['attachments']:
            detail = dict(attachment)
            explicit_slide = attachment['kind'] == 'slides'
            # Inspect all relevant attachments when the HTML does not provide a transcript,
            # and any explicitly labelled slide deck even alongside an HTML speech.
            if not html_has_prose or explicit_slide:
                pdf = pdf_features(cached_download(attachment['url'], cache))
                detail.update({k: v for k, v in pdf.items() if k != 'text'})
                detail['saved_text_match_fraction'] = round(
                    text_match_fraction(pdf['text'], row.get('text', '')), 3)
                explicit_slide = explicit_slide or (
                    SLIDES.search(title) is not None and len(features['attachments']) == 1)
                combined_notes = bool(re.search(
                    r'(?:notes|speech|remarks|transcript)\s+(?:and|&|\+)\s+slides',
                    title + ' ' + attachment['label'], re.I))
                if combined_notes:
                    has_prose = has_slides = True
                    speech_urls.append(attachment['url'])
                    slide_urls.append(attachment['url'])
                    detail['assessment'] = 'combined notes/speech and slides; review'
                elif explicit_slide or pdf['slide_like']:
                    has_slides = True
                    slide_urls.append(attachment['url'])
                    detail['assessment'] = 'explicit slides' if explicit_slide else 'slide-like layout; review'
                    slide_matches.append(detail['saved_text_match_fraction'])
                elif pdf['prose_like'] and attachment['kind'] != 'other':
                    has_prose = True
                    speech_urls.append(attachment['url'])
                    detail['assessment'] = 'prose-like PDF'
                    prose_matches.append(detail['saved_text_match_fraction'])
                else:
                    detail['assessment'] = 'uncertain PDF format'
            elif attachment['kind'] == 'speech':
                detail['assessment'] = 'HTML transcript available; PDF not inspected'
            details.append(detail)
        uncertain = any(d.get('assessment') in ('uncertain PDF format', 'slide-like layout; review',
                                               'combined notes/speech and slides; review')
                        for d in details)
        if has_prose and has_slides:
            result['document_type'] = 'speech + slides'
        elif has_prose:
            result['document_type'] = 'speech text'
        elif has_slides:
            result['document_type'] = 'slides only'
        elif features['recording']:
            result['document_type'] = 'recording only / no text confirmed'
        result['speech_text_url'] = '; '.join(dict.fromkeys(speech_urls))
        result['slides_url'] = '; '.join(dict.fromkeys(slide_urls))
        if SLIDES.search(title):
            evidence.append('Page title explicitly mentions slides.')
        for detail in details:
            evidence.append(f'{detail["label"] or detail["url"]}: {detail.get("assessment", "")}'
                            + (f'; {detail["pages"]} pages, landscape={detail["landscape_fraction"]}, '
                               f'words/page={detail["words_per_page"]}' if 'pages' in detail else ''))
        if result['in_analysis']:
            if result['document_type'] == 'slides only':
                result['classified_text_type'] = 'slides'
            elif result['document_type'] == 'speech text':
                result['classified_text_type'] = 'prose (format inferred)'
            elif result['document_type'] == 'speech + slides':
                prose_match = max(prose_matches, default=0)
                slide_match = max(slide_matches, default=0)
                evidence.append(f'12-word block matches in saved text: prose={prose_match:.0%}, '
                                f'slides={slide_match:.0%}.')
                if prose_match >= 0.7 and slide_match < 0.7:
                    result['classified_text_type'] = 'prose (source matched)'
                elif slide_match >= 0.7 and prose_match < 0.7:
                    result['classified_text_type'] = 'slides (source matched)'
                elif prose_match >= 0.7 and slide_match >= 0.7:
                    result['classified_text_type'] = 'speech + slides / overlapping text'
        else:
            result['classified_text_type'] = 'not classified (excluded)'
        result['review_required'] = (uncertain or result['document_type'] not in
                                     ('speech text', 'speech + slides')
                                     or result['classified_text_type'] in
                                     ('uncertain', 'slides (source matched)',
                                      'speech + slides / overlapping text'))
        result['evidence'] = ' '.join(evidence)
        result['attachment_details'] = json.dumps(details)
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired, PdfReadError) as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        print(f'Audit error: {url}: {result["error"]}', flush=True)
    return result


def run(input_csv: Path, output_root: Path, workers: int = 4, recheck_review: bool = False) -> None:
    if workers < 1 or workers > 4:
        raise ValueError('Use between 1 and 4 download workers.')
    source = pd.read_csv(input_csv, dtype=str, keep_default_na=False)
    if not source.hyperlink.is_unique:
        raise ValueError('Audit input has duplicate hyperlinks.')
    rows = source.assign(in_analysis=True).to_dict('records')
    if EXCLUDED_SLIDES_URL not in set(source.hyperlink):
        rows.append({'hyperlink': EXCLUDED_SLIDES_URL, 'in_analysis': False,
                     'title': 'Slides from Andy Haldane at the Deans lecture', 'speaker': 'Andy Haldane'})
    cache = output_root / 'downloads'
    cache.mkdir(parents=True, exist_ok=True)
    previous = None
    if recheck_review:
        previous = pd.read_csv(output_root / 'speech_format_audit.csv', keep_default_na=False)
        if set(previous.hyperlink) != {row['hyperlink'] for row in rows}:
            raise ValueError('Previous audit does not match the current corpus.')
        targets = set(previous.loc[
            previous.review_required | previous.document_type.ne('speech text'), 'hyperlink'])
        rows = [row for row in rows if row['hyperlink'] in targets]
        if not rows:
            print('No nonstandard or flagged rows to recheck.', flush=True)
            return
    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for index, result in enumerate(executor.map(lambda row: audit_row(row, cache), rows), 1):
            results.append(result)
            if index % 25 == 0:
                pd.DataFrame(results).to_csv(output_root / 'audit_progress.csv', index=False)
                print(f'Audited {index}/{len(rows)} pages.', flush=True)
    table = pd.DataFrame(results)
    if previous is not None:
        table = pd.concat([previous.loc[~previous.hyperlink.isin(table.hyperlink)], table],
                          ignore_index=True)
    manual_path = ROOT / 'speech_format_manual_reviews.csv'
    if manual_path.exists():
        manual = pd.read_csv(manual_path, keep_default_na=False)
        if not manual.hyperlink.is_unique:
            raise ValueError('Manual format reviews have duplicate URLs.')
        table['manual_review_evidence'] = table.hyperlink.map(
            manual.set_index('hyperlink').evidence).fillna('')
        for review in manual.to_dict('records'):
            mask = table.hyperlink.eq(review['hyperlink'])
            if not mask.any():
                raise ValueError(f'Manual review URL not in audit: {review["hyperlink"]}')
            for column in ['document_type', 'classified_text_type']:
                table.loc[mask, column] = review[column]
            if review['document_type'] == 'slides only':
                attachments = json.loads(table.loc[mask, 'attachment_details'].iloc[0])
                if len(attachments) != 1:
                    raise ValueError('Manual slides-only decision needs one unambiguous attachment.')
                table.loc[mask, 'slides_url'] = attachments[0]['url']
                table.loc[mask, 'speech_text_url'] = ''
            table.loc[mask, 'review_required'] = review['document_type'] == 'slides only'
            table.loc[mask, 'evidence'] = table.loc[mask, 'evidence'] + ' Manual check: ' + review['evidence']
    table.to_csv(output_root / 'speech_format_audit.csv', index=False, encoding='utf-8-sig')
    candidates = table.loc[table.review_required | table.document_type.ne('speech text')]
    candidates.to_csv(output_root / 'speech_format_review.csv', index=False, encoding='utf-8-sig')
    slides_in_analysis = table.loc[table.document_type.eq('slides only') & table.in_analysis]
    shortlist_path = output_root / 'slides_only_in_analysis.csv'
    if shortlist_path.exists():
        previous_shortlist = pd.read_csv(shortlist_path, dtype=str, keep_default_na=False)
        if 'exclude_from_analysis' in previous_shortlist.columns:
            if not previous_shortlist.hyperlink.is_unique:
                raise ValueError('Reviewed slide shortlist contains duplicate URLs.')
            if not set(previous_shortlist.hyperlink).issubset(set(slides_in_analysis.hyperlink)):
                raise ValueError('Audit changed the reviewed shortlist; preserve and reconcile decisions first.')
            slides_in_analysis = slides_in_analysis.copy()
            slides_in_analysis['exclude_from_analysis'] = slides_in_analysis.hyperlink.map(
                previous_shortlist.set_index('hyperlink').exclude_from_analysis).fillna('')
    slides_in_analysis.to_csv(output_root / 'slides_only_in_analysis.csv',
                             index=False, encoding='utf-8-sig')
    summary = {'audited_at_utc': datetime.now(timezone.utc).isoformat(),
               'input_csv': str(input_csv.resolve()),
               'input_sha256': hashlib.sha256(input_csv.read_bytes()).hexdigest(),
               'rows': len(table), 'document_types': table.document_type.value_counts().to_dict(),
               'review_rows': int(table.review_required.sum()),
               'slides_only_in_analysis': len(slides_in_analysis),
               'errors': int(table.error.ne('').sum()),
               'method': 'Public pages and relevant PDF attachments; format heuristics are not conclusive. '
                         'Mixed pages require saved-text matching or manual review. '
                         'Manual decisions in speech_format_manual_reviews.csv override format heuristics. '
                         'No source data changed.'}
    (output_root / 'audit_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    (output_root / 'audit_progress.csv').unlink(missing_ok=True)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Audit speech versus slide-only sources without changing analysis.')
    parser.add_argument('--input-csv', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--output-root', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--recheck-review', action='store_true',
                        help='Recheck only nonstandard/flagged rows from a completed audit.')
    args = parser.parse_args()
    run(args.input_csv, args.output_root, args.workers, args.recheck_review)
