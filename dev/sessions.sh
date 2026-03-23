#!/bin/bash
# Unified CLI for the autonomous issue pipeline.
#
# Usage:
#   dev/sessions.sh run <issue> [options]        # Start a new pipeline run (returns run ID)
#   dev/sessions.sh list [--status S] [--issue N] # List all runs
#   dev/sessions.sh watch <run-id>               # Follow live output
#   dev/sessions.sh resume <run-id> [--auto]     # Resume a failed run
#   dev/sessions.sh show <run-id>                # Full run details (JSON)
#   dev/sessions.sh open <run-id>                # Open HA dashboard in browser
#   dev/sessions.sh screenshots <run-id>         # View screenshots
#   dev/sessions.sh teardown <run-id>            # Stop environment + cleanup
#   dev/sessions.sh logs <run-id>                # Show raw log path

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$REPO_ROOT/.venv/bin/python"
REGISTRY="$SCRIPT_DIR/registry.py"

# Helper: get a field from a run by ID
_field() {
    $VENV "$REGISTRY" get-field "$1" "$2" 2>/dev/null
}

# Helper: validate run ID exists, sets WORKTREE variable
_require_run() {
    WORKTREE=$(_field "$1" worktree_path || echo "")
    if [[ -z "$WORKTREE" ]]; then
        echo "Run #$1 not found. Use 'dev/sessions.sh list' to see all runs."
        exit 1
    fi
}

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  run <issue> [--model M] [--branch-prefix P]  Plan interactively, then execute"
    echo "  execute <run-id> [--model M]                 Execute a saved plan"
    echo "  list [--status running|pass|fail] [--issue N] List runs"
    echo "  watch <run-id>                                Follow live output"
    echo "  resume <run-id> [--auto]                      Resume failed run"
    echo "  show <run-id>                                 Full run details"
    echo "  open <run-id>                                 Open HA dashboard"
    echo "  screenshots <run-id>                          View screenshots"
    echo "  logs <run-id>                                 Show log file"
    echo "  plan <run-id>                                View the implementation plan"
    echo "  cancel <run-id>                              Stop running Claude, keep env"
    echo "  feedback <run-id> \"<feedback>\" [--auto]       Give feedback, re-fix, re-review"
    echo "  teardown <run-id>                             Stop + cleanup"
    exit 1
fi

COMMAND="$1"
shift

case "$COMMAND" in
    run|start)
        if [[ $# -lt 1 ]]; then
            echo "Usage: $0 run <issue-number> [--model M] [-f]"
            exit 1
        fi
        exec "$SCRIPT_DIR/work-issue.sh" "$@"
        ;;

    execute|exec)
        if [[ $# -lt 1 ]]; then
            echo "Usage: $0 execute <run-id> [--model M]"
            exit 1
        fi
        RUN_ID="$1"
        shift
        MODEL="claude-sonnet-4-6"
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --model) MODEL="$2"; shift 2 ;;
                *) echo "Unknown: $1"; exit 1 ;;
            esac
        done

        _require_run "$RUN_ID"
        ISSUE=$(_field "$RUN_ID" issue_number)
        PLAN_FILE="$WORKTREE/.plan.md"

        if [[ ! -f "$PLAN_FILE" ]]; then
            echo "No plan found for run #$RUN_ID"
            echo "Start planning: cd $WORKTREE && claude"
            exit 1
        fi

        echo "=== Executing plan for run #$RUN_ID (issue #$ISSUE) ==="
        cat "$PLAN_FILE"
        echo ""
        echo "---"

        PLAN_CONTENT=$(cat "$PLAN_FILE")
        LOG_DIR="$REPO_ROOT/.claude/logs"
        mkdir -p "$LOG_DIR"
        LOG_FILE="$LOG_DIR/issue-${ISSUE}-exec-$(date +%Y%m%d-%H%M%S).log"

        EXEC_PROMPT=$(cat <<EXECEOF
You are implementing a change for the wrtmanager HA integration.
Follow the plan below EXACTLY. Do not deviate or add scope.

Your working directory is: ${WORKTREE}

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
EXECEOF
)

        # Build allowed tools
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

        cd "$WORKTREE"
        stdbuf -oL claude -p "$EXEC_PROMPT" \
            --model "$MODEL" \
            --allowedTools "$ALLOWED_TOOLS" \
            --output-format stream-json \
            --verbose \
            2>&1 | tee -a "$LOG_FILE" | python3 -u -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        continue
    if msg.get('type') == 'assistant':
        for block in msg.get('message', {}).get('content', []):
            if block.get('type') == 'text' and block.get('text', '').strip():
                print(block['text'])
            elif block.get('type') == 'tool_use':
                name = block.get('name', '')
                inp = block.get('input', {})
                if name == 'Edit':
                    print(f'  Edit: {inp.get(\"file_path\",\"\").split(\"/\")[-1]}')
                elif name == 'Read':
                    print(f'  Read: {inp.get(\"file_path\",\"\").split(\"/\")[-1]}')
                elif name == 'Bash':
                    cmd = inp.get('command', '')[:80]
                    print(f'  Run: {cmd}')
                elif name == 'Write':
                    print(f'  Write: {inp.get(\"file_path\",\"\").split(\"/\")[-1]}')
                elif name in ('Glob', 'Grep'):
                    print(f'  {name}: {inp.get(\"pattern\",\"\")[:60]}')
    sys.stdout.flush()
"

        echo ""
        echo "=== Running post-implementation pipeline ==="
        "$SCRIPT_DIR/post-implement.sh" "$RUN_ID" --model "$MODEL"
        ;;

    list|ls)
        $VENV "$REGISTRY" list "$@"
        ;;

    watch|follow|tail)
        if [[ $# -lt 1 ]]; then
            echo "Usage: $0 watch <run-id>"
            exit 1
        fi
        ISSUE=$(_field "$1" issue_number)
        if [[ -z "$ISSUE" ]]; then
            echo "Run #$1 not found"
            exit 1
        fi
        exec "$SCRIPT_DIR/follow-issue.sh" "$ISSUE"
        ;;

    plan)
        if [[ $# -lt 1 ]]; then
            echo "Usage: $0 plan <run-id>"
            exit 1
        fi
        _require_run "$1"
        PLAN_FILE="$WORKTREE/.plan.md"
        if [[ -f "$PLAN_FILE" ]]; then
            cat "$PLAN_FILE"
        else
            echo "No plan found for run #$1"
            echo "Plan is generated during pipeline execution (Step 2)"
        fi
        ;;

    show)
        if [[ $# -lt 1 ]]; then
            echo "Usage: $0 show <run-id>"
            exit 1
        fi
        $VENV "$REGISTRY" get "$1"
        ;;

    resume)
        if [[ $# -lt 1 ]]; then
            echo "Usage: $0 resume <run-id> [--auto]"
            exit 1
        fi
        RUN_ID="$1"
        shift
        AUTO=false
        MODEL="claude-sonnet-4-6"
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --auto) AUTO=true; shift ;;
                --model) MODEL="$2"; shift 2 ;;
                *) echo "Unknown: $1"; exit 1 ;;
            esac
        done

        _require_run "$RUN_ID"
        ISSUE=$(_field "$RUN_ID" issue_number)

        if [[ ! -d "$WORKTREE" ]]; then
            echo "Worktree not found at $WORKTREE. Re-run with: $0 run $ISSUE"
            exit 1
        fi

        if [[ "$AUTO" == true ]]; then
            RESUME_PROMPT=$($VENV "$REGISTRY" resume-context --run-id "$RUN_ID" --prompt)
            LOG_DIR="$REPO_ROOT/.claude/logs"
            mkdir -p "$LOG_DIR"
            LOG_FILE="$LOG_DIR/issue-${ISSUE}-resume-$(date +%Y%m%d-%H%M%S).log"

            echo "Resuming run #$RUN_ID (issue #$ISSUE) non-interactively..."
            cd "$WORKTREE"
            stdbuf -oL claude -p "$RESUME_PROMPT" \
                --model "$MODEL" \
                --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
                --output-format stream-json \
                --verbose \
                2>&1 | tee -a "$LOG_FILE"
        else
            RESUME_PROMPT=$($VENV "$REGISTRY" resume-context --run-id "$RUN_ID" --prompt)
            echo "$RESUME_PROMPT" > "$WORKTREE/.claude-resume-prompt.md"
            echo "=== Resuming run #$RUN_ID (issue #$ISSUE) ==="
            echo "Worktree: $WORKTREE"
            echo ""
            echo "Run: cd $WORKTREE && claude"
            echo "Then: 'Read .claude-resume-prompt.md and fix the issues'"
        fi
        ;;

    open)
        if [[ $# -lt 1 ]]; then
            echo "Usage: $0 open <run-id>"
            exit 1
        fi
        _require_run "$1"
        HA_URL=$(_field "$1" ha_url)
        if [[ -n "$HA_URL" ]]; then
            echo "Opening $HA_URL (wrt / wrt-test-123)"
            xdg-open "$HA_URL" 2>/dev/null || open "$HA_URL" 2>/dev/null || echo "Open: $HA_URL"
        else
            echo "No HA URL found for run #$1"
        fi
        ;;

    screenshots|ss)
        if [[ $# -lt 1 ]]; then
            echo "Usage: $0 screenshots <run-id>"
            exit 1
        fi
        _require_run "$1"
        if [[ ! -d "$WORKTREE" ]]; then
            echo "Worktree not found at $WORKTREE"
            exit 1
        fi
        SS_DIR="$WORKTREE/.test-screenshots"
        if [[ -d "$SS_DIR" ]] && ls "$SS_DIR"/*.png &>/dev/null; then
            COUNT=$(ls "$SS_DIR"/*.png 2>/dev/null | wc -l)
            echo "Screenshots ($COUNT) in: $SS_DIR"
            ls -1 "$SS_DIR"/*-desktop.png 2>/dev/null | while read -r f; do
                echo "  $(basename "$f")"
            done
            # Open first desktop screenshot if viewer available
            FIRST=$(ls "$SS_DIR"/*-desktop.png 2>/dev/null | head -1)
            if [[ -n "$FIRST" ]]; then
                xdg-open "$FIRST" 2>/dev/null || echo "View: $FIRST"
            fi
        else
            echo "No screenshots found for run #$1"
        fi
        ;;

    logs|log)
        if [[ $# -lt 1 ]]; then
            echo "Usage: $0 logs <run-id>"
            exit 1
        fi
        _require_run "$1"
        LOG_FILE=$(_field "$1" log_file)
        ISSUE=$(_field "$1" issue_number)
        if [[ -n "$LOG_FILE" ]] && [[ -f "$LOG_FILE" ]]; then
            echo "Log: $LOG_FILE"
            echo "Follow: tail -f $LOG_FILE"
            echo "Parsed: dev/follow-issue.sh $ISSUE"
        else
            echo "No log found for run #$1"
        fi
        ;;

    cancel|kill)
        if [[ $# -lt 1 ]]; then
            echo "Usage: $0 cancel <run-id>"
            exit 1
        fi
        _require_run "$1"
        ISSUE=$(_field "$1" issue_number)

        # Find and kill claude processes working in this worktree
        KILLED=0
        # Kill work-issue.sh and its children (claude -p, review claude, etc.)
        for pid in $(pgrep -f "work-issue.sh.*$ISSUE" 2>/dev/null); do
            pkill -P "$pid" 2>/dev/null || true  # Kill children first
            kill "$pid" 2>/dev/null || true
            KILLED=$((KILLED + 1))
        done
        # Also kill any claude -p processes in the worktree
        for pid in $(pgrep -f "claude.*$WORKTREE" 2>/dev/null); do
            kill "$pid" 2>/dev/null || true
            KILLED=$((KILLED + 1))
        done

        if [[ $KILLED -gt 0 ]]; then
            echo "Cancelled run #$1 (killed $KILLED processes)"
        else
            echo "No running processes found for run #$1"
        fi
        $VENV "$REGISTRY" update "$1" --status "cancelled" 2>/dev/null || true

        echo ""
        echo "Environment still running. Next steps:"
        echo "  Interactive:  cd $WORKTREE && claude"
        echo "  Feedback:     $0 feedback $1 \"<your feedback>\" --auto"
        echo "  Teardown:     $0 teardown $1"
        ;;

    feedback|fb)
        if [[ $# -lt 2 ]]; then
            echo "Usage: $0 feedback <run-id> \"<feedback text>\" [--auto] [--model M]"
            exit 1
        fi
        RUN_ID="$1"
        FEEDBACK="$2"
        shift 2
        AUTO=false
        MODEL="claude-sonnet-4-6"
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --auto) AUTO=true; shift ;;
                --model) MODEL="$2"; shift 2 ;;
                *) echo "Unknown: $1"; exit 1 ;;
            esac
        done

        _require_run "$RUN_ID"
        ISSUE=$(_field "$RUN_ID" issue_number)
        ISSUE_TITLE=$(_field "$RUN_ID" issue_title || echo "")
        ISSUE_BODY=$(_field "$RUN_ID" issue_body || echo "")
        HA_URL=$(_field "$RUN_ID" ha_url || echo "")

        if [[ ! -d "$WORKTREE" ]]; then
            echo "Worktree not found at $WORKTREE. Re-run with: $0 run $ISSUE"
            exit 1
        fi

        # Save feedback to registry
        $VENV "$REGISTRY" update "$RUN_ID" \
            --status "feedback" \
            --review-feedback "$FEEDBACK" 2>/dev/null || true

        DIFF_STAT=$(git -C "$WORKTREE" diff main...HEAD --stat 2>/dev/null || echo "")

        FEEDBACK_PROMPT=$(cat <<FBEOF
You are fixing issue #${ISSUE} based on human feedback.

Working directory: ${WORKTREE}

## Issue #${ISSUE}: ${ISSUE_TITLE}
${ISSUE_BODY}

## Current changes
${DIFF_STAT}

## Human feedback
${FEEDBACK}

## Instructions
1. Read the relevant source files to understand current state
2. Apply the feedback with minimal changes
3. Run tests: PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
4. Commit: git add <files> && git commit -m "<message>"

Rules:
- Do NOT use gh, curl, or explore dev/ scripts
- Do NOT push or create a PR
- Do NOT mention AI in commit messages
- Keep changes minimal and focused
FBEOF
)

        LOG_DIR="$REPO_ROOT/.claude/logs"
        mkdir -p "$LOG_DIR"
        LOG_FILE="$LOG_DIR/issue-${ISSUE}-feedback-$(date +%Y%m%d-%H%M%S).log"

        if [[ "$AUTO" == true ]]; then
            echo "Applying feedback on run #$RUN_ID (issue #$ISSUE)..."
            echo "Feedback: $FEEDBACK"
            echo ""

            # Build allowed tools list
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

            cd "$WORKTREE"
            stdbuf -oL claude -p "$FEEDBACK_PROMPT" \
                --model "$MODEL" \
                --allowedTools "$ALLOWED_TOOLS" \
                --output-format stream-json \
                --verbose \
                2>&1 | tee -a "$LOG_FILE" | python3 -u -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        continue
    # Show tool use (what Claude is doing)
    if msg.get('type') == 'assistant':
        for block in msg.get('message', {}).get('content', []):
            if block.get('type') == 'text' and block.get('text', '').strip():
                print(block['text'])
            elif block.get('type') == 'tool_use':
                name = block.get('name', '')
                inp = block.get('input', {})
                if name == 'Edit':
                    print(f'  Edit: {inp.get(\"file_path\",\"\").split(\"/\")[-1]}')
                elif name == 'Read':
                    print(f'  Read: {inp.get(\"file_path\",\"\").split(\"/\")[-1]}')
                elif name == 'Bash':
                    cmd = inp.get('command', '')[:80]
                    print(f'  Run: {cmd}')
                elif name == 'Write':
                    print(f'  Write: {inp.get(\"file_path\",\"\").split(\"/\")[-1]}')
                elif name in ('Glob', 'Grep'):
                    print(f'  {name}: {inp.get(\"pattern\",\"\")[:60]}')
    sys.stdout.flush()
"
            CLAUDE_EXIT=$?

            if [[ $CLAUDE_EXIT -eq 0 ]]; then
                # Restart HA to pick up changes
                HA_TOKEN=$(cat "$WORKTREE/.ha-token" 2>/dev/null || echo "")
                if [[ -n "$HA_URL" ]] && [[ -n "$HA_TOKEN" ]]; then
                    echo ""
                    echo "=== Restarting HA ==="
                    curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
                        -H "Content-Type: application/json" \
                        "$HA_URL/api/services/homeassistant/restart" >/dev/null 2>&1
                    for i in $(seq 1 30); do
                        if curl -s -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/" >/dev/null 2>&1; then
                            echo "HA restarted"
                            break
                        fi
                        sleep 2
                    done
                fi

                # Re-take screenshots
                echo ""
                echo "=== Re-taking screenshots ==="
                SCREENSHOT_DIR="$WORKTREE/.test-screenshots"
                rm -f "$SCREENSHOT_DIR"/*.png 2>/dev/null || true
                "$REPO_ROOT/dev/run-tests.sh" \
                    --worktree-path "$WORKTREE" \
                    --browser-only \
                    2>&1 | tee -a "$LOG_FILE" || true

                # Show result
                echo ""
                echo "=== Feedback applied ==="
                echo "Screenshots: dev/sessions.sh screenshots $RUN_ID"
                echo "Open HA:     dev/sessions.sh open $RUN_ID"
                echo "If good, push: cd $WORKTREE && git push origin HEAD"
            fi
        else
            echo "$FEEDBACK_PROMPT" > "$WORKTREE/.claude-resume-prompt.md"
            echo "=== Feedback for run #$RUN_ID (issue #$ISSUE) ==="
            echo "Feedback saved to worktree."
            echo ""
            echo "Run interactively:"
            echo "  cd $WORKTREE && claude"
            echo "  Then: 'Read .claude-resume-prompt.md and apply the feedback'"
            echo ""
            echo "Or run non-interactively:"
            echo "  $0 feedback $RUN_ID \"$FEEDBACK\" --auto"
        fi
        ;;

    teardown|stop|clean)
        if [[ $# -lt 1 ]]; then
            echo "Usage: $0 teardown <run-id>"
            exit 1
        fi
        _require_run "$1"
        if [[ -d "$WORKTREE" ]]; then
            "$SCRIPT_DIR/teardown-worktree.sh" "$WORKTREE"
            $VENV "$REGISTRY" update "$1" --status "teardown" 2>/dev/null || true
        else
            echo "Worktree not found at $WORKTREE (already cleaned up?)"
            $VENV "$REGISTRY" update "$1" --status "teardown" 2>/dev/null || true
        fi
        ;;

    *)
        echo "Unknown command: $COMMAND"
        echo "Run '$0' without arguments for usage."
        exit 1
        ;;
esac
