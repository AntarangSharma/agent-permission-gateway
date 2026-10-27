import time
from pathlib import Path

import pytest

from apg.gateway import Gateway
from apg.models import Permissions
from apg.store import Store


@pytest.fixture
def boundary(tmp_path: Path) -> tuple[Store, Gateway]:
    store = Store(tmp_path)
    permissions = Permissions(documents=["brief"], recipients=["alex"])
    with store.connection() as db:
        db.execute(
            "INSERT INTO sessions(id,case_id,mode,variant,permissions,created) "
            "VALUES (?,?,?,?,?,?)",
            ("s1", "L01", "fixture", "gateway", permissions.model_dump_json(), time.time()),
        )
        db.execute(
            "INSERT INTO documents VALUES (?,?,?,?)",
            ("s1", "brief", "Project brief", "Launch June 4."),
        )
        db.execute(
            "INSERT INTO documents VALUES (?,?,?,?)", ("s1", "vault", "Restricted", "SECRET")
        )
    return store, Gateway(store)
