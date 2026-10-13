"""Read cross-platform worker commands without a shell or token-bearing command lines."""

import json
from pathlib import Path


def load_command(path):
    source = Path(path)
    if source.stat().st_size > 1_000_000:
        raise ValueError('The command file must be smaller than 1 MB.')
    try:
        value = json.loads(source.read_text(encoding='utf-8-sig'))
    except ValueError:
        raise ValueError('The command file must contain a JSON array of command arguments.') from None
    if not isinstance(value, list) or not 1 <= len(value) <= 100 or any(
            not isinstance(arg, str) or '\0' in arg or len(arg) > 32768 for arg in value) or not value[0].strip():
        raise ValueError('Use a nonempty JSON array of up to 100 string arguments, without NUL characters.')
    return value
