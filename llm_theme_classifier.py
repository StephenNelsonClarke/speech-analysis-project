from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

from analyze_mpc_speeches import THEMES, extract_text

THEME_KEYS = list(THEMES.keys())
PROMPT_PATH = Path(__file__).with_name('llm_theme_prompt.txt')
SCHEMA_PATH = Path(__file__).with_name('llm_theme_schema.json')

_COPILOT_CLIENT = None


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))


def load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding='utf-8')


def normalise_theme(theme: str | None) -> str | None:
    if theme is None:
        return None
    value = theme.strip()
    if value in THEME_KEYS:
        return value
    lowered = value.lower().replace(' ', '_').replace('-', '_')
    lowered = re.sub(r'[^a-z0-9_]+', '', lowered)
    for key in THEME_KEYS:
        if key.lower() == lowered:
            return key
    return None


def validate_response(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise ValueError('LLM response was not a JSON object.')

    primary = normalise_theme(response.get('primary_theme'))
    if primary is None:
        raise ValueError(f"Invalid primary_theme: {response.get('primary_theme')!r}")

    secondary = response.get('secondary_themes', [])
    if not isinstance(secondary, list):
        raise ValueError('secondary_themes must be a list.')

    cleaned_secondary = []
    seen: set[str] = set()
    for item in secondary:
        normalised = normalise_theme(item)
        if normalised is None:
            continue
        if normalised not in seen and normalised != primary:
            cleaned_secondary.append(normalised)
            seen.add(normalised)
        if len(cleaned_secondary) >= 3:
            break

    confidence = float(response.get('confidence', 0.0))
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f'confidence must be in [0, 1], got {confidence!r}')

    evidence = str(response.get('evidence_excerpt', '')).strip()
    rationale = str(response.get('rationale', '')).strip()
    if not evidence or not rationale:
        raise ValueError('evidence_excerpt and rationale must be non-empty strings.')

    return {
        'primary_theme': primary,
        'secondary_themes': cleaned_secondary,
        'confidence': round(confidence, 3),
        'evidence_excerpt': evidence,
        'rationale': rationale,
    }


def build_messages(prompt_template: str, speech_text: str) -> list[dict[str, str]]:
    user_prompt = prompt_template.replace('{{SPEECH_TEXT}}', speech_text[:200000])
    return [
        {
            'role': 'system',
            'content': (
                'You are an expert macroeconomist and text analyst. Return only valid JSON that matches the provided schema. '
                'Do not include markdown fences or prose outside the JSON object.'
            ),
        },
        {'role': 'user', 'content': user_prompt},
    ]


def openai_compatible_call(messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
    api_key = os.environ.get('OPENAI_API_KEY') or os.environ.get('OPENAI_KEY')
    base_url = os.environ.get('OPENAI_BASE_URL') or os.environ.get('OPENAI_API_BASE') or 'https://api.openai.com/v1'
    model = os.environ.get('OPENAI_MODEL') or 'gpt-4o-mini'

    if not api_key:
        raise RuntimeError('No API key found. Set OPENAI_API_KEY (or OPENAI_KEY) before running with --provider openai.')

    url = urljoin(base_url.rstrip('/') + '/', 'chat/completions')
    payload = {
        'model': model,
        'messages': messages,
        'response_format': {
            'type': 'json_schema',
            'json_schema': {
                'name': 'speech_theme_classification',
                'schema': schema,
                'strict': True,
            },
        },
    }
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }

    response = requests.post(url, headers=headers, json=payload, timeout=180)
    response.raise_for_status()
    data = response.json()
    try:
        return data['choices'][0]['message']['content']
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f'Unexpected API response: {data}') from exc


def resolve_copilot_helper_root() -> Path:
    configured = os.environ.get('COPILOT_API_HELPER_PATH')
    if configured:
        return Path(configured)
    return Path(r'C:\Users\344816\repos\copilot-api-helper')


def get_copilot_client():
    global _COPILOT_CLIENT
    if _COPILOT_CLIENT is not None:
        return _COPILOT_CLIENT

    helper_root = resolve_copilot_helper_root()
    src_dir = helper_root / 'src'
    if not src_dir.exists():
        raise RuntimeError(
            'Could not find copilot-api-helper src folder. Set COPILOT_API_HELPER_PATH to your copilot-api-helper repo path.'
        )

    if str(helper_root) not in sys.path:
        sys.path.insert(0, str(helper_root))

    module = importlib.import_module('src.copilot_api')
    copilot_api_class = getattr(module, 'CopilotAPI')
    _COPILOT_CLIENT = copilot_api_class()
    return _COPILOT_CLIENT


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith('```'):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.I)
        cleaned = re.sub(r'\s*```\s*$', '', cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{.*\}', cleaned, flags=re.S)
    if not match:
        raise ValueError(f'Could not parse JSON object from Copilot response: {text[:500]}')

    return json.loads(match.group(0))


def copilot_api_call(messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
    del schema
    model_hint = os.environ.get('COPILOT_MODEL_HINT', '').strip()
    prompt_parts = [
        'Return only valid JSON following the required schema.',
        f'Supported theme keys: {", ".join(THEME_KEYS)}.',
    ]
    if model_hint:
        prompt_parts.append(f'Model hint: {model_hint}.')
    for message in messages:
        role = message.get('role', 'user').upper()
        prompt_parts.append(f'[{role}]\n{message.get("content", "")}')

    prompt = '\n\n'.join(prompt_parts)
    client = get_copilot_client()
    response_text, _conversation_name = client.send_message_lite(prompt, continue_conversation=False, use_web=False)
    parsed = extract_json_object(response_text)
    return json.dumps(parsed)


def choose_provider(provider_arg: str) -> str:
    provider = provider_arg.strip().lower()
    if provider != 'auto':
        return provider

    helper_root = resolve_copilot_helper_root()
    if (helper_root / 'src' / 'copilot_api.py').exists():
        return 'copilot-api'
    return 'openai'


def classify_speech(speech_text: str, prompt_template: str, schema: dict[str, Any], provider: str) -> dict[str, Any]:
    messages = build_messages(prompt_template, speech_text)
    if provider == 'openai':
        raw_response = openai_compatible_call(messages, schema)
        parsed = json.loads(raw_response)
    elif provider == 'copilot-api':
        raw_response = copilot_api_call(messages, schema)
        parsed = json.loads(raw_response)
    else:
        raise ValueError(f'Unsupported provider: {provider}')

    return validate_response(parsed)


def iter_speeches(source_root: Path):
    if source_root.is_file():
        yield source_root
        return

    for path in sorted(source_root.glob('20*/**/*')):
        if path.suffix.lower() in {'.html', '.pdf'}:
            yield path


def build_record(path: Path) -> dict[str, Any]:
    text = extract_text(path)
    if not text or not text.strip():
        raise ValueError(f'No text extracted from {path}')

    return {
        'speech_id': path.stem,
        'source_path': str(path),
        'text': text,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Classify speeches with an LLM using the fixed MPC theme taxonomy.')
    parser.add_argument('--source-root', type=Path, required=True, help='Folder containing the HTML/PDF speech corpus.')
    parser.add_argument('--output-jsonl', type=Path, default=Path('llm_theme_results.jsonl'), help='Path for JSONL output.')
    parser.add_argument('--max-speeches', type=int, default=None, help='Optional cap on speeches to classify.')
    parser.add_argument(
        '--provider',
        choices=['auto', 'openai', 'copilot-api'],
        default='auto',
        help='LLM provider. auto prefers copilot-api if helper is available; otherwise openai.',
    )
    args = parser.parse_args()

    if not args.source_root.exists():
        raise FileNotFoundError(f'Source root does not exist: {args.source_root}')

    provider = choose_provider(args.provider)
    print(f'Using provider: {provider}')

    prompt_template = load_prompt_template()
    schema = load_schema()
    output_path = args.output_jsonl
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with output_path.open('w', encoding='utf-8') as f:
        for path in iter_speeches(args.source_root):
            if args.max_speeches and written >= args.max_speeches:
                break
            try:
                record = build_record(path)
                classification = classify_speech(record['text'], prompt_template, schema, provider)
                payload = {
                    'speech_id': record['speech_id'],
                    'source_path': record['source_path'],
                    'provider': provider,
                    'primary_theme': classification['primary_theme'],
                    'secondary_themes': classification['secondary_themes'],
                    'confidence': classification['confidence'],
                    'evidence_excerpt': classification['evidence_excerpt'],
                    'rationale': classification['rationale'],
                }
                f.write(json.dumps(payload, ensure_ascii=False) + '\n')
                written += 1
                print(f'Classified {record["speech_id"]}: {classification["primary_theme"]}')
            except Exception as exc:  # pragma: no cover
                print(f'Failed for {path}: {exc}')

    print(f'Wrote {written} LLM classifications to {output_path}')


if __name__ == '__main__':
    main()
