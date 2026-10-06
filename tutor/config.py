"""Minimal .env loader: literal values only, never shell commands or interpolation."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {'GEMINI_API_KEY', 'GEMINI_MODEL'}


def load_env(path=None):
    path = Path(path) if path is not None else ROOT / '.env'
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        name, value = name.strip(), value.strip()
        if name not in ALLOWED:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '\"\'':
            value = value[1:-1]
        os.environ.setdefault(name, value)
