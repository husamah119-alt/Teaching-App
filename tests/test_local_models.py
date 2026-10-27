from dataclasses import asdict
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

import report_engine
from local_models import discover_models, inspect_model


def gguf(path, payload=b'model weights placeholder'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack('<4sIQQ', b'GGUF', 3, 1, 1) + payload)
    return path


def test_discovery_standard_gguf_ollama_manifests_and_duplicate_aliases(tmp_path):
    lm = gguf(tmp_path / 'lmstudio' / 'publisher' / 'model.gguf')
    (tmp_path / 'lmstudio' / 'duplicate.gguf').symlink_to(lm)
    (tmp_path / 'lmstudio' / 'broken.gguf').write_bytes(b'not a model')
    ollama = tmp_path / 'ollama'
    digest = 'a' * 64
    blob = gguf(ollama / 'blobs' / ('sha256-' + digest))
    manifest = ollama / 'manifests' / 'registry.ollama.ai' / 'library' / 'qwen' / 'latest'
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'layers': [{'mediaType': 'application/vnd.ollama.image.model', 'digest': 'sha256:' + digest}]}))
    models, warnings = discover_models(roots=[tmp_path / 'lmstudio', ollama])
    assert {m.path for m in models} == {str(lm), str(blob)}
    assert any(m.name == 'Ollama: qwen:latest' for m in models)
    assert any('broken.gguf' in w for w in warnings)


def test_refresh_detects_new_and_removed_files_and_scan_bounds(tmp_path):
    first = gguf(tmp_path / 'first.gguf')
    models, _ = discover_models(roots=[tmp_path])
    assert len(models) == 1
    first.unlink()
    second = gguf(tmp_path / 'second.gguf')
    models, _ = discover_models(roots=[tmp_path])
    assert [m.path for m in models] == [str(second)]
    _, warnings = discover_models(roots=[tmp_path], max_entries=1)
    assert any('حد الملفات' in w for w in warnings)
    models, warnings = discover_models(str(tmp_path / 'missing'), roots=[])
    assert not models and warnings


def test_configured_roots_support_gguf_and_ollama_locations(tmp_path, monkeypatch):
    from local_models import default_roots
    file = gguf(tmp_path / 'custom.gguf')
    monkeypatch.setenv('RIWAQ_MODEL_PATH', str(file))
    monkeypatch.setenv('OLLAMA_MODELS', str(tmp_path / 'other_ollama'))
    monkeypatch.setenv('HF_HUB_CACHE', str(tmp_path / 'other_hf'))
    roots = default_roots()
    assert file in roots and tmp_path / 'other_ollama' in roots and tmp_path / 'other_hf' in roots


def test_runtime_switch_closes_previous_model_and_refreshes_replaced_file(tmp_path, monkeypatch):
    first, second = gguf(tmp_path / 'first.gguf'), gguf(tmp_path / 'second.gguf')
    events = []

    def factory(**kwargs):
        events.append(('load', kwargs['model_path']))
        model = Mock()
        model.close.side_effect = lambda: events.append(('close', kwargs['model_path']))
        return model

    monkeypatch.setitem(sys.modules, 'llama_cpp', SimpleNamespace(Llama=factory))
    monkeypatch.setattr(report_engine, '_loaded_model', None)
    monkeypatch.setattr(report_engine, '_loaded_identity', None)
    report_engine.activate_model(first)
    report_engine.activate_model(first)
    assert events == [('load', str(first))]
    report_engine.activate_model(second)
    assert events[-2:] == [('close', str(first)), ('load', str(second))]
    gguf(second, b'new longer model file')
    report_engine.activate_model(second)
    assert events[-2:] == [('close', str(second)), ('load', str(second))]


def test_activation_rejects_corrupt_or_incompatible_model(tmp_path, monkeypatch):
    path = tmp_path / 'bad.gguf'
    path.write_bytes(b'bad')
    with pytest.raises(ValueError):
        report_engine.activate_model(path)
    gguf(path)
    monkeypatch.setattr(report_engine, '_loaded_model', None)
    monkeypatch.setattr(report_engine, '_loaded_identity', None)
    monkeypatch.setitem(sys.modules, 'llama_cpp', SimpleNamespace(Llama=Mock(side_effect=ValueError('unsupported architecture'))))
    with pytest.raises(ValueError, match='تحميل النموذج'):
        report_engine.activate_model(path)
    assert report_engine._loaded_identity is None


def test_sidebar_refresh_activation_and_selected_model_generation(tmp_path, monkeypatch):
    first, second = gguf(tmp_path / 'one.gguf'), gguf(tmp_path / 'two.gguf')
    choices = [inspect_model(first)]
    monkeypatch.setattr('local_models.discover_models', lambda extra='': (choices[:], []))
    activate = Mock(side_effect=inspect_model)
    monkeypatch.setattr(report_engine, 'activate_model', activate)
    generate = Mock(return_value=('## المقدمة\nنص من النموذج المحدد.', []))
    monkeypatch.setattr(report_engine, 'generate_report', generate)
    app = AppTest.from_file(str(Path(__file__).parents[1] / 'app.py'), default_timeout=30).run()
    assert not app.exception
    assert len(next(s for s in app.selectbox if s.label == 'النموذج المحلي').options) == 1
    choices.append(inspect_model(second))
    next(b for b in app.button if b.label == 'تحديث النماذج المحلية').click().run()
    chooser = next(s for s in app.selectbox if s.label == 'النموذج المحلي')
    assert len(chooser.options) == 2
    chooser.select(str(second)).run()
    next(b for b in app.button if b.label == 'تفعيل النموذج المختار').click().run()
    assert not app.exception and not app.error
    activate.assert_called_once_with(str(second))
    assert app.session_state['active_local_model']['path'] == str(second)
    assert next(r for r in app.radio if r.label == 'طريقة إعداد التقرير').value == 'صياغة بنموذج محلي مجاني'
    next(t for t in app.text_input if t.label.startswith('موضوع البحث')).input('الطاقة')
    next(s for s in app.selectbox if s.label == 'المصادر المعتمدة').select('المعرفة العامة')
    next(b for b in app.button if b.label.startswith('إنشاء الشرح')).click().run()
    assert not app.exception and not app.error
    assert generate.call_args.kwargs['model_path'] == str(second)
    assert len(app.get('download_button')) == 2
    second.unlink()
    next(b for b in app.button if b.label == 'تحديث النماذج المحلية').click().run()
    assert any('لم يعد متاحاً' in w.value for w in app.warning)


def test_failed_activation_does_not_report_success(tmp_path, monkeypatch):
    candidate = inspect_model(gguf(tmp_path / 'unsupported.gguf'))
    monkeypatch.setattr('local_models.discover_models', lambda extra='': ([candidate], []))
    monkeypatch.setattr(report_engine, 'activate_model', Mock(side_effect=ValueError('تعذّر تحميل النموذج المحلي.')))
    app = AppTest.from_file(str(Path(__file__).parents[1] / 'app.py'), default_timeout=30).run()
    next(b for b in app.button if b.label == 'تفعيل النموذج المختار').click().run()
    assert not app.exception and any('تحميل النموذج' in e.value for e in app.error)
    assert 'active_local_model' not in app.session_state
