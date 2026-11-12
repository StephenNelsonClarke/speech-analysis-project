import tempfile
import unittest
from pathlib import Path

import pandas as pd

from llm_report_charts import build_chart_tables, write_llm_charts


def annotations():
    return pd.DataFrame([
        {'analysis_year': '2023', 'mpc_member_type': 'internal',
         'completed_years_on_mpc': '0', 'years_on_mpc': '0.9',
         'analysis_llm_primary': 'inflation_and_prices',
         'analysis_llm_secondary': '["labour_market", "labour_market", "inflation_and_prices"]',
         'keyword_1': 'climate', 'analysis_keyword_primary': 'climate_sustainability'},
        {'analysis_year': '2024', 'mpc_member_type': 'external',
         'completed_years_on_mpc': '2', 'years_on_mpc': '2.7',
         'analysis_llm_primary': 'monetary_policy_rates', 'analysis_llm_secondary': '[]',
         'keyword_1': 'climate', 'analysis_keyword_primary': 'climate_sustainability'},
        {'analysis_year': '2024', 'mpc_member_type': 'internal',
         'completed_years_on_mpc': '2', 'years_on_mpc': '2.1',
         'analysis_llm_primary': 'inflation_and_prices',
         'analysis_llm_secondary': '["labour_market", "growth_output"]',
         'keyword_1': 'climate', 'analysis_keyword_primary': 'climate_sustainability'},
    ])


class LLMChartTests(unittest.TestCase):
    def test_exact_counts_roles_membership_and_completed_tenure(self):
        tables = build_chart_tables(annotations())
        tenure = tables['llm_themes_by_completed_mpc_years']
        self.assertEqual(set(tenure.completed_years_on_mpc), {0, 2})
        counts = tenure.set_index(['completed_years_on_mpc', 'theme_role', 'theme_key']).speech_count
        self.assertEqual(counts[0, 'primary', 'inflation_and_prices'], 1)
        self.assertEqual(counts[0, 'secondary', 'labour_market'], 1)
        self.assertEqual(counts[2, 'secondary', 'growth_output'], 1)
        for name, table in tables.items():
            if name.startswith('llm_themes_by_'):
                self.assertEqual(table.loc[table.theme_role.eq('primary'), 'speech_count'].sum(), 3)
                self.assertEqual(table.loc[table.theme_role.eq('secondary'), 'speech_count'].sum(), 3)
                self.assertEqual(table.loc[table.theme_role.eq('total'), 'speech_count'].sum(), 6)
        joint = tables['llm_themes_by_year_member_type']
        self.assertEqual(joint.query(
            'year == 2024 and mpc_member_type == "external" and theme_role == "primary"'
        ).speech_count.sum(), 1)
        self.assertEqual(tables['chart_speeches_by_year_member_type'].speech_count.sum(), 3)
        total = tenure.loc[tenure.theme_role.eq('total')].set_index(
            ['completed_years_on_mpc', 'theme_key']).speech_count
        self.assertEqual(total[0, 'inflation_and_prices'], 1)
        self.assertEqual(total[0, 'labour_market'], 1)
        split = tables['llm_themes_by_completed_mpc_years_member_type']
        self.assertEqual(split.query(
            'completed_years_on_mpc == 2 and mpc_member_type == "external" and theme_role == "total"'
        ).speech_count.sum(), 1)

    def test_member_percentages_use_speeches_not_theme_assignments(self):
        table = build_chart_tables(annotations())['llm_theme_percentages_by_member_type']
        table = table.set_index(['mpc_member_type', 'theme_role', 'theme_key'])
        self.assertEqual(table.loc[('internal', 'total', 'inflation_and_prices'), 'speech_count'], 2)
        self.assertEqual(table.loc[('internal', 'total', 'inflation_and_prices'), 'group_speech_count'], 2)
        pct = table['share_of_member_type_speeches_pct']
        self.assertEqual(pct['internal', 'total', 'inflation_and_prices'], 100)
        self.assertEqual(pct['internal', 'total', 'growth_output'], 50)
        self.assertEqual(pct['external', 'primary', 'monetary_policy_rates'], 100)
        self.assertEqual(pct['external', 'total', 'labour_market'], 0)
        self.assertEqual(pct.loc[('internal', 'secondary')].sum(), 150)
        self.assertEqual(pct.loc[('internal', 'total')].sum(), 250)
        self.assertTrue(pct.between(0, 100).all())

    def test_absent_member_type_has_no_percentage_denominator(self):
        table = build_chart_tables(annotations().iloc[[0]])['llm_theme_percentages_by_member_type']
        self.assertEqual(set(table.mpc_member_type), {'internal'})
        self.assertTrue(table.group_speech_count.eq(1).all())
        self.assertFalse(table.share_of_member_type_speeches_pct.isna().any())

    def test_keyword_columns_do_not_affect_tables(self):
        source = annotations()
        first = build_chart_tables(source)
        second = build_chart_tables(source.assign(
            keyword_1='anything', analysis_keyword_primary='global_economy_trade'))
        for name in first:
            pd.testing.assert_frame_equal(first[name], second[name])

    def test_missing_primary_excludes_secondary(self):
        frame = annotations().iloc[[0]].copy()
        frame['analysis_llm_primary'] = ''
        table = build_chart_tables(frame)['llm_themes_by_year']
        primary = table.loc[table.theme_role.eq('primary')]
        self.assertEqual(primary.theme_key.tolist(), ['unclassified'])
        self.assertEqual(primary.speech_count.tolist(), [1])
        self.assertFalse(table.theme_role.eq('secondary').any())
        self.assertEqual(set(table.loc[table.theme_role.eq('total'), 'theme_key']),
                         {'labour_market', 'inflation_and_prices'})

    def test_invalid_metadata_is_explicit(self):
        for column, value in [
            ('completed_years_on_mpc', ''), ('completed_years_on_mpc', '-1'),
            ('completed_years_on_mpc', '0.9'), ('mpc_member_type', 'unresolved'),
            ('analysis_year', 'Unknown'), ('analysis_llm_secondary', '["invalid"]'),
        ]:
            with self.subTest(column=column, value=value), self.assertRaises(ValueError):
                build_chart_tables(annotations().assign(**{column: value}))

    def test_group_percentages_use_exact_group_denominators(self):
        tables = build_chart_tables(annotations().assign(year='1999'))
        for suffix in ['year', 'year_member_type', 'completed_mpc_years',
                       'completed_mpc_years_member_type']:
            table = tables[f'llm_theme_percentages_by_{suffix}']
            self.assertTrue(table.share_of_group_speeches_pct.between(0, 100).all())
            self.assertFalse(table.share_of_group_speeches_pct.isna().any())
            dimensions = [c for c in ['year', 'completed_years_on_mpc', 'mpc_member_type']
                          if c in table]
            sums = table.loc[table.theme_role.eq('primary')].groupby(
                dimensions).share_of_group_speeches_pct.sum()
            self.assertTrue(sums.eq(100).all())
        table = tables['llm_theme_percentages_by_completed_mpc_years']
        row = table.query('completed_years_on_mpc == 2 and theme_role == "total" '
                          'and theme_key == "inflation_and_prices"').iloc[0]
        self.assertEqual(row.group_speech_count, 2)
        self.assertEqual(row.share_of_group_speeches_pct, 50)
        self.assertNotIn(1, table.completed_years_on_mpc.values)

    def test_charts_tables_and_empty_secondary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = annotations().assign(analysis_llm_secondary='[]')
            path = root / 'annotated_speeches.csv'
            source.to_csv(path, index=False)
            original = path.read_bytes()
            charts = write_llm_charts(root)
            self.assertEqual(len(charts), 31)
            self.assertEqual(len(list(root.glob('*.csv'))), 12)
            self.assertTrue(all(path.stat().st_size > 1000 for path in charts))
            self.assertEqual(path.read_bytes(), original)
            for role in ['primary', 'secondary', 'total']:
                for suffix in ['year', 'year_member_type', 'member_type', 'completed_mpc_years',
                               'completed_mpc_years_member_type', 'member_type_pct',
                               'year_pct', 'year_member_type_pct', 'completed_mpc_years_pct',
                               'completed_mpc_years_member_type_pct']:
                    self.assertTrue((root / f'llm_{role}_themes_by_{suffix}.png').exists())


if __name__ == '__main__':
    unittest.main()
