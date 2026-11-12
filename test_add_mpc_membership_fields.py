import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

import add_mpc_membership_fields as amf
from quantify_mpc_speeches import DEFAULT_MEMBERSHIP, Membership, load_membership

ALIASES, PERIODS = load_membership(DEFAULT_MEMBERSHIP)


def speeches(*rows):
    return pd.DataFrame(rows, columns=['hyperlink', 'text', 'title', 'date'])


class EnrichTests(unittest.TestCase):
    def one(self, title, date_text, text='body'):
        return amf.enrich(speeches(('https://x/1', text, title, date_text))).iloc[0]

    def test_internal_member_years(self):
        row = self.one('Topic - speech by Huw Pill', '06/09/2023')
        self.assertEqual((row.speaker, row.mpc_member_type), ('Huw Pill', 'internal'))
        self.assertEqual(row.mpc_role, 'Chief Economist')
        self.assertEqual(row.completed_years_on_mpc, 2)
        self.assertEqual(row.years_on_mpc, 2.0)

    def test_historical_voting_window_classifies_without_inventing_tenure(self):
        row = self.one('Speech by David Miles', '27/02/2014')
        self.assertEqual(row.mpc_member_type, 'external')
        self.assertEqual(row.mpc_status, 'external')
        self.assertEqual(row.years_on_mpc, 4.67)
        self.assertEqual(row.completed_years_on_mpc, 4)
        self.assertEqual(row.completed_months_on_mpc, 56)
        self.assertEqual(row.mpc_service_start, '2009-06-01')

    def test_1997_member_alias_and_conservative_boundaries(self):
        row = self.one('Speech by Sir Edward George', '06/06/1997')
        self.assertEqual(row.speaker, 'Eddie George')
        self.assertEqual(row.mpc_member_type, 'internal')
        self.assertEqual(row.completed_months_on_mpc, 0)
        before = self.one('Speech by Eddie George', '31/05/1997')
        self.assertEqual(before.mpc_status, 'outside_recorded_tenure')

    def test_haldane_june_vote_and_weale_august_vote_are_covered(self):
        self.assertEqual(self.one('Speech by Andy Haldane', '24/06/2021').mpc_member_type, 'internal')
        self.assertEqual(self.one('Speech by Martin Weale', '05/08/2010').mpc_member_type, 'external')

    def test_single_vote_is_not_a_one_day_tenure(self):
        row = self.one('Speech by Charlotte Hogg', '16/03/2017')
        self.assertEqual(row.mpc_member_type, 'internal')
        self.assertEqual(row.completed_months_on_mpc, 0)
        self.assertEqual(row.years_on_mpc, 0.0)

    def test_uncertain_continuous_start_does_not_gain_false_precision(self):
        periods = {'Test Member': [
            Membership('Test Member', 'external', date(2000, 1, 1), date(2001, 6, 30),
                       'https://example.com/votes', 'voting_window'),
            Membership('Test Member', 'internal', date(2001, 7, 1), date(2003, 1, 1),
                       'https://example.com/appointment'),
        ]}
        result = amf.classify('Test Member', date(2002, 1, 1), periods)
        self.assertEqual(result['mpc_member_type'], 'internal')
        self.assertEqual(result['completed_years_on_mpc'], '')
        self.assertEqual(result['problem'], 'membership_appointment_dates_unverified')
        result = amf.classify('Test Member', date(2002, 1, 1), {
            'Test Member': [periods['Test Member'][1]],
        })
        self.assertEqual(result['completed_years_on_mpc'], 0)

    def test_completed_years_use_month_of_membership_not_day(self):
        row = self.one('Topic - speech by Huw Pill', '05/09/2023')
        self.assertEqual(row.completed_months_on_mpc, 24)
        self.assertEqual(row.completed_years_on_mpc, 2)

    def test_broadbent_continuous_service_and_role_change(self):
        external = self.one('X - speech by Ben Broadbent', '01/06/2012')
        internal = self.one('X - speech by Ben Broadbent', '01/07/2016')
        self.assertEqual(external.mpc_member_type, 'external')
        self.assertEqual(external.mpc_role, 'External member')
        self.assertEqual(internal.mpc_member_type, 'internal')
        self.assertEqual(internal.mpc_role, 'Deputy Governor')
        self.assertEqual(internal.mpc_service_start, '2011-06-01')
        self.assertEqual(internal.completed_years_on_mpc, 5)
        self.assertEqual(internal.completed_months_on_mpc, 61)

    def test_month_zero_and_monthly_tenure_boundaries(self):
        periods = {'Monthly Member': [Membership(
            'Monthly Member', 'external', date(2020, 3, 1), date(2022, 2, 28),
            'https://example.org', 'appointment_month', 'External member')]}
        joining = amf.classify('Monthly Member', date(2020, 3, 1), periods)
        next_month = amf.classify('Monthly Member', date(2020, 4, 30), periods)
        year_one = amf.classify('Monthly Member', date(2021, 3, 1), periods)
        self.assertEqual(joining['completed_months_on_mpc'], 0)
        self.assertEqual(joining['completed_years_on_mpc'], 0)
        self.assertEqual(next_month['completed_months_on_mpc'], 1)
        self.assertEqual(year_one['completed_months_on_mpc'], 12)
        self.assertEqual(year_one['completed_years_on_mpc'], 1)
        self.assertEqual(year_one['mpc_service_start'], '2020-03-01')

    def test_senior_role_changes_use_dated_segments_without_restarting_service(self):
        periods = {key: value for key, value in PERIODS.items()}
        for speaker, dates, roles in [
            ('Mervyn King', ['1997-06-06', '1998-06-01', '2003-07-01'],
             ['Chief Economist', 'Deputy Governor', 'Governor']),
            ('Charles Bean', ['2008-06-30', '2008-07-01'],
             ['Chief Economist', 'Deputy Governor']),
        ]:
            for value, expected in zip(dates, roles):
                result = amf.classify(speaker, date.fromisoformat(value), periods)
                self.assertEqual(result['mpc_role'], expected)
        first = amf.classify('Mervyn King', date(1997, 6, 6), periods)
        last = amf.classify('Mervyn King', date(2013, 6, 6), periods)
        self.assertEqual(first['mpc_service_start'], '1997-06-01')
        self.assertEqual(last['mpc_service_start'], '1997-06-01')

    def test_internal_member_role_label_is_preserved(self):
        row = self.one('Speech by Paul Fisher', '01/07/2011')
        self.assertEqual(row.mpc_member_type, 'internal')
        self.assertEqual(row.mpc_role, 'Internal member')

    def test_outside_tenure_is_flagged_not_guessed(self):
        row = self.one('X - speech by Andrew Bailey', '10/01/2018')
        self.assertEqual(row.mpc_status, 'outside_recorded_tenure')
        self.assertEqual(row.years_on_mpc, '')
        self.assertIn('speech_date_outside_mpc_tenure', row.review_flag)

    def test_missing_title_and_date_uses_text_and_flags(self):
        row = self.one('', '', text='Labour’s Share Speech given by Andrew G Haldane, Chief Economist')
        self.assertEqual((row.speaker, row.speaker_source), ('Andy Haldane', 'text'))
        self.assertEqual(row.mpc_status, 'unresolved')
        self.assertIn('missing_title', row.review_flag)
        self.assertIn('missing_date', row.review_flag)

    def test_honorific_and_alias(self):
        self.assertEqual(self.one('X - speech by Sir Jon Cunliffe', '01/03/2020').mpc_member_type, 'internal')
        self.assertEqual(self.one('X - speech by Catherine L Mann', '01/03/2023').mpc_member_type, 'external')

    def test_unknown_and_ambiguous_speakers(self):
        self.assertIn('speaker_not_identified', self.one('Remarks by Sam Woods', '01/03/2020').review_flag)
        self.assertIn('ambiguous_speaker',
                      self.one('Huw Pill and Megan Greene panel', '01/03/2024').review_flag)

    def test_unparseable_date(self):
        row = self.one('X - speech by Huw Pill', 'sometime')
        self.assertIn('unparseable_date', row.review_flag)
        self.assertEqual(row.mpc_status, 'unresolved')

    def test_iso_date_accepted(self):
        self.assertEqual(amf.parse_speech_date('2024-02-03'), date(2024, 2, 3))
        self.assertIsNone(amf.parse_speech_date('31/02/2024'))

    def test_url_fallback_and_missing_text(self):
        frame = speeches((
            'https://www.bankofengland.co.uk/speech/2020/jon-cunliffe-speech-event',
            '', 'Governance of financial globalisation', '11/02/2020'))
        row = amf.enrich(frame).iloc[0]
        self.assertEqual((row.speaker, row.speaker_source), ('Jon Cunliffe', 'url'))
        self.assertEqual(row.mpc_member_type, 'internal')
        self.assertEqual(row.review_flag, 'missing_text')

    def test_ambiguous_text_is_not_overridden_by_url(self):
        speaker, _, problem = amf.identify_speaker(
            'Huw Pill and Megan Greene panel', '', ALIASES,
            'https://example.com/huw-pill')
        self.assertEqual((speaker, problem), ('', 'ambiguous_speaker'))


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.source = speeches(
            ('https://a', 'original' * 10000, 'First', '01/01/2024'),
            ('https://b', 'old', 'Second', '02/01/2024'))
        self.source['keyword_1'] = ['growth', 'inflation']
        self.updates = self.source.iloc[[1]].copy()
        self.updates.loc[1, ['text', 'title']] = ['', 'Replacement']

    def test_replaces_whole_rows_preserving_order_and_other_values(self):
        original = self.source.copy()
        updated = amf.apply_updates(self.source, self.updates)
        pd.testing.assert_frame_equal(self.source, original)
        pd.testing.assert_series_equal(updated.iloc[0], original.iloc[0])
        pd.testing.assert_series_equal(updated.iloc[1], self.updates.iloc[0])
        self.assertEqual(updated.hyperlink.tolist(), original.hyperlink.tolist())

    def test_rejects_duplicate_and_unmatched_urls_and_schema_mismatch(self):
        bad_updates = [
            pd.concat([self.updates, self.updates]),
            self.updates.assign(hyperlink='https://missing'),
            self.updates.drop(columns='keyword_1'),
        ]
        for updates in bad_updates:
            with self.subTest(updates=updates.to_dict()), self.assertRaises(ValueError):
                amf.apply_updates(self.source, updates)
        with self.assertRaises(ValueError):
            amf.apply_updates(pd.concat([self.source, self.source]), self.updates)

    def test_run_preserves_long_text_and_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, updates, output = [Path(tmp) / name for name in ('s.csv', 'u.csv', 'out.csv')]
            self.source.to_csv(source, index=False)
            self.updates.to_csv(updates, index=False)
            before = [path.read_bytes() for path in (source, updates)]
            amf.run(source, output, updates_csv=updates)
            saved = pd.read_csv(output, dtype=str, keep_default_na=False)
            self.assertEqual(saved.loc[0, 'text'], self.source.loc[0, 'text'])
            self.assertEqual(saved.loc[1, 'text'], '')
            self.assertEqual(saved.loc[0, 'keyword_1'], 'growth')
            self.assertEqual(before, [path.read_bytes() for path in (source, updates)])
            for protected in (source, updates, DEFAULT_MEMBERSHIP):
                with self.assertRaises(ValueError):
                    amf.run(source, protected, updates_csv=updates)


class ReadTests(unittest.TestCase):
    def test_reads_by_header_skips_fragments_and_empty_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 's.csv'
            path.write_text(
                'hyperlink,text,title,date,,,\n'
                'https://a,"body, with comma",T1 - speech by Huw Pill,01/01/2024,,,\n'
                'https://b,truncated\n'
                'tail of text,0.5,more,,,,\n',
                encoding='utf-8')
            frame, skipped = amf.read_speeches(path)
            self.assertEqual(len(frame), 2)
            self.assertEqual(skipped, 1)
            self.assertEqual(frame.loc[0, 'text'], 'body, with comma')
            out = Path(tmp) / 'out.csv'
            amf.run(path, out)
            self.assertTrue(out.exists())
            with self.assertRaises(ValueError):
                amf.run(path, path)

    def test_reads_windows_1252_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 's.csv'
            path.write_bytes('hyperlink,text,title,date\nhttps://a,‘quoted’,T - speech by Huw Pill,01/01/2024\n'
                             .encode('cp1252'))
            frame, _ = amf.read_speeches(path)
            self.assertEqual(frame.loc[0, 'text'], '‘quoted’')

    def test_missing_required_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 's.csv'
            path.write_text('hyperlink,text,title\nhttps://a,b,c\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                amf.read_speeches(path)


if __name__ == '__main__':
    unittest.main()
