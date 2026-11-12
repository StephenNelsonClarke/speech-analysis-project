# MPC speech analysis

## Collaborating using saved classifications

The Git ignore rules retain the reviewed 818-speech analysis dataset at
`outputs\combined_run_taxonomy_v2\quantitative\analysis_speech_database.csv`.
It includes speech text, keyword and LLM classifications, evidence, rationales
and membership fields. The membership reference, taxonomy and reviewed
exclusions are also retained. No Copilot API helper, credentials or LLM cache
is required to develop quantitative analysis.

Create the environment with `conda env create -f environment.yml`, then activate
it with `conda activate speech-analysis`. From the project directory, run:

```powershell
python run_theme_pipeline_v2.py --reports-only --dataset-csv "outputs\combined_run_taxonomy_v2\quantitative\analysis_speech_database.csv"
python current_mpc_theme_chart.py --as-of 2026-11-11
```

The first command validates the saved v2 categories and generates quantitative
reports, count/percentage charts and speaking-rate charts without API calls.
The second adds the current-member primary-category chart. The dataset already
incorporates the 17 reviewed exclusions; do not apply that review a second time.
The original `quantify_mpc_speeches.py` CLI uses the original taxonomy, so use
the v2 entry point for this dataset.

Generated charts/reports, downloads, authentication caches, `env.txt`, local
editor settings, logs and temporary files are ignored. Python source that
integrates with APIs is retained because the shared modules import it, but
authentication is only needed when requesting new classifications.
`.gitignore` is not a secret scanner and does not affect files already tracked.
Before uploading, review the staged files and notebook outputs for credentials
or confidential content, and use an organisation-approved repository with
appropriate access controls.

The existing pipeline extracts HTML/PDF speech text, calculates keyword theme
scores, classifies themes with an LLM, merges the results and reports
disagreements. `run_full_theme_pipeline.py` runs those steps. The quantitative
reporting layer is separate: it reads a saved merged database and does not
download speeches, call an LLM, or alter classification outputs.

## Independent theme-discovery experiment

### Two-stage discovery (recommended)

```powershell
python discover_speech_themes_two_stage.py
```

This **makes live API calls** through the existing Bank Copilot helper. It uses
the same seed-42 sample of 25 speeches, reads each full speech in a separate fresh
conversation, then synthesises the 25 extracted summaries/themes/quotes in one
final request. Neither stage receives the existing taxonomy or a target count.
The final model sees intermediate results, not the original full texts, so
review the intermediate extraction for omissions.

Outputs are saved under `outputs\theme_discovery_two_stage`:
`sampled_speeches.csv`, a provenance manifest, `intermediate_themes.csv` (updated
after each successful speech), and `intermediate_results.json` (all 25).
Each speech has its exact prompt, raw response and validated `themes.json` under
`intermediate\<speech_id>`. Final prompt/response are under `synthesis`;
`discovered_themes.json`, `discovered_themes.csv`, and
`sample_theme_assignments.csv` contain the shared taxonomy and assignments.
Evidence is checked against source text, allowing only whitespace differences
and standalone numeric lines (PDF page-number artefacts); no words are changed.
Original source text and model quotes remain saved unchanged. Final evidence
must also match supplied intermediate quotes.

There are normally 26 requests. Rerunning the same command resumes from saved
responses, without repeating successful API calls. Failed content validation
triggers up to two correction requests with the validation error and original
source material; original and corrected prompts/responses are retained in
separate directories. Remaining failures stop explicitly. Different input,
seed or prompts require a new `--output-root`; earlier experiments
and original datasets are not modified. The shared taxonomy remains influenced
by model judgement and this sample, not an objective corpus-wide theme count.
Tests: `python -m unittest test_discover_speech_themes_two_stage`.

### Single-request discovery

Discover one shared set of **themes across 25 randomly sampled speeches**,
letting the LLM choose the number of themes supported by the content, without
giving it a target count, existing taxonomy, keyword lists or classifications:

```powershell
python discover_speech_themes.py
python discover_speech_themes.py --run-llm
```

The first command prepares the sample and prompt locally with no API calls.
The second sends the full texts together in one fresh conversation through the
existing Bank Copilot API helper, with web searches disabled. Authentication may
open a browser. The default input is the combined 835-speech classified dataset
under `outputs\combined_run`; existing classifications are never sent or changed.
Only speech IDs and full text enter the request. Text is not truncated or
summarised first. A large request may exceed the provider's context limit: this
fails explicitly rather than silently dropping speeches or shortening them.

The default seed is `42`. Sampling is without replacement from URL-sorted rows,
so changing CSV row order does not change the sample. Use `--seed 123` and
`--output-root outputs\theme_discovery_seed123` for another experiment.
The output directory defaults to `outputs\theme_discovery_open_ended`, preserving
the earlier fixed-ten experiment under `outputs\theme_discovery`. The seed and
sampling method are unchanged, so both experiments select the same 25 speeches
when run against the same input:

- `sampled_speeches.csv`: the selected full texts and identifying metadata.
- `sample_manifest.json`: seed, input/prompt hashes, sample IDs and character counts.
- `discovery_prompt.txt`: the exact request, for checking that no taxonomy is supplied.
- `discovery_response.txt`: raw response, retained even if validation fails.
- `discovered_themes.json` and `discovered_themes.csv`: the proposed theme names,
  definitions, distinctions, verbatim evidence and speech counts.
- `sample_theme_assignments.csv`: a summary, one primary theme and up to three
  secondary themes per sampled speech, with identifying metadata.

Validation accepts any nonempty set of distinct theme names with consecutive
integer IDs, all 25 speech assignments, use of every proposed theme, and
supporting quotes that actually occur in assigned source texts (allowing
whitespace differences and standalone PDF page-number lines).
Semantic distinctness and the quality of summaries still require human review;
these checks cannot prove the model read or understood every word.
The number of themes is model-selected, not an objective estimate of a uniquely
correct number: granularity can vary between runs. Results describe this random
sample, not necessarily the whole corpus.

Repeating an identical experiment reuses its saved response without another
API call. Changed inputs, seeds or prompts require a new output directory.
Provider errors stop the run; connection/timeouts receive at most three attempts.
A rejected saved response is not silently replaced: inspect it and choose a new
output directory to request another response.

Tests: `python -m unittest test_discover_speech_themes`.

## Quantitative reports

### Trial importing new speeches from URLs

```powershell
python import_speech_urls.py --urls-csv "New speeches to be added.csv" --base-csv speeches_enriched.csv --output-root outputs\url_import_trial --sample-size 10
```

This selects up to ten new URLs evenly across the supplied list after removing
duplicate URLs and skipping exact URLs already in the curated dataset. It uses
Windows curl for pages and PDF attachments (avoiding PowerShell download timeouts),
saves original pages and PDFs in
`raw`, extracts speech text from `#output` or an unambiguous same-period speech
PDF, and writes `selected_urls.csv`, `import_diagnostics.csv`,
`import_summary.json` and `speeches_enriched_candidate.csv`. Only HTTPS
`www.bankofengland.co.uk` URLs are accepted. Use speech landing-page URLs.
Slides-only, scanned, ambiguous or failed extractions are explicitly reported;
failed rows are not appended to the candidate. The 80-word minimum is a screening
check, not a guarantee of extraction completeness: review the trial output.

Optional title/date/speaker values supplied in the URL CSV take precedence over
extracted metadata. Dates must be ISO or dd/mm/yyyy. A supplied date that differs
from the page is flagged; the page date is taken from the speech's publication
block, never from navigation cards for other speeches. Membership/tenure reuse
the dated reference, with older unrecognised members explicitly flagged.

The candidate preserves all curated rows and colleague keyword columns. New
speeches have blank colleague keyword fields. Neither input is changed and no
LLM or keyword classification is performed. Extraction provenance is retained
on new rows. This is a reviewable candidate, not an automatic replacement of the
master dataset. Increase `--sample-size` for a larger trial.
Tests: `python -m unittest test_import_speech_urls`.

The importer cleans repeated PDF header/footer lines found at page edges,
the Bank's recurring speech-availability line, and associated page numbers.
Matching text inside the page body is retained. Titles, acknowledgements,
references and numerical content are not removed wholesale. PDF equations and
tables can still lose layout/symbols during extraction and need manual review.
HTML cleaning removes navigation, forms, buttons and toolbars; duplicated
popup footnotes are removed only when their paragraph content already occurs
outside the popup. Unique popup references are retained. Paragraph boundaries
and inline word spacing are preserved.

To refresh a trial from its saved originals without another download, add
`--reuse-downloads` to the import command. This updates only the candidate and
diagnostics; it does not clean or modify existing curated rows. Omit that flag
when fresh downloads are required.

### Importing a URL list from Edge favourites

Export Edge favourites as HTML, then select a folder using repeated `--folder`
arguments from parent to child:

```powershell
python extract_favourites_urls.py --export-html "C:\path\favourites.html" --output-csv "New speeches to be added.csv" --folder "saved urls" --folder "New folder"
```

Only the selected folder and its descendants are included. Duplicate URLs are
removed from the extracted list and links already present in the CSV are not
added again. Existing CSV rows and metadata columns are preserved; new rows have
only `hyperlink` populated. Matching is case-insensitive on folder names; ambiguous
folder paths fail rather than mixing folders. Non-web links are ignored and
reported. The HTML export is read locally and never modified; no URLs are fetched.
Output is UTF-8 CSV. Tests: `python -m unittest test_extract_favourites_urls`.

### Fresh classifications from the enriched CSV

To analyse the curated text in `speeches_enriched.csv`, rather than the original
HTML/PDF corpus:

```powershell
conda activate speech-analysis-project
python run_enriched_theme_pipeline.py --input-csv speeches_enriched.csv --output-root outputs\enriched_run --provider copilot-api
```

This runs the existing `analyze_mpc_speeches.score_speech` keyword scorer and
`llm_theme_classifier.classify_speech` on the `text` field, then produces
disagreement diagnostics, all quantitative CSVs and four charts. It does not
rebuild the enriched input or modify it. All input columns, including colleagues'
`keywords_filtered`, `keyword_1`–`keyword_10` and `score_1`–`score_10`, are retained
unchanged in the classified databases and annotated report, but **never used**
to score themes, prompt the LLM or calculate counts. Fresh classifications use
the project's ten-theme taxonomy and separate `primary_theme`, `top_themes`,
theme-specific score and `llm_*` fields. Speech IDs are stable SHA-256 URL IDs.
As with the existing method, keyword scores are hits per 1,000 words and the
top three ranked themes are retained. Unlike the old all-zero tie behaviour,
speeches with no keyword hits are explicitly unclassified.

The LLM uses the existing prompt/schema (up to 200,000 text characters), makes
one independent request per speech and saves each validated response immediately.
`llm_classification_cache.jsonl` supports resuming with the same command:
cached results are reused only for matching URL IDs, full text, prompt/schema,
provider/model settings and classifier implementation. `--max-new-classifications 1`
can be used for a live pilot before the full run. Failures stop explicitly;
partial LLM results are not presented as complete reports. If a changed run
fails or pauses, any older completed reports remain from the previous run.
The Copilot helper may prompt for interactive authentication.

Use `--exclude-url "https://..."` (repeatable) to exclude an explicitly selected
item from this analysis without removing it from the enriched source. For the
current corpus, exclude
`https://www.bankofengland.co.uk/speech/2016/slides-from-andy-haldanes-speech-given-at-the-deans-lecture-at-cass-business-school`:
this is a slides-only row whose text is `No text extracted`. That leaves 406
speeches. Exclusions are recorded in `classification_summary.json`.

Outputs are in `outputs\enriched_run`:

- `mpc_speech_database.csv`: preserved input plus fresh keyword themes.
- `mpc_speech_database_with_llm.csv`: preserved input plus both fresh methods.
- `llm_theme_results.jsonl`: current run's complete LLM results.
- `theme_disagreements.csv` and `classification_summary.json`: diagnostics and provenance.
- `quantitative\`: the reports below plus four PNG charts.

The reporting layer uses `speech_date` for enriched inputs, retaining the raw
`date` field, and checks that enriched membership agrees with the dated reference.
For interactive use, set the notebook's `DATABASE_CSV` to
`outputs\enriched_run\mpc_speech_database_with_llm.csv` and `OUTPUT_ROOT` to
`outputs\enriched_run\quantitative`.

Tests: `python -m unittest test_run_enriched_theme_pipeline test_quantify_mpc_speeches`.

### Additional LLM charts

`python audit_speech_formats.py` audits the analysed URLs plus the excluded
Haldane slides page, without changing datasets or charts. Results are saved in
`outputs\speech_format_audit`: `speech_format_audit.csv` covers every URL,
`speech_format_review.csv` contains nonstandard/ambiguous cases, and
`audit_summary.json` records coverage and errors. `slides_only_in_analysis.csv`
lists slide decks currently counted in the analysis, excluding the already
excluded Haldane deck. Public pages and relevant PDF
attachments are cached for repeat runs. Slide wording and PDF layout provide
evidence, not definitive proof; ambiguous formats and download errors require
review. Mixed speech/slides pages are checked against saved text where possible.
PDF checks also look for sustained prose so that chart appendices and mixed
page orientations do not by themselves imply a slide deck. Explicit manual
decisions are recorded in `speech_format_manual_reviews.csv`.
`--recheck-review` refreshes only flagged/nonstandard cases using cached downloads.

To chart the current MPC members' saved speeches by v2 LLM primary category,
run `python current_mpc_theme_chart.py --as-of 2026-11-10`.
This writes `current_mpc_speeches_by_primary_theme.png` and its backing CSV in
the v2 quantitative folder. Membership is selected from the local reference on
the specified date; counts cover all saved speeches during those members' MPC
service (including earlier terms), up to that date. These are counts, not
annualised rates, and current members with no saved speeches are retained.

The enriched pipeline writes 31 additional PNG charts to its `quantitative`
folder (35 including the four original charts).
`speeches_by_year_internal_external.png` shows annual speech counts stacked by
membership. For each of `primary`, `secondary` and `total`, it writes:

- `llm_<role>_themes_by_year.png`.
- `llm_<role>_themes_by_year_member_type.png`: internal/external panels sharing
  the same vertical scale.
- `llm_<role>_themes_by_member_type.png`: stacked counts by membership.
- `llm_<role>_themes_by_member_type_pct.png`: grouped horizontal bars showing the
  percentage of **all speeches within each member type** mentioning each theme.
  The legend gives the denominator for each type; it is not the share of theme
  assignments or the share of the entire corpus. An absent member type has no
  percentage denominator and is omitted rather than assigned a zero percentage.
- `llm_<role>_themes_by_completed_mpc_years.png`.
- `llm_<role>_themes_by_completed_mpc_years_member_type.png`: internal/external
  tenure panels with shared axes.
- Percentage versions (`_pct.png`) of the year, year/member-type, completed-MPC-years
  and completed-MPC-years/member-type charts use all speeches within each
  corresponding group as the denominator, retaining the same theme colours.
  Stacked bars can exceed 100% for secondary and total themes.

All these theme charts use **only LLM classifications**. Total themes are the
union of a speech's primary and secondary themes, counting each distinct theme
once per speech. Primary and secondary categories remain separate and unchanged.
An unclassified primary is shown explicitly; total counts include only actual
known themes, not the unclassified placeholder. If the primary is missing,
available secondary labels still contribute to total themes.
Except for the explicitly labelled percentage charts, charts show raw counts.
Theme colours are consistent across count charts. Tenure uses completed whole years,
not rounding: the first year of service is year 0, including 0.9 years. Missing
tenure bins are displayed as zero in counts and blank in percentage charts.
Secondary counts deduplicate themes within
each speech, exclude the primary theme, and exclude rows without an LLM primary;
stack totals may exceed the number of speeches. Total themes also have this
multi-label property, so secondary and total percentages can sum to more than
100% across themes, while each individual theme's percentage is at most 100%.
Raw counts are not adjusted for
the number of members, years served, or differing corpus coverage.

The eleven backing CSVs are `llm_themes_by_year.csv`,
`llm_themes_by_year_member_type.csv`, `llm_themes_by_member_type.csv`,
`llm_themes_by_completed_mpc_years.csv`,
`llm_themes_by_completed_mpc_years_member_type.csv` (each with separate
primary/secondary/total rows), `llm_theme_percentages_by_member_type.csv`
(including `speech_count`, `group_speech_count` and
`share_of_member_type_speeches_pct`), and `chart_speeches_by_year_member_type.csv`.
Four further `llm_theme_percentages_by_*.csv` tables correspond to the year
and tenure groups (with and without member type), recording `speech_count`,
`group_speech_count` and `share_of_group_speeches_pct`.
These charts require resolved internal/external membership, a valid year and
nonnegative completed tenure for every row; invalid inputs stop explicitly.

To refresh these charts and backing counts from existing annotations without
calling the LLM or modifying any speech data:

```powershell
python llm_report_charts.py --output-root outputs\enriched_run\quantitative
```

Tests: `python -m unittest test_llm_report_charts test_run_enriched_theme_pipeline`.

### Combined corpus refresh and speaking-rate charts

Run the combined refresh after editing the membership reference:

```powershell
python refresh_combined_reports.py
```

This reads the reviewed candidate in `outputs\url_import_full` and the saved
classifications in `outputs\enriched_run` and `outputs\imported_speeches_run`.
It verifies unique URLs, exact classification coverage and unchanged text before
reusing classifications. No LLM calls are made. Existing source datasets and
previous reports remain unchanged; the refreshed combined outputs are:

- `outputs\combined_run\speeches_enriched.csv`: all 836 enriched records,
  retaining the previously excluded Haldane slides-only record.
- `outputs\combined_run\mpc_speech_database_with_llm.csv`: 835 analysed speeches
  with refreshed monthly membership, roles and tenure and both saved classifiers.
- `outputs\combined_run\excluded_speeches.csv`: the explicit analysis exclusion.
- `outputs\combined_run\refresh_summary.json`: counts, input hashes and methods.
- `outputs\combined_run\quantitative`: all existing reports and 23 charts,
  plus the following three charts and their backing CSVs.

`average_speeches_per_year_by_member_type.png` splits members into internal and
external panels. The rate is **saved speeches / (eligible MPC service months / 12)**,
so five speeches over 18 months equals 3.333 speeches per year. The coverage starts
in January of the earliest speech year and ends in the latest speech month
(currently January 2005 to October 2026). Service before or after this window
does not enter the denominator; zero-speech months and members serving during the
window are included. A member switching between external and internal has separate
speech counts and service-month denominators in each panel. Internal job changes
do not double-count service months.

`average_speeches_per_year_by_joining_year.png` groups members by their first
recorded MPC joining year, even when it predates the corpus or they later change
roles. A cohort bar is the **unweighted arithmetic mean of members' annualised
rates**, not pooled speeches divided by pooled service years. The chart labels
each cohort's contributing member count. Members with zero speeches are included
if they served during the coverage window.

Two grouped-bar variants split the joining-year cohorts:
`average_speeches_per_year_by_joining_year_mpc_member_type.png` (internal/external)
and `average_speeches_per_year_by_joining_year_mpc_role.png` (all five roles).
Each uses the unweighted mean of members' type- or role-specific annual rates:
speeches delivered in that type/role divided by service years in that type/role
within corpus coverage. Members changing roles can contribute to multiple
series, always under their original MPC joining year. Zero-speech members are
included where they have eligible service; groups without members have no bar.
The `n` labels give the contributing member counts.

`speeches_by_year_mpc_role.png` stacks counts by Governor, Deputy Governor,
Chief Economist, External member and Internal member, using the role on the
speech date. The last category is retained to avoid dropping the user's other
internal members. These are counts, not annual rates.

Backing tables are `average_speeches_by_member_type.csv`,
`average_speeches_by_member.csv`, `average_speeches_by_joining_year.csv`,
`chart_speeches_by_year_mpc_role.csv` and `speech_activity_coverage.csv`.
Additional backing tables are `average_speeches_by_member_role.csv`,
`average_speeches_by_joining_year_mpc_member_type.csv` and
`average_speeches_by_joining_year_mpc_role.csv`.
Annualised rates describe the **saved corpus**, not necessarily all speeches:
missing speeches and partial latest-month coverage may affect comparisons.
The existing year-of-tenure charts use completed 12-month blocks since joining;
month 0 is the joining month. Colleague keyword fields remain preserved and unused.

Tests: `python -m unittest test_membership_activity_charts test_refresh_combined_reports`.

Activate the project environment and explicitly choose the merged dataset:

```powershell
conda activate speech-analysis-project
python quantify_mpc_speeches.py `
    --database-csv "outputs\full_run\mpc_speech_database_with_llm.csv" `
    --output-root "outputs\full_run\quantitative"
```

For a new dataset, change both paths to its location. The script deliberately
does not auto-select the latest files, which could mix separate pipeline runs.
An alternative membership reference can be passed using `--membership-csv`.

The input requires `speech_id`, `year`, `date`, `speaker`, `top_themes`,
`llm_primary_theme`, `llm_secondary_themes` and either `primary_theme` or
`primary_theme_label`. Dates must be `YYYY-MM-DD`. Blank metadata is accepted and
flagged; invalid theme labels/list syntax and conflicting keyword primary keys
and labels stop the run before reports are written.

### Alternative (v2) theme taxonomy

A parallel taxonomy is defined in `theme_taxonomy_v2.py`, with its own
`llm_theme_prompt_v2.txt` and `llm_theme_schema_v2.json`. Compared with the
original taxonomy, it:

- removes `fiscal_policy_public_finances`;
- splits `monetary_policy_rates` into `conventional_monetary_policy` (Bank Rate
  and interest-rate policy) and `unconventional_monetary_policy` (QE/QT, asset
  purchases/sales, APF, yield curve control, central-bank balance sheet, forward guidance, funding
  schemes such as FLS/TFS/TFSME, and the lower bound/negative rates);
  the LLM prompt follows the RBA explainer's definition: conventional policy
  means changing the policy rate, and unconventional policy means any other
  monetary policy tool. Forward guidance about the future path of Bank Rate
  must be tagged unconventional;
- leaves the other eight themes, labels and keywords unchanged.

The original taxonomy, prompt, schema, modules and outputs are unchanged.
`run_theme_pipeline_v2.py` runs the existing pipeline with the v2 taxonomy
temporarily substituted, writing to `outputs\combined_run_taxonomy_v2` by default.
Its input is the refreshed combined corpus; the slides-only Haldane row is excluded.

```powershell
# Keyword scoring only (no LLM calls)
python run_theme_pipeline_v2.py --keyword-only
# Full keyword + LLM reclassification (resumable; --max-new-classifications N for a pilot)
python run_theme_pipeline_v2.py
# Classifications only: stop before diagnostics, quantitative analysis and charts
python run_theme_pipeline_v2.py --skip-analysis
# Refresh quantitative reports and all charts using saved classifications (no LLM calls)
python run_theme_pipeline_v2.py --reports-only
```

v2 LLM results are cached separately from the original ones, so a full run
reclassifies all 835 speeches. Results are not directly comparable with the
original taxonomy for the monetary and fiscal categories.
`--skip-analysis` still saves the keyword dataset, LLM results, merged dataset
and classification provenance. Unlike `--skip-charts`, it does not produce
quantitative CSV reports. Both modes reuse valid cached LLM classifications.

The LLM chart set includes count and percentage versions for primary, secondary
and total themes by calendar year, completed MPC years, member type, and year
or completed MPC years split by member type. Percentage charts (`*_pct.png`)
divide each theme's speech count by all speeches within the corresponding
group, not by theme assignments or the whole corpus. Primary stacks sum to
100%; secondary and total stacks can exceed 100% because a speech can have
several themes. Groups with no speeches are blank, not zero percentages.
The `llm_theme_percentages_by_*.csv` tables retain counts, denominators and
percentages for checking the charts.

Once `outputs\speech_format_audit\slides_only_in_analysis.csv` contains an
`exclude_from_analysis` column, `--reports-only` automatically applies that
review: `yes` excludes; `no` or blank retains (blank decisions are logged).
An alternative review can be supplied with `--exclusion-csv`.
The full classified source and LLM cache remain unchanged. The selected corpus
is saved as `quantitative\analysis_speech_database.csv`, with dropped records
in `quantitative\excluded_speeches.csv`. Counts, percentages and speaking rates
are recomputed from the selected corpus. Audit reruns preserve existing
exclusion decisions by hyperlink and stop if a reviewed item disappears
from the shortlist, rather than silently discarding a decision.

### Outputs

| File | Contents |
| --- | --- |
| `speeches_by_year.csv` | Speech rows per supplied year, including an Unknown bucket |
| `speeches_by_speaker.csv` | Speech rows per canonical speaker |
| `speeches_by_speaker_year.csv` | Speaker/year counts |
| `theme_counts.csv` | LLM and keyword primary/secondary theme counts, including zero-count taxonomy themes |
| `theme_counts_by_year.csv` | Theme counts by year, method and primary/secondary role |
| `theme_counts_by_speaker.csv` | Theme counts by speaker, method and primary/secondary role |
| `theme_counts_by_mpc_member_type.csv` | Theme counts by dated MPC status |
| `speeches_by_mpc_member_type.csv` | Internal, external, outside-recorded-tenure and unresolved counts |
| `speeches_by_mpc_member_type_year.csv` | MPC status/year counts |
| `annotated_speeches.csv` | Original fields plus canonical names, membership annotations and normalized themes |
| `data_quality_issues.csv` | Row-level flags, including duplicates, missing dates/names/classifications and year/date conflicts |
| `membership_reference_used.csv` | Snapshot of the membership reference used for this run |
| `quantitative_summary.json` | Totals, classification coverage, quality counts and input paths |

Counts use **one input row per speech**. Duplicate IDs are flagged but not
deduplicated: deciding which source records describe the same speech is an
upstream data-curation task. The reporting code does not join records by ID, so
duplicates cannot create a many-to-many expansion here. They can still affect
the classifications already supplied by the pipeline.

Primary classifications are counted once per row and method; missing primary
classifications appear as `unclassified`. Primary counts, including this bucket,
sum to the number of input rows separately for each method.

Secondary counts mean:

- LLM: each `llm_secondary_themes` theme except the LLM primary theme.
- Keyword: each `top_themes` theme except the keyword primary theme.
- Repeated themes within a row count once. Rows without a primary classification
  are excluded from that method's secondary counts and flagged.
- Secondary counts are multi-label: their total can exceed the speech count.
  The keyword method always selects its top three ranked themes, even when a
  score is zero; these are ranks, not necessarily material subject coverage.

`share_of_all_speeches_pct` uses all input rows as its denominator. It is not an
LLM confidence measure. Grouped theme CSVs contain observed combinations only;
the overall theme table additionally includes zero counts for all ten themes.
Annual counts describe the saved corpus, not necessarily all speeches delivered
in a year; partial-year coverage and differing MPC tenures matter when comparing
speakers.

## MPC membership reference

`mpc_membership.csv` covers the 51 voting members listed in the Bank's official
[Bank Rate voting history](https://www.bankofengland.co.uk/-/media/boe/files/monetary-policy-summary-and-minutes/mpcvoting.xlsx).
Appointment periods are sourced from the Wikipedia [MPC membership list](https://en.wikipedia.org/wiki/Monetary_Policy_Committee_(United_Kingdom)),
which reports most former terms only to the month. Per the user's choice, `start_date`
and `end_date` are stored as `YYYY-MM` and `date_basis` is `appointment_month`;
each month is treated as inclusive for membership and role assignment. Daily
appointment dates should not be inferred from these month values.

Tenure is calculated in completed calendar months: the joining month is month 0,
the next month is month 1, and so forth. `completed_years_on_mpc` is the completed
month count divided into 12-month blocks. `years_on_mpc` is a month-based decimal
and `completed_months_on_mpc` carries the zero-based month count. This deliberately
does not distinguish days within a month. Speech dates in a listed start month are
assigned to month 0; a different exact appointment day in that month will not
change the bucket.

The `date_basis` values retain compatibility with older references:

- `appointment`: exact day-level appointment dates.
- `appointment_month`: inclusive calendar-month appointment periods.
- `voting_window`: first-to-last recorded votes; not appointment dates, and tenure
  remains blank.

Ben Broadbent's external-to-internal change and the known senior-role changes are
separate adjacent rows; tenure continues across continuous service. Existing
curated datasets and saved reports are not automatically changed by reference
updates. Re-enrich and rerun reports deliberately when the reference is updated.
For classification and CSV reports where charts are not appropriate, use
`run_enriched_theme_pipeline.py --skip-charts`. This explicitly omits all charts
while retaining classifications, diagnostics and CSV counts.
LLM connection errors and timeouts are retried up to three attempts with 10/20
second waits. Invalid responses and other errors are not retried; persistent
failures stop explicitly and completed cached classifications remain resumable.
Custom legacy reference CSVs without `date_basis` continue to use appointment dates.

The `mpc_role` field identifies `Governor`, `Deputy Governor`, `Chief Economist`,
`External member` or `Internal member` on the membership month. Known changes between senior
internal offices are separate adjacent rows, while continuous MPC service and
tenure continue across those role changes. Internal roles outside those senior posts are labelled `Internal member` for
review rather than inferred. The enrichment adds
`mpc_role` to each speech; quantitative outputs include role in
`annotated_speeches.csv` and provide `speeches_by_mpc_role.csv` and
`theme_counts_by_mpc_role.csv`. Role-specific rows must be revisited alongside
the appointment-date review; split dates represent role effective dates, not
new MPC appointments.
Membership dates may be entered as year-month (`YYYY-MM`), ISO day dates
(`YYYY-MM-DD`) or UK day/month/year (`DD/MM/YYYY`). Only `appointment_month`
uses the year-month precision.

The Wikipedia membership list and relevant Bank/HM Treasury sources are linked
in each row. For current members, the listed term end is an announced term end,
not a guarantee of future membership. Review the reference when appointments,
early departures or reappointments change, and retain month precision unless an
exact day is separately verified.

Name matching is exact after stripping common honorifics and normalizing
punctuation/case; explicit aliases include Catherine Mann and David Ramsden.
No fuzzy event-title matching or speaker inference is attempted.

Internal/external status is assigned only when a recognized speaker and a valid
full date match a recorded term. Missing/unrecognized speakers, missing/invalid
dates and year/date conflicts are `unresolved`. Dates outside a recognized
speaker's recorded terms are `outside_recorded_tenure`: this signals a reference
coverage or tenure check, not a definitive claim of non-membership. The year is
never used to invent a speech date. Supplied year counts are retained even when
the date is missing or conflicting.

## Notebook and charts

Open `quantitative_speech_report.ipynb` in VS Code, select the
`speech-analysis-project` Python environment, edit the three configuration paths
in the first code cell, and run all cells with the project folder as the working
directory. The notebook uses the same reporting script and saves four PNG charts
alongside the CSVs. It also displays a speaker/topic cross-tab and quality flags.

`environment.yml` includes `matplotlib` and `ipykernel` for charts and notebook
execution. If needed, update the existing environment:

```powershell
conda env update -n speech-analysis-project -f environment.yml
```

On Windows, activate Conda before launching notebook kernels (restart VS Code
from that activated terminal if necessary). Running the environment's Python
executable directly without activation can leave native-library search paths
unset. For non-interactive execution, `conda run -n speech-analysis-project`
provides the same environment initialization.

The environment manifest itself is named `speech-analysis`; when creating it
with `conda env create -f environment.yml` without an explicit `-n`, activate that
name instead. Existing PowerShell pipeline wrappers also default to that name;
pass `-CondaEnvName speech-analysis-project` when using the existing environment.

## Tests

```powershell
python -m unittest test_quantify_mpc_speeches -v
```

The tests cover exact theme counts and totals, duplicate IDs, missing metadata,
speaker aliases, date boundaries, membership role changes and persistent output
files. They also execute every notebook code cell against a temporary dataset
and check that all four chart files are generated.

## Adding MPC membership fields to a speeches CSV

`add_mpc_membership_fields.py` enriches a raw speeches file (columns `hyperlink`, `text`, `title`, `date`; dates as `dd/mm/yyyy` or ISO) and writes a new CSV; the input is never overwritten.

```powershell
python add_mpc_membership_fields.py --input-csv speeches.csv --output-csv speeches_enriched.csv
```

To apply a separate Excel-edited file without passing the original long texts
through Excel:

```powershell
python add_mpc_membership_fields.py --input-csv speeches.csv --updates-csv speeches_edited_update.csv --output-csv speeches_enriched.csv
```

The update file must contain the same named columns as the source, with one
complete replacement row per exact `hyperlink`. All cells in each matched row
are replaced, including blanks. URLs must be unique in both files; unmatched
update URLs, differing schemas and malformed files with skipped rows stop the
update. Source order, untouched rows and all named columns (including keyword
fields) are preserved. Neither source file is modified. Both UTF-8 and
Windows-1252 CSVs are supported. Keep replacement texts below Excel's cell limit,
or supply them without Excel.

Speaker matching falls back to an explicit reference name in the URL slug
when neither the title nor text identifies a speaker. Ambiguous names remain
flagged. Missing text is also flagged, independently of membership coverage.

Validate the enrichment and update step with
`python -m unittest test_add_mpc_membership_fields`.

Added columns: `speaker` (matched against `mpc_membership.csv` from the title, else the "speech given by ..." text), `speaker_source`, `speech_date`, `year`, `mpc_status`, `mpc_member_type` (internal/external on the speech date), `mpc_role` (specified office on the speech date; blank for unclassified internal roles), `mpc_service_start` (start of unbroken MPC service, so Ben Broadbent counts from 2011), `years_on_mpc` (decimal), `completed_years_on_mpc` and `review_flag`.

Speeches with an unrecognised/ambiguous speaker, missing/unparseable date, or a date outside recorded MPC tenure are left blank and flagged in `review_flag`; nothing is guessed. Rows without a hyperlink (e.g. text overflowing Excel's 32,767-character cell limit) are ignored and reported. Voting-window reference entries support membership classification but leave tenure blank and flag the unverified appointment dates.
