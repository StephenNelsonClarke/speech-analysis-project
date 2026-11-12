import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from audit_speech_formats import audit_row, page_features, pdf_features


URL = 'https://www.bankofengland.co.uk/speech/2025/test'
PDF = '/-/media/boe/files/speech/2025/test.pdf'


class FormatAuditTests(unittest.TestCase):
    def test_slide_links_and_reference_links_are_separated(self):
        content = (f'<title>Test</title><main><a href="{PDF}">Slides</a>'
                   f'<div id="output"><a href="{PDF}?ref=1">An earlier speech</a>'
                   '</div></main>').encode()
        features = page_features(content, URL)
        self.assertEqual(len(features['attachments']), 1)
        self.assertEqual(features['attachments'][0]['kind'], 'slides')

    def test_alternate_html_body_is_detected(self):
        prose = 'Inflation and monetary policy affect demand and employment. ' * 100
        features = page_features(
            f'<main><div class="page-content"><p>{prose}</p></div></main>'.encode(), URL)
        self.assertIn('Inflation and monetary policy', features['html_text'])

    @patch('audit_speech_formats.PdfReader')
    def test_continuous_prose_is_not_rejected_for_low_average_density(self, reader):
        prose = (' '.join(['economic'] * 25) + '. ') * 8
        page = SimpleNamespace(mediabox=SimpleNamespace(width=600, height=800),
                               extract_text=lambda: prose)
        reader.return_value.pages = [page, page]
        self.assertTrue(pdf_features(Path('test.pdf'))['prose_like'])
        page.extract_text = lambda: 'GDP Inflation chart sources'
        self.assertFalse(pdf_features(Path('test.pdf'))['prose_like'])

    @patch('audit_speech_formats.pdf_features')
    @patch('audit_speech_formats.cached_download')
    def test_known_slides_and_mixed_page(self, download, pdf):
        pdf.return_value = {'pages': 10, 'landscape_fraction': 1,
                            'words_per_page': 100, 'text': 'slides',
                            'slide_like': True, 'prose_like': False}
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / 'page.html'
            download.return_value = page
            page.write_text(f'<title>Outlook - slides</title><main><a href="{PDF}">Slides</a></main>')
            result = audit_row({'hyperlink': URL, 'text': 'slides'}, Path(tmp))
            self.assertEqual(result['document_type'], 'slides only')
            self.assertEqual(result['classified_text_type'], 'slides')
            self.assertTrue(result['review_required'])
            prose = 'Inflation and monetary policy affect demand and employment. ' * 100
            page.write_text(f'<title>Speech</title><main><div id="output">{prose}</div>'
                            f'<a href="{PDF}">Accompanying slides</a></main>')
            result = audit_row({'hyperlink': URL, 'text': prose}, Path(tmp))
            self.assertEqual(result['document_type'], 'speech + slides')
            self.assertEqual(result['classified_text_type'], 'prose (source matched)')
            page.write_text(f'<title>Speaking notes and slides</title><main>'
                            f'<a href="{PDF}">Speaking notes and slides</a></main>')
            result = audit_row({'hyperlink': URL, 'text': 'slides'}, Path(tmp))
            self.assertEqual(result['document_type'], 'speech + slides')
            self.assertTrue(result['review_required'])

    @patch('audit_speech_formats.cached_download', side_effect=RuntimeError('HTTP 403'))
    def test_failed_pages_are_flagged_not_assumed_speeches(self, download):
        result = audit_row({'hyperlink': URL}, Path('.'))
        self.assertEqual(result['document_type'], 'unclear')
        self.assertTrue(result['review_required'])
        self.assertIn('HTTP 403', result['error'])
