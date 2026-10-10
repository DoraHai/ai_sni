"""Deployment head reads remain fresh and fail closed across transports."""
import importlib.util
import json
from pathlib import Path
import subprocess
from urllib.error import URLError

import pytest


@pytest.fixture
def handler():
    path = Path(__file__).parents[1] / 'ops/customer-workbench/static_release.py'
    spec = importlib.util.spec_from_file_location('static_head_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def response(url, head='a' * 40, name='codex/production-sem'):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return url
        def read(self, maximum): return json.dumps({'name': name, 'commit': {'sha': head}}).encode()
    return Response()


def test_official_api_authorizes_without_git_and_uses_distinct_no_cache_reads(handler, monkeypatch):
    calls = []
    def read(request, timeout):
        calls.append(request)
        assert request.full_url.startswith('https://api.github.com/repos/DoraHai/ai_sni/branches/codex%2Fproduction-sem?release_check=')
        assert request.get_header('Cache-control') == 'no-cache' and timeout == 15
        return response(request.full_url)
    monkeypatch.setattr(handler, 'urlopen', read)
    monkeypatch.setattr(handler.subprocess, 'check_output', lambda *a, **kw: pytest.fail('Git transport is unnecessary'))
    handler.authorize_head('a' * 40)
    handler.authorize_head('a' * 40)
    assert calls[0].full_url != calls[1].full_url


@pytest.mark.parametrize('head,name', [('b' * 40, 'codex/production-sem'), ('a' * 40, 'other-branch'), ('invalid', 'codex/production-sem')])
def test_stale_or_malformed_api_never_falls_back_to_mask_the_mismatch(handler, monkeypatch, head, name):
    monkeypatch.setattr(handler, 'urlopen', lambda req, **kw: response(req.full_url, head, name))
    monkeypatch.setattr(handler.subprocess, 'check_output', lambda *a, **kw: pytest.fail('Must reject observed mismatch'))
    with pytest.raises(ValueError):
        handler.authorize_head('a' * 40)


def test_redirected_branch_source_cannot_authorize(handler, monkeypatch):
    monkeypatch.setattr(handler, 'urlopen', lambda req, **kw: response('https://other.invalid/branch'))
    with pytest.raises(ValueError, match='source'):
        handler.authorize_head('a' * 40)


def test_git_fallback_requires_the_exact_reference_and_both_failures_reject(handler, monkeypatch):
    def unavailable(*a, **kw): raise URLError('offline')
    monkeypatch.setattr(handler, 'urlopen', unavailable)
    outputs = iter(['a' * 40 + '\trefs/heads/codex/production-sem', 'b' * 40 + '\trefs/heads/codex/production-sem'])
    monkeypatch.setattr(handler.subprocess, 'check_output', lambda *a, **kw: next(outputs))
    handler.authorize_head('a' * 40)
    with pytest.raises(ValueError, match='stale'):
        handler.authorize_head('a' * 40)
    def git_unavailable(*a, **kw): raise subprocess.TimeoutExpired(['git'], 20)
    monkeypatch.setattr(handler.subprocess, 'check_output', git_unavailable)
    with pytest.raises(subprocess.TimeoutExpired):
        handler.authorize_head('a' * 40)


def test_head_change_during_staging_keeps_existing_release(handler, monkeypatch, tmp_path):
    old, new = 'a' * 40, 'b' * 40
    files = {name: ('fixture ' + name).encode() for name in handler.FILES}
    handler.activate(tmp_path, old, files)
    heads = iter([new, old])
    monkeypatch.setattr(handler, 'urlopen', lambda req, **kw: response(req.full_url, next(heads)))
    handler.authorize_head(new)
    with pytest.raises(ValueError, match='stale'):
        handler.activate(tmp_path, new, files, authorize=lambda: handler.authorize_head(new))
    assert (tmp_path / 'current').resolve().name == old
