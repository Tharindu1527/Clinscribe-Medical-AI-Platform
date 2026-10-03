from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests by folder, so `-m unit` / `-m integration` work without per-test decorators."""
    for item in items:
        folder = item.path.relative_to(TESTS_DIR).parts[0]
        if folder in ("unit", "integration"):
            item.add_marker(getattr(pytest.mark, folder))
