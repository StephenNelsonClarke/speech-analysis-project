from __future__ import annotations

import json
import contextlib
import io
import tempfile
import unittest
import warnings
from calendar import monthrange
from datetime import datetime
from pathlib import Path

import pandas as pd

from quantify_mpc_speeches import DEFAULT_MEMBERSHIP, build_reports, load_membership, run_analysis


def speech(**overrides: str) -> dict[str, str]:
    return {
        'speech_id': 'test-speech',
        'year': '2024',
        'date': '2024-05-01',
        'speaker': 'Andrew Bailey',
        'primary_theme': 'inflation_and_prices',
        'primary_theme_label': 'Inflation & prices',
        'top_themes': "['Inflation & prices', 'Labour market', 'Growth & output']",
        'llm_primary_theme': 'monetary_policy_rates',
        'llm_secondary_themes': 'inflation_and_prices; labour_market',
        **overrides,
    }


class QuantitativeAnalysisTests(unittest.TestCase):
    def reports(self, *rows: dict[str, str]):
        return build_reports(pd.DataFrame(rows), DEFAULT_MEMBERSHIP)

    def test_totals_and_secondary_counting(self):
        reports, summary = self.reports(
            speech(),
            speech(speech_id='second', year='2025', date='2025-03-01', speaker='Megan Greene',
                   top_themes='["Inflation & prices", "Labour market", "Labour market"]',
                   llm_secondary_themes='monetary_policy_rates; labour_market; labour_market'),
        )
        self.assertEqual(summary['speech_rows'], 2)
        for name in ['speeches_by_year', 'speeches_by_speaker', 'speeches_by_mpc_member_type']:
            self.assertEqual(reports[name]['speech_count'].sum(), 2)
        themes = reports['theme_counts'].set_index(['method', 'theme_role', 'theme_key'])['speech_count']
        self.assertEqual(themes['keyword', 'primary', 'inflation_and_prices'], 2)
        self.assertEqual(themes['llm', 'primary', 'monetary_policy_rates'], 2)
        self.assertEqual(themes['keyword', 'secondary', 'labour_market'], 2)
        self.assertEqual(themes['keyword', 'secondary', 'inflation_and_prices'], 0)
        self.assertEqual(themes['llm', 'secondary', 'monetary_policy_rates'], 0)
        self.assertEqual(themes['llm', 'secondary', 'labour_market'], 2)
        self.assertEqual(themes['keyword', 'primary', 'financial_conditions'], 0)
        self.assertEqual(reports['theme_counts_by_speaker'].query(
            "speaker == 'Megan Greene' and method == 'llm' and theme_role == 'primary'"
        )['speech_count'].sum(), 1)

    def test_monthly_appointment_is_reported_with_monthly_basis(self):
        reports, summary = self.reports(speech(speaker='David Miles', year='2014', date='2014-02-27'))
        row = reports['annotated_speeches'].iloc[0]
        self.assertEqual(row.mpc_member_type, 'external')
        self.assertEqual(row.mpc_membership_reason, 'matched_monthly_appointment')
        self.assertNotIn('membership_appointment_dates_unverified', summary['quality_issue_counts'])

    def test_monthly_membership_date_basis_and_role_are_reported(self):
        reports, _ = self.reports(speech(speaker='Mervyn King', year='2003', date='2003-07-01'))
        row = reports['annotated_speeches'].iloc[0]
        self.assertEqual(row.mpc_membership_reason, 'matched_monthly_appointment')
        self.assertEqual(row.mpc_role, 'Governor')

    def test_monthly_reference_ranges_cover_entire_inclusive_months(self):
        reports, _ = self.reports(
            speech(speaker='Huw Pill', year='2021', date='2021-09-01'),
            speech(speech_id='second', speaker='Huw Pill', year='2027', date='2027-09-30'),
            speech(speech_id='third', speaker='Huw Pill', year='2021', date='2021-08-31'),
        )
        self.assertEqual(reports['annotated_speeches']['mpc_member_type'].tolist(),
                         ['internal', 'internal', 'outside_recorded_tenure'])

    def test_role_is_derived_for_external_and_time_varying_internal_members(self):
        reports, _ = self.reports(
            speech(speaker='Ben Broadbent', year='2012', date='2012-01-01'),
            speech(speech_id='second', speaker='Ben Broadbent', year='2016', date='2016-01-01'),
            speech(speech_id='third', speaker='Mervyn King', year='2004', date='2004-01-01'),
            speech(speech_id='fourth', speaker='Paul Fisher', year='2011', date='2011-07-01'),
        )
        self.assertEqual(reports['annotated_speeches']['mpc_role'].tolist(),
                         ['External member', 'Deputy Governor', 'Governor', 'Internal member'])
        self.assertEqual(reports['speeches_by_mpc_role']['speech_count'].sum(), 4)
        self.assertEqual(reports['theme_counts_by_mpc_role']['speech_count'].sum(), 24)

    def test_membership_evidence_basis_is_validated(self):
        frame = pd.read_csv(DEFAULT_MEMBERSHIP, dtype=str, keep_default_na=False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'reference.csv'
            frame.loc[0, 'date_basis'] = 'estimated'
            frame.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, 'Invalid membership date basis'):
                load_membership(path)
            frame = pd.read_csv(DEFAULT_MEMBERSHIP, dtype=str, keep_default_na=False)
            frame.loc[0, 'mpc_role'] = 'Executive Director'
            frame.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, 'Invalid MPC role'):
                load_membership(path)
            frame.drop(columns=['date_basis', 'mpc_role', 'notes'], errors='ignore', inplace=True)
            for column, end in [('start_date', False), ('end_date', True)]:
                frame[column] = frame[column].map(
                    lambda value: datetime.strptime(
                        f'{value}-01' if not end else
                        f'{value}-{monthrange(*map(int, value.split("-")))[1]}',
                        '%Y-%m-%d').strftime('%d/%m/%Y')
                    if len(value) == 7 else value)
            frame.to_csv(path, index=False)
            _, periods = load_membership(path)
            self.assertTrue(all(p.date_basis == 'appointment' for ps in periods.values() for p in ps))

    def test_membership_dates_accept_user_day_month_year_format_and_internal_role(self):
        frame = pd.read_csv(DEFAULT_MEMBERSHIP, dtype=str, keep_default_na=False)
        for column, end in [('start_date', False), ('end_date', True)]:
            frame[column] = frame[column].map(
                lambda value: datetime.strptime(
                    f'{value}-01' if not end else
                    f'{value}-{monthrange(*map(int, value.split("-")))[1]}',
                    '%Y-%m-%d').strftime('%d/%m/%Y')
                if len(value) == 7 else value)
        frame.loc[frame.speaker.eq('Paul Fisher'), 'mpc_role'] = 'Internal members'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'reference.csv'
            frame.to_csv(path, index=False)
            _, periods = load_membership(path)
        paul = periods['Paul Fisher'][0]
        self.assertEqual(paul.start.isoformat(), '2009-03-01')
        self.assertEqual(paul.role, 'Internal member')

    def test_role_change_and_inclusive_boundaries(self):
        rows = [
            speech(speech_id=str(index), speaker='Ben Broadbent', year=day[:4], date=day)
            for index, day in enumerate(['2011-05-31', '2011-06-01', '2014-06-30',
                                         '2014-07-01', '2024-06-30', '2024-07-01'])
        ]
        reports, _ = self.reports(*rows)
        self.assertEqual(reports['annotated_speeches']['mpc_member_type'].tolist(),
                         ['outside_recorded_tenure', 'external', 'external',
                          'internal', 'internal', 'outside_recorded_tenure'])

    def test_breeden_before_mpc_appointment(self):
        reports, _ = self.reports(
            speech(speaker='Sarah Breeden', year='2023', date='2023-10-31'),
            speech(speech_id='second', speaker='Sarah Breeden', year='2023', date='2023-11-01'),
        )
        self.assertEqual(reports['annotated_speeches']['mpc_member_type'].tolist(),
                         ['outside_recorded_tenure', 'internal'])

    def test_speaker_aliases_and_no_fuzzy_event_matching(self):
        reports, _ = self.reports(
            speech(speaker='Dr. Catherine L Mann'),
            speech(speech_id='2', speaker='Catherine Mann'),
            speech(speech_id='3', speaker='Sir David Ramsden'),
            speech(speech_id='4', speaker='Alan Taylor At National University Of Singapore'),
        )
        self.assertEqual(reports['annotated_speeches']['canonical_speaker'].tolist(),
                         ['Catherine L. Mann', 'Catherine L. Mann', 'Dave Ramsden',
                          'Alan Taylor At National University Of Singapore'])
        self.assertEqual(reports['annotated_speeches']['mpc_member_type'].tolist(),
                         ['external', 'external', 'internal', 'unresolved'])

    def test_missing_dates_are_not_inferred_from_year(self):
        reports, _ = self.reports(speech(date=''))
        row = reports['annotated_speeches'].iloc[0]
        self.assertEqual(row['analysis_year'], '2024')
        self.assertEqual(row['mpc_member_type'], 'unresolved')
        self.assertEqual(row['mpc_membership_reason'], 'missing_or_invalid_date')

    def test_invalid_metadata_is_flagged_and_rows_preserved(self):
        reports, summary = self.reports(
            speech(date='not a date', year='', speaker='Unknown'),
            speech(speech_id='2', date='2024-02-30', year='bad', speaker=''),
            speech(speech_id='3', date='2023-05-01', year='2024'),
            speech(speech_id='4', date='2024-05-01', year='2024.0'),
        )
        self.assertEqual(summary['speech_rows'], 4)
        self.assertEqual(reports['speeches_by_year'].set_index('year').loc['Unknown', 'speech_count'], 2)
        self.assertEqual(reports['speeches_by_speaker'].set_index('speaker').loc['Unknown speaker', 'speech_count'], 2)
        self.assertEqual(reports['annotated_speeches']['mpc_member_type'].tolist(),
                         ['unresolved', 'unresolved', 'unresolved', 'internal'])
        self.assertEqual(summary['quality_issue_counts']['date_year_conflict'], 1)

    def test_duplicate_ids_do_not_multiply_or_remove_rows(self):
        reports, summary = self.reports(speech(), speech(speaker='Megan Greene'))
        self.assertEqual(summary['duplicate_id_groups'], 1)
        self.assertEqual(summary['quality_issue_counts']['duplicate_speech_id'], 2)
        self.assertEqual(len(reports['annotated_speeches']), 2)
        self.assertEqual(reports['theme_counts'].query(
            "method == 'llm' and theme_role == 'primary'"
        )['speech_count'].sum(), 2)

    def test_missing_primary_is_explicit_and_secondary_is_excluded(self):
        reports, summary = self.reports(
            speech(primary_theme='', primary_theme_label='', llm_primary_theme=''),
        )
        self.assertEqual(summary['theme_coverage']['llm']['unclassified_primary_rows'], 1)
        self.assertEqual(summary['theme_coverage']['keyword']['rows_with_secondary_themes'], 0)
        themes = reports['theme_counts']
        self.assertEqual(themes.query("theme_key == 'unclassified'")['speech_count'].sum(), 2)
        self.assertEqual(themes.query("theme_role == 'secondary'")['speech_count'].sum(), 0)

    def test_empty_secondary_lists_are_valid(self):
        reports, summary = self.reports(speech(top_themes='[]', llm_secondary_themes=''))
        self.assertEqual(reports['theme_counts'].query("theme_role == 'secondary'")['speech_count'].sum(), 0)
        self.assertEqual(summary['theme_coverage']['llm']['classified_primary_rows'], 1)

    def test_primary_label_fallback(self):
        row = speech()
        del row['primary_theme']
        reports, _ = self.reports(row)
        self.assertEqual(reports['annotated_speeches'].iloc[0]['analysis_keyword_primary'], 'inflation_and_prices')

    def test_invalid_themes_and_conflicting_primary_fail(self):
        for overrides in [
            {'llm_primary_theme': 'unknown_theme'},
            {'llm_secondary_themes': 'unknown_theme'},
            {'top_themes': '[malformed'},
            {'top_themes': '[1, 2]'},
            {'primary_theme_label': 'Growth & output'},
        ]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.reports(speech(**overrides))

    def test_missing_columns_and_empty_database_fail(self):
        with self.assertRaisesRegex(ValueError, 'missing columns'):
            build_reports(pd.DataFrame([{'speech_id': 'only-id'}]), DEFAULT_MEMBERSHIP)
        with self.assertRaisesRegex(ValueError, 'no speech rows'):
            build_reports(pd.DataFrame([speech()]).iloc[:0], DEFAULT_MEMBERSHIP)
        with self.assertRaisesRegex(ValueError, 'already contains'):
            self.reports(speech(canonical_speaker='Andrew Bailey'))

    def test_reference_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'members.csv'
            rows = [
                {'speaker': 'One', 'member_type': 'internal', 'start_date': '2020-01-01',
                 'end_date': '2021-01-01', 'aliases': '', 'source_url': 'https://example.org'},
                {'speaker': 'One', 'member_type': 'external', 'start_date': '2021-01-01',
                 'end_date': '2022-01-01', 'aliases': '', 'source_url': 'https://example.org'},
            ]
            pd.DataFrame(rows).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, 'Overlapping'):
                load_membership(path)
            rows[1]['speaker'] = 'Two'
            rows[1]['aliases'] = 'One'
            pd.DataFrame(rows).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                load_membership(path)

    def test_persistent_outputs_reconcile_and_input_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'database.csv'
            output = root / 'reports'
            pd.DataFrame([speech(), speech(speech_id='2', date='')]).to_csv(database, index=False)
            original = database.read_bytes()
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                summary = run_analysis(database, output)
            self.assertTrue(any('quality flags' in str(item.message) for item in caught))
            self.assertEqual(database.read_bytes(), original)
            self.assertEqual(json.loads((output / 'quantitative_summary.json').read_text())['speech_rows'], 2)
            self.assertTrue((output / 'membership_reference_used.csv').exists())
            themes = pd.read_csv(output / 'theme_counts.csv')
            for method in ['keyword', 'llm']:
                self.assertEqual(themes.query(
                    "method == @method and theme_role == 'primary'"
                )['speech_count'].sum(), summary['speech_rows'])
            self.assertEqual(pd.read_csv(output / 'speeches_by_mpc_member_type.csv')['speech_count'].sum(), 2)
            self.assertEqual(len(list(output.glob('*.csv'))), 14)

    def test_input_overwrite_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'annotated_speeches.csv'
            pd.DataFrame([speech()]).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                run_analysis(path, root)

    def test_notebook_cells_and_charts(self):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        notebook_path = Path(__file__).with_name('quantitative_speech_report.ipynb')
        notebook = json.loads(notebook_path.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'database.csv'
            output = root / 'reports'
            pd.DataFrame([speech(), speech(speech_id='2', speaker='Megan Greene')]).to_csv(database, index=False)
            original = database.read_bytes()
            namespace = {'__name__': '__main__'}
            with contextlib.redirect_stdout(io.StringIO()):
                for index, cell in enumerate(notebook['cells']):
                    if cell['cell_type'] != 'code':
                        continue
                    source = ''.join(cell['source'])
                    if index == 1:
                        source = source.replace(
                            "DATABASE_CSV = PROJECT_ROOT / 'outputs' / 'full_run' / 'mpc_speech_database_with_llm.csv'",
                            f'DATABASE_CSV = Path({str(database)!r})',
                        ).replace(
                            "OUTPUT_ROOT = PROJECT_ROOT / 'outputs' / 'full_run' / 'quantitative'",
                            f'OUTPUT_ROOT = Path({str(output)!r})',
                        )
                    exec(compile(source, f'{notebook_path.name}:cell-{index}', 'exec'), namespace)
            self.assertEqual(database.read_bytes(), original)
            self.assertEqual(len(list(output.glob('*.csv'))), 14)
            self.assertEqual(len(list(output.glob('*.png'))), 4)
            for chart in output.glob('*.png'):
                self.assertGreater(chart.stat().st_size, 1000)
            self.assertEqual(namespace['cross_tab'].to_numpy().sum(), 2)
            plt.close('all')


if __name__ == '__main__':
    unittest.main()
