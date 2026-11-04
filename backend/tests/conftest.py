import pytest

from missync.config import get_settings
from missync.demo.seed import DEMO_ASSETS, build_demo_db
from missync.models import Asset


@pytest.fixture(scope="session")
def demo_db(tmp_path_factory):
    return build_demo_db(tmp_path_factory.mktemp("demo") / "demo.sqlite")


@pytest.fixture()
def assets():
    return [Asset(name=n, kind=k, depends_on=d) for n, k, d in DEMO_ASSETS]


@pytest.fixture()
def sqlite_conn(demo_db):
    from missync.connectors.sqlite import SQLiteConnector

    c = SQLiteConnector(str(demo_db), enforce_path=False)
    yield c
    c.close()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSYNC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MISSYNC_MODE", "demo")
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from missync.api.app import create_app
    from missync.store.db import Store

    app = create_app(Store(f"sqlite:///{(tmp_path / 'meta.db').as_posix()}"))
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
