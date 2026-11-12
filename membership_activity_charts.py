from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from quantify_mpc_speeches import Membership, iso_date

MEMBER_TYPES = ['internal', 'external']
MPC_ROLES = ['Governor', 'Deputy Governor', 'Chief Economist', 'External member', 'Internal member']


def month_index(value: date) -> int:
    return value.year * 12 + value.month - 1


def build_activity_tables(
    annotated: pd.DataFrame, periods: dict[str, list[Membership]],
) -> dict[str, pd.DataFrame]:
    required = {'canonical_speaker', 'speech_date', 'mpc_member_type', 'mpc_role'}
    if not required.issubset(annotated.columns) or annotated.empty:
        raise ValueError('Activity charts require nonempty dated, membership-annotated speeches.')
    dates = annotated.speech_date.map(iso_date)
    first_month = min(dates).replace(month=1, day=1)
    last_month = max(dates).replace(day=1)
    lower, upper = month_index(first_month), month_index(last_month)
    counts: dict[tuple[str, str], int] = {}
    counts_by_role: dict[tuple[str, str], int] = {}
    role_counts = []
    for row, speech_date in zip(annotated.to_dict('records'), dates):
        speaker, member_type, role = row['canonical_speaker'], row['mpc_member_type'], row['mpc_role']
        if speaker not in periods or member_type not in MEMBER_TYPES or role not in MPC_ROLES:
            raise ValueError(f'Unresolved membership/role for activity chart: {speaker} on {speech_date}.')
        matches = [p for p in periods[speaker] if p.start <= speech_date <= p.end]
        if len(matches) != 1 or matches[0].member_type != member_type or matches[0].role != role:
            raise ValueError(f'Activity chart membership disagrees with reference: {speaker} on {speech_date}.')
        counts[speaker, member_type] = counts.get((speaker, member_type), 0) + 1
        counts_by_role[speaker, role] = counts_by_role.get((speaker, role), 0) + 1
        role_counts.append({'year': speech_date.year, 'mpc_role': role})

    member_type_rows, member_rows, member_role_rows = [], [], []
    for speaker, entries in sorted(periods.items()):
        by_type = {member_type: set() for member_type in MEMBER_TYPES}
        by_role = {role: set() for role in MPC_ROLES}
        for period in entries:
            if period.date_basis != 'appointment_month':
                raise ValueError('Annual speaking rates require month-precision appointment periods.')
            start = max(lower, month_index(period.start))
            end = min(upper, month_index(period.end))
            by_type[period.member_type].update(range(start, end + 1))
            if period.role not in by_role:
                raise ValueError(f'Unresolved role in membership reference for {speaker}.')
            by_role[period.role].update(range(start, end + 1))
        all_months = set().union(*by_type.values())
        if not all_months:
            continue
        if by_type['internal'] & by_type['external']:
            raise ValueError(f'Internal/external membership overlaps within a month for {speaker}.')
        join_year = min(p.start for p in entries).year
        for role, months in by_role.items():
            speeches = counts_by_role.get((speaker, role), 0)
            if speeches and not months:
                raise ValueError(f'No eligible service months for {speaker}, {role}.')
            if months:
                member_role_rows.append({
                    'speaker': speaker, 'mpc_role': role, 'joining_year': join_year,
                    'speech_count': speeches, 'service_months': len(months),
                    'service_years': len(months) / 12,
                    'average_speeches_per_year': speeches * 12 / len(months),
                })
        total_speeches = 0
        for member_type, months in by_type.items():
            speeches = counts.get((speaker, member_type), 0)
            if speeches and not months:
                raise ValueError(f'No eligible service months for {speaker}, {member_type}.')
            if not months:
                continue
            total_speeches += speeches
            member_type_rows.append({
                'speaker': speaker, 'mpc_member_type': member_type,
                'joining_year': join_year, 'speech_count': speeches,
                'service_months': len(months), 'service_years': len(months) / 12,
                'average_speeches_per_year': speeches * 12 / len(months),
            })
        member_rows.append({
            'speaker': speaker, 'joining_year': join_year, 'speech_count': total_speeches,
            'service_months': len(all_months), 'service_years': len(all_months) / 12,
            'average_speeches_per_year': total_speeches * 12 / len(all_months),
        })
    member_type = pd.DataFrame(member_type_rows)
    members = pd.DataFrame(member_rows)
    member_roles = pd.DataFrame(member_role_rows)
    if int(members.speech_count.sum()) != len(annotated):
        raise ValueError('Annualised member counts do not account for every speech.')
    if int(member_roles.speech_count.sum()) != len(annotated):
        raise ValueError('Annualised role counts do not account for every speech.')
    cohorts = members.groupby('joining_year', as_index=False).agg(
        member_count=('speaker', 'size'),
        speech_count=('speech_count', 'sum'),
        service_months=('service_months', 'sum'),
        average_speeches_per_year=('average_speeches_per_year', 'mean'),
    )
    split_cohorts = {}
    for dimension, table in [('mpc_member_type', member_type), ('mpc_role', member_roles)]:
        split_cohorts[f'average_speeches_by_joining_year_{dimension}'] = table.groupby(
            ['joining_year', dimension], as_index=False).agg(
                member_count=('speaker', 'size'),
                speech_count=('speech_count', 'sum'),
                service_months=('service_months', 'sum'),
                average_speeches_per_year=('average_speeches_per_year', 'mean'),
            )
    annual_roles = pd.DataFrame(role_counts).groupby(['year', 'mpc_role']).size().rename('speech_count')
    grid = pd.MultiIndex.from_product(
        [range(first_month.year, last_month.year + 1), MPC_ROLES], names=['year', 'mpc_role'])
    annual_roles = annual_roles.reindex(grid, fill_value=0).reset_index()
    coverage = pd.DataFrame([{
        'coverage_start_month': first_month.strftime('%Y-%m'),
        'coverage_end_month': last_month.strftime('%Y-%m'),
        'speech_rows': len(annotated),
        'eligible_members': len(members),
        'denominator': 'Inclusive MPC service months within coverage / 12; includes zero-speech months and members.',
        'cohort_average': 'Arithmetic mean of member annual rates, not pooled speeches / pooled service years.',
    }])
    return {
        'average_speeches_by_member_type': member_type,
        'average_speeches_by_member': members,
        'average_speeches_by_member_role': member_roles,
        'average_speeches_by_joining_year': cohorts,
        **split_cohorts,
        'chart_speeches_by_year_mpc_role': annual_roles,
        'speech_activity_coverage': coverage,
    }


def write_activity_charts(
    output_root: Path, annotated: pd.DataFrame, periods: dict[str, list[Membership]],
) -> list[Path]:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    tables = build_activity_tables(annotated, periods)
    for name, table in tables.items():
        table.to_csv(output_root / f'{name}.csv', index=False)
    coverage = tables['speech_activity_coverage'].iloc[0]
    note = (f"Corpus: {coverage.coverage_start_month} to {coverage.coverage_end_month}. "
            'Rate = saved speeches / (eligible MPC service months / 12).\n'
            'Includes months and eligible members with no saved speeches; corpus coverage may be incomplete.')
    paths = []

    def save(fig, name, footer):
        fig.text(0.01, 0.01, footer, fontsize=9)
        fig.tight_layout(rect=(0, 0.075, 1, 1))
        path = output_root / f'{name}.png'
        fig.savefig(path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        paths.append(path)

    table = tables['average_speeches_by_member_type']
    height = max(6, max(table.groupby('mpc_member_type').size()) * 0.32)
    fig, axes = plt.subplots(1, 2, figsize=(17, height), sharex=True)
    for member_type, color, ax in zip(MEMBER_TYPES, ['#336699', '#dd8844'], axes):
        selected = table.loc[table.mpc_member_type.eq(member_type)].sort_values(
            ['average_speeches_per_year', 'speaker'])
        ax.barh(selected.speaker, selected.average_speeches_per_year, color=color)
        ax.set(title=f'{member_type.title()} members', xlabel='Average saved speeches per service year')
        ax.grid(axis='x', alpha=0.2)
    fig.suptitle('Annualised speeches by member and MPC membership type')
    save(fig, 'average_speeches_per_year_by_member_type', note)

    cohorts = tables['average_speeches_by_joining_year']
    fig, ax = plt.subplots(figsize=(13, 6))
    bars = ax.bar(cohorts.joining_year.astype(str), cohorts.average_speeches_per_year, color='#336699')
    for bar, count in zip(bars, cohorts.member_count):
        ax.annotate(f'n={count}', (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    ha='center', va='bottom', fontsize=9)
    ax.margins(y=0.15)
    ax.set(title='Average member speaking rate by year first joining the MPC',
           xlabel='Joining year', ylabel='Mean member speeches per service year')
    ax.tick_params(axis='x', rotation=45)
    save(fig, 'average_speeches_per_year_by_joining_year',
         note + '\nCohort bars are unweighted means of member annual rates; n = members contributing.')

    for dimension, categories, colors in [
        ('mpc_member_type', MEMBER_TYPES, ['#336699', '#dd8844']),
        ('mpc_role', MPC_ROLES, plt.get_cmap('tab10').colors[:len(MPC_ROLES)]),
    ]:
        table = tables[f'average_speeches_by_joining_year_{dimension}']
        years = sorted(cohorts.joining_year.unique())
        fig, ax = plt.subplots(figsize=(18, 7))
        width = 0.8 / len(categories)
        positions = {year: index for index, year in enumerate(years)}
        for offset, category, color in zip(range(len(categories)), categories, colors):
            selected = table.loc[table[dimension].eq(category)]
            x = [positions[year] - 0.4 + width * (offset + 0.5)
                 for year in selected.joining_year]
            bars = ax.bar(x, selected.average_speeches_per_year, width=width,
                          color=color, label=category.title() if dimension == 'mpc_member_type'
                          else category)
            for bar, count in zip(bars, selected.member_count):
                ax.annotate(f'n={count}', (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            ha='center', va='bottom', fontsize=7, rotation=90)
        ax.set_xticks(range(len(years)), [str(year) for year in years], rotation=45)
        ax.set(title='Average member speaking rate by MPC joining year and '
               + ('member type' if dimension == 'mpc_member_type' else 'role'),
               xlabel='Year first joining the MPC', ylabel='Mean member speeches per service year')
        ax.margins(y=0.25)
        ax.grid(axis='y', alpha=0.2)
        ax.legend(title='Member type' if dimension == 'mpc_member_type' else 'Role')
        save(fig, f'average_speeches_per_year_by_joining_year_{dimension}',
             note + '\nUnweighted mean of member rates within each type/role; original MPC joining year. '
             'n = contributing members; absent groups have no bar.')

    roles = tables['chart_speeches_by_year_mpc_role'].pivot(
        index='year', columns='mpc_role', values='speech_count').reindex(columns=MPC_ROLES)
    fig, ax = plt.subplots(figsize=(14, 6))
    roles.plot.bar(stacked=True, ax=ax, rot=45, color=plt.get_cmap('tab10').colors[:len(MPC_ROLES)])
    ax.set(title='Speeches per year by MPC role at the speech date', xlabel='Year', ylabel='Speech count')
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    save(fig, 'speeches_by_year_mpc_role',
         'Counts of saved speeches, not annualised rates. Internal member is retained as a separate role.')
    return paths
