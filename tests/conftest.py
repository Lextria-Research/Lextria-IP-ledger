"""Shared pytest fixtures for the whole tests/ suite."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend import auth  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_ip_login_limiter():
    """Every test in this run shares one process, and every request made
    through Starlette's TestClient reports the same fake source address --
    so without this, auth.py's in-memory per-address login limiter would
    carry counts over from one test into an unrelated later one, since
    nothing else in the test suite ever resets it (a real deployment never
    needs to: the limiter is deliberately unpersisted, see auth.py)."""
    auth.reset_ip_login_limiter()
    yield
    auth.reset_ip_login_limiter()
