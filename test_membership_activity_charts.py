import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from membership_activity_charts import build_activity_tables, write_activity_charts
from quantify_mpc_speeches import Membership


def period(speaker, member_type, start, end, role):
    return Membership(speaker, member_type, date.fromisoformat(start), date.fromisoformat(end),
                      'https://example.org', 'appointment_month', role)


def fixture():
    rows = pd.DataFrame([{
        'canonical_speaker': 'Test Member', 'speech_date': day,
        'mpc_member_type': 'external', 'mpc_role': 'External member',
    } for day in ['2020-01-15', '2020-03-01', '2020-07-01', '2021-01-01', '2021-06-30']])
    periods = {'Test Member': [period('Test Member', 'external', '2020-01-01', '2021-06-30',
                                      'External member')]}
    return rows, periods


class ActivityChartTests(unittest.TestCase):
    def test_five_speeches_over_eighteen_months_are_annualised_exactly(self):
        rows, periods = fixture()
        tables = build_activity_tables(rows, periods)
        member = tables['average_speeches_by_member'].iloc[0]
        self.assertEqual(member.service_months, 18)
        self.assertEqual(member.service_years, 1.5)
        self.assertAlmostEqual(member.average_speeches_per_year, 5 / 1.5)
        self.assertEqual(tables['chart_speeches_by_year_mpc_role'].speech_count.sum(), 5)

    def test_zero_speech_members_and_months_contribute_to_cohort_mean(self):
        rows, periods = fixture()
        periods['Quiet Member'] = [
            period('Quiet Member', 'internal', '2020-01-01', '2021-06-30', 'Governor')]
        tables = build_activity_tables(rows, periods)
        cohort = tables['average_speeches_by_joining_year'].iloc[0]
        self.assertEqual(cohort.member_count, 2)
        self.assertAlmostEqual(cohort.average_speeches_per_year, (5 / 1.5) / 2)
        quiet = tables['average_speeches_by_member'].set_index('speaker').loc['Quiet Member']
        self.assertEqual(quiet.speech_count, 0)
        self.assertEqual(quiet.service_months, 18)

    def test_role_changes_split_exposure_but_do_not_change_joining_year(self):
        rows, periods = fixture()
        periods['Test Member'] = [
            period('Test Member', 'external', '2019-06-01', '2020-06-30', 'External member'),
            period('Test Member', 'internal', '2020-07-01', '2021-06-30', 'Deputy Governor')]
        mask = rows.speech_date.ge('2020-07-01')
        rows.loc[mask, ['mpc_member_type', 'mpc_role']] = ['internal', 'Deputy Governor']
        tables = build_activity_tables(rows, periods)
        by_type = tables['average_speeches_by_member_type'].set_index('mpc_member_type')
        self.assertEqual(by_type.loc['external', 'service_months'], 6)
        self.assertEqual(by_type.loc['internal', 'service_months'], 12)
        self.assertEqual(by_type.loc['external', 'speech_count'], 2)
        self.assertEqual(by_type.loc['internal', 'speech_count'], 3)
        self.assertEqual(set(by_type.joining_year), {2019})
        self.assertEqual(tables['average_speeches_by_member'].iloc[0].service_months, 18)
        by_role = tables['average_speeches_by_member_role'].set_index('mpc_role')
        self.assertEqual(by_role.loc['External member', 'service_months'], 6)
        self.assertEqual(by_role.loc['Deputy Governor', 'service_months'], 12)
        self.assertEqual(by_role.loc['External member', 'average_speeches_per_year'], 4)
        self.assertEqual(by_role.loc['Deputy Governor', 'average_speeches_per_year'], 3)
        for dimension in ['mpc_member_type', 'mpc_role']:
            cohort = tables[f'average_speeches_by_joining_year_{dimension}']
            self.assertEqual(set(cohort.joining_year), {2019})
            self.assertTrue(cohort.member_count.eq(1).all())
            self.assertEqual(cohort.speech_count.sum(), 5)

    def test_cohort_mean_is_unweighted_and_future_terms_are_capped(self):
        rows, periods = fixture()
        periods['Quiet Member'] = [
            period('Quiet Member', 'external', '2020-12-01', '2029-12-31', 'External member')]
        tables = build_activity_tables(rows, periods)
        members = tables['average_speeches_by_member'].set_index('speaker')
        self.assertEqual(members.loc['Quiet Member', 'service_months'], 7)
        cohort = tables['average_speeches_by_joining_year'].iloc[0]
        self.assertAlmostEqual(cohort.average_speeches_per_year, (5 / 1.5) / 2)
        for dimension in ['mpc_member_type', 'mpc_role']:
            split = tables[f'average_speeches_by_joining_year_{dimension}'].iloc[0]
            self.assertEqual(split.member_count, 2)
            self.assertAlmostEqual(split.average_speeches_per_year, (5 / 1.5) / 2)

    def test_unresolved_metadata_and_day_precision_are_rejected(self):
        rows, periods = fixture()
        with self.assertRaisesRegex(ValueError, 'Unresolved'):
            build_activity_tables(rows.assign(mpc_member_type='unresolved'), periods)
        exact = periods['Test Member'][0]
        periods['Test Member'] = [Membership(
            exact.speaker, exact.member_type, exact.start, exact.end, exact.source_url,
            role=exact.role)]
        with self.assertRaisesRegex(ValueError, 'month-precision'):
            build_activity_tables(rows, periods)

    def test_five_charts_and_eight_tables_are_saved(self):
        rows, periods = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            charts = write_activity_charts(root, rows, periods)
            self.assertEqual(len(charts), 5)
            self.assertTrue(all(path.stat().st_size > 1000 for path in charts))
            self.assertEqual(len(list(root.glob('*.csv'))), 8)


if __name__ == '__main__':
    unittest.main()
