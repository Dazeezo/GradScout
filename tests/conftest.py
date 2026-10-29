import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import config  # noqa: E402
import server  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402


@pytest.fixture
def gs(tmp_path, monkeypatch):
    """Point all GradScout data files at a temporary folder."""
    monkeypatch.setattr(config, "DATA", tmp_path)
    return SimpleNamespace(cfg=config, store=store, sources=sources, server=server, data=tmp_path)


class FakeResponse:
    def __init__(self, payload=None, content=b"", status_code=200):
        self._payload, self.content, self.status_code = payload, content, status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise sources.httpx.HTTPStatusError("error", request=None, response=None)


@pytest.fixture
def fake_http(monkeypatch):
    """Queue fake responses: fake_http.get.append(FakeResponse(...)); calls are recorded in fake_http.calls."""
    state = SimpleNamespace(get=[], post=[], calls=[])

    def _get(url, params=None, **_):
        state.calls.append(("GET", url, params))
        return state.get.pop(0)

    def _post(url, json=None, **_):
        state.calls.append(("POST", url, json))
        return state.post.pop(0)

    monkeypatch.setattr(sources.httpx, "get", _get)
    monkeypatch.setattr(sources.httpx, "post", _post)
    return state
