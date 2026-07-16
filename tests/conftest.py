from __future__ import annotations

from pathlib import Path

import pytest

from canforge_mcp import tools

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def reset_dbc_cache() -> None:
    tools.clear_dbc_cache()
    yield
    tools.clear_dbc_cache()


@pytest.fixture
def sample_dbc() -> Path:
    return FIXTURES / "sample.dbc"


@pytest.fixture
def changed_dbc() -> Path:
    return FIXTURES / "sample_changed.dbc"


@pytest.fixture
def invalid_dbc() -> Path:
    return FIXTURES / "invalid.dbc"


@pytest.fixture
def candump_log() -> Path:
    return FIXTURES / "candump" / "candump.log"


@pytest.fixture
def asc_log() -> Path:
    return FIXTURES / "vector_asc" / "python_can_logfile.asc"
