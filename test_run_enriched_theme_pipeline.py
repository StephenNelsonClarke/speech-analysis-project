import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import requests

from quantify_mpc_speeches import DEFAULT_MEMBERSHIP, build_reports
from run_enriched_theme_pipeline import classify_keywords, classify_with_retries, run


def source_frame():
    return pd.DataFrame([{
        'hyperlink': 'https://example.org/bailey', 'text': 'Inflation prices inflation interest rates.',
        'title': 'Speech by Andrew Bailey', 'date': '01/05/2024', 'speech_date': '2024-05-01',
        'year': '2024', 'speaker': 'Andrew Bailey', 'mpc_member_type': 'internal',
        'mpc_status': 'internal', 'years_on_mpc': '4.13',
        'completed_years_on_mpc': '4',
        'keyword_1': 'climate change', 'score_1': '99999', 'keywords_filtered': 'climate',
    }])


def classification():
    return {
        'primary_theme': 'inflation_and_prices', 'secondary_themes': ['monetary_policy_rates'],
        'confidence': 0.9, 'evidence_excerpt': 'Inflation prices',
        'rationale': 'The speech discusses inflation.',
    }


class EnrichedPipelineTests(unittest.TestCase):
    @patch('run_enriched_theme_pipeline.time.sleep')
    @patch('run_enriched_theme_pipeline.classify_speech')
    def test_connection_retries_are_bounded_and_validation_is_not_retried(self, call, sleep):
        call.side_effect = [requests.exceptions.ConnectionError('disconnected'), classification()]
        self.assertEqual(classify_with_retries('text', 'prompt', {}, 'copilot-api'), classification())
        self.assertEqual(call.call_count, 2)
        sleep.assert_called_once_with(10)
        call.reset_mock()
        sleep.reset_mock()
        call.side_effect = requests.exceptions.Timeout('timeout')
        with self.assertRaises(requests.exceptions.Timeout):
            classify_with_retries('text', 'prompt', {}, 'copilot-api')
        self.assertEqual(call.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        call.reset_mock()
        call.side_effect = ValueError('invalid classification')
        with self.assertRaises(ValueError):
            classify_with_retries('text', 'prompt', {}, 'copilot-api')
        self.assertEqual(call.call_count, 1)

    @patch('run_enriched_theme_pipeline.write_charts')
    @patch('run_enriched_theme_pipeline.classify_speech', side_effect=lambda *args: classification())
    def test_explicit_skip_charts_preserves_classifications_and_reports(self, call, charts):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = source_frame().assign(
                hyperlink='https://example.org/miles', speaker='David Miles',
                date='27/02/2014', speech_date='2014-02-27', year='2014',
                mpc_member_type='external', mpc_status='external',
                years_on_mpc='', completed_years_on_mpc='')
            path, output = root / 'source.csv', root / 'results'
            source.to_csv(path, index=False)
            result = run(path, output, provider='copilot-api', skip_charts=True)
            self.assertTrue(result['complete'])
            self.assertEqual(call.call_count, 1)
            charts.assert_not_called()
            self.assertTrue((output / 'mpc_speech_database_with_llm.csv').exists())
            self.assertTrue((output / 'quantitative' / 'theme_counts.csv').exists())
            self.assertFalse(json.loads((output / 'classification_summary.json').read_text())['charts_generated'])

    def test_colleague_fields_are_preserved_but_do_not_affect_scores(self):
        source = source_frame()
        original = source.copy()
        first = classify_keywords(source)
        pd.testing.assert_frame_equal(first[source.columns], original)
        changed = source.assign(keyword_1='labour market', score_1='-1', keywords_filtered='employment')
        second = classify_keywords(changed)
        generated = first.columns.difference(source.columns)
        pd.testing.assert_frame_equal(first[generated], second[generated])
        pd.testing.assert_frame_equal(source, original)
        self.assertNotEqual(first.loc[0, 'primary_theme'], 'climate_sustainability')

    def test_zero_hits_are_unclassified(self):
        result = classify_keywords(source_frame().assign(text='xyzzy'))
        self.assertEqual(result.loc[0, 'primary_theme'], '')
        self.assertEqual(result.loc[0, 'top_themes'], '[]')

    def test_bad_input_rejected(self):
        for frame in [
            source_frame().assign(text='NA'),
            pd.concat([source_frame(), source_frame()]),
            source_frame().assign(primary_theme='inflation_and_prices'),
        ]:
            with self.subTest(columns=frame.columns.tolist()), self.assertRaises(ValueError):
                classify_keywords(frame)

    def test_enriched_report_preserves_source_fields_and_checks_membership(self):
        source = source_frame()
        database = classify_keywords(source).assign(
            llm_primary_theme='inflation_and_prices', llm_secondary_themes='monetary_policy_rates')
        reports, summary = build_reports(database, DEFAULT_MEMBERSHIP)
        pd.testing.assert_frame_equal(reports['annotated_speeches'][source.columns], source)
        self.assertEqual(summary['rows_with_quality_issues'], 0)
        with self.assertRaisesRegex(ValueError, 'disagrees'):
            build_reports(database.assign(mpc_member_type='external'), DEFAULT_MEMBERSHIP)

    def test_blank_member_type_with_explicit_unresolved_status_is_consistent(self):
        database = classify_keywords(source_frame()).assign(
            llm_primary_theme='inflation_and_prices', llm_secondary_themes='',
            speaker='David Miles', mpc_member_type='', mpc_status='outside_recorded_tenure',
            speech_date='2024-05-01')
        reports, _ = build_reports(database, DEFAULT_MEMBERSHIP)
        self.assertEqual(reports['annotated_speeches'].iloc[0].mpc_member_type, 'outside_recorded_tenure')
        reports, _ = build_reports(database.assign(speaker='Unknown person', mpc_status='unresolved'),
                                  DEFAULT_MEMBERSHIP)
        self.assertEqual(reports['annotated_speeches'].iloc[0].mpc_member_type, 'unresolved')
        with self.assertRaisesRegex(ValueError, 'disagrees'):
            build_reports(database.assign(mpc_status='internal'), DEFAULT_MEMBERSHIP)

    @patch('run_enriched_theme_pipeline.write_charts')
    @patch('run_enriched_theme_pipeline.classify_speech', side_effect=lambda *args: classification())
    def test_end_to_end_and_resume_invalidation(self, call, charts):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, output = root / 'source.csv', root / 'results'
            source = source_frame()
            source.to_csv(path, index=False)
            before = path.read_bytes()
            first = run(path, output, provider='copilot-api')
            self.assertTrue(first['complete'])
            self.assertEqual(call.call_count, 1)
            self.assertEqual(path.read_bytes(), before)
            merged = pd.read_csv(output / 'mpc_speech_database_with_llm.csv',
                                 dtype=str, keep_default_na=False)
            pd.testing.assert_frame_equal(merged[source.columns], source)
            self.assertEqual(len(list((output / 'quantitative').glob('*.csv'))), 14)
            themes = pd.read_csv(output / 'quantitative' / 'theme_counts.csv')
            for method in ['llm', 'keyword']:
                self.assertEqual(themes.query(
                    'method == @method and theme_role == "primary"').speech_count.sum(), 1)
            run(path, output, provider='copilot-api')
            self.assertEqual(call.call_count, 1)
            source['text'] += ' More inflation.'
            source.to_csv(path, index=False)
            run(path, output, provider='copilot-api')
            self.assertEqual(call.call_count, 2)
            with patch('run_enriched_theme_pipeline.load_prompt_template', return_value='New {{SPEECH_TEXT}}'):
                run(path, output, provider='copilot-api')
            self.assertEqual(call.call_count, 3)
            self.assertTrue(charts.called)

    @patch('run_enriched_theme_pipeline.write_charts')
    @patch('run_enriched_theme_pipeline.classify_speech', side_effect=lambda *args: classification())
    def test_pilot_resumes_without_partial_reports(self, call, charts):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = source_frame()
            source = pd.concat([source, source.assign(hyperlink='https://example.org/second')])
            path, output = root / 's.csv', root / 'out'
            source.to_csv(path, index=False)
            result = run(path, output, provider='copilot-api', max_new_classifications=1)
            self.assertFalse(result['complete'])
            self.assertFalse((output / 'mpc_speech_database_with_llm.csv').exists())
            self.assertFalse(charts.called)
            run(path, output, provider='copilot-api')
            self.assertEqual(call.call_count, 2)

    @patch('run_enriched_theme_pipeline.classify_speech', side_effect=RuntimeError('provider failed'))
    def test_failure_is_explicit_and_does_not_produce_reports(self, call):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, output = root / 's.csv', root / 'out'
            source_frame().to_csv(path, index=False)
            with self.assertRaisesRegex(RuntimeError, 'saved results can be resumed'):
                run(path, output, provider='copilot-api')
            self.assertFalse((output / 'quantitative').exists())

    def test_input_in_output_folder_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'separate'):
                run(root / 's.csv', root)

    @patch('run_enriched_theme_pipeline.classify_speech', side_effect=lambda *args: classification())
    def test_persistent_charts(self, call):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, output = root / 's.csv', root / 'out'
            source_frame().assign(text='Inflation prices. ' * 10000).to_csv(path, index=False)
            run(path, output, provider='copilot-api')
            charts = list((output / 'quantitative').glob('*.png'))
            self.assertEqual(len(charts), 23)
            for chart in charts:
                self.assertGreater(chart.stat().st_size, 1000)

    @patch('run_enriched_theme_pipeline.write_charts')
    @patch('run_enriched_theme_pipeline.classify_speech', side_effect=lambda *args: classification())
    def test_explicit_exclusion_preserves_input_and_avoids_missing_text(self, call, charts):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, output = root / 's.csv', root / 'out'
            frame = pd.concat([source_frame(), source_frame().assign(
                hyperlink='https://example.org/slides', text='No text extracted')])
            frame.to_csv(path, index=False)
            before = path.read_bytes()
            summary = run(path, output, provider='copilot-api',
                          exclude_urls=('https://example.org/slides',))
            self.assertEqual(summary['speech_rows'], 1)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(path.read_bytes(), before)
            manifest = json.loads((output / 'classification_summary.json').read_text())
            self.assertEqual(manifest['excluded_urls'], ['https://example.org/slides'])


if __name__ == '__main__':
    unittest.main()
