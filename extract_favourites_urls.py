from __future__ import annotations

import argparse
import csv
import io
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


@dataclass
class Folder:
    name: str
    children: list[Folder] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


class FavouritesParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Folder('')
        self.stack = [self.root]
        self.pending: Folder | None = None
        self.heading: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == 'h3':
            self.heading = []
        elif tag == 'dl':
            self.stack.append(self.pending if self.pending is not None else self.stack[-1])
            self.pending = None
        elif tag == 'a':
            href = dict(attrs).get('href')
            if href:
                self.stack[-1].links.append(href.strip())

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if tag == 'h3' and self.heading is not None:
            self.pending = Folder(''.join(self.heading).strip())
            self.stack[-1].children.append(self.pending)
            self.heading = None
        elif tag == 'dl':
            if len(self.stack) <= 1:
                raise ValueError('Malformed favourites export: unmatched closing folder list.')
            self.stack.pop()


def extract_urls(html: str, folder_path: list[str]) -> tuple[list[str], int]:
    if not folder_path or any(not part.strip() for part in folder_path):
        raise ValueError('Supply at least one nonblank folder name.')
    parser = FavouritesParser()
    parser.feed(html)
    parser.close()
    if len(parser.stack) != 1:
        raise ValueError('Malformed favourites export: unclosed folder list.')
    wanted = tuple(part.strip().casefold() for part in folder_path)
    matches = []

    def visit(folder: Folder, parents: tuple[str, ...]) -> None:
        path = parents + (folder.name.casefold(),)
        if path[-len(wanted):] == wanted:
            matches.append(folder)
        for child in folder.children:
            visit(child, path)

    for folder in parser.root.children:
        visit(folder, ())
    if len(matches) != 1:
        raise ValueError(f'Expected one matching folder, found {len(matches)}. '
                         'Check the names or supply additional parent folders.')
    urls: list[str] = []
    ignored = 0

    def collect(folder: Folder) -> None:
        nonlocal ignored
        for url in folder.links:
            parsed = urlsplit(url)
            if parsed.scheme.lower() in {'http', 'https'} and parsed.netloc:
                urls.append(url)
            else:
                ignored += 1
        for child in folder.children:
            collect(child)

    collect(matches[0])
    return list(dict.fromkeys(urls)), ignored


def append_urls(export: Path, destination: Path, folder_path: list[str]) -> dict[str, int]:
    if export.resolve() == destination.resolve():
        raise ValueError('The destination must not overwrite the HTML export.')
    urls, ignored = extract_urls(export.read_text(encoding='utf-8-sig'), folder_path)
    if not urls:
        raise ValueError('The selected folder contains no HTTP/HTTPS links; CSV unchanged.')
    columns = ['hyperlink']
    existing = []
    if destination.exists() and destination.stat().st_size:
        raw = destination.read_bytes()
        try:
            content = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            print('Warning: existing CSV is Windows-1252; output will be UTF-8.')
            content = raw.decode('cp1252')
        reader = csv.DictReader(io.StringIO(content, newline=''))
        columns = reader.fieldnames or []
        if 'hyperlink' not in columns or len(set(columns)) != len(columns):
            raise ValueError('Existing CSV needs a hyperlink column and unique column names.')
        existing = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in existing):
            raise ValueError('Existing CSV contains malformed rows; CSV unchanged.')
    known = {row['hyperlink'].strip() for row in existing}
    additions = [url for url in urls if url not in known]
    if additions:
        with destination.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(existing)
            writer.writerows({column: url if column == 'hyperlink' else '' for column in columns}
                             for url in additions)
    summary = {'folder_unique_urls': len(urls), 'added': len(additions),
               'already_in_csv': len(urls) - len(additions), 'ignored_non_web_links': ignored,
               'total_csv_rows': len(existing) + len(additions)}
    for key, value in summary.items():
        print(f'{key}: {value}')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Append URLs from one exported Edge favourites folder to CSV.')
    parser.add_argument('--export-html', type=Path, required=True)
    parser.add_argument('--output-csv', type=Path, required=True)
    parser.add_argument('--folder', action='append', required=True,
                        help='Folder names from parent to child; repeat for each level.')
    args = parser.parse_args()
    append_urls(args.export_html, args.output_csv, args.folder)


if __name__ == '__main__':
    main()
