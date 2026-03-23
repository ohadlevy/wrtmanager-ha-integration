#!/bin/bash
# Teardown test environment for a worktree.
#
# Stops mock servers and HA container. Optionally removes the worktree.
#
# Usage:
#   dev/teardown-worktree.sh <worktree-path> [--remove-worktree]
#   dev/teardown-worktree.sh .claude/worktrees/42-fix-something
#   dev/teardown-worktree.sh .claude/worktrees/42-fix-something --remove-worktree

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <worktree-path> [--remove-worktree]"
    exit 1
fi

WORKTREE_PATH="$1"
shift

# Make absolute if relative
if [[ "$WORKTREE_PATH" != /* ]]; then
    WORKTREE_PATH="$REPO_ROOT/$WORKTREE_PATH"
fi

REMOVE_WORKTREE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --remove-worktree) REMOVE_WORKTREE=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=== Tearing down test environment ==="
echo "Worktree: $WORKTREE_PATH"

# --- Stop mock servers ---

MOCK_PID_FILE="$WORKTREE_PATH/.mock-server.pid"
if [[ -f "$MOCK_PID_FILE" ]]; then
    MOCK_PID=$(cat "$MOCK_PID_FILE")
    if kill -0 "$MOCK_PID" 2>/dev/null; then
        echo "Stopping mock ubus servers (PID: $MOCK_PID)..."
        kill "$MOCK_PID" 2>/dev/null || true
        # Wait for graceful shutdown
        for i in $(seq 1 10); do
            if ! kill -0 "$MOCK_PID" 2>/dev/null; then
                break
            fi
            sleep 0.5
        done
        # Force kill if still running
        if kill -0 "$MOCK_PID" 2>/dev/null; then
            kill -9 "$MOCK_PID" 2>/dev/null || true
        fi
        echo "Mock servers stopped"
    else
        echo "Mock server PID $MOCK_PID not running"
    fi
    rm -f "$MOCK_PID_FILE"
fi

# --- Stop HA container ---

echo "Stopping HA container..."
"$SCRIPT_DIR/ha-env.sh" clean --worktree-path "$WORKTREE_PATH" 2>/dev/null || true

# --- Clean up state files ---

rm -f "$WORKTREE_PATH/.mock-ports.json"
rm -f "$WORKTREE_PATH/.ha-token"
rm -f "$WORKTREE_PATH/.ha-test-state.json"
rm -f "$WORKTREE_PATH/.dev-env-state.json"

# --- Optionally remove worktree ---

if [[ "$REMOVE_WORKTREE" == true ]]; then
    echo "Removing worktree..."
    cd "$REPO_ROOT"

    # Get the branch name before removing
    BRANCH_NAME=$(git -C "$WORKTREE_PATH" branch --show-current 2>/dev/null || echo "")

    git worktree remove --force "$WORKTREE_PATH" 2>/dev/null || {
        echo "git worktree remove failed, removing manually"
        rm -rf "$WORKTREE_PATH"
        git worktree prune
    }

    if [[ -n "$BRANCH_NAME" ]]; then
        echo "Worktree removed (branch '$BRANCH_NAME' preserved)"
        echo "To delete the branch: git branch -d $BRANCH_NAME"
    fi
else
    echo "Worktree preserved at: $WORKTREE_PATH"
fi

echo "Teardown complete"
