"""Tests for verifying emoji removal from log statements."""

import re
from pathlib import Path


def test_no_emoji_in_coordinator_source_code():
    """Test that the coordinator source code contains no emoji characters."""
    coordinator_file = (
        Path(__file__).parent.parent / "custom_components" / "wrtmanager" / "coordinator.py"
    )

    # Read the source code
    with open(coordinator_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Define emoji pattern - common emoji used in logging
    emoji_pattern = r"[🔍🚀📊⚠️✅❌🏠🌐🖥️📄🎯🔥📶]"

    # Find all emoji matches
    emoji_matches = re.findall(emoji_pattern, content)

    # Assert no emoji found
    assert not emoji_matches, f"Found emoji characters in coordinator.py: {emoji_matches}"


def test_no_emoji_in_data_validation_script():
    """Test that the data validation script contains no emoji characters."""
    validation_file = Path(__file__).parent.parent / "scripts" / "data_validation.py"

    # Read the source code
    with open(validation_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Define emoji pattern - common emoji used in logging/output
    emoji_pattern = r"[🔍🚀📊⚠️✅❌🏠🌐🖥️📄🎯🔥📶]"

    # Find all emoji matches
    emoji_matches = re.findall(emoji_pattern, content)

    # Assert no emoji found
    assert not emoji_matches, f"Found emoji characters in data_validation.py: {emoji_matches}"


def test_coordinator_logging_without_emoji():
    """Test that coordinator source code doesn't contain emoji in log statements."""
    # This test is now redundant with the source code tests above,
    # but we keep it for completeness. The source code verification
    # is sufficient to ensure emoji has been removed from logging.
    coordinator_file = (
        Path(__file__).parent.parent / "custom_components" / "wrtmanager" / "coordinator.py"
    )

    # Read the source code
    with open(coordinator_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Check specifically for _LOGGER calls with emoji
    logger_lines = [line for line in content.split("\n") if "_LOGGER." in line]
    emoji_pattern = r"[🔍🚀📊⚠️✅❌🏠🌐🖥️📄🎯🔥📶]"

    for line in logger_lines:
        emoji_matches = re.findall(emoji_pattern, line)
        assert not emoji_matches, f"Found emoji in logger statement: '{line.strip()}'"


def test_log_messages_are_professional():
    """Test that log messages in coordinator are professional and descriptive."""
    coordinator_file = (
        Path(__file__).parent.parent / "custom_components" / "wrtmanager" / "coordinator.py"
    )

    # Read the source code
    with open(coordinator_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Find all _LOGGER.debug statements
    debug_pattern = r'_LOGGER\.debug\(["\']([^"\']+)["\']\s*[,)]'
    debug_matches = re.findall(debug_pattern, content)

    # Check that debug messages don't contain "DEBUG:" prefix anymore
    for message in debug_matches:
        assert not message.startswith("DEBUG:"), f"Found 'DEBUG:' prefix in message: '{message}'"
        assert "🔍" not in message, f"Found emoji in debug message: '{message}'"

    # Find all _LOGGER.error statements
    error_pattern = r'_LOGGER\.error\(["\']([^"\']+)["\']\s*[,)]'
    error_matches = re.findall(error_pattern, content)

    # Check that error messages are clean
    for message in error_matches:
        assert "🔍" not in message, f"Found emoji in error message: '{message}'"


def test_reduced_verbosity_in_coordinator():
    """Test that excessive debug logging has been reduced."""
    coordinator_file = (
        Path(__file__).parent.parent / "custom_components" / "wrtmanager" / "coordinator.py"
    )

    # Read the source code
    with open(coordinator_file, "r", encoding="utf-8") as f:
        content = f.read()

    # These debug messages should have been removed as they were overly verbose
    excessive_debug_messages = [
        "_collect_router_data() called",
        "Starting data collection",
        "Getting wireless devices",
        "Getting system info",
        "Getting network interfaces",
        "Got system data",
        "Finished _collect_router_data",
        "CRITICAL DEBUG",
    ]

    for message in excessive_debug_messages:
        assert (
            message not in content
        ), f"Found excessive debug message that should be removed: '{message}'"
