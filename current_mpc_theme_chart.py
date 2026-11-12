from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from quantify_mpc_speeches import DEFAULT_MEMBERSHIP, Membership, iso_date, load_membership
from theme_taxonomy_v2 import THEMES

ROOT = Path(__file__).resolve().parent
DEFAULT_REPORTS = ROOT / 'outputs' / 'combined_run_taxonomy_v2' / 'quantitative'


def build_current_member_counts(
    annotated: pd.DataFrame, periods: dict[str, list[Membership]], as_of: date,
) -> pd.DataFrame:
    required = {'canonical_speaker', 'speech_date', 'analysis_llm_primary'}
    if annotated.empty or not required.issubset(annotated.columns):
        raise ValueError('Current MPC chart requires dated, annotated LLM classifications.')
    current = {
        speaker: period for speaker, entries in periods.items()
        for period in entries if period.start <= as_of <= period.end
    }
    if not current:
        raise ValueError(f'No MPC members recorded on {as_of}.')
    counts = {}
    for row in annotated.to_dict('records'):
        speaker = row['canonical_speaker']
        speech_date = iso_date(row['speech_date'])
        if speaker not in current or speech_date > as_of:
            continue
        if not any(p.start <= speech_date <= p.end for p in periods[speaker]):
            raise ValueError(f'Speech outside recorded MPC service: {speaker}, {speech_date}.')
        theme = row['analysis_llm_primary']
        if theme not in THEMES:
            raise ValueError(f'Invalid LLM primary category for {speaker}: {theme!r}')
        counts[speaker, theme] = counts.get((speaker, theme), 0) + 1
    return pd.DataFrame([
        {'speaker': speaker, 'current_role': period.role,
         'current_member_type': period.member_type, 'membership_as_of': as_of.isoformat(),
         'theme_key': key, 'theme_label': meta['label'],
         'speech_count': counts.get((speaker, key), 0)}
        for speaker, period in current.items() for key, meta in THEMES.items()
    ])


def write_chart(reports_root: Path, membership_csv: Path, as_of: date) -> Path:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    annotated = pd.read_csv(reports_root / 'annotated_speeches.csv', dtype=str,
                            keep_default_na=False)
    _, periods = load_membership(membership_csv)
    counts = build_current_member_counts(annotated, periods, as_of)
    counts.to_csv(reports_root / 'current_mpc_speeches_by_primary_theme.csv', index=False)
    table = counts.pivot(index='speaker', columns='theme_key', values='speech_count').reindex(
        columns=list(THEMES))
    order = table.sum(axis=1).sort_values().index
    table = table.loc[order]
    fig, ax = plt.subplots(figsize=(15, 7))
    table.rename(columns={key: meta['label'] for key, meta in THEMES.items()}).plot.barh(
        stacked=True, ax=ax, color=plt.get_cmap('tab10').colors, width=0.75)
    for position, total in enumerate(table.sum(axis=1)):
        ax.text(total + 0.3, position, f'n={total}', va='center', fontsize=9)
    ax.set(title=f'Current MPC members: saved speeches by LLM primary category ({as_of:%d %B %Y})',
           xlabel='Speech count', ylabel='')
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.margins(x=0.12)
    ax.legend(title='LLM primary category', bbox_to_anchor=(1.02, 1), loc='upper left')
    dates = annotated.speech_date.map(iso_date)
    fig.text(0.01, 0.02,
             f'Corpus: {min(dates):%B %Y} to {max(dates):%B %Y}. '
             'All saved speeches during each current member\'s MPC service, not just 2026.\n'
             'One primary category per speech. Raw counts, not adjusted for length of service. '
             'Current membership follows the local membership reference.', fontsize=9)
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    path = reports_root / 'current_mpc_speeches_by_primary_theme.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f'Saved {path}: {len(table)} members, {int(table.sum().sum())} speeches.')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Chart current MPC members by v2 LLM primary theme.')
    parser.add_argument('--reports-root', type=Path, default=DEFAULT_REPORTS)
    parser.add_argument('--membership-csv', type=Path, default=DEFAULT_MEMBERSHIP)
    parser.add_argument('--as-of', type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    write_chart(args.reports_root, args.membership_csv, args.as_of)
