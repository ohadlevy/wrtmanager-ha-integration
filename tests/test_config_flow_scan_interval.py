"""Tests for the configurable scan interval functionality."""

import pytest
import voluptuous as vol
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wrtmanager.config_flow import OptionsFlowHandler
from custom_components.wrtmanager.const import (
    CONF_ROUTERS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry with test router data."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ROUTERS: [
                {
                    CONF_HOST: "192.168.1.1",
                    CONF_NAME: "Test Router",
                    CONF_USERNAME: "hass",
                    CONF_PASSWORD: "test123",
                }
            ]
        },
        options={},
        entry_id="test_entry",
    )


@pytest.fixture
def mock_config_entry_with_scan_interval():
    """Create a mock config entry with existing scan interval."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ROUTERS: [
                {
                    CONF_HOST: "192.168.1.1",
                    CONF_NAME: "Test Router",
                    CONF_USERNAME: "hass",
                    CONF_PASSWORD: "test123",
                }
            ]
        },
        options={CONF_SCAN_INTERVAL: 60},
        entry_id="test_entry",
    )


@pytest.mark.asyncio
async def test_options_flow_init_includes_scan_interval(mock_config_entry):
    """Test that options flow init includes scan interval option."""
    options_flow = OptionsFlowHandler(mock_config_entry)

    # Test initial options menu
    result = await options_flow.async_step_init()

    assert result["type"] == "form"
    assert result["step_id"] == "init"

    # Check that scan interval is in the action options
    action_options = result["data_schema"].schema["action"].container
    assert "scan_interval" in action_options
    assert action_options["scan_interval"] == "Configure Polling Interval"


@pytest.mark.asyncio
async def test_scan_interval_step_default_value(mock_config_entry):
    """Test scan interval step shows default value when no options set."""
    options_flow = OptionsFlowHandler(mock_config_entry)

    result = await options_flow.async_step_scan_interval()

    assert result["type"] == "form"
    assert result["step_id"] == "scan_interval"

    # Check that the schema contains the scan interval field
    assert CONF_SCAN_INTERVAL in result["data_schema"].schema

    # Verify the description includes helpful text about range
    description = result["description_placeholders"]["description"]
    assert "10-300 seconds" in description
    assert "polling interval" in description.lower()


@pytest.mark.asyncio
async def test_scan_interval_step_existing_value(mock_config_entry_with_scan_interval):
    """Test scan interval step shows existing value from options."""
    options_flow = OptionsFlowHandler(mock_config_entry_with_scan_interval)

    result = await options_flow.async_step_scan_interval()

    assert result["type"] == "form"
    assert result["step_id"] == "scan_interval"

    # Check that the schema contains the scan interval field
    assert CONF_SCAN_INTERVAL in result["data_schema"].schema


@pytest.mark.asyncio
async def test_scan_interval_validation_range():
    """Test scan interval validation accepts valid range."""
    # Test minimum valid value
    schema = vol.Schema(
        {vol.Required(CONF_SCAN_INTERVAL): vol.All(int, vol.Range(min=10, max=300))}
    )

    # Test valid values
    assert schema({CONF_SCAN_INTERVAL: 10})[CONF_SCAN_INTERVAL] == 10
    assert schema({CONF_SCAN_INTERVAL: 30})[CONF_SCAN_INTERVAL] == 30
    assert schema({CONF_SCAN_INTERVAL: 300})[CONF_SCAN_INTERVAL] == 300

    # Test invalid values
    with pytest.raises(vol.Invalid):
        schema({CONF_SCAN_INTERVAL: 9})  # Below minimum

    with pytest.raises(vol.Invalid):
        schema({CONF_SCAN_INTERVAL: 301})  # Above maximum


@pytest.mark.asyncio
async def test_scan_interval_step_save_value(mock_config_entry):
    """Test scan interval step saves the configured value."""
    options_flow = OptionsFlowHandler(mock_config_entry)

    user_input = {CONF_SCAN_INTERVAL: 45}
    result = await options_flow.async_step_scan_interval(user_input)

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SCAN_INTERVAL] == 45
    assert result["title"] == ""


@pytest.mark.asyncio
async def test_scan_interval_preserves_existing_options():
    """Test that setting scan interval preserves other existing options."""
    # Create a config entry with existing options
    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ROUTERS: [
                {
                    CONF_HOST: "192.168.1.1",
                    CONF_NAME: "Test Router",
                    CONF_USERNAME: "hass",
                    CONF_PASSWORD: "test123",
                }
            ]
        },
        options={CONF_SCAN_INTERVAL: 60, "vlan_names": {1: "Main Network", 2: "Guest Network"}},
        entry_id="test_entry",
    )

    options_flow = OptionsFlowHandler(mock_config_entry)

    user_input = {CONF_SCAN_INTERVAL: 90}
    result = await options_flow.async_step_scan_interval(user_input)

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SCAN_INTERVAL] == 90
    # Verify other options are preserved
    assert result["data"]["vlan_names"] == {1: "Main Network", 2: "Guest Network"}


@pytest.mark.asyncio
async def test_scan_interval_navigation_from_init(mock_config_entry):
    """Test navigation from init step to scan interval step."""
    options_flow = OptionsFlowHandler(mock_config_entry)

    # Navigate to scan interval step
    user_input = {"action": "scan_interval"}
    result = await options_flow.async_step_init(user_input)

    assert result["type"] == "form"
    assert result["step_id"] == "scan_interval"


def test_scan_interval_constants_exist():
    """Test that required constants are defined."""
    assert CONF_SCAN_INTERVAL == "scan_interval"
    assert DEFAULT_SCAN_INTERVAL == 30
    assert isinstance(DEFAULT_SCAN_INTERVAL, int)


def test_scan_interval_validation_edge_cases():
    """Test edge cases for scan interval validation."""
    schema = vol.Schema(
        {vol.Required(CONF_SCAN_INTERVAL): vol.All(int, vol.Range(min=10, max=300))}
    )

    # Test edge values
    assert schema({CONF_SCAN_INTERVAL: 10})[CONF_SCAN_INTERVAL] == 10  # Minimum
    assert schema({CONF_SCAN_INTERVAL: 300})[CONF_SCAN_INTERVAL] == 300  # Maximum

    # Test string inputs that should be converted to int
    with pytest.raises((vol.Invalid, TypeError, ValueError)):
        schema({CONF_SCAN_INTERVAL: "30"})

    # Test float inputs
    with pytest.raises((vol.Invalid, TypeError)):
        schema({CONF_SCAN_INTERVAL: 30.5})

    # Test negative values
    with pytest.raises(vol.Invalid):
        schema({CONF_SCAN_INTERVAL: -10})
