import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from discover_speech_themes import evidence_matches, select_sample
from discover_speech_themes_two_stage import (
    run, speech_prompt, synthesis_prompt, validate_intermediate, validated_request,
)
from test_discover_speech_themes import source_frame, valid_result


class TwoStageTests(unittest.TestCase):
    def test_evidence_accepts_pdf_layout_but_not_changed_words(self):
        self.assertTrue(evidence_matches('An exact quote.', 'An exact\n\n5\nquote.'))
        self.assertTrue(evidence_matches('An exact quote.', 'An exact\nquote.'))
        self.assertFalse(evidence_matches('An altered quote.', 'An exact\n\n5\nquote.'))
        self.assertFalse(evidence_matches('Growth was 5 percent.', 'Growth was 6 percent.'))

    @patch('discover_speech_themes_two_stage.request_discovery')
    def test_validation_correction_preserves_raw_and_resumes(self, request):
        good = {'speech_id': 'id', 'summary': 'Summary', 'themes': [{
            'name': 'Subject', 'description': 'Description', 'evidence': ['Exact quote.'],
        }]}
        bad = {**good, 'speech_id': 'wrong'}
        request.side_effect = [json.dumps(bad), json.dumps(good)]
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            validator = lambda value: validate_intermediate(value, 'id', 'Exact quote.')
            self.assertEqual(validated_request(directory, 'prompt', validator), good)
            self.assertEqual(validated_request(directory, 'prompt', validator), good)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(json.loads((directory / 'response.txt').read_text()), bad)
            self.assertEqual(len(list(directory.glob('correction_1_*/response.txt'))), 1)

    def test_prompts_and_validation(self):
        text = 'An exact quotation. ' * 20000
        prompt = speech_prompt('id', text)
        self.assertIn(json.dumps(text), prompt)
        result = {'speech_id': 'id', 'summary': 'Summary', 'themes': [{
            'name': 'Subject', 'description': 'Description', 'evidence': ['An exact quotation.'],
        }]}
        self.assertEqual(validate_intermediate(result, 'id', text), result)
        final_prompt = synthesis_prompt([result])
        self.assertIn('there is no target count', final_prompt)
        self.assertNotIn(text, final_prompt)
        result['themes'][0]['evidence'] = ['invented']
        with self.assertRaises(ValueError):
            validate_intermediate(result, 'id', text)

    @patch('discover_speech_themes_two_stage.request_discovery')
    def test_complete_run_and_resume(self, request):
        source = source_frame()
        sample = select_sample(source, 42)
        intermediate = [{
            'speech_id': row.speech_id, 'summary': 'Argument', 'themes': [{
                'name': 'Subject', 'description': 'Description', 'evidence': [row.text[:18]],
            }],
        } for row in sample.itertuples()]
        request.side_effect = [json.dumps(record) for record in intermediate] + [
            json.dumps(valid_result(sample)),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'source.csv'
            source.to_csv(path, index=False)
            original = path.read_bytes()
            out = Path(temp) / 'out'
            run(path, out, 42)
            self.assertEqual(request.call_count, 26)
            self.assertEqual(len(pd.read_csv(out / 'intermediate_themes.csv')), 25)
            self.assertEqual(len(pd.read_csv(out / 'discovered_themes.csv')), 7)
            self.assertEqual(len(pd.read_csv(out / 'sample_theme_assignments.csv')), 25)
            run(path, out, 42)
            self.assertEqual(request.call_count, 26)
            self.assertEqual(path.read_bytes(), original)
            with self.assertRaises(ValueError):
                run(path, out, 43)

    @patch('discover_speech_themes_two_stage.request_discovery')
    def test_interruption_preserves_completed_speeches(self, request):
        sample = select_sample(source_frame(), 42)
        row = sample.iloc[0]
        request.side_effect = [json.dumps({
            'speech_id': row.speech_id, 'summary': 'Argument', 'themes': [{
                'name': 'Subject', 'description': 'Description', 'evidence': [row.text[:18]],
            }],
        }), RuntimeError('API unavailable')]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'source.csv'
            source_frame().to_csv(path, index=False)
            out = Path(temp) / 'out'
            with self.assertRaisesRegex(RuntimeError, 'API unavailable'):
                run(path, out, 42)
            self.assertEqual(len(pd.read_csv(out / 'intermediate_themes.csv')), 1)
            self.assertTrue((out / 'intermediate' / row.speech_id / 'themes.json').exists())
            self.assertFalse((out / 'discovered_themes.json').exists())


if __name__ == '__main__':
    unittest.main()
