#!/bin/bash
# Analyze a completed pipeline run and suggest improvements.
#
# Parses the log to find:
# - Wasted effort (repeated reads, failed commands, permission denials)
# - Missing docs (files Claude read but aren't referenced in CLAUDE.md)
# - Tool patterns to whitelist
# - Common mistakes to document as rules
#
# Usage:
#   dev/analyze-run.sh 124                    # Analyze latest run for issue
#   dev/analyze-run.sh 124 --apply            # Apply suggestions automatically
#   dev/analyze-run.sh --log path/to/log      # Analyze specific log file

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ISSUE=""
LOG_FILE=""
APPLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --log) LOG_FILE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        [0-9]*) ISSUE="$1"; shift ;;
        *) echo "Usage: $0 <issue-number> [--apply] [--log path]"; exit 1 ;;
    esac
done

if [[ -z "$LOG_FILE" ]] && [[ -n "$ISSUE" ]]; then
    LOG_FILE=$(ls -t "$REPO_ROOT/.claude/logs/issue-${ISSUE}"-*.log 2>/dev/null | head -1)
fi

if [[ -z "$LOG_FILE" ]] || [[ ! -f "$LOG_FILE" ]]; then
    echo "No log file found"
    exit 1
fi

echo "=== Analyzing: $LOG_FILE ==="
echo ""

python3 -u -c "
import json, sys, os
from collections import Counter, defaultdict

log_file = '$LOG_FILE'
repo_root = '$REPO_ROOT'

with open(log_file) as f:
    lines = f.readlines()

# Collect metrics
file_reads = Counter()
file_edits = Counter()
bash_commands = []
failed_commands = []
permission_denials = []
grep_searches = []
repeated_reads = []
tool_calls = Counter()
total_input_tokens = 0
total_output_tokens = 0
total_cache_read = 0
total_cache_create = 0
msg_count = 0
screenshot_reads = 0

for line in lines:
    line = line.strip()
    if not line:
        continue
    try:
        obj = json.loads(line)
    except:
        # Check non-JSON lines for denials
        if 'denied' in line.lower() or 'not allowed' in line.lower():
            permission_denials.append(line[:150])
        continue

    msg_type = obj.get('type', '')

    if msg_type == 'assistant':
        usage = obj.get('message', {}).get('usage', {})
        total_input_tokens += usage.get('input_tokens', 0)
        total_output_tokens += usage.get('output_tokens', 0)
        total_cache_read += usage.get('cache_read_input_tokens', 0)
        total_cache_create += usage.get('cache_creation_input_tokens', 0)
        msg_count += 1

        content = obj.get('message', {}).get('content', [])
        for block in content:
            if not isinstance(block, dict) or block.get('type') != 'tool_use':
                continue
            tool = block.get('name', '?')
            inp = block.get('input', {})
            tool_calls[tool] += 1

            if tool == 'Read':
                path = inp.get('file_path', '')
                short = path.replace(repo_root + '/', '')
                file_reads[short] += 1
                if '.png' in path:
                    screenshot_reads += 1
            elif tool == 'Edit':
                path = inp.get('file_path', '')
                short = path.replace(repo_root + '/', '')
                file_edits[short] += 1
            elif tool == 'Bash':
                cmd = inp.get('command', '')
                bash_commands.append(cmd[:200])
            elif tool == 'Grep':
                grep_searches.append(inp.get('pattern', '')[:80])

    elif msg_type == 'result':
        result = str(obj.get('result', ''))
        if 'error' in result.lower()[:100] or 'denied' in result.lower()[:100]:
            failed_commands.append(result[:150])

# Analysis
print('=' * 60)
print('METRICS')
print('=' * 60)
print(f'Messages:         {msg_count}')
print(f'Tool calls:       {sum(tool_calls.values())}')
print(f'  Read:           {tool_calls.get(\"Read\", 0)} ({screenshot_reads} screenshots)')
print(f'  Edit:           {tool_calls.get(\"Edit\", 0)}')
print(f'  Write:          {tool_calls.get(\"Write\", 0)}')
print(f'  Bash:           {tool_calls.get(\"Bash\", 0)}')
print(f'  Grep:           {tool_calls.get(\"Grep\", 0)}')
print(f'  Glob:           {tool_calls.get(\"Glob\", 0)}')
print(f'Input tokens:     {total_input_tokens:,}')
print(f'Output tokens:    {total_output_tokens:,}')
print(f'Cache created:    {total_cache_create:,}')
print(f'Cache read:       {total_cache_read:,}')
input_cost = (total_input_tokens + total_cache_create) * 3.0 / 1_000_000
cache_cost = total_cache_read * 0.30 / 1_000_000
output_cost = total_output_tokens * 15.0 / 1_000_000
total_cost = input_cost + cache_cost + output_cost
print(f'Est. cost:        \${total_cost:.2f} (Sonnet pricing)')
print()

# Repeated file reads (waste)
print('=' * 60)
print('REPEATED FILE READS (potential waste)')
print('=' * 60)
for path, count in file_reads.most_common(10):
    if count > 1:
        print(f'  {count}x  {path}')
print()

# Files read most (should be in CLAUDE.md?)
print('=' * 60)
print('MOST-READ FILES (consider referencing in CLAUDE.md)')
print('=' * 60)
for path, count in file_reads.most_common(15):
    if '.png' not in path:
        print(f'  {count}x  {path}')
print()

# Bash commands (what's Claude running?)
print('=' * 60)
print(f'BASH COMMANDS ({len(bash_commands)} total)')
print('=' * 60)
cmd_types = Counter()
for cmd in bash_commands:
    if cmd.startswith('git '):
        cmd_types['git'] += 1
    elif cmd.startswith('gh '):
        cmd_types['gh'] += 1
    elif cmd.startswith('ls') or cmd.startswith('find'):
        cmd_types['ls/find (exploration)'] += 1
    elif cmd.startswith('cat'):
        cmd_types['cat (should use Read)'] += 1
    elif cmd.startswith('grep'):
        cmd_types['grep (should use Grep)'] += 1
    elif cmd.startswith('curl'):
        cmd_types['curl'] += 1
    elif 'pytest' in cmd:
        cmd_types['pytest'] += 1
    elif 'run-tests' in cmd:
        cmd_types['run-tests'] += 1
    elif cmd.startswith('sed') or cmd.startswith('awk'):
        cmd_types['sed/awk (should use Edit)'] += 1
    else:
        cmd_types['other'] += 1
for typ, count in cmd_types.most_common():
    print(f'  {count:3d}  {typ}')
print()

# Failed/error commands
if failed_commands:
    print('=' * 60)
    print(f'ERRORS/FAILURES ({len(failed_commands)})')
    print('=' * 60)
    for cmd in failed_commands[:10]:
        print(f'  {cmd[:120]}')
    print()

# Permission denials
if permission_denials:
    print('=' * 60)
    print(f'PERMISSION DENIALS ({len(permission_denials)})')
    print('=' * 60)
    for d in permission_denials[:10]:
        print(f'  {d}')
    print()

# Suggestions
print('=' * 60)
print('SUGGESTIONS')
print('=' * 60)
suggestions = []

cat_count = cmd_types.get('cat (should use Read)', 0)
grep_count = cmd_types.get('grep (should use Grep)', 0)
sed_count = cmd_types.get('sed/awk (should use Edit)', 0)
ls_count = cmd_types.get('ls/find (exploration)', 0)

if cat_count > 0:
    suggestions.append(f'Add to CLAUDE.md: \"Use Read tool instead of cat/head/tail\" ({cat_count} violations)')
if grep_count > 0:
    suggestions.append(f'Add to CLAUDE.md: \"Use Grep tool instead of grep/rg\" ({grep_count} violations)')
if sed_count > 0:
    suggestions.append(f'Add to CLAUDE.md: \"Use Edit tool instead of sed/awk\" ({sed_count} violations)')
if ls_count > 5:
    suggestions.append(f'Add to CLAUDE.md: \"Use Glob tool instead of ls/find\" ({ls_count} exploration commands)')

repeated = [(p, c) for p, c in file_reads.most_common(5) if c > 2 and '.png' not in p]
if repeated:
    files = ', '.join(p.split('/')[-1] for p, _ in repeated)
    suggestions.append(f'Add key file summaries to CLAUDE.md to reduce re-reads: {files}')

if screenshot_reads > 10:
    suggestions.append(f'Reduce screenshots sent to reviewer ({screenshot_reads} read, consider desktop-only)')

if msg_count > 100:
    suggestions.append(f'Too many turns ({msg_count}). Add more context to CLAUDE.md to reduce exploration.')

curl_count = cmd_types.get('curl', 0)
if curl_count > 2:
    suggestions.append(f'Claude tested servers manually ({curl_count} curl calls). Add mock server docs to CLAUDE.md.')

if not suggestions:
    suggestions.append('No major issues found!')

for i, s in enumerate(suggestions, 1):
    print(f'  {i}. {s}')
print()
"
