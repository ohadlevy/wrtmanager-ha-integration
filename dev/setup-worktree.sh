#!/bin/bash
# Entry point: create a worktree for an issue and start the full test environment.
#
# Creates:
#   - Git worktree at .claude/worktrees/<branch-name>/
#   - Mock ubus servers (one per simulated router)
#   - HA container with custom_components mounted from the worktree
#   - Configures HA with the wrtmanager integration
#
# Usage:
#   dev/setup-worktree.sh <issue-number> [--branch-prefix feature|fix|chore]
#   dev/setup-worktree.sh 42
#   dev/setup-worktree.sh 42 --branch-prefix fix
#
# Output: JSON with all connection details (for Claude/scripts to consume)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKTREE_BASE="$REPO_ROOT/.claude/worktrees"
SCENARIO="${SCENARIO:-$SCRIPT_DIR/scenarios/default.json}"
MOCK_BASE_PORT="${MOCK_BASE_PORT:-18001}"
VENV="$REPO_ROOT/.venv/bin/python"

# --- Parse args ---

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <issue-number> [--branch-prefix feature|fix|chore] [--no-env]"
    echo ""
    echo "Options:"
    echo "  --branch-prefix PREFIX  Branch prefix (default: feature)"
    echo "  --no-env                Skip starting mock servers and HA container"
    echo "  --scenario PATH         Scenario file (default: dev/scenarios/default.json)"
    exit 1
fi

ISSUE_NUMBER="$1"
shift

BRANCH_PREFIX="feature"
START_ENV=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --branch-prefix) BRANCH_PREFIX="$2"; shift 2 ;;
        --no-env) START_ENV=false; shift ;;
        --scenario) SCENARIO="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- Fetch issue title for branch name ---

ISSUE_TITLE=""
if command -v gh &>/dev/null; then
    ISSUE_TITLE=$(gh issue view "$ISSUE_NUMBER" --json title -q '.title' 2>/dev/null || echo "")
fi

if [[ -z "$ISSUE_TITLE" ]]; then
    BRANCH_SLUG="issue-${ISSUE_NUMBER}"
else
    # Slugify title: lowercase, replace non-alphanum with hyphens, trim
    BRANCH_SLUG=$(echo "$ISSUE_TITLE" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//' | head -c 40)
    BRANCH_SLUG="${ISSUE_NUMBER}-${BRANCH_SLUG}"
fi

BRANCH_NAME="${BRANCH_PREFIX}/${BRANCH_SLUG}"
WORKTREE_PATH="$WORKTREE_BASE/$BRANCH_SLUG"

# --- Create worktree ---

echo "=== Setting up worktree for issue #${ISSUE_NUMBER} ==="
echo "Branch: $BRANCH_NAME"
echo "Path: $WORKTREE_PATH"

mkdir -p "$WORKTREE_BASE"

if [[ -d "$WORKTREE_PATH" ]]; then
    # Worktree exists — reuse it, just teardown old environment
    echo "Worktree exists, reusing..."
    "$SCRIPT_DIR/teardown-worktree.sh" "$WORKTREE_PATH" 2>/dev/null || true
fi

if [[ ! -d "$WORKTREE_PATH" ]]; then
    # Create branch from main
    cd "$REPO_ROOT"
    git fetch origin main 2>/dev/null || true

    if git show-ref --verify --quiet "refs/heads/$BRANCH_NAME" 2>/dev/null; then
        echo "Branch $BRANCH_NAME already exists, using it"
        git worktree add "$WORKTREE_PATH" "$BRANCH_NAME"
    else
        git worktree add -b "$BRANCH_NAME" "$WORKTREE_PATH" origin/main
    fi
    echo "Worktree created"
fi

# --- Setup venv symlink in worktree ---

if [[ ! -d "$WORKTREE_PATH/.venv" ]]; then
    ln -sf "$REPO_ROOT/.venv" "$WORKTREE_PATH/.venv"
    echo "Linked .venv into worktree"
fi

# Link .claude settings so interactive sessions have correct permissions
if [[ ! -d "$WORKTREE_PATH/.claude" ]]; then
    mkdir -p "$WORKTREE_PATH/.claude"
fi
if [[ -f "$REPO_ROOT/.claude/settings.json" ]]; then
    ln -sf "$REPO_ROOT/.claude/settings.json" "$WORKTREE_PATH/.claude/settings.json"
    echo "Linked .claude/settings.json into worktree"
fi

# --- Start test environment ---

if [[ "$START_ENV" == true ]]; then
    echo ""
    echo "=== Starting test environment ==="

    # Calculate unique ports for this worktree
    HASH=$(echo -n "$WORKTREE_PATH" | md5sum | head -c 8)
    PORT_OFFSET=$((16#$HASH % 800))
    MOCK_PORT=$((18001 + PORT_OFFSET))
    HA_PORT=$((18100 + PORT_OFFSET))

    MOCK_PORT_FILE="$WORKTREE_PATH/.mock-ports.json"
    MOCK_PID_FILE="$WORKTREE_PATH/.mock-server.pid"

    # Start mock ubus servers
    echo "Starting mock ubus servers on port $MOCK_PORT..."
    MOCK_LOG_FILE="$WORKTREE_PATH/.mock-server.log"
    $VENV "$SCRIPT_DIR/mock_ubus_server.py" \
        --scenario "$SCENARIO" \
        --base-port "$MOCK_PORT" \
        --port-file "$MOCK_PORT_FILE" \
        > "$MOCK_LOG_FILE" 2>&1 &
    MOCK_PID=$!
    echo "$MOCK_PID" > "$MOCK_PID_FILE"
    sleep 2

    # Verify mock server is running
    if ! kill -0 "$MOCK_PID" 2>/dev/null; then
        echo "ERROR: Mock server failed to start"
        exit 1
    fi
    echo "Mock servers running (PID: $MOCK_PID)"

    # Start HA container
    echo ""
    echo "Starting HA container on port $HA_PORT..."
    "$SCRIPT_DIR/ha-env.sh" start \
        --worktree-path "$WORKTREE_PATH" \
        --ha-port "$HA_PORT" \
        --mock-port-file "$MOCK_PORT_FILE"

    # Setup HA (onboarding + integration)
    echo ""
    echo "Setting up HA integration..."
    TOKEN_FILE="$WORKTREE_PATH/.ha-token"
    $VENV "$SCRIPT_DIR/setup-ha.py" \
        --ha-url "http://localhost:$HA_PORT" \
        --mock-port-file "$MOCK_PORT_FILE" \
        --token-file "$TOKEN_FILE" || {
        echo "WARNING: HA setup failed. You may need to configure manually."
        echo "  URL: http://localhost:$HA_PORT"
    }

    # --- Output summary ---

    echo ""
    echo "=========================================="
    echo "  Test environment ready!"
    echo "=========================================="
    echo ""

    STATE_JSON=$(cat <<EOF
{
  "issue_number": $ISSUE_NUMBER,
  "branch_name": "$BRANCH_NAME",
  "worktree_path": "$WORKTREE_PATH",
  "ha_url": "http://localhost:$HA_PORT",
  "ha_port": $HA_PORT,
  "mock_base_port": $MOCK_PORT,
  "mock_pid": $MOCK_PID,
  "mock_port_file": "$MOCK_PORT_FILE",
  "token_file": "$TOKEN_FILE",
  "scenario": "$SCENARIO"
}
EOF
)
    # Save full state
    echo "$STATE_JSON" > "$WORKTREE_PATH/.dev-env-state.json"
    echo "$STATE_JSON"
else
    # Output minimal JSON so callers can parse worktree_path and branch_name
    cat <<EOF
{
  "issue_number": $ISSUE_NUMBER,
  "branch_name": "$BRANCH_NAME",
  "worktree_path": "$WORKTREE_PATH"
}
EOF
fi
