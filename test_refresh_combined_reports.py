import unittest

import pandas as pd

from quantify_mpc_speeches import DEFAULT_MEMBERSHIP
from refresh_combined_reports import combine_classifications, refresh_membership
from run_enriched_theme_pipeline import GENERATED_COLUMNS


def source():
    return pd.DataFrame([{
        'hyperlink': 'https://example.org/speech', 'speaker': 'Huw Pill',
        'speaker_source': 'user_confirmed', 'speech_date': '2021-09-10',
        'date': '10/09/2021', 'year': '2021', 'title': 'Speech', 'text': 'Original text',
        'review_flag': 'membership_appointment_dates_unverified;retained_flag',
        'mpc_member_type': 'internal', 'years_on_mpc': '',
    }])


def saved(source_frame):
    result = source_frame.copy()
    for column in GENERATED_COLUMNS:
        result[column] = 'saved'
    return result


class RefreshTests(unittest.TestCase):
    def test_refresh_retains_user_speaker_text_dates_and_unrelated_flags(self):
        original = source()
        refreshed = refresh_membership(original, DEFAULT_MEMBERSHIP)
        self.assertEqual(refreshed.iloc[0].completed_months_on_mpc, '0')
        self.assertEqual(refreshed.iloc[0].mpc_role, 'Chief Economist')
        self.assertEqual(refreshed.iloc[0].review_flag, 'retained_flag')
        for field in ['text', 'title', 'date', 'speaker_source']:
            self.assertEqual(refreshed.iloc[0][field], original.iloc[0][field])
        self.assertEqual(original.iloc[0].years_on_mpc, '')

    def test_classification_reuse_requires_exact_url_coverage_and_unchanged_text(self):
        enriched = refresh_membership(source(), DEFAULT_MEMBERSHIP)
        database = saved(enriched)
        combined, exclusions = combine_classifications(enriched, [database], ())
        self.assertEqual(combined.iloc[0].llm_primary_theme, 'saved')
        self.assertTrue(exclusions.empty)
        with self.assertRaisesRegex(ValueError, 'text has changed'):
            combine_classifications(enriched, [database.assign(text='different')], ())
        with self.assertRaisesRegex(ValueError, 'exactly cover'):
            combine_classifications(enriched, [database.assign(hyperlink='other')], ())
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            combine_classifications(enriched, [database, database], ())

    def test_explicit_slides_exclusion_does_not_remove_source_row(self):
        enriched = refresh_membership(source(), DEFAULT_MEMBERSHIP)
        excluded = enriched.assign(hyperlink='https://example.org/slides', text='No text extracted')
        full = pd.concat([enriched, excluded], ignore_index=True)
        combined, exclusions = combine_classifications(
            full, [saved(enriched)], ('https://example.org/slides',))
        self.assertEqual(len(combined), 1)
        self.assertEqual(len(exclusions), 1)
        self.assertEqual(len(full), 2)


if __name__ == '__main__':
    unittest.main()
