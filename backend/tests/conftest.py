from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def database_path():
    directory = Path.cwd() / ".test-data"
    directory.mkdir(exist_ok=True)
    path = directory / f"matches-{uuid4().hex}.sqlite3"
    yield path
    for candidate in (path, Path(f"{path}-shm"), Path(f"{path}-wal")):
        candidate.unlink(missing_ok=True)
