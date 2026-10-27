"""Download an official free GGUF model, verifying its publisher LFS SHA-256."""
import hashlib
import re
from pathlib import Path
import sys
import tempfile

import requests

REPO = 'Qwen/Qwen2.5-1.5B-Instruct-GGUF'
FILENAME = 'qwen2.5-1.5b-instruct-q4_k_m.gguf'
ROOT = Path(__file__).resolve().parents[1]


def install():
    # TLS verification stays enabled; the expected hash comes from official metadata.
    response = requests.get(f'https://huggingface.co/api/models/{REPO}', params={'blobs': 'true'}, timeout=(15, 30))
    response.raise_for_status()
    metadata = response.json()
    entry = next(f for f in metadata['siblings'] if f['rfilename'] == FILENAME)
    expected = entry['lfs'].get('sha256') or entry['lfs'].get('oid')
    revision = metadata['sha']
    if not re.fullmatch(r'[0-9a-f]{64}', expected or '') or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Invalid publisher checksum or revision')
    destination = ROOT / 'models' / FILENAME
    destination.parent.mkdir(exist_ok=True)
    if destination.exists():
        with destination.open('rb') as existing:
            digest = hashlib.file_digest(existing, 'sha256').hexdigest()
        if digest != expected:
            raise ValueError('Existing model differs from publisher checksum; move it before retrying.')
        print('Verified existing model:', destination.name)
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.part', delete=False) as output:
            temporary = Path(output.name)
            hasher = hashlib.sha256()
            with requests.get(f'https://huggingface.co/{REPO}/resolve/{revision}/{FILENAME}', stream=True, timeout=(15, 90)) as model:
                model.raise_for_status()
                total = 0
                for block in model.iter_content(1024 * 1024):
                    total += len(block)
                    if total > 2 * 1024 ** 3:
                        raise ValueError('Model download exceeds expected size limit')
                    output.write(block)
                    hasher.update(block)
            if hasher.hexdigest() != expected:
                raise ValueError('Model checksum verification failed')
        with temporary.open('rb') as data:
            if data.read(4) != b'GGUF':
                raise ValueError('Downloaded file is not GGUF')
        temporary.replace(destination)
        print('Installed and SHA-256 verified:', destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        install()
    except (requests.RequestException, ValueError, KeyError, StopIteration) as exc:
        print('Model installation failed. Check access to huggingface.co and its download domains, or provide an official verified GGUF file.', file=sys.stderr)
        sys.exit(1)
