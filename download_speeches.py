import os
import requests
from bs4 import BeautifulSoup

# List of speech slugs (newest → oldest)
speech_slugs = [
    # Page 1
    "mixed-signals-research-findings-and-policy-judgements",
    "running-on-empty",
    "central-reservations",
    "speech-by-andrew-bailey-at-the-london-school-of-economics",
    "speech-by-megan-greene-at-the-london-school-of-economics",
    "speech-by-huw-pill-at-the-london-school-of-economics",
    "speech-by-catherine-l-mann-at-the-london-school-of-economics",
    "speech-by-jonathan-haskel-at-the-london-school-of-economics",
    "speech-by-dave-ramsden-at-the-london-school-of-economics",
    "speech-by-sarah-breeden-at-the-london-school-of-economics",
    "speech-by-ben-broadbent-at-the-london-school-of-economics",
    "speech-by-andrew-hauser-at-the-london-school-of-economics",
    "speech-by-michael-saunders-at-the-london-school-of-economics",
    "speech-by-silvana-tenreyro-at-the-london-school-of-economics",
    "speech-by-huw-pill-at-the-london-school-of-economics",
    "speech-by-catherine-l-mann-at-the-london-school-of-economics",
    "speech-by-jonathan-haskel-at-the-london-school-of-economics",
    "speech-by-dave-ramsden-at-the-london-school-of-economics",
    "speech-by-sarah-breeden-at-the-london-school-of-economics",
    "speech-by-ben-broadbent-at-the-london-school-of-economics",
    "speech-by-andrew-hauser-at-the-london-school-of-economics",
    "speech-by-michael-saunders-at-the-london-school-of-economics",
    "speech-by-silvana-tenreyro-at-the-london-school-of-economics",
    "speech-by-huw-pill-at-the-london-school-of-economics",
    "speech-by-catherine-l-mann-at-the-london-school-of-economics",
    "speech-by-jonathan-haskel-at-the-london-school-of-economics",
    "speech-by-dave-ramsden-at-the-london-school-of-economics",
    "speech-by-sarah-breeden-at-the-london-school-of-economics",
    "speech-by-ben-broadbent-at-the-london-school-of-economics",
    "cross-checking",

    # Page 2
    "lets-get-ready-to-repo",
    "transformation-and-conjuncture",
    "from-nice-to-not-so-nice",
    "climate-change-the-macroeconomy-and-monetary-policy",
    "outlier-or-laggard",
    "worlds-apart",
    "uk-inflation-and-monetary-policy-in-an-international-context",
    "monetary-policy-as-engineering",
    "signal-versus-noise",
    "uk-inflation-since-the-pandemic",
    "climate-policy-and-monetary-policy",
    "less-is-more-or-less-is-a-bore",
    "recent-developments-in-uk-monetary-policy",
    "monetary-policy-in-the-face-of-large-shocks",
    "monetary-policy-prices-versus-quantities",
    "update-and-outlook",
    "monetary-and-financial-stability-lessons",
    "inflation-persistence-and-monetary-policy",
    "supply-matters",
    "expectations-lags-and-the-transmission-of-monetary-policy",
    "gauging-disinflationary-pressures",
    "turning-points-and-monetary-policy-strategy",
    "uk-monetary-policy-outlook",
    "monetary-policy-and-central-bank-asset-purchases",
    "recent-uk-monetary-policy-in-a-changing-economy",
    "the-path-to-2-per-cent",
    "monetary-policy-and-financial-stability-interventions",
    "monetary-policy-an-anchor-in-challenging-times",
    "inflation-expectations-inflation-persistence-and-monetary-policy-strategy",
    "bringing-inflation-back-to-the-2-target",
    "some-reflections-on-monetary-policy",

    # Page 3
    "the-economic-landscape-structural-change",
    "economic-outlook",
    "returning-inflation-to-target",
    "what-did-the-monetarists-ever-do-for-us",
    "uk-monetary-policy-in-the-context-of-global-spillovers",
    "old-dogs-new-tricks",
    "opening-remarks-at-oenb",
    "the-economic-situation-and-monetary-policy",
    "the-route-back-to-2-inflation",
    "a-monetary-policymaker-faces-uncertainty",
    "reliable-partners",
    "the-uk-economic-outlook-and-monetary-policy",
    "the-economy-and-policy-trade-offs",
    "shocks-uncertainty-and-the-monetary-policy-response",
    "monetary-policy-with-a-steady-hand",
    "on-returning-inflation-back-to-target",
    "lags-trade-offs-and-the-challenges-facing-monetary-policy",
    "the-outlook-for-inflation-and-monetary-policy",
    "uk-monetary-policy-crossing-the-river",
    "inflation-now-and-then",
    "international-trade-global-supply-chains",
    "the-hard-yards",
    "the-inflation-outlook",
    "navigating-the-economy-through-the-covid-crisis",
    "thirty-years-of-hurt",
    "tackling-climate-for-real",
    "what-are-government-bond-yields-telling-us",
    "its-not-easy-being-green",
    "housing-the-quiet-decade",
    "meeting-varied-people",

    # Page 4
    "opening-remarks-meeting-varied-people",
    "the-global-outlook-international-trade-and-resilience",
    "response-to-the-covid-19-pandemic",
    "remarks-on-challenges-to-the-economic-outlook",
    "inflation-a-tiger-by-the-tail",
    "an-update-on-the-economic-outlook",
    "qe-as-an-economic-policy-tool",
    "modern-challenges-for-the-modern-central-bank",
    "covid-and-the-composition-of-spending",
    "lets-talk-about-negative-interest-rates",
    "what-has-central-bank-independence-ever-done-for-us",
    "the-potential-long-term-effects-of-covid",
    "the-monetary-policy-toolbox-in-the-uk",
    "assessing-the-health-of-the-economy",
    "avoiding-economic-anxiety",
    "the-economy-and-covid-19",
    "covid-19-and-the-economy",
    "remarks-on-covid-19-and-monetary-policy",
    "the-second-quarter",
    "covid-19-and-monetary-policy",
    "monetary-policy-and-the-bank-of-englands-balance-sheet",
    "monetary-policy-during-pandemics",
    "inflation-and-beliefs-about-inflation",
    "its-time-to-talk-about-money",
    "monetary-policy-in-the-intangible-economy",
    "risk-management-in-a-sluggish-economy"
]

BASE = "https://www.bankofengland.co.uk/speech/"

def download(url, path):
    r = requests.get(url)
    if r.status_code == 200:
        with open(path, "wb") as f:
            f.write(r.content)
        print(f"Saved: {path}")
    else:
        print(f"Failed: {url}")

for slug in speech_slugs:
    html_url = BASE + slug
    print(f"Fetching: {html_url}")

    r = requests.get(html_url)
    if r.status_code != 200:
        print(f"Could not fetch {html_url}")
        continue

    soup = BeautifulSoup(r.text, "html.parser")

    # Extract date for folder naming
    date_tag = soup.find("time")
    year = date_tag["datetime"][:4] if date_tag else "unknown"

    os.makedirs(year, exist_ok=True)

    # Save HTML
    html_path = os.path.join(year, f"{slug}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(r.text)

    # Find PDF link
    pdf_link = None
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if href.endswith(".pdf"):
            pdf_link = href
            break

    if pdf_link:
        if pdf_link.startswith("/"):
            pdf_link = "https://www.bankofengland.co.uk" + pdf_link
        pdf_path = os.path.join(year, f"{slug}.pdf")
        download(pdf_link, pdf_path)
    else:
        print(f"No PDF found for {slug}")
