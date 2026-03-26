#!/bin/bash
# Post-implementation pipeline:
#   code review → HA restart → entity validation → screenshots → visual review → PR
#
# Usage:
#   dev/post-implement.sh <run-id> [--model MODEL]
#
# Expects: worktree with committed changes, running HA environment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$REPO_ROOT/.venv/bin/python"
REGISTRY="$SCRIPT_DIR/registry.py"

# --- Helper: capture diagnostics (HA logs, dashboard, entities) ---
# Writes to $WORKTREE_PATH/.diagnostics.txt for use by fix prompts
capture_diagnostics() {
    local ha_url="$1" ha_token="$2" worktree="$3"
    local diag_file="$worktree/.diagnostics.txt"
    > "$diag_file"

    echo "=== Capturing diagnostics ==="

    # 1. HA error log (last 50 lines with wrtmanager mentions)
    echo "--- HA Logs (wrtmanager-related) ---" >> "$diag_file"
    local ha_container
    ha_container=$(podman ps --format '{{.Names}}' 2>/dev/null | grep "ha-wrt-test" | head -1 || echo "")
    if [[ -n "$ha_container" ]]; then
        podman logs --tail 200 "$ha_container" 2>&1 | grep -i "wrtmanager\|error\|warning\|exception\|traceback" | tail -50 >> "$diag_file" 2>/dev/null || echo "(no logs)" >> "$diag_file"
    else
        echo "(no HA container found)" >> "$diag_file"
    fi
    echo "" >> "$diag_file"

    # 2. Dashboard cards
    echo "--- Dashboard Cards ---" >> "$diag_file"
    $VENV -c "
import asyncio, json, aiohttp
async def check():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect('${ha_url}/api/websocket') as ws:
                await ws.receive_json()
                await ws.send_json({'type': 'auth', 'access_token': '${ha_token}'})
                msg = await ws.receive_json()
                if msg.get('type') != 'auth_ok':
                    print('Auth failed: ' + str(msg))
                    return
                await ws.send_json({'id': 1, 'type': 'lovelace/config'})
                config = await ws.receive_json()
                views = config.get('result', {}).get('views', [])
                cards = views[0].get('cards', []) if views else []
                for c in cards:
                    print('  ' + c.get('type', '?'))
    except Exception as e:
        print(f'Error: {e}')
asyncio.run(check())
" >> "$diag_file" 2>/dev/null || echo "(could not read dashboard)" >> "$diag_file"
    echo "" >> "$diag_file"

    # 3. Wrtmanager entity states (name + state + key attributes)
    echo "--- Wrtmanager Entities ---" >> "$diag_file"
    curl -s -H "Authorization: Bearer $ha_token" "$ha_url/api/states" 2>/dev/null | \
        $VENV -c "
import json, sys
try:
    entities = json.load(sys.stdin)
    wrt = sorted([e for e in entities if 'wrtmanager' in e.get('entity_id', '')],
                 key=lambda e: e['entity_id'])
    for e in wrt:
        attrs = e.get('attributes', {})
        attr_summary = ''
        # For card sensors, show attribute count
        if isinstance(attrs, dict) and len(attrs) > 3:
            attr_summary = f' ({len(attrs)} attrs)'
        print(f\"  {e['entity_id']}: {e.get('state', '?')}{attr_summary}\")
    print(f'Total: {len(wrt)} entities')
except Exception as ex:
    print(f'Error: {ex}')
" >> "$diag_file" 2>/dev/null || echo "(could not read entities)" >> "$diag_file"
    echo "" >> "$diag_file"

    # 4. Browser console errors (from last Playwright run if available)
    local console_log="$worktree/.test-screenshots/console-errors.txt"
    if [[ -f "$console_log" ]]; then
        echo "--- Browser Console Errors ---" >> "$diag_file"
        cat "$console_log" >> "$diag_file"
        echo "" >> "$diag_file"
    fi

    local line_count
    line_count=$(wc -l < "$diag_file")
    echo "Diagnostics captured ($line_count lines) → .diagnostics.txt"
}

# --- Helper: wait for entities to appear after HA restart ---
# HA API responding ≠ integration loaded ≠ first data poll complete.
# Without this, diagnostics/screenshots capture a transient "0 entities" state.
wait_for_entities() {
    local ha_url="$1" ha_token="$2" max_wait="${3:-60}"
    echo "Waiting for wrtmanager entities to load (up to ${max_wait}s)..."
    for i in $(seq 1 "$max_wait"); do
        local count
        count=$(curl -s -H "Authorization: Bearer $ha_token" "$ha_url/api/states" 2>/dev/null | \
            $VENV -c "import json,sys; e=json.load(sys.stdin); print(len([x for x in e if 'wrtmanager' in x.get('entity_id','')]))" 2>/dev/null || echo "0")
        if [[ "$count" -gt 0 ]]; then
            echo "  $count entities loaded after ${i}s"
            return 0
        fi
        sleep 1
    done
    echo "  WARNING: No entities after ${max_wait}s"
    return 1
}

# --- Helper: smoke test (returns 0 if OK, 1 if issues found) ---
smoke_test() {
    local ha_url="$1" ha_token="$2" worktree="$3"
    local issues=""

    echo "=== Smoke test ==="

    # Check entities exist and aren't unavailable
    local entity_count unavail_count
    entity_count=$(curl -s -H "Authorization: Bearer $ha_token" "$ha_url/api/states" 2>/dev/null | \
        $VENV -c "import json,sys; e=json.load(sys.stdin); wrt=[x for x in e if 'wrtmanager' in x.get('entity_id','')]; print(len(wrt))" 2>/dev/null || echo "0")
    unavail_count=$(curl -s -H "Authorization: Bearer $ha_token" "$ha_url/api/states" 2>/dev/null | \
        $VENV -c "import json,sys; e=json.load(sys.stdin); wrt=[x for x in e if 'wrtmanager' in x.get('entity_id','') and x.get('state') in ('unavailable','unknown')]; print(len(wrt))" 2>/dev/null || echo "0")

    echo "  Entities: $entity_count total, $unavail_count unavailable"

    if [[ "$entity_count" -eq 0 ]]; then
        issues+="No wrtmanager entities found in HA. Integration may not have loaded.\n"
    fi
    if [[ "$unavail_count" -gt 0 ]]; then
        issues+="$unavail_count entities are unavailable/unknown.\n"
    fi

    # Check dashboard has cards
    local card_count
    card_count=$($VENV -c "
import asyncio, aiohttp
async def check():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect('${ha_url}/api/websocket') as ws:
                await ws.receive_json()
                await ws.send_json({'type': 'auth', 'access_token': '${ha_token}'})
                msg = await ws.receive_json()
                if msg.get('type') != 'auth_ok': print('0'); return
                await ws.send_json({'id': 1, 'type': 'lovelace/config'})
                config = await ws.receive_json()
                views = config.get('result', {}).get('views', [])
                cards = views[0].get('cards', []) if views else []
                print(len(cards))
    except: print('0')
asyncio.run(check())
" 2>/dev/null || echo "0")

    echo "  Dashboard cards: $card_count"

    if [[ "$card_count" -eq 0 ]]; then
        issues+="No cards on dashboard. setup-ha.py may have failed.\n"
    fi

    # Check HA logs for integration errors
    local ha_container error_count
    ha_container=$(podman ps --format '{{.Names}}' 2>/dev/null | grep "ha-wrt-test" | head -1 || echo "")
    if [[ -n "$ha_container" ]]; then
        error_count=$(podman logs --tail 100 "$ha_container" 2>&1 | grep -ci "error.*wrtmanager\|wrtmanager.*error\|exception.*wrtmanager" || echo "0")
        echo "  HA log errors (wrtmanager): $error_count"
        if [[ "$error_count" -gt 0 ]]; then
            issues+="$error_count wrtmanager errors in HA logs.\n"
        fi
    fi

    if [[ -n "$issues" ]]; then
        echo ""
        echo "Smoke test FAILED:"
        echo -e "$issues"
        return 1
    else
        echo "  Smoke test passed"
        return 0
    fi
}

RUN_ID="$1"
shift
MODEL="claude-sonnet-4-6"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --model) MODEL="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# Look up run details
WORKTREE_PATH=$($VENV "$REGISTRY" get-field "$RUN_ID" worktree_path 2>/dev/null || echo "")
ISSUE_NUMBER=$($VENV "$REGISTRY" get-field "$RUN_ID" issue_number 2>/dev/null || echo "")
ISSUE_TITLE=$($VENV "$REGISTRY" get-field "$RUN_ID" issue_title 2>/dev/null || echo "")
ISSUE_BODY=$($VENV "$REGISTRY" get-field "$RUN_ID" issue_body 2>/dev/null || echo "")
ISSUE_TEXT="# ${ISSUE_TITLE}

${ISSUE_BODY}"

# Use worktree's setup-ha.py (it knows about new cards added by the branch)
SETUP_HA="$WORKTREE_PATH/dev/setup-ha.py"
[[ -f "$SETUP_HA" ]] || SETUP_HA="$SCRIPT_DIR/setup-ha.py"

PLAN_FILE="$WORKTREE_PATH/.plan.md"
PLAN_TEXT=""
if [[ -f "$PLAN_FILE" ]]; then
    PLAN_TEXT=$(cat "$PLAN_FILE")
fi

if [[ -z "$WORKTREE_PATH" ]] || [[ ! -d "$WORKTREE_PATH" ]]; then
    echo "ERROR: Worktree not found for run #$RUN_ID"
    exit 1
fi

LOG_DIR="$REPO_ROOT/.claude/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/issue-${ISSUE_NUMBER}-post-$(date +%Y%m%d-%H%M%S).log"

echo "=== Post-implementation pipeline for run #$RUN_ID (issue #$ISSUE_NUMBER) ==="

# --- Code review ---

FULL_DIFF=$(git -C "$WORKTREE_PATH" diff main...HEAD 2>/dev/null || echo "")
if [[ -n "$FULL_DIFF" ]]; then
    echo ""
    echo "=== Code review ==="

    CODE_REVIEW_PROMPT=$(cat <<CREOF
Review this diff for quality. Fix any issues, then commit.
If the diff is clean, say "LGTM" and do nothing.
Do NOT touch code outside this diff.

${FULL_DIFF}
CREOF
)

    cd "$WORKTREE_PATH"
    claude -p "$CODE_REVIEW_PROMPT" \
        --model sonnet \
        --allowedTools "Read,Edit,Bash(git add:*),Bash(git commit:*),Bash(git diff:*)" \
        --verbose \
        2>&1 | tee -a "$LOG_FILE"
    echo "Code review complete"
fi

# --- Restart HA ---

HA_URL=""
STATE_FILE="$WORKTREE_PATH/.dev-env-state.json"
if [[ -f "$STATE_FILE" ]]; then
    HA_URL=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['ha_url'])" 2>/dev/null || echo "")
fi

if [[ -n "$HA_URL" ]]; then
    HA_TOKEN=$(cat "$WORKTREE_PATH/.ha-token" 2>/dev/null || echo "")
    if [[ -n "$HA_TOKEN" ]]; then
        echo ""
        echo "=== Restarting HA ==="
        curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            "$HA_URL/api/services/homeassistant/restart" >/dev/null 2>&1
        for i in $(seq 1 30); do
            if curl -s -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/" >/dev/null 2>&1; then
                echo "HA restarted and ready"
                break
            fi
            sleep 2
        done

        # Update Lovelace dashboard to pick up any new cards added since initial setup
        MOCK_PORT_FILE="$WORKTREE_PATH/.mock-ports.json"
        if [[ -f "$MOCK_PORT_FILE" ]]; then
            echo "Updating Lovelace dashboard..."
            $VENV "$SETUP_HA" \
                --ha-url "$HA_URL" \
                --mock-port-file "$MOCK_PORT_FILE" \
                --token-file "$WORKTREE_PATH/.ha-token" \
                --skip-onboarding 2>/dev/null || true
        fi
    fi
fi

# --- Entity validation ---
# Check that expected entities exist in HA before wasting time on screenshots

ENTITY_ISSUES=""
if [[ -n "$HA_URL" ]]; then
    HA_TOKEN=$(cat "$WORKTREE_PATH/.ha-token" 2>/dev/null || echo "")
    if [[ -n "$HA_TOKEN" ]]; then
        echo ""
        echo "=== Entity validation ==="

        # Get all wrtmanager entities from HA
        HA_ENTITIES_FILE="$WORKTREE_PATH/.ha-entities.json"
        HTTP_CODE=$(curl -s -o "$HA_ENTITIES_FILE" -w '%{http_code}' -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/states" 2>/dev/null || echo "000")
        if [[ "$HTTP_CODE" != "200" ]]; then
            echo "WARNING: HA API returned $HTTP_CODE (token may be expired). Refreshing token..."
            # Re-run HA setup to get a fresh token
            MOCK_PORT_FILE="$WORKTREE_PATH/.mock-ports.json"
            $VENV "$SETUP_HA" \
                --ha-url "$HA_URL" \
                --mock-port-file "$MOCK_PORT_FILE" \
                --token-file "$WORKTREE_PATH/.ha-token" \
                --skip-onboarding 2>/dev/null || true
            HA_TOKEN=$(cat "$WORKTREE_PATH/.ha-token" 2>/dev/null || echo "")
            HTTP_CODE=$(curl -s -o "$HA_ENTITIES_FILE" -w '%{http_code}' -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/states" 2>/dev/null || echo "000")
        fi
        if [[ "$HTTP_CODE" != "200" ]]; then
            echo "WARNING: Cannot reach HA API (HTTP $HTTP_CODE), skipping entity validation"
            echo "[]" > "$HA_ENTITIES_FILE"
        fi

        ENTITY_ISSUES=$($VENV -c "
import json, sys

with open('$HA_ENTITIES_FILE') as f:
    entities = json.load(f)
wrt = [e for e in entities if 'wrtmanager' in e.get('entity_id', '')]

issues = []
unavailable = [e['entity_id'] for e in wrt if e.get('state') in ('unavailable', 'unknown')]
if unavailable:
    issues.append('Unavailable entities (' + str(len(unavailable)) + '):\n' + '\n'.join(unavailable[:10]))

print('\n'.join(issues) if issues else '')
" 2>/dev/null || echo "")

        # Check what entities the card JS expects vs what HA actually loaded
        ENTITY_CHECK=$($VENV -c "
import json, re, subprocess

with open('$HA_ENTITIES_FILE') as f:
    entities = json.load(f)
wrt_ids = {e['entity_id'] for e in entities if 'wrtmanager' in e.get('entity_id', '')}

card_diff = subprocess.run(
    ['git', '-C', '$WORKTREE_PATH', 'diff', 'main...HEAD', '--',
     'custom_components/wrtmanager/www/wrtmanager-cards.js'],
    capture_output=True, text=True).stdout

# Extract sensor ID suffixes referenced in card JS
card_refs = set(re.findall(r'sensor\.\\\$\{prefix\}_(\w+)', card_diff))
card_refs.update(re.findall(r'sensor\.\$\{prefix\}_(\w+)', card_diff))

if card_refs:
    missing = [s for s in card_refs if not any(eid.endswith('_' + s) for eid in wrt_ids)]
    if missing:
        print(f'Card JS references entities not found in HA: {missing}')
        sensor_ids = sorted(eid.split('.')[-1] for eid in wrt_ids if eid.startswith('sensor.'))
        print(f'Existing wrtmanager sensors: {sensor_ids[:20]}')
" 2>/dev/null || echo "")

        if [[ -n "$ENTITY_ISSUES" ]] || [[ -n "$ENTITY_CHECK" ]]; then
            echo "Entity issues found:"
            [[ -n "$ENTITY_ISSUES" ]] && echo "$ENTITY_ISSUES"
            [[ -n "$ENTITY_CHECK" ]] && echo "$ENTITY_CHECK"

            ENTITY_FEEDBACK="${ENTITY_ISSUES}
${ENTITY_CHECK}"

            # Fix entity issues before taking screenshots
            MAX_ENTITY_ROUNDS=2
            for EROUND in $(seq 1 $MAX_ENTITY_ROUNDS); do
                echo ""
                echo "=== Entity fix round $EROUND/$MAX_ENTITY_ROUNDS ==="

                DIFF_STAT_E=$(git -C "$WORKTREE_PATH" diff main...HEAD --stat 2>/dev/null || echo "")

                ENTITY_FIX_PROMPT=$(cat <<EFEOF
You are fixing entity registration issues for the wrtmanager HA integration.

Working directory: ${WORKTREE_PATH}

## Problem
The following entity issues were detected after loading the integration in HA:

${ENTITY_FEEDBACK}

## Plan context
${PLAN_TEXT}

## Current changes
${DIFF_STAT_E}

## Instructions
1. Read the relevant source files (sensor.py, wrtmanager-cards.js, coordinator.py)
2. Fix the entity ID mismatches or registration issues
3. Run tests: PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
4. Commit: git add <files> && git commit -m "<message>"

Common issues:
- Entity ID suffix in sensor.py doesn't match what card JS looks for
- Sensor not added to async_setup_entry()
- Coordinator doesn't expose the data the sensor reads

Rules:
- Fix ONLY the entity issues listed above
- Follow the plan — do NOT add features not in the plan
- Do NOT use gh, curl, or explore dev/ scripts
- Do NOT push or create a PR
EFEOF
)
                # Code-only tools (same as fix step — no infrastructure)
                E_ALLOWED="Read,Write,Edit,Glob,Grep,Bash(git status:*),Bash(git diff:*),Bash(git log:*),Bash(git add:*),Bash(git commit:*),Bash(git branch:*),Bash(git show:*),Bash(PYTHONPATH=. .venv/bin/python -m pytest:*),Bash(.venv/bin/python -m pytest:*),Bash(.venv/bin/python -m black:*),Bash(.venv/bin/python -m isort:*),Bash(.venv/bin/python -m flake8:*),Bash(ls:*),Bash(tree:*)"

                cd "$WORKTREE_PATH"
                stdbuf -oL claude -p "$ENTITY_FIX_PROMPT" \
                    --model "$MODEL" \
                    --allowedTools "$E_ALLOWED" \
                    --output-format stream-json \
                    --verbose \
                    2>&1 | tee -a "$LOG_FILE"

                # Restart HA and re-check
                echo ""
                echo "=== Restarting HA after entity fix ==="
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

                # Re-check entities
                HA_TOKEN=$(cat "$WORKTREE_PATH/.ha-token" 2>/dev/null || echo "")
                curl -s -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/states" -o "$HA_ENTITIES_FILE" 2>/dev/null
                python3 -c "import json; json.load(open('$HA_ENTITIES_FILE'))" 2>/dev/null || echo "[]" > "$HA_ENTITIES_FILE"
                ENTITY_CHECK=$($VENV -c "
import json, re, subprocess

with open('$HA_ENTITIES_FILE') as f:
    entities = json.load(f)
wrt_ids = {e['entity_id'] for e in entities if 'wrtmanager' in e.get('entity_id', '')}

card_diff = subprocess.run(
    ['git', '-C', '$WORKTREE_PATH', 'diff', 'main...HEAD', '--',
     'custom_components/wrtmanager/www/wrtmanager-cards.js'],
    capture_output=True, text=True).stdout
card_refs = set(re.findall(r'sensor\.\\\$\{prefix\}_(\w+)', card_diff))
card_refs.update(re.findall(r'sensor\.\$\{prefix\}_(\w+)', card_diff))

if card_refs:
    missing = [s for s in card_refs if not any(eid.endswith('_' + s) for eid in wrt_ids)]
    if missing:
        print(f'Still missing: {missing}')
" 2>/dev/null || echo "")

                if [[ -z "$ENTITY_CHECK" ]]; then
                    echo "Entity validation passed"
                    break
                else
                    echo "$ENTITY_CHECK"
                    ENTITY_FEEDBACK="$ENTITY_CHECK"
                fi
            done
        else
            echo "All entities loaded correctly"
        fi
    fi
fi

# --- Smoke test ---

SCREENSHOT_DIR="$WORKTREE_PATH/.test-screenshots"
DIAG_FILE="$WORKTREE_PATH/.diagnostics.txt"

if [[ -n "$HA_URL" ]]; then
    HA_TOKEN=$(cat "$WORKTREE_PATH/.ha-token" 2>/dev/null || echo "")
    if [[ -n "$HA_TOKEN" ]]; then
        # Wait for integration to load and entities to appear
        wait_for_entities "$HA_URL" "$HA_TOKEN" 60
        if ! smoke_test "$HA_URL" "$HA_TOKEN" "$WORKTREE_PATH"; then
            echo ""
            echo "Smoke test failed — capturing diagnostics before screenshots..."
            capture_diagnostics "$HA_URL" "$HA_TOKEN" "$WORKTREE_PATH"
        fi
    fi
fi

# --- Screenshots ---

echo ""
echo "=== Taking screenshots ==="
rm -f "$SCREENSHOT_DIR"/*.png 2>/dev/null || true
"$WORKTREE_PATH/dev/run-tests.sh" \
    --worktree-path "$WORKTREE_PATH" \
    --review-only \
    2>&1 | tee -a "$LOG_FILE" || true

# --- Visual review ---

REVIEW_FILE="$WORKTREE_PATH/.review-result.md"
MAX_REVIEW_ROUNDS=3

for ROUND in $(seq 1 $MAX_REVIEW_ROUNDS); do
    if [[ ! -d "$SCREENSHOT_DIR" ]] || ! ls "$SCREENSHOT_DIR"/*.png &>/dev/null; then
        echo "No screenshots available, skipping visual review"
        break
    fi

    # Resize for review
    REVIEW_SCREENSHOT_DIR="$WORKTREE_PATH/.review-screenshots"
    mkdir -p "$REVIEW_SCREENSHOT_DIR"
    rm -f "$REVIEW_SCREENSHOT_DIR"/*.png
    for img in "$SCREENSHOT_DIR"/*-desktop.png; do
        if [[ -f "$img" ]]; then
            IMG_BASENAME=$(basename "$img")
            if command -v convert &>/dev/null; then
                convert "$img" -resize 800x -quality 85 "$REVIEW_SCREENSHOT_DIR/$IMG_BASENAME" 2>/dev/null || \
                    cp "$img" "$REVIEW_SCREENSHOT_DIR/$IMG_BASENAME"
            else
                cp "$img" "$REVIEW_SCREENSHOT_DIR/$IMG_BASENAME"
            fi
        fi
    done
    REVIEW_SCREENSHOT_COUNT=$(ls "$REVIEW_SCREENSHOT_DIR"/*.png 2>/dev/null | wc -l)

    echo ""
    echo "=== Visual review round $ROUND/$MAX_REVIEW_ROUNDS ($REVIEW_SCREENSHOT_COUNT screenshots) ==="

    DIFF_STAT=$(git -C "$WORKTREE_PATH" diff main...HEAD --stat 2>/dev/null || echo "No diff")
    SCREENSHOT_FILES=$(ls "$REVIEW_SCREENSHOT_DIR"/*.png 2>/dev/null | tr '\n' ' ')

    # Use plan as source of truth (it defines scope and "NOT doing" items)
    # Fall back to issue text if no plan exists
    if [[ -n "$PLAN_TEXT" ]]; then
        REVIEW_CONTEXT="## Implementation Plan
${PLAN_TEXT}"
    else
        REVIEW_CONTEXT="## Issue #${ISSUE_NUMBER}
${ISSUE_TEXT}"
    fi

    # Include diagnostics if available
    DIAG_FOR_REVIEW=""
    if [[ -f "$DIAG_FILE" ]]; then
        DIAG_FOR_REVIEW=$(cat "$DIAG_FILE" 2>/dev/null || echo "")
    fi

    REVIEW_PROMPT=$(cat <<REVIEWEOF
You are a visual reviewer. Compare screenshots against the PLAN below.

IMPORTANT: Only evaluate what the plan says should be done. If the plan has a "NOT doing" section, do NOT fail for those items.

${REVIEW_CONTEXT}

## Code changes
${DIFF_STAT}

## Runtime diagnostics (from HA instance)
${DIAG_FOR_REVIEW:-No diagnostics available.}

## Screenshots to review (${REVIEW_SCREENSHOT_COUNT})
${SCREENSHOT_FILES}

## Instructions
1. Read each screenshot image file
2. Check: do the screenshots show what the plan says should be implemented?
3. Use the diagnostics above to understand what entities/cards HA actually loaded
4. Check design quality (HA native style, CSS variables, units, layout)
5. Write verdict to ${REVIEW_FILE}

First line MUST be: PASS, NEEDS_CHANGES, or FAIL
Then explain specifically what is wrong or missing so a developer can fix it.
Be precise: mention entity IDs, CSS issues, missing UI elements, wrong values.
If diagnostics show entities are unavailable or cards are missing from dashboard, mention this.
Do NOT fix code yourself — only diagnose and write the verdict.
Do NOT fail for items listed as out of scope in the plan.
REVIEWEOF
)

    REVIEW_TOOLS="Read,Write"

    stdbuf -oL claude -p "$REVIEW_PROMPT" \
        --model sonnet \
        --allowedTools "$REVIEW_TOOLS" \
        --output-format stream-json \
        --verbose \
        2>&1 | tee -a "$LOG_FILE"

    if [[ ! -f "$REVIEW_FILE" ]]; then
        echo "Review did not produce a verdict, stopping"
        break
    fi

    VERDICT=$(head -1 "$REVIEW_FILE" | tr -d '[:space:]')
    echo ""
    echo "--- Review verdict: $VERDICT ---"
    cat "$REVIEW_FILE"
    echo "---"

    REVIEW_BODY=$(cat "$REVIEW_FILE")
    CURRENT_DIFF=$(git -C "$WORKTREE_PATH" diff main...HEAD --stat 2>/dev/null || echo "")
    $VENV "$REGISTRY" update "$RUN_ID" \
        --review-verdict "$VERDICT" \
        --review-feedback "$REVIEW_BODY" \
        --diff-stat "$CURRENT_DIFF"

    if [[ "$VERDICT" == "PASS" ]]; then
        echo "Review passed!"
        $VENV "$REGISTRY" update "$RUN_ID" --status pass
        break
    elif [[ "$VERDICT" == "FAIL" ]] || [[ "$VERDICT" == "NEEDS_CHANGES" ]]; then
        if [[ $ROUND -eq $MAX_REVIEW_ROUNDS ]]; then
            echo "Max review rounds reached (verdict: $VERDICT)"
            [[ "$VERDICT" == "FAIL" ]] && $VENV "$REGISTRY" update "$RUN_ID" --status fail
            break
        fi

        # --- Fix step: feed review feedback + diagnostics to Claude ---
        echo ""
        echo "=== Applying fix (round $ROUND, verdict: $VERDICT) ==="

        # Capture diagnostics so fix Claude knows what HA actually loaded
        DIAG_CONTEXT=""
        if [[ -n "$HA_URL" ]]; then
            HA_TOKEN=$(cat "$WORKTREE_PATH/.ha-token" 2>/dev/null || echo "")
            if [[ -n "$HA_TOKEN" ]]; then
                capture_diagnostics "$HA_URL" "$HA_TOKEN" "$WORKTREE_PATH"
                DIAG_CONTEXT=$(cat "$DIAG_FILE" 2>/dev/null || echo "")
            fi
        fi

        DIFF_STAT_FIX=$(git -C "$WORKTREE_PATH" diff main...HEAD --stat 2>/dev/null || echo "")

        FIX_PROMPT=$(cat <<FIXEOF
You are fixing issue #${ISSUE_NUMBER} based on visual review feedback.

Working directory: ${WORKTREE_PATH}

## Plan (source of truth for scope)
${PLAN_TEXT:-No plan available. Use issue context: ${ISSUE_TEXT}}

## Current changes
${DIFF_STAT_FIX}

## Review feedback (verdict: ${VERDICT})
${REVIEW_BODY}

## Runtime diagnostics
These were captured from the running HA instance after loading your code:

${DIAG_CONTEXT:-No diagnostics available.}

## Instructions
1. Read the relevant source files to understand the current state
2. Use the diagnostics above to understand what HA actually loaded vs what was expected
3. Fix the issue described in the review feedback
4. Run tests: PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
5. Commit: git add <files> && git commit -m "<message>"

Rules:
- Focus ONLY on the review feedback — do not add unrelated changes
- Follow the plan scope — do NOT add features marked as "NOT doing"
- Do NOT use gh, curl, or explore dev/ scripts
- Do NOT push or create a PR
- Do NOT mention AI in commit messages
FIXEOF
)

        # Build allowed tools — code-only, no infrastructure
        # The fix step must NOT run mock servers, HA commands, curl, or podman
        # because child processes spawned by claude -p prevent it from exiting.
        FIX_ALLOWED="Read,Write,Edit,Glob,Grep,Bash(git status:*),Bash(git diff:*),Bash(git log:*),Bash(git add:*),Bash(git commit:*),Bash(git branch:*),Bash(git show:*),Bash(PYTHONPATH=. .venv/bin/python -m pytest:*),Bash(.venv/bin/python -m pytest:*),Bash(.venv/bin/python -m black:*),Bash(.venv/bin/python -m isort:*),Bash(.venv/bin/python -m flake8:*),Bash(ls:*),Bash(tree:*)"

        cd "$WORKTREE_PATH"
        stdbuf -oL claude -p "$FIX_PROMPT" \
            --model "$MODEL" \
            --allowedTools "$FIX_ALLOWED" \
            --output-format stream-json \
            --verbose \
            2>&1 | tee -a "$LOG_FILE"

        # Restart HA to pick up fixes
        HA_TOKEN=$(cat "$WORKTREE_PATH/.ha-token" 2>/dev/null || echo "")
        if [[ -n "$HA_URL" ]] && [[ -n "$HA_TOKEN" ]]; then
            echo ""
            echo "=== Restarting HA after fix ==="
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

            # Update Lovelace dashboard to pick up any new cards added since initial setup
            MOCK_PORT_FILE="$WORKTREE_PATH/.mock-ports.json"
            if [[ -f "$MOCK_PORT_FILE" ]]; then
                echo "Updating Lovelace dashboard..."
                $VENV "$SETUP_HA" \
                    --ha-url "$HA_URL" \
                    --mock-port-file "$MOCK_PORT_FILE" \
                    --token-file "$WORKTREE_PATH/.ha-token" \
                    --skip-onboarding 2>/dev/null || true
            fi
        fi

        # Wait for entities + smoke test after fix
        if [[ -n "$HA_URL" ]]; then
            HA_TOKEN=$(cat "$WORKTREE_PATH/.ha-token" 2>/dev/null || echo "")
            if [[ -n "$HA_TOKEN" ]]; then
                wait_for_entities "$HA_URL" "$HA_TOKEN" 60
                smoke_test "$HA_URL" "$HA_TOKEN" "$WORKTREE_PATH" || true
            fi
        fi

        # Re-take screenshots
        echo ""
        echo "=== Re-taking screenshots after fix ==="
        rm -f "$SCREENSHOT_DIR"/*.png 2>/dev/null || true
        "$WORKTREE_PATH/dev/run-tests.sh" \
            --worktree-path "$WORKTREE_PATH" \
            --review-only \
            2>&1 | tee -a "$LOG_FILE" || true
    else
        echo "Unknown verdict '$VERDICT', stopping"
        break
    fi
done

# --- Create PR (only on PASS) ---

REVIEW_VERDICT=$(head -1 "$REVIEW_FILE" 2>/dev/null | tr -d '[:space:]' || echo "N/A")
PR_NUMBER=""

if [[ "$REVIEW_VERDICT" == "PASS" ]]; then
    BRANCH_NAME=$(git -C "$WORKTREE_PATH" branch --show-current)
    echo ""
    echo "=== Creating PR (review passed) ==="

    # Squash all commits into one clean commit and rebase onto main
    COMMIT_COUNT=$(git -C "$WORKTREE_PATH" rev-list main..HEAD --count 2>/dev/null || echo "0")
    if [[ "$COMMIT_COUNT" -gt 1 ]]; then
        echo "Squashing $COMMIT_COUNT commits into one..."
        MERGE_BASE=$(git -C "$WORKTREE_PATH" merge-base main HEAD)
        FIRST_MSG=$(git -C "$WORKTREE_PATH" log --format='%s' --reverse main..HEAD | head -1)
        git -C "$WORKTREE_PATH" reset --soft "$MERGE_BASE"
        git -C "$WORKTREE_PATH" commit --no-verify -m "$FIRST_MSG

Closes #${ISSUE_NUMBER}"
    fi

    # Rebase onto latest main to avoid conflicts
    git -C "$REPO_ROOT" fetch origin main:main 2>/dev/null || true
    if ! git -C "$WORKTREE_PATH" rebase main 2>/dev/null; then
        echo "Rebase conflict — attempting auto-resolve (prefer worktree changes)..."
        # For each conflicted file, prefer the branch version
        git -C "$WORKTREE_PATH" diff --name-only --diff-filter=U | while read -r f; do
            git -C "$WORKTREE_PATH" checkout --theirs "$f"
            git -C "$WORKTREE_PATH" add "$f"
        done
        git -C "$WORKTREE_PATH" rebase --continue 2>/dev/null || git -C "$WORKTREE_PATH" rebase --abort
    fi

    git -C "$WORKTREE_PATH" push -u origin HEAD --force-with-lease 2>&1 || echo "ERROR: Failed to push"

    DIFF_STAT=$(git -C "$WORKTREE_PATH" diff main...HEAD --stat 2>/dev/null || echo "")
    PR_BODY="$(cat <<PRBODYEOF
Fixes #${ISSUE_NUMBER}

## Changes
${DIFF_STAT}

## Test plan
- Unit tests: \`dev/run-tests.sh --worktree-path <path> --unit-only\`
- Browser tests: screenshots in \`.test-screenshots/\`
PRBODYEOF
)"

    PR_URL=$(cd "$WORKTREE_PATH" && gh pr create \
        --title "$ISSUE_TITLE" \
        --body "$PR_BODY" \
        2>&1) && echo "PR created: $PR_URL" || echo "PR creation failed: $PR_URL"

    PR_NUMBER=$(echo "$PR_URL" | grep -oP '/pull/\K[0-9]+' || echo "")

    if [[ -n "$PR_NUMBER" ]]; then
        $VENV "$REGISTRY" update "$RUN_ID" --pr-number "$PR_NUMBER" --pr-url "$PR_URL"

        # Upload screenshots to orphan branch and add PR comment
        SCREENSHOT_DIR="$WORKTREE_PATH/.test-screenshots"
        if ls "$SCREENSHOT_DIR"/*-desktop.png &>/dev/null; then
            echo "Uploading screenshots to PR #$PR_NUMBER..."
            REPO_SLUG=$(cd "$WORKTREE_PATH" && gh repo view --json nameWithOwner -q '.nameWithOwner' 2>/dev/null || echo "")
            if [[ -n "$REPO_SLUG" ]]; then
                SS_TMPDIR=$(mktemp -d)
                git clone --single-branch --branch screenshots \
                    "$(git -C "$WORKTREE_PATH" remote get-url origin)" "$SS_TMPDIR" 2>/dev/null || true
                if [[ -d "$SS_TMPDIR/.git" ]]; then
                    mkdir -p "$SS_TMPDIR/pr-${PR_NUMBER}"
                    cp "$SCREENSHOT_DIR"/*-desktop.png "$SS_TMPDIR/pr-${PR_NUMBER}/"
                    git -C "$SS_TMPDIR" add "pr-${PR_NUMBER}/"
                    git -C "$SS_TMPDIR" commit -m "Add screenshots for PR #${PR_NUMBER}" --no-verify 2>/dev/null || true
                    git -C "$SS_TMPDIR" push 2>/dev/null || true

                    # Build image markdown
                    SS_IMAGES=""
                    for img in "$SS_TMPDIR/pr-${PR_NUMBER}"/*.png; do
                        IMG_NAME=$(basename "$img" .png | sed 's/-desktop$//' | sed 's/-/ /g')
                        IMG_FILE=$(basename "$img")
                        SS_IMAGES+="### ${IMG_NAME}
![${IMG_NAME}](https://raw.githubusercontent.com/${REPO_SLUG}/screenshots/pr-${PR_NUMBER}/${IMG_FILE})

"
                    done

                    REVIEW_BODY=$(cat "$REVIEW_FILE" 2>/dev/null | tail -n +2 || echo "")
                    cd "$WORKTREE_PATH" && gh pr comment "$PR_NUMBER" \
                        --body "$(cat <<SSEOF
## Automated Visual Review: ${REVIEW_VERDICT}

${REVIEW_BODY}

${SS_IMAGES}
SSEOF
)" 2>/dev/null && echo "Review comment with screenshots added to PR" || true
                fi
                rm -rf "$SS_TMPDIR"
            fi
        fi
    fi
else
    echo ""
    echo "=== Skipping PR (review verdict: $REVIEW_VERDICT) ==="
    echo "Fix: dev/sessions.sh feedback $RUN_ID \"<feedback>\" --auto"
fi

echo ""
echo "=========================================="
echo "  Run #${RUN_ID} — Issue #${ISSUE_NUMBER} post-implementation complete"
echo "=========================================="
echo "  Review: ${REVIEW_VERDICT}"
echo "  Screenshots: dev/sessions.sh screenshots $RUN_ID"
echo "  Open HA: dev/sessions.sh open $RUN_ID"
echo "=========================================="
