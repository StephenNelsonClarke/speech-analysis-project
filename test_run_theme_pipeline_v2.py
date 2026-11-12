import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import analyze_mpc_speeches
import llm_theme_classifier
import run_enriched_theme_pipeline
import theme_taxonomy_v2
from run_theme_pipeline_v2 import (
    apply_reviewed_exclusions, check_prompt_and_schema, run, run_saved_reports, use_taxonomy_v2,
)
from test_run_enriched_theme_pipeline import source_frame

PROJECT = Path(__file__).resolve().parent


def v2_classification():
    return {
        'primary_theme': 'unconventional_monetary_policy',
        'secondary_themes': ['conventional_monetary_policy'], 'confidence': 0.8,
        'evidence_excerpt': 'quantitative easing', 'rationale': 'The speech discusses QE.',
    }


class TaxonomyV2Tests(unittest.TestCase):
    def test_reviewed_exclusions_preserve_retained_rows_and_reject_invalid_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'review.csv'
            source = pd.DataFrame({'hyperlink': ['drop', 'retain', 'unreviewed'],
                                   'text': ['one', 'two', 'three']})
            pd.DataFrame({'hyperlink': ['drop', 'retain'],
                          'exclude_from_analysis': ['yes', '']}).to_csv(path, index=False)
            selected, excluded = apply_reviewed_exclusions(source, path)
            self.assertEqual(selected.hyperlink.tolist(), ['retain', 'unreviewed'])
            self.assertEqual(excluded.hyperlink.tolist(), ['drop'])
            self.assertEqual(source.hyperlink.tolist(), ['drop', 'retain', 'unreviewed'])
            pd.DataFrame({'hyperlink': ['drop'],
                          'exclude_from_analysis': ['maybe']}).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, 'decisions must'):
                apply_reviewed_exclusions(source, path)
            pd.DataFrame({'hyperlink': ['missing'],
                          'exclude_from_analysis': ['yes']}).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, 'absent'):
                apply_reviewed_exclusions(source, path)

    def test_taxonomy_replaces_fiscal_and_splits_monetary_policy(self):
        themes = theme_taxonomy_v2.THEMES
        self.assertEqual(len(themes), 10)
        self.assertNotIn('fiscal_policy_public_finances', themes)
        self.assertNotIn('monetary_policy_rates', themes)
        self.assertEqual(list(themes)[1:3],
                         ['conventional_monetary_policy', 'unconventional_monetary_policy'])
        for key, meta in analyze_mpc_speeches.THEMES.items():
            if key not in theme_taxonomy_v2.REMOVED_THEMES:
                self.assertEqual(themes[key], meta)
        self.assertEqual(len({m['label'] for m in themes.values()}), 10)

    def test_original_taxonomy_files_are_unchanged(self):
        self.assertIn('fiscal_policy_public_finances', analyze_mpc_speeches.THEMES)
        self.assertIn('monetary_policy_rates', analyze_mpc_speeches.THEMES)
        self.assertIn('fiscal_policy_public_finances',
                      (PROJECT / 'llm_theme_prompt.txt').read_text(encoding='utf-8'))

    def test_prompt_and_schema_match_taxonomy(self):
        check_prompt_and_schema()

    def test_prompt_assigns_forward_guidance_to_unconventional(self):
        prompt = (PROJECT / 'llm_theme_prompt_v2.txt').read_text(encoding='utf-8')
        self.assertIn('Forward guidance rule', prompt)
        self.assertIn('include unconventional_monetary_policy as the primary or a secondary theme',
                      prompt)
        self.assertIn('{{SPEECH_TEXT}}', prompt)

    def test_keywords_separate_conventional_from_unconventional(self):
        with use_taxonomy_v2():
            scores = analyze_mpc_speeches.score_speech(
                'Quantitative easing and asset purchases with forward guidance at the lower bound.')
            self.assertGreater(scores['unconventional_monetary_policy'], 0)
            self.assertEqual(scores['conventional_monetary_policy'], 0)
            scores = analyze_mpc_speeches.score_speech('Yield curve control.')
            self.assertGreater(scores['unconventional_monetary_policy'], 0)
            scores = analyze_mpc_speeches.score_speech('Bank Rate and the policy rate path.')
            self.assertGreater(scores['conventional_monetary_policy'], 0)
            self.assertEqual(scores['unconventional_monetary_policy'], 0)
            self.assertNotIn('fiscal_policy_public_finances', scores)

    def test_patches_are_restored(self):
        with use_taxonomy_v2():
            self.assertIs(analyze_mpc_speeches.THEMES, theme_taxonomy_v2.THEMES)
            self.assertIn('unconventional_monetary_policy', llm_theme_classifier.THEME_KEYS)
        self.assertIn('monetary_policy_rates', llm_theme_classifier.THEME_KEYS)
        self.assertEqual(llm_theme_classifier.PROMPT_PATH.name, 'llm_theme_prompt.txt')
        self.assertIn('monetary_policy_rates_score', run_enriched_theme_pipeline.GENERATED_COLUMNS)

    @patch('run_enriched_theme_pipeline.write_charts')
    @patch('run_enriched_theme_pipeline.classify_speech', side_effect=lambda *a: v2_classification())
    def test_pipeline_uses_v2_prompt_schema_and_columns(self, call, charts):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, output = root / 'source.csv', root / 'results'
            source_frame().assign(text='Quantitative easing and Bank Rate.').to_csv(path, index=False)
            result = run(path, output, provider='copilot-api', exclude_urls=(), skip_charts=True)
            self.assertTrue(result['complete'])
            prompt, schema = call.call_args.args[1:3]
            self.assertIn('unconventional_monetary_policy', prompt)
            self.assertNotIn('fiscal_policy_public_finances', json.dumps(schema))
            merged = pd.read_csv(output / 'mpc_speech_database_with_llm.csv')
            self.assertIn('unconventional_monetary_policy_score', merged.columns)
            self.assertNotIn('fiscal_policy_public_finances_score', merged.columns)
            self.assertEqual(merged.loc[0, 'llm_primary_theme'], 'unconventional_monetary_policy')
            counts = pd.read_csv(output / 'quantitative' / 'theme_counts.csv')
            self.assertEqual(set(counts.theme_key) - {'unclassified'}, set(theme_taxonomy_v2.THEMES))
            self.assertTrue((output / 'taxonomy_v2.json').exists())

    @patch('run_theme_pipeline_v2.write_activity_charts')
    @patch('run_enriched_theme_pipeline.write_charts')
    @patch('run_enriched_theme_pipeline.run_analysis')
    @patch('run_enriched_theme_pipeline.build_disagreement_rows')
    @patch('run_enriched_theme_pipeline.classify_speech', side_effect=lambda *a: v2_classification())
    def test_classification_only_skips_all_analysis_and_resumes_cache(
            self, call, disagreements, analysis, charts, activity):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, output = root / 'source.csv', root / 'results'
            source_frame().to_csv(path, index=False)
            result = run(path, output, provider='copilot-api', exclude_urls=(), skip_analysis=True)
            self.assertTrue(result['complete'])
            self.assertFalse(result['analysis_generated'])
            self.assertEqual(result['new_classifications'], 1)
            resumed = run(path, output, provider='copilot-api', exclude_urls=(), skip_analysis=True)
            self.assertEqual(resumed['new_classifications'], 0)
            self.assertEqual(call.call_count, 1)
            for operation in (disagreements, analysis, charts, activity):
                operation.assert_not_called()
            self.assertFalse((output / 'quantitative').exists())
            self.assertTrue((output / 'mpc_speech_database_with_llm.csv').exists())
            self.assertTrue((output / 'llm_theme_results.jsonl').exists())

    @patch('run_theme_pipeline_v2.write_activity_charts')
    @patch('run_enriched_theme_pipeline.write_charts')
    @patch('run_enriched_theme_pipeline.classify_speech', side_effect=lambda *a: v2_classification())
    def test_saved_reports_do_not_reclassify_and_reject_stale_prompt(self, call, charts, activity):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, output = root / 'source.csv', root / 'results'
            source_frame().to_csv(path, index=False)
            run(path, output, provider='copilot-api', exclude_urls=(), skip_analysis=True)
            original = (output / 'mpc_speech_database_with_llm.csv').read_bytes()
            summary = run_saved_reports(output)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(summary['llm_calls'], 0)
            self.assertTrue((output / 'quantitative' / 'theme_counts.csv').exists())
            self.assertEqual((output / 'mpc_speech_database_with_llm.csv').read_bytes(), original)
            charts.assert_called_once()
            activity.assert_called_once()
            with patch('run_enriched_theme_pipeline.load_cache') as cache:
                shared = run_saved_reports(
                    root / 'colleague', dataset_csv=output / 'mpc_speech_database_with_llm.csv')
                self.assertEqual(shared['speech_rows'], 1)
                self.assertEqual(shared['llm_calls'], 0)
                cache.assert_not_called()
            self.assertEqual(call.call_count, 1)
            with patch('llm_theme_classifier.load_prompt_template', return_value='changed'):
                with self.assertRaisesRegex(ValueError, 'does not match current cache'):
                    run_saved_reports(output)


if __name__ == '__main__':
    unittest.main()
