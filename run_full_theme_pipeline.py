from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE_ROOT = Path(os.environ.get('MPC_SPEECH_SOURCE_ROOT', str(PROJECT_ROOT)))
DEFAULT_OUTPUT_ROOT = Path(os.environ.get('MPC_SPEECH_OUTPUT_ROOT', str(PROJECT_ROOT / 'outputs')))


def run_python_script(script_path: Path, *args: str) -> None:
    command = [sys.executable, str(script_path), *args]
    print(f'Running: {command}')
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Run the full MPC speech theme pipeline: keyword analysis, LLM classification, merge, and disagreement check.'
    )
    parser.add_argument('--source-root', type=Path, default=DEFAULT_SOURCE_ROOT, help='Folder containing the HTML/PDF speeches.')
    parser.add_argument('--output-root', type=Path, default=DEFAULT_OUTPUT_ROOT, help='Folder for generated CSV/JSON outputs.')
    parser.add_argument('--skip-llm', action='store_true', help='Skip the LLM classification step.')
    parser.add_argument('--skip-compare', action='store_true', help='Skip disagreement comparison step.')
    parser.add_argument('--skip-merge', action='store_true', help='Skip merge of LLM output into the main CSV.')
    parser.add_argument(
        '--llm-provider',
        choices=['auto', 'openai', 'copilot-api'],
        default='auto',
        help='Provider for llm_theme_classifier.py. auto prefers copilot-api if helper is available; otherwise openai.',
    )
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()

    if not source_root.exists():
        raise FileNotFoundError(f'Source root does not exist: {source_root}')

    output_root.mkdir(parents=True, exist_ok=True)

    analyze_script = PROJECT_ROOT / 'analyze_mpc_speeches.py'
    database_csv = output_root / 'mpc_speech_database.csv'
    llm_jsonl = output_root / 'llm_theme_results.jsonl'
    llm_merge_csv = output_root / 'mpc_speech_database_with_llm.csv'
    disagreement_csv = output_root / 'theme_disagreements.csv'

    run_python_script(
        analyze_script,
        '--source-root',
        str(source_root),
        '--output-root',
        str(output_root),
    )

    if not args.skip_llm:
        llm_classifier = PROJECT_ROOT / 'llm_theme_classifier.py'
        run_python_script(
            llm_classifier,
            '--source-root',
            str(source_root),
            '--output-jsonl',
            str(llm_jsonl),
            '--provider',
            args.llm_provider,
        )

    if not args.skip_compare:
        if llm_jsonl.exists():
            compare_script = PROJECT_ROOT / 'compare_keyword_and_llm_themes.py'
            run_python_script(
                compare_script,
                '--csv',
                str(database_csv),
                '--llm-results',
                str(llm_jsonl),
                '--output-csv',
                str(disagreement_csv),
            )
        else:
            print(f'Skipping comparison because LLM results file does not exist: {llm_jsonl}')

    if not args.skip_merge:
        if llm_jsonl.exists():
            merge_script = PROJECT_ROOT / 'merge_llm_to_database.py'
            run_python_script(
                merge_script,
                '--database-csv',
                str(database_csv),
                '--llm-jsonl',
                str(llm_jsonl),
                '--output-csv',
                str(llm_merge_csv),
            )
        else:
            print(f'Skipping merge because LLM results file does not exist: {llm_jsonl}')

    print(f'Pipeline completed. Outputs are in: {output_root}')


if __name__ == '__main__':
    main()
