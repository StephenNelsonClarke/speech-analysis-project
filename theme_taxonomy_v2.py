"""Alternative (v2) theme taxonomy.

Differences from ``analyze_mpc_speeches.THEMES``:
- ``fiscal_policy_public_finances`` is removed.
- ``monetary_policy_rates`` is split into ``conventional_monetary_policy`` (Bank Rate and
  interest-rate policy) and ``unconventional_monetary_policy`` (QE/QT, central-bank balance
  sheet, forward guidance, funding schemes and the lower bound).
All other themes, labels and keywords are copied unchanged.
"""
from __future__ import annotations

from collections import OrderedDict

from analyze_mpc_speeches import THEMES as THEMES_V1

TAXONOMY_VERSION = 'v2'
REMOVED_THEMES = ('fiscal_policy_public_finances', 'monetary_policy_rates')

CONVENTIONAL = {
    'label': 'Conventional monetary policy',
    'keywords': [
        'monetary policy', 'bank rate', 'interest rates', 'rate path', 'policy rate',
        'rate rises', 'rate cuts', 'monetary tightening', 'monetary easing',
        'policy tightening', 'policy easing', 'real rates', 'policy stance',
        'short-term rates', 'long-term rates',
    ],
}
UNCONVENTIONAL = {
    'label': 'Unconventional monetary policy',
    'keywords': [
        'quantitative easing', 'quantitative tightening', 'qe', 'qt', 'asset purchases',
        'asset purchase', 'apf', 'gilt purchases', 'gilt sales', 'asset sales', 'yield curve control',
        'central bank balance sheet', 'balance sheet reduction', 'unconventional monetary policy',
        'unconventional policy', 'forward guidance', 'funding for lending', 'fls',
        'term funding scheme', 'tfs', 'tfsme', 'lower bound', 'negative interest rates',
        'negative rates',
    ],
}


def _build() -> OrderedDict:
    themes = OrderedDict()
    for key, meta in THEMES_V1.items():
        if key == 'monetary_policy_rates':
            themes['conventional_monetary_policy'] = CONVENTIONAL
            themes['unconventional_monetary_policy'] = UNCONVENTIONAL
        elif key not in REMOVED_THEMES:
            themes[key] = {'label': meta['label'], 'keywords': list(meta['keywords'])}
    return themes


THEMES = _build()
THEME_ORDER = list(THEMES)
