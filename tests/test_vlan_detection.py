"""Tests for the configurable VLAN detection functionality."""

import pytest
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wrtmanager.config_flow import OptionsFlowHandler
from custom_components.wrtmanager.const import (
    ATTR_INTERFACE,
    ATTR_IP,
    CONF_ROUTERS,
    CONF_VLAN_DETECTION_RULES,
    DEFAULT_VLAN_DETECTION_RULES,
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
def mock_config_entry_with_vlan_rules():
    """Create a mock config entry with existing VLAN detection rules."""
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
        options={
            CONF_VLAN_DETECTION_RULES: {
                "static_mappings": {
                    "wlan0-ap0": 1,
                    "wlan0-ap1": 10,
                },
                "interface_patterns": {
                    r".*iot.*": 3,
                    r".*guest.*": 100,
                },
            }
        },
        entry_id="test_entry",
    )


@pytest.mark.asyncio
async def test_options_flow_init_includes_vlan_detection(mock_config_entry):
    """Test that options flow init includes VLAN detection option."""
    options_flow = OptionsFlowHandler(mock_config_entry)

    # Test initial options menu
    result = await options_flow.async_step_init()

    assert result["type"] == "form"
    assert result["step_id"] == "init"

    # Check that VLAN detection is in the action options
    action_options = result["data_schema"].schema["action"].container
    assert "vlan_detection" in action_options
    assert action_options["vlan_detection"] == "Configure VLAN Detection Rules"


@pytest.mark.asyncio
async def test_vlan_detection_step_default_values(mock_config_entry):
    """Test VLAN detection step shows default values when no options set."""
    options_flow = OptionsFlowHandler(mock_config_entry)

    result = await options_flow.async_step_vlan_detection()

    assert result["type"] == "form"
    assert result["step_id"] == "vlan_detection"

    # Check that the schema contains static mapping and pattern fields
    schema_keys = list(result["data_schema"].schema.keys())

    # Should have static mapping fields (interface and VLAN ID pairs)
    assert any("static_interface_" in str(key) for key in schema_keys)
    assert any("static_vlan_" in str(key) for key in schema_keys)

    # Should have pattern fields
    assert any("pattern_" in str(key) for key in schema_keys)

    # Verify the description includes helpful text
    description = result["description_placeholders"]["description"]
    assert "Static mappings take precedence" in description
    assert "regex" in description.lower()


@pytest.mark.asyncio
async def test_vlan_detection_step_existing_values(mock_config_entry_with_vlan_rules):
    """Test VLAN detection step shows existing values from options."""
    options_flow = OptionsFlowHandler(mock_config_entry_with_vlan_rules)

    result = await options_flow.async_step_vlan_detection()

    assert result["type"] == "form"
    assert result["step_id"] == "vlan_detection"


@pytest.mark.asyncio
async def test_vlan_detection_step_save_values(mock_config_entry):
    """Test VLAN detection step saves the configured values."""
    options_flow = OptionsFlowHandler(mock_config_entry)

    user_input = {
        "static_interface_1": "wlan0-ap0",
        "static_vlan_1": "1",
        "static_interface_2": "wlan0-ap1",
        "static_vlan_2": "10",
        "pattern_1": ".*iot.*",
        "pattern_vlan_1": "3",
        "pattern_2": ".*guest.*",
        "pattern_vlan_2": "100",
        # Empty fields should be ignored
        "static_interface_3": "",
        "static_vlan_3": "",
    }

    result = await options_flow.async_step_vlan_detection(user_input)

    assert result["type"] == "create_entry"
    assert CONF_VLAN_DETECTION_RULES in result["data"]

    vlan_rules = result["data"][CONF_VLAN_DETECTION_RULES]

    # Check static mappings
    assert vlan_rules["static_mappings"] == {
        "wlan0-ap0": 1,
        "wlan0-ap1": 10,
    }

    # Check interface patterns
    assert vlan_rules["interface_patterns"] == {
        ".*iot.*": 3,
        ".*guest.*": 100,
    }

    # Explicitly verify that empty patterns or interfaces don't create spurious entries
    assert "" not in vlan_rules["static_mappings"]
    assert "" not in vlan_rules["interface_patterns"]

    assert result["title"] == ""


@pytest.mark.asyncio
async def test_vlan_detection_preserves_existing_options():
    """Test that setting VLAN detection rules preserves other existing options."""
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
        options={"scan_interval": 60, "vlan_names": {1: "Main Network", 3: "IoT Network"}},
        entry_id="test_entry",
    )

    options_flow = OptionsFlowHandler(mock_config_entry)

    user_input = {
        "static_interface_1": "wlan0-ap0",
        "static_vlan_1": "1",
        "pattern_1": ".*iot.*",
        "pattern_vlan_1": "3",
    }

    result = await options_flow.async_step_vlan_detection(user_input)

    assert result["type"] == "create_entry"

    # Verify VLAN detection rules are saved
    assert CONF_VLAN_DETECTION_RULES in result["data"]

    # Verify other options are preserved
    assert result["data"]["scan_interval"] == 60
    assert result["data"]["vlan_names"] == {1: "Main Network", 3: "IoT Network"}


@pytest.mark.asyncio
async def test_vlan_detection_invalid_vlan_ids(mock_config_entry):
    """Test VLAN detection handles invalid VLAN IDs and regex patterns gracefully."""
    options_flow = OptionsFlowHandler(mock_config_entry)

    user_input = {
        "static_interface_1": "wlan0-ap0",
        "static_vlan_1": "0",  # Invalid: below range
        "static_interface_2": "wlan0-ap1",
        "static_vlan_2": "4095",  # Invalid: above range
        "static_interface_3": "wlan0-ap2",
        "static_vlan_3": "abc",  # Invalid: not a number
        "static_interface_4": "wlan0-ap3",
        "static_vlan_4": "10",  # Valid
        "pattern_1": ".*iot.*",
        "pattern_vlan_1": "3",  # Valid
        "pattern_2": "[",  # Invalid regex pattern
        "pattern_vlan_2": "5",  # Valid VLAN ID but invalid pattern
    }

    result = await options_flow.async_step_vlan_detection(user_input)

    assert result["type"] == "create_entry"

    vlan_rules = result["data"][CONF_VLAN_DETECTION_RULES]

    # Only valid entries should be saved
    assert vlan_rules["static_mappings"] == {
        "wlan0-ap3": 10,  # Only the valid one
    }

    assert vlan_rules["interface_patterns"] == {
        ".*iot.*": 3,  # Only the valid pattern, invalid "[" pattern filtered out
    }


@pytest.mark.asyncio
async def test_vlan_detection_navigation_from_init(mock_config_entry):
    """Test navigation from init step to VLAN detection step."""
    options_flow = OptionsFlowHandler(mock_config_entry)

    # Navigate to VLAN detection step
    user_input = {"action": "vlan_detection"}
    result = await options_flow.async_step_init(user_input)

    assert result["type"] == "form"
    assert result["step_id"] == "vlan_detection"


def test_vlan_detection_constants_exist():
    """Test that required constants are defined."""
    assert CONF_VLAN_DETECTION_RULES == "vlan_detection_rules"
    assert isinstance(DEFAULT_VLAN_DETECTION_RULES, dict)
    assert "interface_patterns" in DEFAULT_VLAN_DETECTION_RULES
    assert "static_mappings" in DEFAULT_VLAN_DETECTION_RULES


def test_vlan_detection_logic():
    """Test the actual VLAN detection logic with configurable rules."""
    # Import the actual function we need to test
    from custom_components.wrtmanager.coordinator import _determine_vlan_with_rules

    # Test static mappings take precedence
    vlan_rules = {
        "static_mappings": {"wlan0-ap0": 50},
        "interface_patterns": {".*ap0.*": 1},
    }
    device = {ATTR_INTERFACE: "wlan0-ap0"}
    assert _determine_vlan_with_rules(device, vlan_rules) == 50

    # Test pattern matching with regex validation
    vlan_rules = {
        "static_mappings": {},
        "interface_patterns": {".*iot.*": 3, ".*guest.*": 100},
    }
    device = {ATTR_INTERFACE: "wlan0-iot-network"}
    assert _determine_vlan_with_rules(device, vlan_rules) == 3

    device = {ATTR_INTERFACE: "wlan1-guest-ap"}
    assert _determine_vlan_with_rules(device, vlan_rules) == 100

    # Test explicit VLAN tag detection (should work regardless of custom rules)
    device = {ATTR_INTERFACE: "wlan0-vlan25"}
    assert _determine_vlan_with_rules(device, vlan_rules) == 25

    # Test IP-based detection - use empty rules to trigger fallback to IP detection
    vlan_rules = {
        "static_mappings": {},
        "interface_patterns": {},
    }
    device = {ATTR_IP: "192.168.5.100"}
    assert _determine_vlan_with_rules(device, vlan_rules) == 5

    # Test fallback to hardcoded patterns
    device = {ATTR_INTERFACE: "wlan0-iot"}  # No custom rules, should use hardcoded
    assert _determine_vlan_with_rules(device, vlan_rules) == 3

    # Test default VLAN
    device = {}
    assert _determine_vlan_with_rules(device, vlan_rules) == 1


def test_invalid_regex_patterns():
    """Test that invalid regex patterns are handled gracefully."""
    from custom_components.wrtmanager.coordinator import _determine_vlan_with_rules

    # Test with invalid regex patterns
    vlan_rules = {
        "static_mappings": {},
        "interface_patterns": {
            "[": 3,  # Invalid regex - unclosed bracket
            ".*iot.*": 5,  # Valid regex
        },
    }

    device = {ATTR_INTERFACE: "wlan0-iot-network"}
    # Should match the valid pattern and ignore the invalid one
    assert _determine_vlan_with_rules(device, vlan_rules) == 5

    device = {ATTR_INTERFACE: "wlan0-other"}
    # Should return default since invalid pattern is skipped
    assert _determine_vlan_with_rules(device, vlan_rules) == 1


def test_regex_validation_function():
    """Test the actual regex validation function from the coordinator."""
    from custom_components.wrtmanager.coordinator import _validate_regex_pattern

    # Test valid patterns
    assert _validate_regex_pattern(".*iot.*") is True
    assert _validate_regex_pattern("wlan0-.*") is True
    assert _validate_regex_pattern("^guest.*$") is True

    # Test invalid patterns (too long)
    long_pattern = "a" * 101
    assert _validate_regex_pattern(long_pattern) is False

    # Test dangerous patterns that could cause ReDoS
    # These test the string-based checks for dangerous patterns
    assert _validate_regex_pattern("(a+)+") is False  # Nested quantifiers
    assert _validate_regex_pattern("(a*)*") is False  # Nested quantifiers
    assert _validate_regex_pattern("(.+)*") is False  # Very dangerous pattern

    # Test invalid regex syntax
    assert _validate_regex_pattern("[") is False  # Unclosed bracket
    assert _validate_regex_pattern("(") is False  # Unclosed parenthesis
    assert _validate_regex_pattern("*") is False  # Invalid start with quantifier

    # Test additional dangerous patterns
    assert _validate_regex_pattern("([a-z]+)*") is False  # Character class with nested quantifier
    assert _validate_regex_pattern("(.*){5,}") is False  # High repetition count pattern
    assert _validate_regex_pattern("((a+)+)+") is False  # Multiple nested quantifiers

    # Test patterns that should be allowed
    assert _validate_regex_pattern("test.*pattern") is True
    assert _validate_regex_pattern("^(iot|smart).*") is True
    assert _validate_regex_pattern("ap[0-9]+") is True


def test_redos_protection():
    """Test that ReDoS protection actually catches dangerous patterns."""
    from custom_components.wrtmanager.coordinator import _validate_regex_pattern

    # Test actual ReDoS patterns that should be blocked
    dangerous_redos_patterns = [
        "(a+)+",  # Classic ReDoS pattern
        "(a*)*",  # Classic ReDoS pattern
        "(a+)*",  # Classic ReDoS pattern
        "(a+)+b",  # ReDoS with specific terminator
        "(a*)+c",  # ReDoS with specific terminator
        "(.*a){10,}",  # Potentially dangerous repetition
        "([a-zA-Z]+)*",  # Character class with unlimited repetition
        "(.+)*",  # Very dangerous: any character, any amount, unlimited times
        "((a+)+)+",  # Nested quantifiers
    ]

    for pattern in dangerous_redos_patterns:
        # These patterns should be rejected by the validation
        result = _validate_regex_pattern(pattern)
        assert result is False, f"Pattern '{pattern}' should be rejected but was allowed"

    # Test patterns that look dangerous but are actually safe
    safe_patterns = [
        "a+",  # Single quantifier, safe
        "a*",  # Single quantifier, safe
        "a{1,10}",  # Bounded quantifier, safe
        "(abc)+",  # Group with simple repetition, safe
        "[a-z]*",  # Character class with single quantifier, safe
        "^prefix.*$",  # Anchored pattern, safe
        "test.*",  # Simple patterns used in the codebase
    ]

    for pattern in safe_patterns:
        # These patterns should be allowed
        result = _validate_regex_pattern(pattern)
        assert result is True, f"Pattern '{pattern}' should be allowed but was rejected"
