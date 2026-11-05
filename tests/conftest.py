"""Shared fixtures."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom component loadable in every test."""
    yield


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """Give each test its own writable config directory.

    pytest-homeassistant points every test at a shared ``tests/testing_config``
    that this repository does not have; the tts component failed to create its
    cache there and every tts pool test failed with it.
    """
    return hass_tmp_config_dir
