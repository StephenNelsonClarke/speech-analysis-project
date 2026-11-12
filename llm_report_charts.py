from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from analyze_mpc_speeches import THEMES
from quantify_mpc_speeches import count_rows

THEME_LABELS = {key: meta['label'] for key, meta in THEMES.items()}
THEME_LABELS['unclassified'] = 'Unclassified'
MEMBERS = ['internal', 'external']
ROLES = ['primary', 'secondary', 'total']


def build_chart_tables(annotated: pd.DataFrame) -> dict[str, pd.DataFrame]:
    required = {'analysis_year', 'mpc_member_type', 'completed_years_on_mpc',
                'analysis_llm_primary', 'analysis_llm_secondary'}
    if not required.issubset(annotated.columns):
        raise ValueError(f'Chart input is missing columns: {sorted(required - set(annotated.columns))}')
    if annotated.empty:
        raise ValueError('Chart input contains no speeches.')
    rows = []
    for index, row in annotated.iterrows():
        member = row['mpc_member_type']
        if member not in MEMBERS:
            raise ValueError(f'Row {index + 1}: membership must be internal or external for these charts.')
        tenure = str(row['completed_years_on_mpc'])
        if not tenure.isdigit():
            raise ValueError(f'Row {index + 1}: completed MPC years must be a nonnegative integer.')
        year = str(row['analysis_year'])
        if not year.isdigit() or len(year) != 4:
            raise ValueError(f'Row {index + 1}: chart year must be a four-digit year.')
        primary = row['analysis_llm_primary']
        secondary = json.loads(row['analysis_llm_secondary'])
        if primary and primary not in THEMES:
            raise ValueError(f'Row {index + 1}: invalid LLM primary theme.')
        if not isinstance(secondary, list) or not all(isinstance(key, str) and key in THEMES
                                                     for key in secondary):
            raise ValueError(f'Row {index + 1}: invalid LLM secondary themes.')
        base = {'year': int(year), 'mpc_member_type': member, 'completed_years_on_mpc': int(tenure)}
        rows.append({**base, 'theme_role': 'primary', 'theme_key': primary or 'unclassified'})
        if primary:
            for key in dict.fromkeys(secondary):
                if key != primary:
                    rows.append({**base, 'theme_role': 'secondary', 'theme_key': key})
        for key in dict.fromkeys(([primary] if primary else []) + secondary):
            rows.append({**base, 'theme_role': 'total', 'theme_key': key})
    assignments = pd.DataFrame(rows)
    tables = {}
    for suffix, dimensions in [
        ('year', ['year']),
        ('year_member_type', ['year', 'mpc_member_type']),
        ('member_type', ['mpc_member_type']),
        ('completed_mpc_years', ['completed_years_on_mpc']),
        ('completed_mpc_years_member_type', ['completed_years_on_mpc', 'mpc_member_type']),
    ]:
        table = count_rows(assignments, [*dimensions, 'theme_role', 'theme_key'])
        table['theme_label'] = table['theme_key'].map(THEME_LABELS)
        tables[f'llm_themes_by_{suffix}'] = table
    member_year = annotated[['analysis_year', 'mpc_member_type']].rename(
        columns={'analysis_year': 'year'}).copy()
    member_year['year'] = member_year['year'].astype(int)
    tables['chart_speeches_by_year_member_type'] = count_rows(member_year, ['year', 'mpc_member_type'])
    denominators = annotated.groupby('mpc_member_type').size()
    keys = list(THEMES)
    if annotated.analysis_llm_primary.eq('').any():
        keys.append('unclassified')
    grid = pd.MultiIndex.from_product(
        [[member for member in MEMBERS if member in denominators], ROLES, keys],
        names=['mpc_member_type', 'theme_role', 'theme_key'],
    )
    percentages = tables['llm_themes_by_member_type'].set_index(
        ['mpc_member_type', 'theme_role', 'theme_key']).reindex(grid).reset_index()
    percentages['speech_count'] = percentages['speech_count'].fillna(0).astype(int)
    percentages['theme_label'] = percentages['theme_key'].map(THEME_LABELS)
    percentages['group_speech_count'] = percentages['mpc_member_type'].map(denominators).astype(int)
    percentages['share_of_member_type_speeches_pct'] = (
        100 * percentages['speech_count'] / percentages['group_speech_count']
    )
    tables['llm_theme_percentages_by_member_type'] = percentages
    metadata = annotated[['analysis_year', 'mpc_member_type', 'completed_years_on_mpc']].rename(
        columns={'analysis_year': 'year'}).copy()
    metadata['year'] = metadata['year'].astype(int)
    metadata['completed_years_on_mpc'] = metadata['completed_years_on_mpc'].astype(int)
    for suffix, dimensions in [
        ('year', ['year']),
        ('year_member_type', ['year', 'mpc_member_type']),
        ('completed_mpc_years', ['completed_years_on_mpc']),
        ('completed_mpc_years_member_type', ['completed_years_on_mpc', 'mpc_member_type']),
    ]:
        groups = metadata.groupby(dimensions).size().rename('group_speech_count').reset_index()
        grid = groups.merge(pd.DataFrame({'theme_role': ROLES}), how='cross').merge(
            pd.DataFrame({'theme_key': keys}), how='cross')
        percentages = grid.merge(
            tables[f'llm_themes_by_{suffix}'].drop(columns='theme_label'),
            on=[*dimensions, 'theme_role', 'theme_key'], how='left')
        percentages['speech_count'] = percentages['speech_count'].fillna(0).astype(int)
        percentages['theme_label'] = percentages['theme_key'].map(THEME_LABELS)
        percentages['share_of_group_speeches_pct'] = (
            100 * percentages['speech_count'] / percentages['group_speech_count'])
        tables[f'llm_theme_percentages_by_{suffix}'] = percentages
    return tables


def write_llm_charts(output_root: Path) -> list[Path]:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    annotated = pd.read_csv(output_root / 'annotated_speeches.csv', dtype=str, keep_default_na=False)
    tables = build_chart_tables(annotated)
    for name, table in tables.items():
        table.to_csv(output_root / f'{name}.csv', index=False)
    years = sorted(annotated.analysis_year.astype(int).unique())
    tenures = range(int(annotated.completed_years_on_mpc.astype(int).max()) + 1)
    theme_keys = list(THEMES)
    if annotated.analysis_llm_primary.eq('').any():
        theme_keys.append('unclassified')
    colors = dict(zip(THEMES, plt.get_cmap('tab10').colors))
    colors['unclassified'] = (0.65, 0.65, 0.65)
    paths = []

    def save(fig, name, note=''):
        if note:
            fig.text(0.01, 0.01, note, fontsize=9)
        fig.tight_layout(rect=(0, 0.045, 1, 1))
        path = output_root / f'{name}.png'
        fig.savefig(path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        paths.append(path)

    def theme_table(table, dimension, index):
        return table.pivot(index=dimension, columns='theme_key', values='speech_count').reindex(
            index=index, columns=theme_keys).fillna(0).astype(int)

    def plot_themes(table, ax, title, xlabel):
        table.rename(columns=THEME_LABELS).plot.bar(
            stacked=True, ax=ax, color=[colors[key] for key in table.columns], width=0.8, legend=False)
        ax.set(title=title, xlabel=xlabel, ylabel='Speech count / theme assignments')
        ax.tick_params(axis='x', rotation=0)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))

    def legend(ax):
        handles = [plt.Rectangle((0, 0), 1, 1, color=colors[key]) for key in theme_keys]
        ax.legend(handles, [THEME_LABELS[key] for key in theme_keys],
                  bbox_to_anchor=(1.02, 1), loc='upper left', title='LLM theme')

    counts = tables['chart_speeches_by_year_member_type'].pivot(
        index='year', columns='mpc_member_type', values='speech_count').reindex(
            index=years, columns=MEMBERS).fillna(0)
    fig, ax = plt.subplots(figsize=(12, 5))
    counts.rename(columns={'internal': 'Internal', 'external': 'External'}).plot.bar(
        stacked=True, ax=ax, color=['#336699', '#dd8844'], rot=0)
    ax.set(title='Speeches per year by MPC membership', xlabel='Year', ylabel='Speech count')
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    save(fig, 'speeches_by_year_internal_external')

    for role in ROLES:
        note = ('Counts describe the supplied speech corpus, not speaking rates per member.'
                if role == 'primary' else
                ('Secondary themes exclude the primary. ' if role == 'secondary' else
                 'Total themes combine primary and secondary. ') +
                'Each theme counts once per speech. '
                'Stack totals can exceed speech counts.')
        for suffix, dimension, index, xlabel in [
            ('year', 'year', years, 'Year'),
            ('member_type', 'mpc_member_type', MEMBERS, 'MPC membership'),
            ('completed_mpc_years', 'completed_years_on_mpc', tenures, 'Completed years on MPC'),
        ]:
            table = tables[f'llm_themes_by_{suffix}']
            table = table.loc[table.theme_role.eq(role)]
            fig, ax = plt.subplots(figsize=(14, 7))
            plot_themes(theme_table(table, dimension, index), ax,
                        f'LLM {role} themes by {xlabel.lower()}', xlabel)
            legend(ax)
            save(fig, f'llm_{role}_themes_by_{suffix}', note)

        for suffix, dimension, index, xlabel in [
            ('year_member_type', 'year', years, 'Year'),
            ('completed_mpc_years_member_type', 'completed_years_on_mpc', tenures,
             'Completed years on MPC'),
        ]:
            table = tables[f'llm_themes_by_{suffix}']
            fig, axes = plt.subplots(1, 2, figsize=(18, 7), sharey=True)
            for member, ax in zip(MEMBERS, axes):
                selected = table.loc[table.theme_role.eq(role) & table.mpc_member_type.eq(member)]
                plot_themes(theme_table(selected, dimension, index), ax,
                            member.title() + ' members', xlabel)
            fig.suptitle(f'LLM {role} themes by {xlabel.lower()} and MPC membership')
            legend(axes[-1])
            save(fig, f'llm_{role}_themes_by_{suffix}', note)

        table = tables['llm_theme_percentages_by_member_type']
        selected = table.loc[table.theme_role.eq(role)]
        percentages = selected.pivot(
            index='theme_key', columns='mpc_member_type', values='share_of_member_type_speeches_pct'
        ).reindex(index=theme_keys, columns=[member for member in MEMBERS
                                           if member in selected.mpc_member_type.values])
        denominators = annotated.groupby('mpc_member_type').size()
        percentages = percentages.rename(
            index=THEME_LABELS,
            columns={member: f'{member.title()} (n={denominators[member]})'
                     for member in percentages.columns})
        fig, ax = plt.subplots(figsize=(13, 8))
        percentages.plot.barh(ax=ax, color=['#336699' if member.startswith('Internal')
                                          else '#dd8844' for member in percentages.columns])
        ax.set(title=f'LLM {role} themes: share of speeches within each member type',
               xlabel='Percentage of speeches within member type', ylabel='', xlim=(0, 100))
        from matplotlib.ticker import PercentFormatter
        ax.xaxis.set_major_formatter(PercentFormatter(xmax=100))
        percentage_note = (
            'Denominator: all speeches by the corresponding member type, not theme assignments. '
            'Each theme counts once per speech.'
        )
        if role != 'primary':
            percentage_note += ' Percentages across themes can sum to more than 100%.'
        save(fig, f'llm_{role}_themes_by_member_type_pct', percentage_note)
        for suffix, dimension, index, xlabel, split in [
            ('year', 'year', years, 'Year', False),
            ('completed_mpc_years', 'completed_years_on_mpc', tenures,
             'Completed years on MPC', False),
            ('year_member_type', 'year', years, 'Year', True),
            ('completed_mpc_years_member_type', 'completed_years_on_mpc', tenures,
             'Completed years on MPC', True),
        ]:
            data = tables[f'llm_theme_percentages_by_{suffix}']
            fig, axes = plt.subplots(1, 2 if split else 1,
                                     figsize=(18 if split else 14, 7), squeeze=False, sharey=True)
            for member, ax in zip(MEMBERS if split else [None], axes[0]):
                selected = data.loc[data.theme_role.eq(role)]
                if member:
                    selected = selected.loc[selected.mpc_member_type.eq(member)]
                values = selected.pivot(
                    index=dimension, columns='theme_key', values='share_of_group_speeches_pct'
                ).reindex(index=index, columns=theme_keys)
                # Missing groups have no denominator; leave gaps rather than inventing zero shares.
                values.rename(columns=THEME_LABELS).plot.bar(
                    stacked=True, ax=ax, color=[colors[key] for key in values.columns],
                    width=0.8, legend=False)
                ax.set(xlabel=xlabel, ylabel='Percentage of speeches within group',
                       title=f'{member.title()} members' if member else '')
                ax.tick_params(axis='x', rotation=45 if dimension == 'year' else 0)
                if dimension == 'year':
                    for label in ax.get_xticklabels():
                        label.set_horizontalalignment('right')
                ax.yaxis.set_major_formatter(PercentFormatter(xmax=100))
                if role == 'primary':
                    ax.set_ylim(0, 100)
            fig.suptitle(f'LLM {role} themes by {xlabel.lower()}'
                         + (' and MPC membership' if split else '') + ' (%)')
            legend(axes[0][-1])
            save(fig, f'llm_{role}_themes_by_{suffix}_pct',
                 'Denominator: all speeches in each displayed group, not theme assignments. '
                 'Groups with no speeches are blank. Each theme counts once per speech.'
                 + (' Secondary/total stacks can exceed 100%.' if role != 'primary' else ''))
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description='Add LLM-only charts from saved quantitative annotations.')
    parser.add_argument('--output-root', type=Path, required=True,
                        help='Existing quantitative report directory containing annotated_speeches.csv.')
    args = parser.parse_args()
    paths = write_llm_charts(args.output_root)
    print(f'Wrote {len(paths)} charts and backing CSVs to {args.output_root}')


if __name__ == '__main__':
    main()
