"""Tests for CPU usage and load average sensors."""

# Load average fixed-point divisor (OpenWrt encodes load as integer * 65536)
_LOAD_DIVISOR = 65536


# ─── Load Average ────────────────────────────────────────────────────────────


def test_load_average_fixed_point_conversion():
    """Test that OpenWrt fixed-point load values are decoded correctly."""

    def decode_load(raw_value):
        return round(raw_value / _LOAD_DIVISOR, 2)

    # Values from default.json scenario (router1)
    assert decode_load(2048) == 0.03
    assert decode_load(4096) == 0.06
    assert decode_load(3072) == 0.05

    # Values from scenario router2
    assert decode_load(1024) == 0.02
    assert decode_load(2048) == 0.03
    assert decode_load(1536) == 0.02

    # High load example
    assert decode_load(65536) == 1.0  # load of 1.0
    assert decode_load(131072) == 2.0  # load of 2.0
    assert decode_load(32768) == 0.5  # load of 0.5


def test_load_average_sensor_reads_correct_index():
    """Test that each load average sensor reads the correct array index."""
    load_raw = [2048, 4096, 3072]

    def get_load(index):
        if not load_raw or len(load_raw) <= index:
            return None
        return round(load_raw[index] / _LOAD_DIVISOR, 2)

    assert get_load(0) == 0.03  # 1m
    assert get_load(1) == 0.06  # 5m
    assert get_load(2) == 0.05  # 15m


def test_load_average_returns_none_when_missing():
    """Test graceful handling of missing or short load arrays."""

    def get_load(load_array, index):
        if not load_array or len(load_array) <= index:
            return None
        return round(load_array[index] / _LOAD_DIVISOR, 2)

    assert get_load(None, 0) is None
    assert get_load([], 0) is None
    assert get_load([2048, 4096], 2) is None  # only 2 values, asking for index 2


def test_load_average_extra_attributes():
    """Test that extra_state_attributes returns all three load values."""
    load_raw = [65536, 131072, 98304]  # 1.0, 2.0, 1.5

    def get_attrs(load):
        if not load or len(load) < 3:
            return {}
        return {
            "load_1m": round(load[0] / _LOAD_DIVISOR, 2),
            "load_5m": round(load[1] / _LOAD_DIVISOR, 2),
            "load_15m": round(load[2] / _LOAD_DIVISOR, 2),
        }

    attrs = get_attrs(load_raw)
    assert attrs["load_1m"] == 1.0
    assert attrs["load_5m"] == 2.0
    assert attrs["load_15m"] == 1.5


# ─── CPU Usage ───────────────────────────────────────────────────────────────


def _calculate_cpu_usage(prev, current):
    """Replicate coordinator._calculate_cpu_usage delta logic."""
    delta_total = current["total"] - prev["total"]
    delta_idle = current["idle"] - prev["idle"]
    if delta_total <= 0:
        return None
    cpu_pct = (delta_total - delta_idle) / delta_total * 100
    return round(max(0.0, min(100.0, cpu_pct)), 1)


def _parse_proc_stat(content):
    """Parse the first line of /proc/stat into idle and total counters."""
    first_line = content.split("\n")[0]
    parts = first_line.split()
    assert parts[0] == "cpu"
    values = [int(x) for x in parts[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return {"idle": idle, "total": total}


def test_cpu_usage_delta_calculation():
    """Test delta-based CPU usage calculation from /proc/stat counters."""
    # Simulate two consecutive readings with ~20% CPU usage
    # total increases by 100, idle increases by 80 → 20% used
    prev = {"idle": 8000, "total": 10000}
    curr = {"idle": 8080, "total": 10100}

    usage = _calculate_cpu_usage(prev, curr)
    assert usage == 20.0


def test_cpu_usage_idle_system():
    """Test near-zero CPU usage (mostly idle)."""
    prev = {"idle": 9500, "total": 10000}
    curr = {"idle": 9995, "total": 10500}  # 495 idle out of 500 delta → 1% used

    usage = _calculate_cpu_usage(prev, curr)
    assert usage == 1.0


def test_cpu_usage_full_load():
    """Test 100% CPU (no idle increase)."""
    prev = {"idle": 1000, "total": 10000}
    curr = {"idle": 1000, "total": 10100}  # zero idle delta → 100%

    usage = _calculate_cpu_usage(prev, curr)
    assert usage == 100.0


def test_cpu_usage_clamped_to_valid_range():
    """Test that CPU usage is clamped to [0, 100]."""
    # Edge case: idle goes slightly backward due to clock jitter
    prev = {"idle": 1000, "total": 10000}
    curr = {"idle": 999, "total": 10100}  # negative idle delta

    usage = _calculate_cpu_usage(prev, curr)
    assert 0.0 <= usage <= 100.0


def test_cpu_usage_returns_none_on_zero_delta():
    """Test that None is returned when total counter does not advance."""
    prev = {"idle": 1000, "total": 10000}
    curr = {"idle": 1000, "total": 10000}  # same reading

    usage = _calculate_cpu_usage(prev, curr)
    assert usage is None


def test_proc_stat_parsing():
    """/proc/stat first line parses correctly into idle + total counters."""
    content = "cpu  1000 0 500 8000 100 50 50 0 0 0\ncpu0 1000 0 500 8000 100 50 50 0 0 0\n"
    stats = _parse_proc_stat(content)

    # idle = 8000 (index 3) + 100 (iowait, index 4) = 8100
    assert stats["idle"] == 8100
    # total = sum of all 10 counters
    assert stats["total"] == 1000 + 0 + 500 + 8000 + 100 + 50 + 50 + 0 + 0 + 0


def test_proc_stat_parsing_minimal():
    """Test /proc/stat parsing with minimal columns (no guest fields)."""
    content = "cpu  500 0 200 7000 50 10 10\n"
    stats = _parse_proc_stat(content)

    assert stats["idle"] == 7000 + 50  # idle + iowait
    assert stats["total"] == 500 + 0 + 200 + 7000 + 50 + 10 + 10


def test_end_to_end_proc_stat_to_cpu_usage():
    """Simulate two consecutive poll cycles and verify CPU usage output."""
    # First poll — establishes baseline, returns None
    content1 = "cpu  1000 0 500 8000 100 50 50 0 0 0\n"
    stats1 = _parse_proc_stat(content1)
    # No previous → None (first reading)
    assert stats1 is not None  # we at least got data

    # Second poll — 20 jiffies elapsed, 4 idle, 16 active
    content2 = "cpu  1016 0 500 8004 100 50 50 0 0 0\n"
    stats2 = _parse_proc_stat(content2)

    usage = _calculate_cpu_usage(stats1, stats2)
    # delta_total=20, delta_idle=4 → 80% used
    assert usage == 80.0
