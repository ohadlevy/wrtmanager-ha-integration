# Contributing to WrtManager

Thank you for your interest in contributing to WrtManager! This document provides guidelines and best practices for contributing to the project.

## Development Environment Setup

### 1. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/ohadlevy/wrtmanager-ha-integration.git
cd wrtmanager-ha-integration

# Set up development environment (this creates a venv and installs everything)
make setup-dev

# Activate virtual environment
source venv/bin/activate
```

### 2. Alternative Manual Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install development dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

## Development Workflow

### Quick Commands

```bash
# Run tests
make test

# Run tests with coverage
make test-cov

# Format code
make format

# Run all quality checks
make dev-check

# Fix and validate code
make dev-fix
```

### Step-by-Step Development Process

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following our coding standards

3. **Run quality checks**:
   ```bash
   make dev-check
   ```

4. **Commit your changes**:
   ```bash
   git add .
   git commit -m "feat: add new feature"
   ```

5. **Push and create a pull request**:
   ```bash
   git push origin feature/your-feature-name
   ```

## Code Quality Standards

### 1. Testing Requirements

#### Test Coverage
- **Minimum 80% code coverage** required
- All new features must include comprehensive tests
- Tests should cover both success and error scenarios

#### Test Types
```bash
# Unit tests (fast, isolated)
make test-unit

# Integration tests (with external dependencies)
make test-integration

# All tests
make test
```

#### Writing Tests
- Place tests in `tests/` directory
- Use descriptive test names: `test_authentication_success_with_valid_credentials`
- Mock external dependencies (HTTP calls, file system, etc.)
- Test both happy path and error cases

Example test structure:
```python
@pytest.mark.asyncio
async def test_ubus_authentication_success():
    """Test successful authentication with valid credentials."""
    client = UbusClient("192.168.1.1", "user", "password")

    with aioresponses() as m:
        m.post("http://192.168.1.1/ubus", payload={"result": [0, {"session": "123"}]})

        session_id = await client.authenticate()
        assert session_id == "123"
```

### 2. Code Formatting

We use automated code formatting to ensure consistency:

```bash
# Format code
make format

# Check formatting
make format-check
```

**Standards:**
- **Black** for Python code formatting (100 character line length)
- **isort** for import sorting
- **Trailing whitespaces** removed automatically

### 3. Type Checking

We use **mypy** for static type checking:

```bash
# Run type checking
make type-check
```

**Requirements:**
- All public functions must have type hints
- Use `Optional[T]` for nullable types
- Import types from `typing` module

Example:
```python
from typing import Dict, List, Optional

async def get_devices(session_id: str) -> Optional[List[Dict[str, Any]]]:
    """Get wireless devices from router."""
    ...
```

### 4. Linting

We use multiple linters for code quality:

```bash
# Run all linting
make lint
```

**Tools:**
- **flake8** for general Python linting
- **pylint** for additional code quality checks
- **mypy** for type checking

### 5. Pre-commit Hooks

Pre-commit hooks automatically run quality checks before each commit:

```bash
# Install hooks (done automatically with make setup-dev)
make pre-commit-install

# Run hooks manually
make pre-commit
```

**What gets checked:**
- Code formatting (Black, isort)
- Linting (flake8, pylint)
- Type checking (mypy)
- Tests execution
- Basic file checks (trailing whitespace, etc.)

## Architecture Guidelines

### 1. Directory Structure

```
custom_components/wrtmanager/
├── __init__.py          # Integration setup
├── manifest.json        # HA integration metadata
├── config_flow.py       # Configuration UI
├── coordinator.py       # Data update coordinator
├── ubus_client.py       # OpenWrt ubus API client
├── device_manager.py    # Device identification logic
├── const.py            # Constants
├── sensor.py           # Sensor entities
├── binary_sensor.py    # Binary sensor entities
└── device_tracker.py   # Device tracker entities

tests/
├── conftest.py         # Test fixtures
├── unit/               # Unit tests
├── integration/        # Integration tests
└── fixtures/           # Test data
```

### 2. Design Patterns

#### DataUpdateCoordinator Pattern
```python
class WrtManagerCoordinator(DataUpdateCoordinator):
    """Coordinate data updates from multiple routers."""

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from all configured routers."""
        return await self.collect_router_data()
```

#### Dependency Injection
```python
class UbusClient:
    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self._session = session or aiohttp.ClientSession()
```

#### Error Handling
```python
try:
    result = await self.api_call()
    return self.process_result(result)
except ApiError as ex:
    _LOGGER.error("API call failed: %s", ex)
    return None
except Exception as ex:
    _LOGGER.exception("Unexpected error: %s", ex)
    raise
```

### 3. Performance Guidelines

- Use `async/await` for all I/O operations
- Implement proper connection pooling for HTTP clients
- Cache expensive computations
- Batch multiple API calls when possible
- Use `asyncio.gather()` for parallel operations

### 4. Security Guidelines

- Never log sensitive information (passwords, session tokens)
- Validate all user inputs
- Use secure defaults for configuration
- Implement proper timeout handling
- Use HTTPS when available

## Testing Strategy

### 1. Test Pyramid

```
         E2E Tests (Few)
       ↗               ↖
Integration Tests (Some)
       ↗               ↖
    Unit Tests (Many)
```

#### Unit Tests (80% of tests)
- Fast execution (< 1s per test)
- No external dependencies
- Mock all I/O operations
- Test individual functions/methods

#### Integration Tests (15% of tests)
- Test component interactions
- May use test doubles for external services
- Validate data flow between modules

#### End-to-End Tests (5% of tests)
- Test complete user scenarios
- Use real (test) routers when possible
- Validate full integration workflows

### 2. Test Organization

```python
class TestUbusClient:
    """Test UbusClient functionality."""

    class TestAuthentication:
        """Test authentication methods."""

        async def test_successful_login(self):
            """Test successful authentication."""

        async def test_invalid_credentials(self):
            """Test authentication with invalid credentials."""

    class TestDeviceDiscovery:
        """Test device discovery methods."""

        async def test_get_wireless_devices(self):
            """Test getting wireless device list."""
```

### 3. Test Data Management

- Store test data in `tests/fixtures/`
- Use realistic data based on actual router responses
- Create factories for generating test data
- Version test data with the code

## Continuous Integration

### 1. GitHub Actions Pipeline

Our CI pipeline runs automatically on:
- **Every push** to `main` and `develop` branches
- **Every pull request** to `main`

#### Pipeline Stages:

1. **Test Suite** - Run tests on Python 3.11 and 3.12
2. **Code Quality** - Formatting, linting, type checking
3. **Security Scan** - Vulnerability scanning
4. **HA Validation** - Home Assistant compliance checks
5. **Build Check** - Package build verification

### 2. Quality Gates

Pull requests must pass all checks:
- ✅ All tests passing
- ✅ Code coverage ≥ 80%
- ✅ No linting errors
- ✅ Type checking passes
- ✅ Security scan clean
- ✅ HA validation passes

## Documentation Standards

### 1. Code Documentation

```python
def get_device_associations(self, session_id: str, interface: str) -> Optional[List[Dict[str, Any]]]:
    """Get associated devices for a wireless interface.

    Args:
        session_id: Valid ubus session identifier
        interface: Wireless interface name (e.g., 'phy0-ap0')

    Returns:
        List of associated devices with MAC, signal strength, etc.
        Returns None if the interface doesn't exist or on error.

    Raises:
        UbusConnectionError: If unable to connect to router
        UbusTimeoutError: If request times out
    """
```

### 2. README Updates

When adding new features:
- Update feature list in README.md
- Add configuration examples
- Update compatibility information

### 3. Changelog Maintenance

Follow [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
## [1.0.1] - 2025-01-15

### Added
- Support for WPA3 networks
- Device offline detection

### Changed
- Improved error handling for unreachable routers

### Fixed
- Race condition in device discovery
```

## Release Process

### 1. Version Management

Update versions in both files:
- `custom_components/wrtmanager/manifest.json`
- `pyproject.toml`

### 2. Release Checklist

```bash
# 1. Ensure all tests pass
make ci

# 2. Check release readiness
make release-check

# 3. Update CHANGELOG.md
# 4. Commit version bump
# 5. Create GitHub release
# 6. HACS will automatically detect the new release
```

## Getting Help

### 1. Development Issues
- Check existing [GitHub Issues](https://github.com/ohadlevy/wrtmanager-ha-integration/issues)
- Run `make dev-check` to identify common problems
- Check the [Home Assistant Developer Documentation](https://developers.home-assistant.io/)

### 2. OpenWrt Integration
- Refer to [OpenWrt ubus documentation](https://openwrt.org/docs/techref/ubus)
- Check the `scripts/setup_openwrt_ha_integration.sh` for configuration

### 3. Questions and Discussions
- Open a [GitHub Discussion](https://github.com/ohadlevy/wrtmanager-ha-integration/discussions)
- Join the Home Assistant Discord #developers channel

Thank you for contributing to WrtManager! 🚀