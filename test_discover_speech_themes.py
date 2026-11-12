import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import requests

from discover_speech_themes import (
    build_prompt, request_discovery, run, select_sample, validate_result,
)


def source_frame():
    return pd.DataFrame([{
        'hyperlink': f'https://www.bankofengland.co.uk/speech/{i}',
        'title': f'Title {i}', 'speaker': 'Speaker', 'speech_date': '2020-01-01',
        'text': f'Unique argument {i}. ' + 'Full speech content. ' * 20,
        'llm_primary_theme': 'DO_NOT_SEND_SAVED_CLASSIFICATION',
        'keyword_1': 'DO_NOT_SEND_KEYWORDS',
    } for i in range(30)])


def valid_result(sample, theme_count=7):
    speeches = [{
        'speech_id': row.speech_id, 'summary': 'Main argument.',
        'primary_theme_id': i % theme_count + 1, 'secondary_theme_ids': [],
    } for i, row in enumerate(sample.itertuples())]
    return {
        'themes': [{
            'theme_id': i + 1, 'name': f'Discovered subject {i + 1}',
            'description': 'A substantive subject.', 'boundary': 'Distinct scope.',
            'evidence': [{'speech_id': sample.iloc[i].speech_id,
                          'quote': sample.iloc[i].text[:18]}],
        } for i in range(theme_count)],
        'speeches': speeches,
    }


class DiscoveryTests(unittest.TestCase):
    def test_sample_is_reproducible_unique_and_row_order_independent(self):
        source = source_frame()
        sample = select_sample(source, 42)
        self.assertEqual(len(sample), 25)
        self.assertTrue(sample.hyperlink.is_unique)
        pd.testing.assert_frame_equal(sample, select_sample(source.iloc[::-1], 42))
        self.assertNotEqual(sample.hyperlink.tolist(), select_sample(source, 43).hyperlink.tolist())
        self.assertNotIn('llm_primary_theme', sample.columns)
        for change in ['short', 'duplicate', 'missing']:
            bad = source.copy()
            if change == 'short':
                bad = bad.iloc[:24]
            elif change == 'duplicate':
                bad.loc[0, 'hyperlink'] = bad.loc[1, 'hyperlink']
            else:
                bad.loc[0, 'text'] = 'No text extracted'
            with self.subTest(change=change), self.assertRaises(ValueError):
                select_sample(bad, 42)

    def test_prompt_contains_every_full_text_and_no_saved_labels(self):
        source = source_frame()
        source.loc[0, 'text'] = 'LONG_START ' + 'word ' * 50000 + ' LONG_END'
        sample = select_sample(source, 42)
        # Test a long text regardless of whether row zero is in the random draw.
        sample.loc[0, 'text'] = source.loc[0, 'text']
        prompt = build_prompt(sample)
        records = json.loads(prompt.split('SPEECHES (JSON; full, untruncated text):\n')[1])
        self.assertEqual(records, sample[['speech_id', 'text']].to_dict('records'))
        self.assertNotIn('DO_NOT_SEND', prompt)
        self.assertNotIn('inflation_and_prices', prompt)
        self.assertNotIn('monetary_policy_rates', prompt)
        instructions = prompt.split('SPEECHES (JSON; full, untruncated text):\n')[0]
        self.assertIn('there is no target count', instructions)
        self.assertNotIn('10', instructions)
        self.assertNotIn('ten themes', instructions)

    def test_validation_accepts_variable_theme_counts(self):
        sample = select_sample(source_frame(), 42)
        for count in [1, 4, 10, 13, 25]:
            with self.subTest(count=count):
                result = valid_result(sample, count)
                self.assertEqual(validate_result(result, sample), result)

    def test_validation_requires_supported_themes_and_all_speeches(self):
        sample = select_sample(source_frame(), 42)
        valid = valid_result(sample)
        self.assertEqual(validate_result(valid, sample), valid)
        for kind in ['count', 'empty', 'duplicate_name', 'duplicate_id', 'missing_speech',
                     'bad_quote', 'unknown_speech', 'bad_id', 'duplicate_assignment',
                     'wrong_evidence_assignment']:
            bad = copy.deepcopy(valid)
            if kind == 'count':
                bad['themes'].pop()
            elif kind == 'empty':
                bad['themes'] = []
            elif kind == 'duplicate_name':
                bad['themes'][1]['name'] = bad['themes'][0]['name']
            elif kind == 'duplicate_id':
                bad['themes'][1]['theme_id'] = 1
            elif kind == 'missing_speech':
                bad['speeches'][0] = bad['speeches'][1]
            elif kind == 'bad_quote':
                bad['themes'][0]['evidence'][0]['quote'] = 'Invented quote'
            elif kind == 'unknown_speech':
                bad['speeches'][0]['speech_id'] = 'unknown'
            elif kind == 'bad_id':
                bad['speeches'][0]['primary_theme_id'] = True
            elif kind == 'duplicate_assignment':
                bad['speeches'][0]['secondary_theme_ids'] = [1]
            else:
                bad['themes'][0]['evidence'][0] = bad['themes'][1]['evidence'][0]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate_result(bad, sample)

    @patch('discover_speech_themes.get_copilot_client')
    def test_request_bypasses_fixed_taxonomy_and_starts_fresh(self, get_client):
        get_client.return_value.send_message_lite.return_value = ('{}', 'conversation')
        self.assertEqual(request_discovery('blind prompt'), '{}')
        get_client.return_value.send_message_lite.assert_called_once_with(
            'blind prompt', continue_conversation=False, use_web=False,
        )

    @patch('discover_speech_themes.time.sleep')
    @patch('discover_speech_themes.get_copilot_client')
    def test_bounded_connection_retries(self, get_client, sleep):
        get_client.return_value.send_message_lite.side_effect = requests.exceptions.Timeout()
        with self.assertRaises(requests.exceptions.Timeout):
            request_discovery('prompt')
        self.assertEqual(get_client.return_value.send_message_lite.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [10, 20])

    @patch('discover_speech_themes.request_discovery')
    def test_prepare_run_reuse_and_input_protection(self, request):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.csv'
            source_frame().to_csv(source, index=False)
            original = source.read_bytes()
            out = root / 'out'
            run(source, out, 42)
            request.assert_not_called()
            sample = pd.read_csv(out / 'sampled_speeches.csv', keep_default_na=False)
            request.return_value = json.dumps(valid_result(sample))
            run(source, out, 42, run_llm=True)
            run(source, out, 42, run_llm=True)
            request.assert_called_once()
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(len(pd.read_csv(out / 'discovered_themes.csv')), 7)
            manifest = json.loads((out / 'sample_manifest.json').read_text(encoding='utf-8'))
            self.assertIsNone(manifest['requested_themes'])
            self.assertEqual(manifest['theme_count_policy'], 'model_selected')
            self.assertEqual(len(pd.read_csv(out / 'sample_theme_assignments.csv')), 25)
            with self.assertRaisesRegex(ValueError, 'different experiment'):
                run(source, out, 43)

    @patch('discover_speech_themes.request_discovery', return_value='{"themes":[]}')
    def test_invalid_response_is_saved_without_complete_results(self, request):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source.csv'
            source_frame().to_csv(source, index=False)
            out = Path(temp) / 'out'
            with self.assertRaises(ValueError):
                run(source, out, 42, run_llm=True)
            self.assertTrue((out / 'discovery_response.txt').exists())
            self.assertFalse((out / 'discovered_themes.json').exists())


if __name__ == '__main__':
    unittest.main()
