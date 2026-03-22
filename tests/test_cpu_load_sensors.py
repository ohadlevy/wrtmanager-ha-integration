"""Tests for CPU usage and load average sensors."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorStateClass

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator
from custom_components.wrtmanager.sensor import (
    WrtManagerCpuUsageSensor,
    WrtManagerLoadAverageSensor,
)

ROUTER_HOST = "192.168.1.1"
ROUTER_NAME = "Test Router"


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with system data including load and cpu_usage."""
    coordinator = MagicMock(spec=WrtManagerCoordinator)
    coordinator.last_update_success = True
    coordinator.data = {
        "system_info": {
            ROUTER_HOST: {
                "uptime": 3600,
                "model": "Test Router",
                "release": {"version": "22.03.0"},
                "memory": {"total": 262144000, "free": 131072000},
                # load is fixed-point: divide by 65536 to get float
                "load": [65536, 131072, 196608],  # 1.0, 2.0, 3.0
                "cpu_usage": 42.5,
            }
        },
        "devices": [],
    }
    return coordinator


# ─── Load Average Sensors ────────────────────────────────────────────


class TestWrtManagerLoadAverageSensor:
    """Tests for load average sensors."""

    def test_1m_sensor_properties(self, mock_coordinator):
        """Verify 1m sensor metadata."""
        sensor = WrtManagerLoadAverageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME, "1m")
        assert sensor._attr_state_class == SensorStateClass.MEASUREMENT
        assert sensor._attr_icon == "mdi:gauge"
        assert "load_average_1m" in sensor.unique_id
        assert "Load Average 1m" in sensor.name

    def test_5m_sensor_properties(self, mock_coordinator):
        """Verify 5m sensor metadata."""
        sensor = WrtManagerLoadAverageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME, "5m")
        assert "load_average_5m" in sensor.unique_id
        assert "Load Average 5m" in sensor.name

    def test_15m_sensor_properties(self, mock_coordinator):
        """Verify 15m sensor metadata."""
        sensor = WrtManagerLoadAverageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME, "15m")
        assert "load_average_15m" in sensor.unique_id
        assert "Load Average 15m" in sensor.name

    def test_1m_native_value(self, mock_coordinator):
        """Verify 1m load average divides fixed-point by 65536."""
        sensor = WrtManagerLoadAverageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME, "1m")
        assert sensor.native_value == 1.0  # 65536 / 65536

    def test_5m_native_value(self, mock_coordinator):
        """Verify 5m load average divides fixed-point by 65536."""
        sensor = WrtManagerLoadAverageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME, "5m")
        assert sensor.native_value == 2.0  # 131072 / 65536

    def test_15m_native_value(self, mock_coordinator):
        """Verify 15m load average divides fixed-point by 65536."""
        sensor = WrtManagerLoadAverageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME, "15m")
        assert sensor.native_value == 3.0  # 196608 / 65536

    def test_fractional_load_average(self, mock_coordinator):
        """Verify fractional load averages are rounded to 2 decimal places."""
        mock_coordinator.data["system_info"][ROUTER_HOST]["load"] = [98304, 0, 0]  # 1.5
        sensor = WrtManagerLoadAverageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME, "1m")
        assert sensor.native_value == 1.5

    def test_native_value_none_when_load_missing(self, mock_coordinator):
        """Verify native_value is None when load key is absent."""
        del mock_coordinator.data["system_info"][ROUTER_HOST]["load"]
        sensor = WrtManagerLoadAverageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME, "1m")
        assert sensor.native_value is None

    def test_native_value_none_when_load_empty(self, mock_coordinator):
        """Verify native_value is None when load array is empty."""
        mock_coordinator.data["system_info"][ROUTER_HOST]["load"] = []
        sensor = WrtManagerLoadAverageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME, "1m")
        assert sensor.native_value is None

    def test_unavailable_when_no_system_data(self, mock_coordinator):
        """Verify sensor is unavailable when system_info is missing for router."""
        mock_coordinator.data = {"devices": [], "system_info": {}}
        sensor = WrtManagerLoadAverageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME, "1m")
        assert not sensor.available


# ─── CPU Usage Sensor ────────────────────────────────────────────────


class TestWrtManagerCpuUsageSensor:
    """Tests for CPU usage sensor."""

    def test_sensor_properties(self, mock_coordinator):
        """Verify sensor metadata."""
        sensor = WrtManagerCpuUsageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME)
        assert sensor._attr_state_class == SensorStateClass.MEASUREMENT
        assert sensor._attr_icon == "mdi:chip"
        assert "cpu_usage" in sensor.unique_id
        assert "CPU Usage" in sensor.name

    def test_native_value(self, mock_coordinator):
        """Verify native_value returns cpu_usage from system_data."""
        sensor = WrtManagerCpuUsageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME)
        assert sensor.native_value == 42.5

    def test_native_value_none_when_missing(self, mock_coordinator):
        """Verify native_value is None when cpu_usage is not yet computed."""
        del mock_coordinator.data["system_info"][ROUTER_HOST]["cpu_usage"]
        sensor = WrtManagerCpuUsageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME)
        assert sensor.native_value is None

    def test_unavailable_when_no_system_data(self, mock_coordinator):
        """Verify sensor is unavailable when system_info is missing for router."""
        mock_coordinator.data = {"devices": [], "system_info": {}}
        sensor = WrtManagerCpuUsageSensor(mock_coordinator, ROUTER_HOST, ROUTER_NAME)
        assert not sensor.available


# ─── Coordinator CPU parsing helpers ─────────────────────────────────


class TestCoordinatorCpuHelpers:
    """Tests for _parse_cpu_stat and _compute_cpu_usage on WrtManagerCoordinator."""

    PROC_STAT = "cpu  100 20 30 800 10 5 5 0 0 0\n" "cpu0 50 10 15 400 5 2 3 0 0 0\n" "intr 12345\n"

    def test_parse_cpu_stat_basic(self):
        """Verify parsing extracts correct counters from /proc/stat."""
        result = WrtManagerCoordinator._parse_cpu_stat(self.PROC_STAT)
        assert result is not None
        assert result["user"] == 100
        assert result["nice"] == 20
        assert result["system"] == 30
        assert result["idle"] == 800
        assert result["iowait"] == 10
        assert result["irq"] == 5
        assert result["softirq"] == 5
        assert result["steal"] == 0

    def test_parse_cpu_stat_no_steal_field(self):
        """Verify steal defaults to 0 when field is absent."""
        data = "cpu  100 20 30 800 10 5 5\n"
        result = WrtManagerCoordinator._parse_cpu_stat(data)
        assert result is not None
        assert result["steal"] == 0

    def test_parse_cpu_stat_returns_none_on_empty(self):
        """Verify None returned when no cpu line found."""
        result = WrtManagerCoordinator._parse_cpu_stat("intr 12345\n")
        assert result is None

    def test_compute_cpu_usage_normal(self):
        """Verify CPU usage percentage calculation from two samples."""
        prev = {
            "user": 100,
            "nice": 0,
            "system": 50,
            "idle": 800,
            "iowait": 10,
            "irq": 5,
            "softirq": 5,
            "steal": 0,
        }
        # Add 40 active ticks, 10 idle ticks → 40/50 = 80%
        curr = {
            "user": 130,
            "nice": 0,
            "system": 60,
            "idle": 810,
            "iowait": 10,
            "irq": 5,
            "softirq": 5,
            "steal": 0,
        }
        result = WrtManagerCoordinator._compute_cpu_usage(prev, curr)
        assert result == 80.0

    def test_compute_cpu_usage_idle(self):
        """Verify 0% CPU usage when all ticks are idle."""
        prev = {
            "user": 100,
            "nice": 0,
            "system": 50,
            "idle": 800,
            "iowait": 10,
            "irq": 0,
            "softirq": 0,
            "steal": 0,
        }
        curr = {
            "user": 100,
            "nice": 0,
            "system": 50,
            "idle": 850,
            "iowait": 10,
            "irq": 0,
            "softirq": 0,
            "steal": 0,
        }
        result = WrtManagerCoordinator._compute_cpu_usage(prev, curr)
        assert result == 0.0

    def test_compute_cpu_usage_zero_delta(self):
        """Verify 0% returned when total delta is zero (prevents division by zero)."""
        counters = {
            "user": 100,
            "nice": 0,
            "system": 50,
            "idle": 800,
            "iowait": 10,
            "irq": 5,
            "softirq": 5,
            "steal": 0,
        }
        result = WrtManagerCoordinator._compute_cpu_usage(counters, counters)
        assert result == 0.0

    def test_compute_cpu_usage_rounding(self):
        """Verify result is rounded to 1 decimal place."""
        prev = {
            "user": 0,
            "nice": 0,
            "system": 0,
            "idle": 0,
            "iowait": 0,
            "irq": 0,
            "softirq": 0,
            "steal": 0,
        }
        # 1 active tick out of 3 total → 33.333...%
        curr = {
            "user": 1,
            "nice": 0,
            "system": 0,
            "idle": 2,
            "iowait": 0,
            "irq": 0,
            "softirq": 0,
            "steal": 0,
        }
        result = WrtManagerCoordinator._compute_cpu_usage(prev, curr)
        assert result == 33.3
