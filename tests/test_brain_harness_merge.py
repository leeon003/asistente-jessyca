"""Preserve the Brain branch's document backend when merging audit guards."""
import asyncio
from unittest.mock import Mock

from core.anydoc import adapter as module
from core.anydoc.models import AnyDocResult, ConversionStatus


def test_docling_conversion_does_not_require_anydoc(monkeypatch, tmp_path):
    monkeypatch.setattr(module, 'anydoc', None)
    adapter = module.AnyDocAdapter(backend='docling')
    source = tmp_path / 'input.txt'
    source.write_text('Document')
    backend = Mock()
    backend.health.return_value = {'status': 'healthy'}
    result = AnyDocResult(operation_id='merge', status=ConversionStatus.SUCCESS,
                         input_path=str(source), detected_format='txt')
    backend.convert_document.return_value = result
    adapter._docling_backend = backend
    monkeypatch.setattr(adapter, 'validate_and_confine_path', lambda path, **kwargs: str(path))
    assert asyncio.run(adapter.initialize()) is True
    assert asyncio.run(adapter.health_check()).is_healthy
    assert adapter.convert_file(str(source)) is result
    backend.convert_document.assert_called_once()


def test_failed_docling_without_native_fallback_preserves_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(module, 'anydoc', None)
    adapter = module.AnyDocAdapter(backend='docling')
    source = tmp_path / 'input.txt'
    source.write_text('Document')
    backend = Mock()
    backend.health.return_value = {'status': 'healthy'}
    result = AnyDocResult(operation_id='merge', status=ConversionStatus.UNSUPPORTED,
                         input_path=str(source), detected_format='txt')
    backend.convert_document.return_value = result
    adapter._docling_backend = backend
    monkeypatch.setattr(adapter, 'validate_and_confine_path', lambda path, **kwargs: str(path))
    assert adapter.convert_file(str(source)) is result
