"""
Shared fixtures for all tests (unit + e2e).
"""

import os
import pytest
import httpx


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def pytest_addoption(parser):
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="Run end-to-end tests (require all services running)",
    )
    parser.addoption(
        "--iterations",
        action="store",
        default=5,
        type=int,
        help="Number of iterations for E2E tests (default: 5)",
    )
    parser.addoption(
        "--model",
        action="store",
        default=None,
        type=str,
        help="Run tests only for a specific model name (substring match)",
    )
    parser.addoption(
        "--report-dir",
        action="store",
        default="backend/tests/reports",
        type=str,
        help="Directory for JSON report files (default: backend/tests/reports)",
    )


@pytest.fixture(scope="session")
def iterations(request):
    return request.config.getoption("--iterations")


@pytest.fixture(scope="session")
def model_filter(request):
    return request.config.getoption("--model")


@pytest.fixture(scope="session")
def report_dir(request):
    return request.config.getoption("--report-dir")


@pytest.fixture(scope="session")
def http_client():
    """HTTP client pointing at the real backend."""
    with httpx.Client(base_url=BACKEND_URL, timeout=180.0) as client:
        yield client


@pytest.fixture(scope="session")
async def async_http_client():
    """Async version of the HTTP client."""
    async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=180.0) as client:
        yield client


def pytest_collection_modifyitems(config, items):
    """Skip E2E tests if --e2e not passed explicitly."""
    if not config.getoption("--e2e", default=False):
        skip_e2e = pytest.mark.skip(reason="Use --e2e to run end-to-end tests")
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip_e2e)
