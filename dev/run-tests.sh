#!/bin/bash
# Test runner: unit tests + E2E tests + screenshots.
#
# Usage:
#   dev/run-tests.sh                           # Run all tests (unit + E2E if env is up)
#   dev/run-tests.sh --unit-only               # Only unit tests
#   dev/run-tests.sh --e2e-only                # Only E2E tests (requires running env)
#   dev/run-tests.sh --worktree-path /path     # Run in specific worktree context
#   dev/run-tests.sh --lint                    # Include lint checks
#   dev/run-tests.sh --full                    # Start env, run all tests, teardown
#
# Exit code 0 = all tests passed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Parse args ---

WORKTREE_PATH="$REPO_ROOT"
UNIT=true
E2E=true
LINT=false
FULL=false
SCREENSHOTS=true
BROWSER_ONLY=false
REVIEW_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --worktree-path) WORKTREE_PATH="$2"; shift 2 ;;
        --unit-only) E2E=false; shift ;;
        --e2e-only) UNIT=false; shift ;;
        --lint) LINT=true; shift ;;
        --full) FULL=true; shift ;;
        --no-screenshots) SCREENSHOTS=false; shift ;;
        --browser-only) UNIT=false; E2E=false; BROWSER_ONLY=true; shift ;;
        --review-only) UNIT=false; E2E=false; BROWSER_ONLY=true; REVIEW_ONLY=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Make absolute
if [[ "$WORKTREE_PATH" != /* ]]; then
    WORKTREE_PATH="$REPO_ROOT/$WORKTREE_PATH"
fi

VENV="$REPO_ROOT/.venv/bin/python"
EXIT_CODE=0

echo "=== Running tests ==="
echo "Worktree: $WORKTREE_PATH"
echo ""

# --- Full mode: start environment ---

if [[ "$FULL" == true ]]; then
    echo "--- Starting test environment (full mode) ---"
    # Use a temp issue number for full mode
    MOCK_PORT_FILE="$WORKTREE_PATH/.mock-ports.json"
    MOCK_PID_FILE="$WORKTREE_PATH/.mock-server.pid"

    HASH=$(echo -n "$WORKTREE_PATH" | md5sum | head -c 8)
    PORT_OFFSET=$((16#$HASH % 800))
    MOCK_PORT=$((18001 + PORT_OFFSET))
    HA_PORT=$((18100 + PORT_OFFSET))

    # Start mock
    MOCK_LOG_FILE="$WORKTREE_PATH/.mock-server.log"
    $VENV "$SCRIPT_DIR/mock_ubus_server.py" \
        --scenario "$SCRIPT_DIR/scenarios/default.json" \
        --base-port "$MOCK_PORT" \
        --port-file "$MOCK_PORT_FILE" \
        > "$MOCK_LOG_FILE" 2>&1 &
    echo $! > "$MOCK_PID_FILE"
    sleep 2

    # Start HA
    "$SCRIPT_DIR/ha-env.sh" start \
        --worktree-path "$WORKTREE_PATH" \
        --ha-port "$HA_PORT" \
        --mock-port-file "$MOCK_PORT_FILE"

    # Setup HA
    $VENV "$SCRIPT_DIR/setup-ha.py" \
        --ha-url "http://localhost:$HA_PORT" \
        --mock-port-file "$MOCK_PORT_FILE" \
        --token-file "$WORKTREE_PATH/.ha-token" || true

    echo ""
fi

# --- Lint ---

if [[ "$LINT" == true ]]; then
    echo "--- Lint checks ---"
    cd "$WORKTREE_PATH"

    $VENV -m black --check custom_components/ tests/ 2>&1 && echo "PASS: black" || { echo "FAIL: black"; EXIT_CODE=1; }
    $VENV -m isort --check-only custom_components/ tests/ 2>&1 && echo "PASS: isort" || { echo "FAIL: isort"; EXIT_CODE=1; }
    $VENV -m flake8 custom_components/ tests/ --max-line-length=100 --extend-ignore=E203,W503 2>&1 && echo "PASS: flake8" || { echo "FAIL: flake8"; EXIT_CODE=1; }
    echo ""
fi

# --- Unit tests ---

if [[ "$UNIT" == true ]]; then
    echo "--- Unit tests ---"
    cd "$WORKTREE_PATH"
    PYTHONPATH=. $VENV -m pytest tests/ -v --tb=short --maxfail=5 || { EXIT_CODE=1; echo "FAIL: Unit tests"; }
    echo ""
fi

# --- E2E tests ---

if [[ "$E2E" == true ]]; then
    # Check if HA is running
    STATE_FILE="$WORKTREE_PATH/.ha-test-state.json"
    DEV_STATE_FILE="$WORKTREE_PATH/.dev-env-state.json"

    HA_URL=""
    TOKEN=""

    if [[ -f "$DEV_STATE_FILE" ]]; then
        HA_URL=$(python3 -c "import json; print(json.load(open('$DEV_STATE_FILE'))['ha_url'])" 2>/dev/null || echo "")
    elif [[ -f "$STATE_FILE" ]]; then
        HA_URL=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['ha_url'])" 2>/dev/null || echo "")
    fi

    TOKEN_FILE="$WORKTREE_PATH/.ha-token"
    if [[ -f "$TOKEN_FILE" ]]; then
        TOKEN=$(cat "$TOKEN_FILE")
    fi

    if [[ -n "$HA_URL" ]] && curl -s -o /dev/null -w '%{http_code}' "$HA_URL/api/" 2>/dev/null | grep -qE '(200|401|403)'; then
        echo "--- E2E tests (HA at $HA_URL) ---"

        # Run API-based E2E tests
        cd "$WORKTREE_PATH"
        HA_URL="$HA_URL" HA_TOKEN="$TOKEN" PYTHONPATH=. $VENV -m pytest tests/e2e/ -v --tb=short 2>/dev/null || {
            if [[ -d "$WORKTREE_PATH/tests/e2e" ]]; then
                EXIT_CODE=1
                echo "FAIL: E2E tests"
            else
                echo "SKIP: No tests/e2e/ directory"
            fi
        }

        # Run Playwright browser tests in container
        BROWSER_TEST_DIR="$REPO_ROOT/tests/e2e/browser"
        if [[ -d "$BROWSER_TEST_DIR" ]]; then
            echo ""
            echo "--- Browser tests (Playwright in container) ---"
            SCREENSHOT_DIR="$WORKTREE_PATH/.test-screenshots"
            mkdir -p "$SCREENSHOT_DIR"

            PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v1.52.0-noble"
            PLAYWRIGHT_CONTAINER="playwright-wrt-test-$$"

            # HA is on the host, so the container needs to reach it
            # Use host.containers.internal for podman bridge networking
            CONTAINER_HA_URL=$(echo "$HA_URL" | sed 's|localhost|host.containers.internal|g' | sed 's|127\.0\.0\.1|host.containers.internal|g')

            # Persistent npm cache volume (avoids npm install on every run)
            NPM_CACHE_VOL="playwright-npm-cache"
            podman volume exists "$NPM_CACHE_VOL" 2>/dev/null || podman volume create "$NPM_CACHE_VOL" >/dev/null

            podman run --rm \
                --name "$PLAYWRIGHT_CONTAINER" \
                --add-host=host.containers.internal:host-gateway \
                -v "$BROWSER_TEST_DIR:/work:Z" \
                -v "$SCREENSHOT_DIR:/screenshots:Z" \
                -v "$NPM_CACHE_VOL:/work/node_modules" \
                -e "HA_URL=$CONTAINER_HA_URL" \
                -e "HA_TOKEN=$TOKEN" \
                -e "SCREENSHOT_DIR=/screenshots" \
                -w /work \
                "$PLAYWRIGHT_IMAGE" \
                bash -c "npm install --silent 2>/dev/null && npx playwright test --config=playwright.config.ts --reporter=list" || {
                EXIT_CODE=1
                echo "FAIL: Browser tests"
            }

            if [[ "$SCREENSHOTS" == true ]] && [[ -d "$SCREENSHOT_DIR" ]]; then
                echo ""
                echo "Screenshots saved to: $SCREENSHOT_DIR"
                ls -la "$SCREENSHOT_DIR"/*.png 2>/dev/null || echo "(no screenshots captured)"
            fi
        fi
    else
        echo "SKIP: E2E tests (HA not running - use --full or start env manually)"
    fi
    echo ""
fi

# --- Browser-only mode (for review loop re-screenshots) ---

if [[ "$BROWSER_ONLY" == true ]]; then
    STATE_FILE="$WORKTREE_PATH/.dev-env-state.json"
    HA_URL=""
    TOKEN=""

    if [[ -f "$STATE_FILE" ]]; then
        HA_URL=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['ha_url'])" 2>/dev/null || echo "")
    fi
    TOKEN_FILE="$WORKTREE_PATH/.ha-token"
    if [[ -f "$TOKEN_FILE" ]]; then
        TOKEN=$(cat "$TOKEN_FILE")
    fi

    if [[ -n "$HA_URL" ]]; then
        BROWSER_TEST_DIR="$REPO_ROOT/tests/e2e/browser"
        SCREENSHOT_DIR="$WORKTREE_PATH/.test-screenshots"
        mkdir -p "$SCREENSHOT_DIR"

        PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v1.52.0-noble"
        PLAYWRIGHT_CONTAINER="playwright-wrt-test-$$"
        CONTAINER_HA_URL=$(echo "$HA_URL" | sed 's|localhost|host.containers.internal|g' | sed 's|127\.0\.0\.1|host.containers.internal|g')

        # Review-only: desktop viewport, card tests only (~40s vs ~2.4m)
        if [[ "$REVIEW_ONLY" == true ]]; then
            PLAYWRIGHT_ARGS="--project=desktop --grep='(router-health|network-devices|network-topology|signal-heatmap|roaming-activity|dashboard loads|no console errors)'"
            echo "--- Browser tests (review: desktop cards only) ---"
        else
            PLAYWRIGHT_ARGS=""
            echo "--- Browser tests (screenshots only) ---"
        fi

        podman run --rm \
            --name "$PLAYWRIGHT_CONTAINER" \
            --add-host=host.containers.internal:host-gateway \
            -v "$BROWSER_TEST_DIR:/work:Z" \
            -v "$SCREENSHOT_DIR:/screenshots:Z" \
            -e "HA_URL=$CONTAINER_HA_URL" \
            -e "HA_TOKEN=$TOKEN" \
            -e "SCREENSHOT_DIR=/screenshots" \
            -w /work \
            "$PLAYWRIGHT_IMAGE" \
            bash -c "npm install --silent 2>/dev/null && npx playwright test --config=playwright.config.ts --reporter=list $PLAYWRIGHT_ARGS" || {
            EXIT_CODE=1
            echo "FAIL: Browser tests"
        }

        echo "Screenshots saved to: $SCREENSHOT_DIR"
        ls -la "$SCREENSHOT_DIR"/*.png 2>/dev/null || echo "(no screenshots captured)"
    else
        echo "SKIP: Browser-only mode requires running HA environment"
        EXIT_CODE=1
    fi
fi

# --- Full mode: teardown ---

if [[ "$FULL" == true ]]; then
    echo "--- Tearing down test environment ---"
    "$SCRIPT_DIR/teardown-worktree.sh" "$WORKTREE_PATH" 2>/dev/null || true
    echo ""
fi

# --- Summary ---

echo "=========================================="
if [[ $EXIT_CODE -eq 0 ]]; then
    echo "  All tests passed"
else
    echo "  Some tests FAILED (exit code: $EXIT_CODE)"
fi
echo "=========================================="

exit $EXIT_CODE
