#!/usr/bin/env python3
"""Single-command launcher for Seven-Step Topic Tutor, powered by Gemini."""
import argparse
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import venv
from tutor.config import load_env

ROOT = Path(__file__).resolve().parent


def choose_port(host: str, preferred_port: int) -> int:
    for port in range(preferred_port, preferred_port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f'No free port available starting at {preferred_port}.')


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=os.getenv('GEMINI_MODEL', 'gemini-3.8-flash'))
    parser.add_argument('--port', type=int, default=8501)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--check', action='store_true', help='Install dependencies and verify GEMINI_API_KEY and model access without generating a lesson')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or newer is required; Python 3.12 is recommended.')
    env_dir = ROOT / '.venv'
    python = env_dir / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('Creating isolated Python environment…', flush=True)
        venv.EnvBuilder(with_pip=True).create(env_dir)
    requirement = ROOT / 'requirements.txt'
    digest = hashlib.sha256(requirement.read_bytes()).hexdigest()
    stamp = env_dir / '.requirements-hash'
    if not stamp.exists() or stamp.read_text() != digest:
        subprocess.check_call([str(python), '-m', 'pip', 'install', '-r', str(requirement)])
        stamp.write_text(digest)
    os.environ['GEMINI_MODEL'] = args.model
    if args.check:
        script = 'import os; from tutor.grok_client import GrokClient; print("Model access verified:", GrokClient(model=os.environ["GEMINI_MODEL"]).resolve_model())'
        result = subprocess.run([str(python), '-c', script], cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'Credential check failed.')
        print(result.stdout.strip())
        return

    actual_port = args.port
    if args.port == 8501:
        try:
            actual_port = choose_port(args.host, args.port)
        except RuntimeError:
            actual_port = args.port

    print('Open http://' + args.host + ':' + str(actual_port) + ' and enter your Gemini key in the sidebar if not configured.', flush=True)
    subprocess.run([str(python), '-m', 'streamlit', 'run', 'app.py', '--server.address', args.host, '--server.port', str(actual_port), '--browser.gatherUsageStats=false'], cwd=ROOT, check=True)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped.')
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'\nStartup failed: {exc}', file=sys.stderr)
        sys.exit(1)
