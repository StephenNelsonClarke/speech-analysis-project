import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from bs4 import BeautifulSoup

from import_speech_urls import clean_pdf_pages, html_speech_text, page_metadata, run, speech_pdf, validate_url


class ImportTests(unittest.TestCase):
    def test_pdf_repeated_edges_and_page_numbers_preserve_body_and_numbers(self):
        pages = [
            f'Repeated speech header\n{i}\nUnique body {i}: inflation 2.5%.\n'
            'Repeated speech header\nReferences must remain\n42\nRepeated footer'
            for i in range(1, 4)
        ]
        text = clean_pdf_pages(pages)
        self.assertEqual(text.count('Repeated speech header'), 3)
        self.assertNotIn('Repeated footer', text)
        self.assertIn('Unique body 2: inflation 2.5%.', text)
        self.assertIn('42', text)
        self.assertNotIn('\n2\n', text)

    def test_pdf_boilerplate_cover_and_single_page_preserved(self):
        text = clean_pdf_pages([
            'Acknowledgements\nAll speeches are available online at '
            'www.bankofengland.co.uk/publications/Pages/speeches/default.aspx\n1\n'
            'Speech given by\nDavid Miles\n27 February 2014\nBody 100'
        ])
        self.assertNotIn('All speeches are available', text)
        self.assertIn('David Miles', text)
        self.assertIn('27 February 2014', text)
        self.assertIn('Body 100', text)

    def test_html_controls_duplicate_dialog_and_unique_footnotes(self):
        soup = BeautifulSoup(
            '<div id="output"><p>Inflation <em>is</em> 2.5%.</p>'
            '<p>Reference A.</p><div role="dialog"><p>Reference A.</p><button>Close</button></div>'
            '<div role="dialog"><p>Unique reference B.</p><button>Close</button></div>'
            '<nav>Share this page</nav><div role="toolbar">Print</div></div>', 'html.parser')
        text = html_speech_text(soup)
        self.assertIn('Inflation is 2.5%.', text)
        self.assertEqual(text.count('Reference A.'), 1)
        self.assertIn('Unique reference B.', text)
        self.assertNotIn('Close', text)
        self.assertNotIn('Share this page', text)
        self.assertNotIn('Print', text)

    def test_metadata_ignores_navigation_dates_and_preserves_text(self):
        soup = BeautifulSoup(
            '<title>Test - speech by Huw Pill | Bank of England</title>'
            '<nav><time datetime="2026-07-01">Other</time></nav>'
            '<main><div class="published-date">Published on 14 October 2025</div>'
            '<div id="output"><h2>Speech</h2><p>Inflation is 2.5%.</p>'
            '<ul><li>First point</li></ul><script>ignore</script></div></main>', 'html.parser')
        self.assertEqual(page_metadata(soup), ('Test - speech by Huw Pill', '2025-10-14'))
        text = html_speech_text(soup)
        self.assertIn('2.5%', text)
        self.assertIn('First point', text)
        self.assertNotIn('ignore', text)
        self.assertIn('\n', text)

    def test_pdf_scope_and_ambiguity(self):
        soup = BeautifulSoup(
            '<a href="/-/media/boe/files/speech/2025/october/one.pdf">Download speech</a>'
            '<a href="/-/media/boe/files/speech/2024/october/old.pdf">Download speech</a>'
            '<a href="/-/media/boe/files/speech/2025/october/slides.pdf">Slides</a>', 'html.parser')
        url = 'https://www.bankofengland.co.uk/speech/2025/october/topic'
        self.assertTrue(speech_pdf(soup, url).endswith('/one.pdf'))
        soup.append(BeautifulSoup(
            '<a href="/-/media/boe/files/speech/2025/october/two.pdf">Full text PDF</a>', 'html.parser'))
        with self.assertRaisesRegex(ValueError, 'Multiple'):
            speech_pdf(soup, url)

    def test_other_hosts_rejected(self):
        for url in ['https://www.bing.com/a', 'http://www.bankofengland.co.uk/a',
                    'https://www.bankofengland.co.uk.evil.example/a']:
            with self.assertRaises(ValueError):
                validate_url(url)

    def test_speech_attachment_labels_and_charts(self):
        soup = BeautifulSoup(
            '<title>A progress report - speech by Huw Pill | Bank of England</title>'
            '<a href="/-/media/boe/files/speech/2026/report.pdf">A progress report - speech by Huw Pill</a>'
            '<a href="/-/media/boe/files/speech/2026/report-charts.pdf">Download charts</a>', 'html.parser')
        self.assertTrue(speech_pdf(soup, 'https://www.bankofengland.co.uk/speech/2026/may/pill')
                        .endswith('/report.pdf'))
        soup = BeautifulSoup(
            '<a href="/-/media/boe/files/speech/2013/topic.pdf">Summary of remarks</a>', 'html.parser')
        self.assertTrue(speech_pdf(soup, 'https://www.bankofengland.co.uk/speech/2013/topic')
                        .endswith('/topic.pdf'))
        soup = BeautifulSoup(
            '<a href="/-/media/boe/files/speech/2013/chartwell.pdf">Remarks at Chartwell</a>',
            'html.parser')
        self.assertTrue(speech_pdf(soup, 'https://www.bankofengland.co.uk/speech/2013/chartwell')
                        .endswith('/chartwell.pdf'))

    def test_exact_title_can_match_official_paper_attachment(self):
        soup = BeautifulSoup(
            '<title>Tail risks and contract design from a financial stability perspective - '
            'paper by Paul Fisher | Bank of England</title>'
            '<a href="/-/media/boe/files/paper/2011/tail-risks-and-contract-design-from-a-'
            'financial-stability-perspective-paper-by-paul-fisher.pdf">'
            'Tail risks and contract design from a financial stability perspective</a>', 'html.parser')
        self.assertTrue(speech_pdf(
            soup,
            'https://www.bankofengland.co.uk/speech/2011/tail-risks-and-contract-design-from-a-'
            'financial-stability-perspective-paper-by-paul-fisher',
        ).endswith('.pdf'))

    def test_pdf_title_match_supports_year_only_attachment_paths(self):
        soup = BeautifulSoup(
            '<title>Old exposures, new actors - speech by Catherine L. Mann | Bank of England</title>'
            '<a href="/-/media/boe/files/speech/2026/old-exposures.pdf">Old exposures, new actors</a>'
            '<a href="/-/media/boe/files/speech/2026/other.pdf">Unrelated paper</a>', 'html.parser')
        self.assertTrue(speech_pdf(
            soup, 'https://www.bankofengland.co.uk/speech/2026/may/catherine-mann'
        ).endswith('/old-exposures.pdf'))

    @patch('import_speech_urls.extract_url')
    def test_candidate_preserves_curated_rows_and_flags_failures(self, extract):
        def fake(row, raw_root, reuse_downloads=False):
            if row['hyperlink'].endswith('/bad'):
                raise ValueError('No text extracted')
            return {'hyperlink': row['hyperlink'], 'text': 'Inflation is 2%. ' * 200,
                    'title': 'Speech by Huw Pill', 'date': '2025-10-14',
                    'import_text_type': 'html', 'import_text_url': row['hyperlink'],
                    'import_text_path': 'test.html', 'import_page_path': 'test.html',
                    'import_review_flag': ''}
        extract.side_effect = fake
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_path, urls_path = root/'base.csv', root/'urls.csv'
            base = pd.DataFrame([{'hyperlink': 'https://www.bankofengland.co.uk/speech/old',
                                 'text': 'curated full text', 'title': 'Curated', 'date': '2024-01-01',
                                 'speaker': 'Huw Pill', 'keyword_1': 'colleague keyword',
                                 'years_on_mpc': '2.3'}])
            base.to_csv(base_path, index=False)
            pd.DataFrame([{'hyperlink': u, 'speaker': speaker} for u,speaker in [
                (base.iloc[0].hyperlink, ''),
                ('https://www.bankofengland.co.uk/speech/new', 'David Miles'),
                ('https://www.bankofengland.co.uk/speech/bad', ''),
            ]]).to_csv(urls_path, index=False)
            originals = [p.read_bytes() for p in [base_path,urls_path]]
            summary = run(urls_path,base_path,root/'out',10)
            self.assertEqual((summary['extracted'],summary['failed'],summary['candidate_rows']), (1,1,2))
            saved = pd.read_csv(root/'out'/'speeches_enriched_candidate.csv',
                                dtype=str,keep_default_na=False)
            pd.testing.assert_frame_equal(saved.iloc[:1][base.columns],base)
            self.assertEqual(saved.iloc[1].keyword_1,'')
            self.assertEqual(saved.iloc[1].speaker,'David Miles')
            self.assertIn('speech_date_outside_mpc_tenure',saved.iloc[1].review_flag)
            self.assertEqual(originals,[p.read_bytes() for p in [base_path,urls_path]])


if __name__ == '__main__':
    unittest.main()
