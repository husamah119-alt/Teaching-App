"""Discover local GGUF files without network access or loading model weights."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import struct


@dataclass(frozen=True)
class LocalModel:
    path: str
    name: str
    size: int
    modified_ns: int

    @property
    def identity(self):
        return self.path, self.size, self.modified_ns

    @property
    def label(self):
        return f'{self.name} · {self.size / (1024 ** 3):.2f} GB'


def inspect_model(path, name=None):
    """A GGUF header indicates a candidate, not proof of loadability."""
    try:
        file = Path(path).expanduser().resolve(strict=True)
        stat = file.stat()
        if not file.is_file() or stat.st_size < 24:
            raise ValueError('ملف النموذج غير صالح أو غير مكتمل.')
        with file.open('rb') as stream:
            magic, version = struct.unpack('<4sI', stream.read(8))
        if magic != b'GGUF' or version not in (2, 3):
            raise ValueError('الملف ليس نموذج GGUF مدعوماً أو ما زال غير مكتمل.')
        return LocalModel(str(file), name or Path(path).name, stat.st_size, stat.st_mtime_ns)
    except (OSError, RuntimeError, struct.error):
        raise ValueError('تعذّرت قراءة النموذج. تحقق من وجود الملف وصلاحياته.') from None


def default_roots():
    home = Path.home()
    roots = [Path(__file__).parent / 'models', home / '.lmstudio/models',
             home / '.cache/lm-studio/models', home / '.cache/huggingface/hub',
             home / '.ollama/models', Path('/usr/share/ollama/.ollama/models'),
             Path('/var/lib/ollama/models')]
    if os.environ.get('HF_HOME'):
        roots.append(Path(os.environ['HF_HOME']) / 'hub')
    if os.environ.get('HF_HUB_CACHE'):
        roots.append(Path(os.environ['HF_HUB_CACHE']))
    if os.environ.get('OLLAMA_MODELS'):
        roots.append(Path(os.environ['OLLAMA_MODELS']))
    if os.environ.get('RIWAQ_MODEL_PATH'):
        roots.append(Path(os.environ['RIWAQ_MODEL_PATH']))
    return roots


def discover_models(extra_folder='', *, roots=None, max_entries=15000, max_depth=10):
    """Bounded search of known caches and an optional user-supplied directory."""
    roots = list(default_roots() if roots is None else roots)
    if extra_folder.strip():
        roots.insert(0, Path(extra_folder.strip()).expanduser())
    models, warnings, seen_roots = {}, [], set()
    visited = 0

    def candidate(path, name=None):
        try:
            model = inspect_model(path, name)
            models.setdefault(model.path, model)
        except ValueError:
            warnings.append(f'تجاهلنا ملفاً غير صالح أو غير قابل للقراءة: {path}')

    def manifest(path, root):
        try:
            if path.stat().st_size > 1024 * 1024:
                raise ValueError('Manifest too large')
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                return
            for layer in data.get('layers', []):
                if not isinstance(layer, dict) or layer.get('mediaType') != 'application/vnd.ollama.image.model':
                    continue
                digest = layer.get('digest', '')
                if re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
                    # Blob paths come only from a validated digest, never manifest paths.
                    relative = path.relative_to(root / 'manifests')
                    candidate(root / 'blobs' / digest.replace(':', '-'), f'Ollama: {relative.parent.name}:{relative.name}')
        except (OSError, ValueError, TypeError, AttributeError):
            warnings.append(f'تعذّرت قراءة بيانات نموذج Ollama: {path}')

    for root in roots:
        root = Path(root).expanduser()
        try:
            key = str(root.resolve())
            if key in seen_roots:
                continue
            seen_roots.add(key)
            if not root.exists():
                if extra_folder.strip() and root == Path(extra_folder.strip()).expanduser():
                    warnings.append('المجلد الإضافي غير موجود على الجهاز الذي يشغّل التطبيق.')
                continue
            if root.is_file():
                candidate(root)
                continue
            if not root.is_dir():
                continue
            ollama_root = root if (root / 'manifests').is_dir() else None

            def onerror(error):
                warnings.append(f'تعذّر فحص مجلد: {error.filename}')

            for directory, directories, filenames in os.walk(root, followlinks=False, onerror=onerror):
                relative = Path(directory).relative_to(root)
                if len(relative.parts) >= max_depth:
                    if directories:
                        warnings.append(f'توقف الفحص عند حد عمق المجلدات: {directory}')
                    directories[:] = []
                directories[:] = sorted(d for d in directories if d not in {'.git', '.venv', '__pycache__', 'node_modules'})
                visited += 1 + len(filenames)
                if visited > max_entries:
                    warnings.append('وصل الفحص إلى حد الملفات؛ استخدم مجلداً إضافياً أضيق لإكمال البحث.')
                    return sorted(models.values(), key=lambda m: (m.name.casefold(), m.path)), warnings
                for name in sorted(filenames):
                    path = Path(directory) / name
                    if name.lower().endswith('.gguf'):
                        # llama.cpp opens other shards through the first file.
                        shard = re.search(r'-(\d{5})-of-\d{5}\.gguf$', name, flags=re.I)
                        if not shard or shard.group(1) == '00001':
                            candidate(path)
                    elif ollama_root and relative.parts and relative.parts[0] == 'manifests':
                        manifest(path, ollama_root)
        except (OSError, RuntimeError):
            warnings.append(f'تعذّر فحص المسار: {root}')
    return sorted(models.values(), key=lambda m: (m.name.casefold(), m.path)), warnings
