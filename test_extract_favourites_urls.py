import csv
import tempfile
import unittest
from pathlib import Path

from extract_favourites_urls import append_urls, extract_urls


HTML = '''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
<DT><H3>saved urls</H3>
<DL><p>
<DT><H3>New folder</H3>
<DL><p>
<DT><A HREF="https://example.org/a?x=1&amp;y=2">One</A>
<DT><A HREF="https://example.org/a?x=1&amp;y=2">Duplicate</A>
<DT><H3>Child</H3><DL><p>
<DT><A HREF="https://example.org/b">Two</A>
<DT><A HREF="javascript:void(0)">Ignore</A>
</DL><p></DL><p></DL><p>
<DT><H3>Private</H3><DL><p>
<DT><A HREF="https://private.example.org">Unrelated</A>
</DL><p></DL><p>'''


class FavouritesTests(unittest.TestCase):
    def test_selected_folder_descendants_entities_and_duplicates(self):
        urls, ignored = extract_urls(HTML, ['SAVED URLS', 'New folder'])
        self.assertEqual(urls, ['https://example.org/a?x=1&y=2', 'https://example.org/b'])
        self.assertEqual(ignored, 1)

    def test_missing_ambiguous_and_malformed_folders_fail(self):
        for html, path in [(HTML, ['absent']), (HTML + HTML, ['New folder']),
                           (HTML + '<DL>', ['New folder'])]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                extract_urls(html, path)

    def test_append_preserves_metadata_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export, dest = root / 'bookmarks.html', root / 'urls.csv'
            export.write_text(HTML, encoding='utf-8')
            dest.write_text('hyperlink,title,date,speaker\n'
                            'https://example.org/b,"Existing, title",2026-01-01,Name\n',
                            encoding='utf-8')
            original = export.read_bytes()
            summary = append_urls(export, dest, ['saved urls', 'New folder'])
            self.assertEqual(summary['added'], 1)
            with dest.open(encoding='utf-8-sig', newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]['title'], 'Existing, title')
            self.assertEqual(rows[1]['title'], '')
            saved = dest.read_bytes()
            self.assertEqual(append_urls(export, dest, ['saved urls', 'New folder'])['added'], 0)
            self.assertEqual(dest.read_bytes(), saved)
            self.assertEqual(export.read_bytes(), original)

    def test_creates_url_only_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export, dest = root / 'b.html', root / 'new.csv'
            export.write_text(HTML, encoding='utf-8')
            append_urls(export, dest, ['saved urls', 'New folder'])
            self.assertTrue(dest.read_text(encoding='utf-8-sig').startswith('hyperlink\n'))


if __name__ == '__main__':
    unittest.main()
