#!/bin/bash
# WrtManager Development Environment Setup Script

set -e

echo "🚀 Setting up WrtManager development environment..."

# Check if Python 3.11+ is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.11 or higher."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "✅ Found Python $PYTHON_VERSION"

# Check if we're already in a virtual environment
if [[ "$VIRTUAL_ENV" != "" ]]; then
    echo "⚠️  Already in virtual environment: $VIRTUAL_ENV"
    echo "   Proceeding with current environment..."
else
    # Create virtual environment if it doesn't exist
    if [ ! -d "venv" ]; then
        echo "📦 Creating virtual environment..."
        python3 -m venv venv
    fi

    echo "🔄 Activating virtual environment..."
    source venv/bin/activate
fi

# Install development dependencies
echo "📚 Installing development dependencies..."
pip install --upgrade pip
pip install -e ".[dev]"

# Install pre-commit hooks
echo "🔗 Setting up pre-commit hooks..."
pre-commit install

# Verify installation
echo "🧪 Running verification tests..."

echo "  → Testing pytest installation..."
if ! python -m pytest --version > /dev/null; then
    echo "❌ pytest installation failed"
    exit 1
fi

echo "  → Testing code formatting tools..."
if ! black --version > /dev/null || ! isort --version > /dev/null; then
    echo "❌ Code formatting tools installation failed"
    exit 1
fi

echo "  → Testing linting tools..."
if ! flake8 --version > /dev/null || ! mypy --version > /dev/null; then
    echo "❌ Linting tools installation failed"
    exit 1
fi

# Run a quick test to ensure everything works
echo "🧪 Running quick test suite..."
if python -m pytest tests/test_ubus_direct.py tests/test_ubus_coverage.py -v --tb=short; then
    echo "✅ Quick test suite passed!"
else
    echo "❌ Some tests failed. Check the output above."
    exit 1
fi

echo ""
echo "🎉 Development environment setup complete!"
echo ""
echo "📋 Quick reference:"
echo "  • Activate environment: source venv/bin/activate"
echo "  • Run tests: make test"
echo "  • Run tests with coverage: make test-cov"
echo "  • Format code: make format"
echo "  • Run all quality checks: make dev-check"
echo "  • Get help: make help"
echo ""
echo "🔍 Available make commands:"
make help