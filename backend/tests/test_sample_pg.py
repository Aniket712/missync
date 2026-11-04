"""The embedded sample database must fail fast, with a clear message, where pgserver exposes no TCP port (Linux/macOS use a Unix socket)."""
import pytest

from missync.demo import sample_pg


class _SocketOnlyServer:
    cleaned = False

    def get_uri(self, database=None):
        return "postgresql://postgres:@/postgres?host=/tmp/pgsock"

    def cleanup(self):
        self.cleaned = True


class _FakePgserver:
    server = _SocketOnlyServer()

    def get_server(self, *_a, **_k):
        return self.server


@pytest.fixture(autouse=True)
def _reset():
    sample_pg._server = None
    yield
    sample_pg._server = None


def test_start_without_tcp_port_raises_clear_error_and_stops_server(monkeypatch, tmp_path):
    fake = _FakePgserver()
    monkeypatch.setattr(sample_pg, "_import_pgserver", lambda: fake)
    with pytest.raises(sample_pg.SampleUnavailable, match="Unix socket"):
        sample_pg.start(tmp_path)
    assert fake.server.cleaned and sample_pg._server is None  # nothing left running, the lock is released
    with pytest.raises(sample_pg.SampleUnavailable):  # a second attempt is not blocked by a held lock
        sample_pg.start(tmp_path)


def test_status_reports_unavailable_for_socket_only_server(monkeypatch):
    monkeypatch.setattr(sample_pg, "_import_pgserver", lambda: _FakePgserver())
    sample_pg._server = _SocketOnlyServer()
    st = sample_pg.status()
    assert st["available"] is False and "Unix socket" in st["message"]
