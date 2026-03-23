#!/bin/bash
# Launch a Claude instance to autonomously work on a GitHub issue.
#
# Usage:
#   dev/work-issue.sh <issue-number>
#   dev/work-issue.sh 42
#   dev/work-issue.sh 42 --branch-prefix fix
#
# What happens:
#   1. Sets up worktree + test environment
#   2. Launches claude in non-interactive mode with the issue context
#   3. Claude implements, tests, and creates a PR
#   4. Tears down the test environment
#
# To run multiple issues in parallel:
#   dev/work-issue.sh 42 &
#   dev/work-issue.sh 43 &

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <issue-number> [options]"
    echo "  -f, --follow          Run in background and follow with human-readable output"
    echo "  --branch-prefix PREFIX  Branch prefix (default: feature)"
    echo "  --model MODEL         Claude model (default: claude-sonnet-4-6)"
    exit 1
fi

ISSUE_NUMBER="$1"
shift

BRANCH_PREFIX="feature"
MODEL="claude-sonnet-4-6"
FOLLOW=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --branch-prefix) BRANCH_PREFIX="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        -f|--follow) FOLLOW=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# If --follow, re-launch in background and tail with follow-issue.sh
if [[ "$FOLLOW" == true ]]; then
    # Re-run without -f in background
    ARGS=("$ISSUE_NUMBER")
    [[ "$BRANCH_PREFIX" != "feature" ]] && ARGS+=(--branch-prefix "$BRANCH_PREFIX")
    [[ "$MODEL" != "claude-sonnet-4-6" ]] && ARGS+=(--model "$MODEL")
    "$0" "${ARGS[@]}" &
    BG_PID=$!
    sleep 2  # Let log file be created
    echo "Pipeline running in background (PID: $BG_PID)"
    exec "$REPO_ROOT/dev/follow-issue.sh" "$ISSUE_NUMBER"
fi

LOG_DIR="$REPO_ROOT/.claude/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/issue-${ISSUE_NUMBER}-$(date +%Y%m%d-%H%M%S).log"

VENV="$REPO_ROOT/.venv/bin/python"
REGISTRY="$SCRIPT_DIR/registry.py"

echo "=== Working on issue #${ISSUE_NUMBER} ==="
echo "Log: $LOG_FILE"

# --- Step 1: Setup worktree (no environment yet — that starts after planning) ---

echo "Setting up worktree..."
SETUP_OUTPUT=$("$SCRIPT_DIR/setup-worktree.sh" "$ISSUE_NUMBER" --branch-prefix "$BRANCH_PREFIX" --no-env 2>&1 | tee -a "$LOG_FILE")

# Extract worktree path
WORKTREE_PATH=$(echo "$SETUP_OUTPUT" | grep '"worktree_path"' | head -1 | sed 's/.*: *"\(.*\)".*/\1/')

if [[ -z "$WORKTREE_PATH" ]]; then
    echo "ERROR: Could not determine worktree path"
    exit 1
fi

BRANCH_NAME_ACTUAL=$(echo "$SETUP_OUTPUT" | grep '"branch_name"' | head -1 | sed 's/.*: *"\(.*\)".*/\1/' || echo "")

# Register run (no HA details yet — env starts after planning)
RUN_ID=$($VENV "$REGISTRY" create \
    --issue "$ISSUE_NUMBER" \
    --branch "$BRANCH_NAME_ACTUAL" \
    --worktree "$WORKTREE_PATH" \
    --model "$MODEL" \
    --log "$LOG_FILE" \
    --ha-url "" \
    --ha-port 0 \
    --mock-pid 0)
echo ""
echo "  Run ID: $RUN_ID  (use this with: dev/sessions.sh <command> $RUN_ID)"
echo "  Worktree: $WORKTREE_PATH"

# --- Step 2: Plan ---

# Pre-fetch issue text to inject into prompt (saves tool calls)
ISSUE_TITLE=$(gh issue view "${ISSUE_NUMBER}" --json title -q '.title' 2>/dev/null || echo "Issue #${ISSUE_NUMBER}")
ISSUE_BODY=$(gh issue view "${ISSUE_NUMBER}" --json body -q '.body' 2>/dev/null || echo "")
ISSUE_TEXT="# ${ISSUE_TITLE}

${ISSUE_BODY}"

# Store issue text in registry
$VENV "$REGISTRY" update "$RUN_ID" \
    --issue-title "$ISSUE_TITLE" \
    --issue-body "$ISSUE_BODY" 2>/dev/null || true

PLAN_FILE="$WORKTREE_PATH/.plan.md"
CLAUDE_DEBUG_FILE="$WORKTREE_PATH/.claude-debug.log"

cd "$WORKTREE_PATH"

# Append planning context to worktree CLAUDE.md so Claude sees it automatically
cat >> "$WORKTREE_PATH/CLAUDE.md" <<PLANEOF

## Current Task: Plan issue #${ISSUE_NUMBER}

You are in PLANNING mode. Read the codebase and propose a plan — do NOT implement anything.

### Issue #${ISSUE_NUMBER}
${ISSUE_TEXT}

### What to do
1. Read the relevant source files (sensor.py, coordinator.py, wrtmanager-cards.js, etc.)
2. Propose a plan to the user
3. When the user approves, write the final plan to \`.plan.md\`
4. Say "Plan saved. You can exit to continue the pipeline."

### Plan format (.plan.md)
# Plan: <one-line summary>

## Files to modify
For each file: path + line range, what to change, key code snippet showing the pattern

## UI changes (if any)
Where in existing card/layout, NOT new sections. Color/unit/format decisions.

MUST include an ASCII visual mockup showing the card layout. Example:
\`\`\`
┌─ Router Health ──────────────────────────┐
│  🖧 Main Router              📶 11  ⏱ 10d│
│    Linksys E8450                         │
│  Memory  ████████████░░░░░  59.5%        │
│  Load    ████░░░░░░░░░░░░░  0.52         │
│          5m 0.35  15m 0.24               │
│  ↓ 146.5 GB  ↑ 73.2 GB     since boot   │
│                                  23.05.3 │
└──────────────────────────────────────────┘
\`\`\`

## Data flow
ubus call → coordinator field → sensor entity → card display. Field names and types.

## Tests
Test cases + which test file to add to.

## NOT doing
Out of scope items.

### Rules
- Base plan on actual code, not assumptions
- Be specific: line numbers, function names, variable names
- UI changes MUST include ASCII visual mockup of the card layout
- UI changes MUST integrate into existing sections
- Smallest change that solves the issue
- Do NOT implement, only plan
PLANEOF

echo ""
echo "=========================================="
echo "  Planning issue #${ISSUE_NUMBER}"
echo "=========================================="
echo ""
echo "  Claude has the issue context in CLAUDE.md."
echo "  It will propose a plan. Review and steer it."
echo "  When approved, Claude writes .plan.md."
echo "  Then exit (/exit) to continue the pipeline."
echo ""
echo "=========================================="
echo ""

# Launch Claude interactively for planning
# CLAUDE.md already has the issue context and planning instructions
claude --model "$MODEL" --verbose

# Check if plan was written
if [[ ! -f "$PLAN_FILE" ]]; then
    echo ""
    echo "No plan file found (.plan.md). Pipeline stopped."
    echo "To resume: cd $WORKTREE_PATH && claude"
    echo "Then write .plan.md and run: dev/sessions.sh execute $RUN_ID"
    $VENV "$REGISTRY" update "$RUN_ID" --status "plan-pending" 2>/dev/null || true
    exit 0
fi

echo ""
echo "=== Plan approved ==="
echo "Starting test environment..."

# --- Step 2b: Start environment (after planning, so tokens are fresh) ---

ENV_OUTPUT=$("$SCRIPT_DIR/setup-worktree.sh" "$ISSUE_NUMBER" --branch-prefix "$BRANCH_PREFIX" 2>&1 | tee -a "$LOG_FILE")

HA_URL_ACTUAL=$(echo "$ENV_OUTPUT" | grep '"ha_url"' | head -1 | sed 's/.*: *"\(.*\)".*/\1/' || echo "")
HA_PORT_ACTUAL=$(echo "$ENV_OUTPUT" | grep '"ha_port"' | head -1 | sed 's/.*: *\([0-9]*\).*/\1/' || echo "0")
MOCK_PID_ACTUAL=$(echo "$ENV_OUTPUT" | grep '"mock_pid"' | head -1 | sed 's/.*: *\([0-9]*\).*/\1/' || echo "0")

$VENV "$REGISTRY" update "$RUN_ID" \
    --ha-url "$HA_URL_ACTUAL" \
    --ha-port "${HA_PORT_ACTUAL:-0}" \
    --mock-pid "${MOCK_PID_ACTUAL:-0}" 2>/dev/null || true

echo "Environment ready. Continuing with automated execution..."

# --- Step 3: Execute ---

PLAN_CONTENT=$(cat "$PLAN_FILE")

EXEC_PROMPT=$(cat <<EOF
You are implementing a change for the wrtmanager HA integration.
Follow the plan below EXACTLY. Do not deviate or add scope.

Your working directory is: ${WORKTREE_PATH}

## Plan
${PLAN_CONTENT}

## Instructions
1. Implement each file change listed in the plan
2. Write the tests listed in the plan
3. Run tests ONCE: PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
4. If tests fail, fix and re-run (max 2 retries)
5. Commit: git add <files> && git commit -m "<message>"

Rules:
- Follow the plan — do NOT add features or changes not in the plan
- Do NOT use gh, curl, or explore dev/ scripts
- Do NOT push or create a PR
- Do NOT mention AI in commit messages
EOF
)

echo ""
echo "=== Executing plan ==="

# Build allowed tools list from .claude/settings.json, excluding noisy tools
ALLOWED_TOOLS_FILE="$REPO_ROOT/.claude/settings.json"
EXCLUDE_TOOLS="TodoWrite,ToolSearch,WebSearch,WebFetch,AskUserQuestion,Skill,EnterPlanMode,ExitPlanMode,EnterWorktree,ExitWorktree,CronCreate,CronDelete,CronList"
if [[ -f "$ALLOWED_TOOLS_FILE" ]]; then
    ALLOWED_TOOLS=$(python3 -c "
import json
exclude = set('$EXCLUDE_TOOLS'.split(','))
with open('$ALLOWED_TOOLS_FILE') as f:
    settings = json.load(f)
tools = [t for t in settings.get('permissions', {}).get('allow', []) if t.split('(')[0] not in exclude]
print(','.join(tools))
")
else
    ALLOWED_TOOLS="Read,Write,Edit,Glob,Grep,Bash"
fi

stdbuf -oL claude -p "$EXEC_PROMPT" \
    --model "$MODEL" \
    --allowedTools "$ALLOWED_TOOLS" \
    --output-format stream-json \
    --debug-file "$CLAUDE_DEBUG_FILE" \
    --verbose \
    2>&1 | tee -a "$LOG_FILE"

CLAUDE_EXIT=$?

# Update registry with implementation result
if [[ $CLAUDE_EXIT -ne 0 ]]; then
    $VENV "$REGISTRY" update "$RUN_ID" --status error --error-message "Claude exited with code $CLAUDE_EXIT"
fi

# Report any permission denials for whitelisting
if [[ -f "$CLAUDE_DEBUG_FILE" ]]; then
    DENIED=$(grep -i "denied\|permission\|not allowed\|blocked" "$CLAUDE_DEBUG_FILE" 2>/dev/null || true)
    if [[ -n "$DENIED" ]]; then
        echo ""
        echo "=== Permission denials (add to .claude/settings.json to whitelist) ==="
        echo "$DENIED" | head -20
        echo "Full debug log: $CLAUDE_DEBUG_FILE"
    fi
fi

# --- Step 4: Post-implementation pipeline (code review → HA restart → screenshots → visual review → PR) ---

if [[ $CLAUDE_EXIT -eq 0 ]]; then
    "$SCRIPT_DIR/post-implement.sh" "$RUN_ID" --model "$MODEL"
else
    echo "Skipping post-implementation (Claude exited with $CLAUDE_EXIT)"
fi

REVIEW_FILE="$WORKTREE_PATH/.review-result.md"
REVIEW_VERDICT=$(head -1 "$REVIEW_FILE" 2>/dev/null | tr -d '[:space:]' || echo "N/A")
PR_NUMBER=$($VENV "$REGISTRY" get-field "$RUN_ID" pr_number 2>/dev/null || echo "")

# --- Step 5: Verify commit messages ---

if [[ $CLAUDE_EXIT -eq 0 ]]; then
    echo ""
    echo "=== Commit message check ==="
    COMMITS=$(git -C "$WORKTREE_PATH" log --oneline main..HEAD 2>/dev/null)
    BAD_COMMITS=""

    while IFS= read -r commit; do
        [[ -z "$commit" ]] && continue
        msg="${commit#* }"
        # Check for common issues
        if echo "$msg" | grep -qiE "ai|claude|gpt|llm|assistant"; then
            BAD_COMMITS+="  AI mention: $commit\n"
        fi
        if [[ ${#msg} -lt 10 ]]; then
            BAD_COMMITS+="  Too short: $commit\n"
        fi
        if echo "$msg" | grep -qE "^(fix|update|change) "; then
            # Vague commit message
            BAD_COMMITS+="  Vague (explain why, not what): $commit\n"
        fi
    done <<< "$COMMITS"

    if [[ -n "$BAD_COMMITS" ]]; then
        echo "WARNING: Commit message issues found:"
        echo -e "$BAD_COMMITS"
    else
        echo "Commit messages look good"
    fi
fi

# --- Step 6: Run analysis ---

echo ""
echo "=== Run analysis ==="
ANALYSIS=$("$REPO_ROOT/dev/analyze-run.sh" "$ISSUE_NUMBER" 2>&1 | tee -a "$LOG_FILE")

# Extract cost from analysis and update registry
COST=$(echo "$ANALYSIS" | grep -oP 'Est\. cost:\s+\$\K[0-9.]+' || echo "")
if [[ -n "$COST" ]] && [[ -n "$RUN_ID" ]]; then
    $VENV "$REGISTRY" update "$RUN_ID" --cost-estimate "$COST" 2>/dev/null || true
fi

# Append suggestions to cumulative file for tracking patterns across runs
SUGGESTIONS_FILE="$REPO_ROOT/.claude/run-suggestions.md"
mkdir -p "$(dirname "$SUGGESTIONS_FILE")"
{
    echo ""
    echo "## Issue #${ISSUE_NUMBER} — $(date +%Y-%m-%d)"
    "$REPO_ROOT/dev/analyze-run.sh" "$ISSUE_NUMBER" 2>/dev/null | sed -n '/SUGGESTIONS/,$ p'
} >> "$SUGGESTIONS_FILE" 2>/dev/null || true

echo ""
echo "=========================================="
echo "  Run #${RUN_ID} — Issue #${ISSUE_NUMBER} (exit: $CLAUDE_EXIT)"
echo "=========================================="
echo ""
echo "  Run ID: $RUN_ID"
echo "  Log: $LOG_FILE"
echo "  Worktree: $WORKTREE_PATH"
if [[ -n "$HA_URL_ACTUAL" ]]; then
echo "  HA: $HA_URL_ACTUAL (wrt / wrt-test-123)"
fi
if [[ -f "$REVIEW_FILE" ]]; then
echo "  Review: $(head -1 "$REVIEW_FILE" 2>/dev/null)"
fi
echo ""
echo "  Commands:"
echo "    dev/sessions.sh show $RUN_ID"
echo "    dev/sessions.sh screenshots $RUN_ID"
echo "    dev/sessions.sh open $RUN_ID"
echo "    dev/sessions.sh logs $RUN_ID"
echo "    dev/sessions.sh teardown $RUN_ID"
echo "=========================================="
echo ""
echo ">>> PIPELINE FINISHED <<<"

exit $CLAUDE_EXIT
