"""Test configuration and fixtures."""

import pytest


@pytest.fixture
def expected_lingering_threads() -> bool:
    """Allow lingering threads for aiohttp tests.

    This specifically allows the _run_safe_shutdown_loop thread created by aiohttp
    connectors to linger after test completion as it's cleaned up asynchronously.
    The pytest-homeassistant-custom-component plugin checks for this fixture.
    """
    return True


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Allow lingering timers for aiohttp tests.

    This is needed because aiohttp creates background timers that
    are cleaned up asynchronously and may not finish before test teardown.
    """
    return True


@pytest.fixture
def expected_lingering_tasks() -> bool:
    """Allow lingering tasks for aiohttp tests."""
    return True
