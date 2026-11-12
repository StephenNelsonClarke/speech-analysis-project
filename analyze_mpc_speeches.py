from __future__ import annotations

import argparse
import json
import os
import re
from collections import OrderedDict
from datetime import datetime
from html import unescape
from pathlib import Path

import numpy as np
import pandas as pd
from html.parser import HTMLParser
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE_ROOT = Path(
    os.environ.get(
        'MPC_SPEECH_SOURCE_ROOT',
        str(ROOT),
    )
)
DEFAULT_OUTPUT_ROOT = Path(os.environ.get('MPC_SPEECH_OUTPUT_ROOT', str(ROOT / 'outputs')))

THEMES = OrderedDict([
    ('inflation_and_prices', {
        'label': 'Inflation & prices',
        'keywords': [
            'inflation', 'price inflation', 'cpi', 'rpi', 'consumer prices',
            'food prices', 'energy prices', 'gas prices', 'goods prices',
            'prices', 'cost of living', 'inflation target', 'inflation outlook',
            'real incomes', 'price stability'
        ]
    }),
    ('monetary_policy_rates', {
        'label': 'Monetary policy & rates',
        'keywords': [
            'monetary policy', 'bank rate', 'interest rates', 'rate path', 'policy rate',
            'tightening', 'easing', 'quantitative tightening', 'quantitative easing',
            'qt', 'qe', 'real rates', 'policy stance', 'short-term rates', 'long-term rates'
        ]
    }),
    ('growth_output', {
        'label': 'Growth & output',
        'keywords': [
            'growth', 'gdp', 'economic activity', 'output gap', 'output', 'recession',
            'business investment', 'domestic demand', 'economic growth', 'household spending',
            'gross domestic product', 'investment', 'activity'
        ]
    }),
    ('labour_market', {
        'label': 'Labour market',
        'keywords': [
            'labour market', 'labour force', 'employment', 'unemployment', 'wages',
            'earnings', 'vacancies', 'job market', 'hours worked', 'workforce',
            'economic inactivity', 'participation rate', 'productivity'
        ]
    }),
    ('financial_conditions', {
        'label': 'Financial conditions',
        'keywords': [
            'financial conditions', 'credit spreads', 'bond yields', 'mortgage rates',
            'bank lending', 'credit conditions', 'market pricing', 'term premia',
            'asset prices', 'house prices', 'equity prices', 'borrowing costs'
        ]
    }),
    ('global_economy_trade', {
        'label': 'Global economy & trade',
        'keywords': [
            'global economy', 'international economy', 'trade', 'global demand',
            'supply chains', 'world economy', 'euro area', 'us economy', 'imports',
            'exports', 'geopolitics', 'commodity prices', 'global inflation'
        ]
    }),
    ('fiscal_policy_public_finances', {
        'label': 'Fiscal policy & public finances',
        'keywords': [
            'fiscal policy', 'government spending', 'public finances', 'tax', 'budget',
            'government borrowing', 'taxation', 'public debt', 'fiscal support',
            'budget deficit', 'public spending'
        ]
    }),
    ('financial_stability_regulation', {
        'label': 'Financial stability & regulation',
        'keywords': [
            'financial stability', 'banking system', 'liquidity', 'capital', 'leverage',
            'stress tests', 'supervision', 'regulation', 'resilience', 'systemic risk',
            'credit risk', 'bank balance sheets', 'non bank'
        ]
    }),
    ('climate_sustainability', {
        'label': 'Climate & sustainability',
        'keywords': [
            'climate change', 'climate risk', 'net zero', 'transition', 'green investment',
            'sustainability', 'environmental risk', 'climate policy', 'carbon'
        ]
    }),
    ('uncertainty_forecasting', {
        'label': 'Uncertainty & forecasting',
        'keywords': [
            'uncertainty', 'risk', 'forecast', 'forecasts', 'judgement', 'scenario',
            'data', 'models', 'model uncertainty', 'signals', 'outlook', 'evidence',
            'rebalancing', 'key risks'
        ]
    }),
])

THEME_ORDER = list(THEMES.keys())


class SpeechHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_output = False
        self.output_depth = 0
        self.in_paragraph = False
        self.current_paragraph = []
        self.paragraphs = []

    def handle_starttag(self, tag, attrs):
        attrs = {key.lower(): value for key, value in attrs}
        if tag == 'div' and attrs.get('id') == 'output':
            self.in_output = True
            self.output_depth = 1
        elif self.in_output and tag == 'div':
            self.output_depth += 1
        elif self.in_output and tag == 'p':
            self.in_paragraph = True
            self.current_paragraph = []

    def handle_data(self, data):
        if self.in_output and self.in_paragraph:
            cleaned = ' '.join(data.split())
            if cleaned:
                self.current_paragraph.append(cleaned)

    def handle_endtag(self, tag):
        if self.in_output and tag == 'p' and self.in_paragraph:
            paragraph = ' '.join(self.current_paragraph).strip()
            if len(paragraph) >= 30:
                self.paragraphs.append(paragraph)
            self.in_paragraph = False
            self.current_paragraph = []

        if self.in_output and tag == 'div':
            if self.output_depth > 0:
                self.output_depth -= 1
            if self.output_depth == 0:
                self.in_output = False


def clean_html_text(value: str) -> str:
    if value is None:
        return ''
    value = unescape(value)
    value = re.sub(r'<.*?>', ' ', value, flags=re.S)
    value = re.sub(r'\s+', ' ', value)
    return value.strip()


def parse_title_and_speaker(title_html: str) -> tuple[str, str]:
    cleaned = clean_html_text(title_html)
    if not cleaned:
        return '', ''

    title = re.sub(r'\s*\|\s*Bank of England.*$', '', cleaned, flags=re.I)
    title = title.replace('−', '-').replace('–', '-')

    # Prefer the explicit speaker patterns used on Bank of England pages.
    match = re.search(r'(?:speech|remarks|presentation) by\s+(.+)$', title, flags=re.I)
    if not match:
        match = re.search(r'(?:slides|remarks|speech|presentation)[^A-Za-z]*?from\s+(.+)$', title, flags=re.I)
    if not match:
        match = re.search(r'-(?:\s*)([A-Z][A-Za-z\.\'\-]*(?:\s+[A-Z][A-Za-z\.\'\-]*)+)$', title)

    speaker = match.group(1).strip() if match else ''
    if speaker:
        speaker = re.sub(r'^(?:speech|remarks|slides|presentation)\s+by\s+', '', speaker, flags=re.I)
        speaker = re.sub(r'^(?:from|by)\s+', '', speaker, flags=re.I)
        speaker = speaker.strip(' -')

    title_without_speaker = title
    trailing = re.sub(r'\s*[-–−]\s*(?:speech by|remarks by|slides by|slides from|speech|presentation from|presentation by|by|from)\s*.*$', '', title, flags=re.I)
    if trailing != title:
        title_without_speaker = trailing
    elif ' - ' in title and speaker:
        parts = title.rsplit(' - ', 1)
        if len(parts) == 2 and speaker.lower() in parts[1].lower():
            title_without_speaker = parts[0].strip()
        elif len(parts) == 2:
            title_without_speaker = parts[0].strip()
    title = title_without_speaker.strip()
    return title, speaker


def extract_metadata(path: Path) -> dict:
    html = path.read_text(encoding='utf-8', errors='ignore')

    title_match = re.search(r'<title>(.*?)</title>', html, flags=re.S | re.I)
    title_raw = title_match.group(1) if title_match else ''
    title, speaker = parse_title_and_speaker(title_raw)

    event_match = re.search(r'<span class="hero">(.*?)</span>', html, flags=re.S | re.I)
    event = clean_html_text(event_match.group(1)) if event_match else ''

    canonical_match = re.search(r'<link\s+rel="canonical"\s+href="(.*?)"', html, flags=re.S | re.I)
    canonical_url = canonical_match.group(1).strip() if canonical_match else ''

    date_match = re.search(r'Published on\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})', html, flags=re.S | re.I)
    date_value = date_match.group(1).strip() if date_match else ''
    date_obj = None
    for fmt in ('%d %B %Y', '%d %b %Y', '%B %d %Y', '%b %d %Y'):
        try:
            date_obj = datetime.strptime(date_value, fmt).date()
            break
        except ValueError:
            continue

    year = path.parent.name if path.parent.name.isdigit() else str(date_obj.year) if date_obj else 'unknown'
    return {
        'speech_id': path.stem,
        'file_name': path.name,
        'year': int(year) if str(year).isdigit() else np.nan,
        'date': date_obj.isoformat() if date_obj else pd.NaT,
        'speaker': speaker,
        'speech_title': title,
        'event': event,
        'source_path': str(path),
        'source_url': canonical_url or f'https://www.bankofengland.co.uk/{path.name}',
        'source_type': 'html',
    }


def normalise_text(text: str) -> str:
    text = unescape(text)
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def count_keyword_hits(text: str, keyword_list: list[str]) -> int:
    text_norm = normalise_text(text)
    hits = 0
    for keyword in keyword_list:
        phrase = normalise_text(keyword)
        if not phrase:
            continue
        hits += len(re.findall(r'(?<![a-z0-9])' + re.escape(phrase) + r'(?![a-z0-9])', text_norm))
    return hits


def extract_text(path: Path) -> str:
    if path.suffix.lower() == '.pdf':
        return extract_pdf_text(path)
    html = path.read_text(encoding='utf-8', errors='ignore')
    parser = SpeechHTMLParser()
    parser.feed(html)
    return ' '.join(parser.paragraphs)


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ''
        if text:
            pages.append(text)
    return ' '.join(pages)


def parse_pdf_title_and_speaker(path: Path, text: str) -> tuple[str, str, str]:
    first_chunk = ' '.join(text.split())
    first_chunk = first_chunk[:5000]

    event = ''
    given_at = re.search(r'Given at\s+(.*?)(?=\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}|$)', first_chunk, flags=re.I)
    if given_at:
        event = given_at.group(1).strip()

    title_pattern = r'(?:^|\b\d+\s+)(?P<title>[A-Z][^\n]{20,200}?)\s*(?:Speech|Remarks|Presentation|Lecture|Keynote|Address|Slides)\s+(?:given by|by|from)'
    match = re.search(title_pattern, first_chunk, flags=re.I)
    if match:
        title = match.group('title').strip(' -:,.')
    else:
        title = path.stem.replace('-', ' ').title()

    speaker = 'Unknown'
    stem_lower = path.stem.lower()
    speaker_match = re.search(r'(?:speech|remarks|slides|presentation|lecture|keynote|address|fireside-chat|speaker|panellist)[-_](?:given[-_])?(?:by|from)[-_]([a-z0-9.]+(?:[-_][a-z0-9.]+)*)$', stem_lower, flags=re.I)
    if speaker_match:
        speaker = speaker_match.group(1).replace('-', ' ').title()
    elif 'speech' in stem_lower and re.search(r'\b(?:megan|swati|huw|catherine|jonathan|dave|sarah|silvana|gertjan|alan|andrew|ben|clare|david|ruth|michael)\b', stem_lower):
        last_token = re.sub(r'^.*?[-_]', '', path.stem)
        speaker = last_token.replace('-', ' ').title()

    return title, speaker, event


def extract_pdf_metadata(path: Path) -> dict:
    text = extract_pdf_text(path)
    title, speaker, event = parse_pdf_title_and_speaker(path, text)
    year = path.parent.name if path.parent.name.isdigit() else 'unknown'
    try:
        year_val = int(year)
    except ValueError:
        year_val = np.nan
    return {
        'speech_id': path.stem,
        'file_name': path.name,
        'year': year_val,
        'date': pd.NaT,
        'speaker': speaker,
        'speech_title': title,
        'event': event,
        'source_path': str(path),
        'source_url': '',
        'source_type': 'pdf',
    }


def score_speech(text: str) -> dict:
    total_words = len(re.findall(r'\b\w+\b', text))
    theme_scores = {}
    for theme_key, theme_meta in THEMES.items():
        hits = count_keyword_hits(text, theme_meta['keywords'])
        score = round((hits / max(1, total_words / 1000)) if total_words else 0, 3)
        theme_scores[theme_key] = score
    return theme_scores


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Analyze MPC speeches and score themes.')
    parser.add_argument(
        '--source-root',
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
        help='Folder containing the HTML and PDF speech corpus.',
    )
    parser.add_argument(
        '--output-root',
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help='Folder where analysis outputs should be written.',
    )
    return parser.parse_args()


def main(source_root: Path, output_root: Path) -> None:
    if not source_root.exists():
        raise FileNotFoundError(f'Source root does not exist: {source_root}')

    output_root.mkdir(parents=True, exist_ok=True)

    records = []
    html_files = sorted(source_root.glob('20*/**/*.html'))
    pdf_files = sorted(source_root.glob('20*/**/*.pdf'))

    if not html_files and not pdf_files:
        raise FileNotFoundError(f'No HTML or PDF speech files found under {source_root}')

    for path in html_files:
        if 'speech' not in path.name.lower() and 'speech' not in str(path.parent).lower():
            # Keep all HTML pages in the speech folder, even where the title uses other patterns.
            pass
        metadata = extract_metadata(path)
        text = extract_text(path)
        theme_scores = score_speech(text)
        metadata['word_count'] = len(re.findall(r'\b\w+\b', text))
        metadata['primary_theme'] = max(theme_scores, key=theme_scores.get)
        metadata['primary_theme_label'] = THEMES[metadata['primary_theme']]['label']
        metadata['top_themes'] = [
            THEMES[k]['label'] for k, _ in sorted(theme_scores.items(), key=lambda item: item[1], reverse=True)[:3]
        ]

        for theme_key, theme_meta in THEMES.items():
            metadata[f'{theme_key}_score'] = theme_scores[theme_key]
            metadata[f'{theme_key}_label'] = theme_meta['label']

        records.append(metadata)

    for path in pdf_files:
        metadata = extract_pdf_metadata(path)
        text = extract_text(path)
        theme_scores = score_speech(text)
        metadata['word_count'] = len(re.findall(r'\b\w+\b', text))
        if metadata['word_count'] <= 0:
            continue
        metadata['primary_theme'] = max(theme_scores, key=theme_scores.get)
        metadata['primary_theme_label'] = THEMES[metadata['primary_theme']]['label']
        metadata['top_themes'] = [
            THEMES[k]['label'] for k, _ in sorted(theme_scores.items(), key=lambda item: item[1], reverse=True)[:3]
        ]

        for theme_key, theme_meta in THEMES.items():
            metadata[f'{theme_key}_score'] = theme_scores[theme_key]
            metadata[f'{theme_key}_label'] = theme_meta['label']

        records.append(metadata)

    if pdf_files:
        print(f'Processed {len(pdf_files)} PDF files using pypdf; HTML files processed separately.')

    df = pd.DataFrame.from_records(records)
    if 'word_count' in df.columns:
        df = df[df['word_count'] > 0].copy()
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], errors='coerce')

    df = df.sort_values(['year', 'date', 'speaker'], na_position='last', kind='mergesort').reset_index(drop=True)

    theme_columns = [f'{theme_key}_score' for theme_key in THEME_ORDER]
    if not theme_columns:
        raise ValueError('No theme scores were generated.')

    output_file = output_root / 'mpc_speech_database.csv'
    df.to_csv(output_file, index=False)

    long_format = []
    for _, row in df.iterrows():
        for theme_key in THEME_ORDER:
            long_format.append({
                'speech_id': row['speech_id'],
                'speaker': row['speaker'],
                'year': row['year'],
                'date': row['date'],
                'speech_title': row['speech_title'],
                'theme_key': theme_key,
                'theme_label': THEMES[theme_key]['label'],
                'score': row[f'{theme_key}_score'],
            })

    long_df = pd.DataFrame(long_format)
    long_df.to_csv(output_root / 'mpc_speech_theme_scores.csv', index=False)

    summary = {
        'speech_count': int(len(df)),
        'html_files_processed': int(len(html_files)),
        'pdf_files_found': int(len(pdf_files)),
        'pdf_files_processed': int(len(pdf_files)),
        'pdf_files_skipped': 0,
        'year_span': [int(df['year'].min()), int(df['year'].max())] if df['year'].notna().any() else [None, None],
        'most_common_primary_theme': df['primary_theme_label'].value_counts().idxmax() if len(df) else None,
        'avg_word_count': round(float(df['word_count'].mean()), 1) if len(df) else 0.0,
        'top_themes_by_average_score': [
            {'theme': THEMES[k]['label'], 'score': round(float(df[f'{k}_score'].mean()), 3)}
            for k in THEME_ORDER
        ],
    }
    (output_root / 'speech_analysis_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')

    print(f'Processed {len(df)} speeches and saved outputs to {output_root}')
    print(f'Primary theme overall: {summary["most_common_primary_theme"]}')
    print(f'Average word count: {summary["avg_word_count"]}')


if __name__ == '__main__':
    args = parse_args()
    main(args.source_root, args.output_root)
