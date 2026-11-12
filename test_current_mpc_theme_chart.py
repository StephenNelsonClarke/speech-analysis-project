import unittest
from datetime import date

import pandas as pd

from current_mpc_theme_chart import build_current_member_counts
from test_membership_activity_charts import period


class CurrentMPCChartTests(unittest.TestCase):
    def test_current_roster_historical_service_and_zero_speeches(self):
        periods = {
            'Current': [
                period('Current', 'external', '2010-01-01', '2011-12-31', 'External member'),
                period('Current', 'internal', '2020-01-01', '2029-12-31', 'Governor')],
            'Quiet': [period('Quiet', 'external', '2020-01-01', '2029-12-31', 'External member')],
            'Former': [period('Former', 'external', '2010-01-01', '2011-12-31', 'External member')],
        }
        source = pd.DataFrame([
            {'canonical_speaker': speaker, 'speech_date': day,
             'analysis_llm_primary': 'inflation_and_prices'}
            for speaker, day in [('Current', '2010-06-01'), ('Current', '2021-06-01'),
                                 ('Current', '2028-06-01'), ('Former', '2010-06-01')]
        ])
        counts = build_current_member_counts(source, periods, date(2026, 11, 10))
        self.assertEqual(set(counts.speaker), {'Current', 'Quiet'})
        self.assertEqual(counts.speech_count.sum(), 2)
        self.assertEqual(counts.loc[counts.speaker.eq('Quiet'), 'speech_count'].sum(), 0)
        self.assertEqual(set(counts.loc[counts.speaker.eq('Current'), 'current_role']), {'Governor'})
        with self.assertRaisesRegex(ValueError, 'Invalid LLM primary'):
            build_current_member_counts(source.assign(analysis_llm_primary='bad'),
                                        periods, date(2026, 11, 10))
        source.loc[0, 'speech_date'] = '2015-06-01'
        with self.assertRaisesRegex(ValueError, 'outside recorded MPC service'):
            build_current_member_counts(source, periods, date(2026, 11, 10))
