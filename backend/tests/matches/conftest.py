import pytest

from app.matches.catalog import HARNESSES
from app.matches.repository import MatchRepository


@pytest.fixture
def repository(database_path):
    store = MatchRepository(str(database_path))
    yield store
    store.close()


@pytest.fixture
def harnesses():
    return HARNESSES[0], HARNESSES[1]
