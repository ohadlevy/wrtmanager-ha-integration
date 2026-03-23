# WrtManager HA Integration

## Rules
- Do not mention AI/Claude in commit messages
- ALWAYS use git worktrees for all work (never commit directly to main)
- Use `gh` CLI for PRs, issues, and all GitHub operations
- Every change MUST have tests
- Pre-commit hooks run automatically: black, isort, flake8, pylint, pytest

## Tool Usage (saves tokens and time)
- Use `Read` tool to read files — NEVER use `cat`, `head`, `tail`, or `sed` via Bash
- Use `Grep` tool to search file contents — NEVER use `grep` or `rg` via Bash
- Use `Glob` tool to find files — NEVER use `find` or `ls` via Bash
- Use `Edit` tool to modify files — NEVER use `sed` or `awk` via Bash
- Do NOT manually test mock servers with `curl` — they are pre-configured and tested
- Do NOT explore `dev/` scripts to understand infrastructure — it is already set up for you
- Read a file ONCE, do not re-read the same file multiple times

## Autonomous Issue Pipeline

### Quick start: work on an issue
```bash
dev/sessions.sh run <issue-number>
dev/sessions.sh run 42 --model claude-opus-4-6   # for complex issues
dev/sessions.sh run 42 -f                        # run + follow live output
```

This runs the full pipeline autonomously:
1. Creates git worktree + branch from main
2. Starts mock ubus servers + HA container + configures integration + creates dashboard
3. **Plan**: reads codebase, writes `.plan.md` (files, UI, data flow, tests)
4. **Execute**: implements the plan, writes tests, commits
5. **Code review**: catches unnecessary changes, bloat, style issues
6. HA restarts to load code changes
7. **Visual review loop** (up to 3 rounds): screenshots compared against issue + design principles
8. PR created only on PASS; use `dev/sessions.sh cancel/feedback` to intervene

### Review the result
- **Auto-review**: verdict (PASS/NEEDS_CHANGES/FAIL) printed at the end, saved to `.review-result.md`
- **Browser**: open the HA URL printed at the end (login: wrt / wrt-test-123)
- **Screenshots**: `.claude/worktrees/<branch>/.test-screenshots/` (desktop/mobile/tablet)
- **Interactive**: `cd .claude/worktrees/<branch> && claude`

### Run tests
```bash
# Unit tests (fast, no infra needed)
dev/run-tests.sh --worktree-path <worktree> --unit-only

# Unit + lint
dev/run-tests.sh --worktree-path <worktree> --unit-only --lint

# Full: unit + E2E API + Playwright browser tests (needs running env)
dev/run-tests.sh --worktree-path <worktree>

# Nuclear: spin up fresh env, test everything, teardown
dev/run-tests.sh --worktree-path <worktree> --full
```

### Manage sessions
All commands use the **run ID** (shown when pipeline starts and in `list` output):
```bash
dev/sessions.sh list                    # All runs with status
dev/sessions.sh list --status fail      # Failed runs only
dev/sessions.sh show <run-id>           # Full run details (JSON)
dev/sessions.sh screenshots <run-id>    # View screenshots
dev/sessions.sh open <run-id>           # Open HA dashboard
dev/sessions.sh logs <run-id>           # Show log file
dev/sessions.sh feedback <run-id> "msg"  # Give feedback, apply fix
dev/sessions.sh feedback <run-id> "msg" --auto  # Fix + restart HA + re-screenshot
dev/sessions.sh resume <run-id>         # Resume failed run interactively
dev/sessions.sh resume <run-id> --auto  # Resume non-interactively
dev/sessions.sh teardown <run-id>       # Clean up environment
```

### Parallel issues
```bash
dev/work-issue.sh 42 &
dev/work-issue.sh 43 &
```
Each gets its own worktree, mock servers, and HA container on unique ports.

### Follow progress
```bash
dev/follow-issue.sh <issue-number>    # Human-readable live output
dev/work-issue.sh <issue> -f          # Run + auto-follow
```

## Autonomous Issue Workflow (for Claude)

When given a GitHub issue number, follow this pipeline:

### 1. Setup
```bash
dev/setup-worktree.sh <issue-number> [--branch-prefix fix|feature|chore]
```
Creates worktree, starts mock ubus servers, starts HA container, configures integration + dashboard. Output is JSON with all connection details.

### 2. Understand
- `gh issue view <number>` - read the issue fully
- Read ALL referenced files before coding
- If ambiguous, ask for clarification BEFORE coding
- Check for related open PRs: `gh pr list`

### 3. Implement
- Work inside the worktree (path from setup output)
- Make minimal, focused changes
- Follow existing code patterns

### 4. Test
```bash
dev/run-tests.sh --worktree-path <worktree> --unit-only
```

### 5. Submit
- Commit with clear message (the "why", not the "what")
- Do NOT push or create a PR — the pipeline handles that after visual review

## Test Infrastructure (`dev/`)

> **IMPORTANT**: When running inside `work-issue.sh`, the test infrastructure is ALREADY
> set up for you. Do NOT read, explore, or test `dev/` scripts. Just use `dev/run-tests.sh`.

| Script | Purpose |
|--------|---------|
| `dev/work-issue.sh <issue>` | Full autonomous pipeline: setup + claude + review |
| `dev/sessions.sh list\|resume\|open` | Manage runs: list, resume failed, open dashboard |
| `dev/setup-worktree.sh <issue>` | Create worktree + start mock servers + HA container |
| `dev/teardown-worktree.sh <path>` | Stop everything, clean up |
| `dev/run-tests.sh` | Run unit tests, E2E tests, browser tests |
| `dev/analyze-run.sh <issue>` | Post-run analysis: token usage, waste, suggestions |
| `dev/follow-issue.sh <issue>` | Human-readable log viewer for running pipelines |
| `dev/registry.py` | SQLite run registry (backing store for sessions.sh) |
| `dev/build-ha-snapshot.sh` | Build pre-onboarded HA image (run once) |
| `dev/mock_ubus_server.py` | Mock OpenWrt ubus JSON-RPC server (multi-router) |
| `dev/ha-env.sh start\|stop\|status\|logs` | HA container lifecycle (podman) |
| `dev/setup-ha.py` | HA onboarding + integration + dashboard setup |
| `dev/scenarios/default.json` | 3-router scenario with roaming + time events |

### Mock server details (DO NOT test manually with curl)
The mock servers simulate 3 OpenWrt routers with:
- `system.info` → uptime, memory, load averages (`load` array: fixed-point ÷65536)
- `iwinfo.assoclist` → connected WiFi clients per interface
- `network.wireless.status` → SSIDs and radio config
- `luci-rpc.getDHCPLeases` → DHCP leases (main router only, `is_dhcp_server: true`)
- `file.read` → `/proc/stat` for CPU usage
- `hostapd.*.del_client` → disconnect a WiFi client
- Time events simulate roaming, connect/disconnect after startup

### Browser tests (Playwright)
Browser tests run in a container (`mcr.microsoft.com/playwright`), no local npm install needed.
They authenticate via HA's login_flow API, navigate the dashboard, and take screenshots
across desktop (1920x1080), mobile (iPhone 14), and tablet (iPad) viewports.

Screenshots are saved to `<worktree>/.test-screenshots/`.

### Running tests manually
```bash
# Unit tests only (no infra needed)
PYTHONPATH=. .venv/bin/python -m pytest tests/ -v

# Start mock server standalone
.venv/bin/python dev/mock_ubus_server.py --scenario dev/scenarios/default.json --base-port 18001

# HA container for a worktree
dev/ha-env.sh start --worktree-path .claude/worktrees/my-branch --ha-port 18200
dev/ha-env.sh logs --worktree-path .claude/worktrees/my-branch --follow
dev/ha-env.sh stop --worktree-path .claude/worktrees/my-branch
```

## What Requires Manual Testing (flag in PR)
- Changes to `custom_components/wrtmanager/www/wrtmanager-cards.js` - Lovelace cards
- Changes to config_flow.py UI behavior
- New entity types (verify they appear correctly in HA)

Browser tests capture screenshots for review but can't validate visual correctness.

## Card Design Principles
When implementing or modifying Lovelace cards (`www/wrtmanager-cards.js`), follow these:

### Visual consistency
- Match Home Assistant's native card style (ha-card, --ha-card-border-radius, etc.)
- Use HA CSS variables for colors: `--primary-color`, `--secondary-text-color`, `--divider-color`
- Never hardcode colors — always use CSS variables so cards work with all HA themes (dark/light)
- Card padding: 16px. Section spacing: 12px. Inner element gaps: 8px.

### Data visualization
- Gauges: use color coding (green < 60%, yellow 60-85%, red > 85%)
- Numbers: right-align numeric values, left-align labels
- Units: always show units (%, MB, dBm) next to values
- Empty state: show "No data" or "Waiting..." — never show blank/empty cards
- Loading state: show a spinner or skeleton, never a blank card

### Layout
- Cards must work at all widths (HA dashboard columns vary 300-800px)
- Use CSS Grid or Flexbox with `flex-wrap` — never fixed widths
- Mobile: stack vertically, no horizontal scroll
- Tables/lists: use alternating row backgrounds for readability
- Max items visible: ~10-15 rows, then "Show more" or scrollable with max-height

### Typography
- Card title: 16px, `--primary-text-color`
- Section headers: 14px, `--secondary-text-color`, uppercase optional
- Data values: 14px monospace for numbers, proportional for text
- Small labels: 12px, `--secondary-text-color`

### Icons
- Use Material Design Icons (mdi:*) — HA's built-in icon set
- Device types: mdi:cellphone, mdi:laptop, mdi:speaker, mdi:router-wireless
- Status: mdi:check-circle (ok), mdi:alert (warning), mdi:close-circle (error)
- Signal: mdi:wifi-strength-1 through mdi:wifi-strength-4

## Architecture
```
custom_components/wrtmanager/
  __init__.py          - Integration setup + Lovelace card registration
  config_flow.py       - Configuration UI flow
  const.py             - Constants
  coordinator.py       - DataUpdateCoordinator, multi-router parallel polling
  ubus_client.py       - HTTP ubus JSON-RPC client
  binary_sensor.py     - Device presence, interface status, SSID monitoring
  sensor.py            - System/network monitoring sensors
  button.py            - WiFi client disconnect buttons
  device_manager.py    - MAC OUI vendor identification
  diagnostics.py       - HA diagnostics
  www/                 - Lovelace custom cards (JS)
```

Data flow: `ubus_client (HTTP/JSON-RPC) -> coordinator (poll/aggregate) -> entities`

## Key Technical Notes
- ubus response `[0]` = success with no data (NOT an error)
- ubus error `-32002` = Access denied (router ACL issue)
- Multi-AP: coordinator polls all routers in parallel
- Roaming: same MAC on different AP = device roamed
- Unique IDs use MAC-only format for presence sensors
- Test command: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -v`
- Mock scenario uses fake MACs and 192.168.1.x IPs (no real data)
- Test credentials: wrt / wrt-test-123 (HA test instance only)
