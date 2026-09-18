#!/usr/bin/env python3
"""Write the local config for hustcer/deepseek-review from the workflow file.

The PR review on GitHub and the pre-flight review run here should be the same
reviewer: same model, temperature, exclusions and, above all, the same system
prompt. Two copies of that prompt would drift within a week. So there is one -
in .github/workflows/deepseek-review.yml, where the action reads it - and this
derives the CLI's config.yml from it each time the wrapper runs.

Where the workflow leaves an input unset, the action supplies a default, and
so must this - the action's own, read from action.yaml in the pinned checkout,
not a guess written here. A default of ours that differed from the action's
would be the drift this file exists to prevent, arriving by the back door.

Secrets never touch the repository. The DeepSeek token comes from CHAT_TOKEN in
the environment, the GitHub token from `gh auth token`, and the file this
writes lands in the user's config directory with mode 600.

    review-config.py --action ACTION_YAML [--workflow FILE] [--out FILE]
"""

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
WORKFLOW = REPO / '.github' / 'workflows' / 'deepseek-review.yml'
OUT = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'deepseek-review' / 'config.yml'


def review_step(workflow: dict) -> dict:
    for job in workflow['jobs'].values():
        for step in job.get('steps', []):
            if 'deepseek-review' in str(step.get('uses', '')):
                return step['with']
    sys.exit(f'{WORKFLOW}: no step uses hustcer/deepseek-review')


def today() -> str:
    # the workflow's Today step: date -u '+%A %d %B %Y'
    return dt.datetime.now(dt.timezone.utc).strftime('%A %d %B %Y')


def gh_token() -> str:
    try:
        return subprocess.run(['gh', 'auth', 'token'], check=True, capture_output=True,
                              text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def inputs(step_with: dict, action_yaml: Path) -> dict:
    """Every input the action knows, valued as the action would see it: what
    the workflow sets, else the action's default. Then expanded, and refused
    if any expression is left that this script cannot expand - in any field,
    not only the prompt."""
    with open(action_yaml, encoding='utf-8') as f:
        action = yaml.safe_load(f)
    out = {}
    for name, spec in action['inputs'].items():
        value = step_with.get(name, spec.get('default'))
        if isinstance(value, str):
            value = value.replace('${{ steps.today.outputs.date }}', today())
            # the action's own default for github-token is the workflow's
            # token, which does not exist here; gh supplies ours below
            if name == 'github-token' and '${{ github.token }}' in value:
                value = ''
            if '${{' in value:
                sys.exit(f'{name}: has an expression this script does not know how to expand: {value!r}')
        out[name] = value
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--action', type=Path, required=True,
                    help='action.yaml of the pinned hustcer/deepseek-review checkout, for the defaults')
    ap.add_argument('--workflow', type=Path, default=WORKFLOW)
    ap.add_argument('--out', type=Path, default=OUT)
    args = ap.parse_args()

    with open(args.workflow, encoding='utf-8') as f:
        wf = yaml.safe_load(f)
    w = inputs(review_step(wf), args.action)

    chat_token = os.environ.get('CHAT_TOKEN', '')
    if not chat_token:
        # a config with a placeholder token fails later, at the API, with a
        # message about authentication rather than about the missing token
        sys.exit('review-config: CHAT_TOKEN is not set; nothing written')

    config = {
        'settings': {
            'provider': 'DeepSeek',
            'max-length': int(w['max-length']),
            'temperature': float(w['temperature']),
            'user-prompt': 'default',
            'system-prompt': 'default',
            'github-token': gh_token(),
            'default-github-repo': 'opengeofiction-net/danu',
            'include-patterns': w['include-patterns'] or '',
            'exclude-patterns': w['exclude-patterns'] or '',
        },
        'providers': [{
            'name': 'DeepSeek',
            'token': chat_token,
            'base-url': w['base-url'],
            'models': [{'name': w['model'], 'enabled': True}],
        }],
        'prompts': {
            'user': [{'name': 'default', 'prompt': w['user-prompt']}],
            'system': [{'name': 'default', 'prompt': w['sys-prompt']}],
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write('# Generated by packaging/ci/review-config.py from the workflow - do not edit,\n'
                '# do not commit. Holds tokens.\n')
        yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True, width=100)
    os.chmod(args.out, 0o600)
    return 0


if __name__ == '__main__':
    sys.exit(main())
