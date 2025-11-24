"""Tests for password sanitization in SSID data."""

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator


def test_sanitize_config_redacts_key():
    """Test that _sanitize_config redacts the 'key' field."""
    config = {
        "ssid": "MyNetwork",
        "key": "super_secret_password",
        "encryption": "psk2",
        "mode": "ap",
    }

    sanitized = WrtManagerCoordinator._sanitize_config(config)

    assert sanitized["ssid"] == "MyNetwork"
    assert sanitized["key"] == "***REDACTED***"
    assert sanitized["encryption"] == "psk2"
    assert sanitized["mode"] == "ap"


def test_sanitize_config_redacts_wpa_passphrase():
    """Test that _sanitize_config redacts the 'wpa_passphrase' field."""
    config = {
        "ssid": "MyNetwork",
        "wpa_passphrase": "another_secret",
        "encryption": "psk2",
    }

    sanitized = WrtManagerCoordinator._sanitize_config(config)

    assert sanitized["ssid"] == "MyNetwork"
    assert sanitized["wpa_passphrase"] == "***REDACTED***"
    assert sanitized["encryption"] == "psk2"


def test_sanitize_config_redacts_wpa_psk():
    """Test that _sanitize_config redacts the 'wpa_psk' field."""
    config = {
        "ssid": "MyNetwork",
        "wpa_psk": "psk_password",
        "encryption": "psk2",
    }

    sanitized = WrtManagerCoordinator._sanitize_config(config)

    assert sanitized["ssid"] == "MyNetwork"
    assert sanitized["wpa_psk"] == "***REDACTED***"
    assert sanitized["encryption"] == "psk2"


def test_sanitize_config_redacts_password():
    """Test that _sanitize_config redacts the 'password' field."""
    config = {
        "ssid": "MyNetwork",
        "password": "generic_password",
        "encryption": "psk2",
    }

    sanitized = WrtManagerCoordinator._sanitize_config(config)

    assert sanitized["ssid"] == "MyNetwork"
    assert sanitized["password"] == "***REDACTED***"
    assert sanitized["encryption"] == "psk2"


def test_sanitize_config_handles_multiple_sensitive_fields():
    """Test that _sanitize_config redacts multiple sensitive fields."""
    config = {
        "ssid": "MyNetwork",
        "key": "password1",
        "wpa_passphrase": "password2",
        "wpa_psk": "password3",
        "encryption": "psk2",
    }

    sanitized = WrtManagerCoordinator._sanitize_config(config)

    assert sanitized["ssid"] == "MyNetwork"
    assert sanitized["key"] == "***REDACTED***"
    assert sanitized["wpa_passphrase"] == "***REDACTED***"
    assert sanitized["wpa_psk"] == "***REDACTED***"
    assert sanitized["encryption"] == "psk2"


def test_sanitize_config_preserves_non_sensitive_fields():
    """Test that _sanitize_config preserves all non-sensitive fields."""
    config = {
        "ssid": "MyNetwork",
        "encryption": "psk2",
        "mode": "ap",
        "hidden": False,
        "isolate": True,
        "network": "lan",
        "disabled": False,
    }

    sanitized = WrtManagerCoordinator._sanitize_config(config)

    # All fields should be preserved as-is
    assert sanitized == config


def test_sanitize_config_handles_empty_config():
    """Test that _sanitize_config handles empty config."""
    config = {}

    sanitized = WrtManagerCoordinator._sanitize_config(config)

    assert sanitized == {}


def test_sanitize_config_preserves_none_values():
    """Test that _sanitize_config preserves None values in sensitive fields.

    None values indicate no password is set (e.g., open network),
    not that a password exists and was redacted.
    """
    config = {
        "ssid": "MyNetwork",
        "key": None,
        "encryption": "psk2",
    }

    sanitized = WrtManagerCoordinator._sanitize_config(config)

    assert sanitized["ssid"] == "MyNetwork"
    assert sanitized["key"] is None  # None should be preserved, not redacted
    assert sanitized["encryption"] == "psk2"
