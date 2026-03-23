#!/bin/bash
# Follow a running work-issue pipeline with human-readable output.
#
# Usage:
#   dev/follow-issue.sh 124

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <issue-number>"
    exit 1
fi

ISSUE="$1"

# Wait briefly for log file to appear (if pipeline just started)
for i in 1 2 3 4 5; do
    LOG_FILE=$(ls -t "$REPO_ROOT/.claude/logs/issue-${ISSUE}"-*.log 2>/dev/null | head -1)
    [[ -n "$LOG_FILE" ]] && break
    sleep 1
done

if [[ -z "$LOG_FILE" ]]; then
    echo "No log file found for issue #${ISSUE}"
    exit 1
fi

echo "Following issue #${ISSUE}: $LOG_FILE"
echo "Press Ctrl+C to stop following (pipeline continues running)"
echo "---"

tail -f "$LOG_FILE" | python3 -u -c "
import sys, json

def shorten(path, max_len=60):
    \"\"\"Shorten file paths for display.\"\"\"
    parts = path.split('/')
    # Remove common prefixes
    for prefix in ['.claude/worktrees/', 'custom_components/wrtmanager/']:
        if prefix in path:
            idx = path.index(prefix) + len(prefix)
            return '...' + path[idx:]
    if len(path) > max_len:
        return '...' + path[-(max_len-3):]
    return path

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue

    # Try to parse as stream-json
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        # Not JSON - show only meaningful status lines, skip noise
        if len(line) > 200:
            continue
        # Skip data lines (tokens, hashes, JSON fragments, paths)
        if line.startswith(('TOKEN=', 'eyJ', '{', '}', '  \"', '45ff', 'Next:')):
            continue
        # Show stage markers and important status
        if line.startswith('===') or 'INFO:' in line or line.startswith('Launching') or 'ready' in line.lower() or 'error' in line.lower() or line.startswith('>>>'):
            print(line)
            sys.stdout.flush()
        continue

    msg_type = obj.get('type', '')

    if msg_type == 'system':
        subtype = obj.get('subtype', '')
        if subtype == 'init':
            model = obj.get('model', '?')
            print(f'[INIT] Model: {model}')

    elif msg_type == 'assistant':
        content = obj.get('message', {}).get('content', [])
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get('type', '')

            if block_type == 'text':
                text = block.get('text', '')
                if text.strip():
                    print(text)

            elif block_type == 'tool_use':
                tool = block.get('name', '?')
                inp = block.get('input', {})
                if tool == 'Read':
                    path = shorten(inp.get('file_path', '?'))
                    print(f'  >> Read {path}')
                elif tool == 'Write':
                    path = shorten(inp.get('file_path', '?'))
                    print(f'  >> Write {path}')
                elif tool == 'Edit':
                    path = shorten(inp.get('file_path', '?'))
                    print(f'  >> Edit {path}')
                elif tool == 'Glob':
                    print(f'  >> Glob {inp.get(\"pattern\", \"?\")}')
                elif tool == 'Grep':
                    print(f'  >> Grep \"{inp.get(\"pattern\", \"?\")}\"')
                elif tool == 'Bash':
                    cmd = inp.get('command', '?')
                    # Show first meaningful line only
                    cmd = cmd.split(chr(10))[0].strip()
                    if len(cmd) > 100:
                        cmd = cmd[:100] + '...'
                    print(f'  >> \$ {cmd}')
                elif tool == 'ToolSearch':
                    pass  # Skip noise
                elif tool == 'TodoWrite':
                    todos = inp.get('todos', [])
                    active = [t for t in todos if t.get('status') == 'in_progress']
                    if active:
                        print(f'  >> Task: {active[0].get(\"content\", \"?\")}')
                else:
                    print(f'  >> {tool}')

            elif block_type == 'thinking':
                # Show first line of thinking as status
                thought = block.get('thinking', '')
                if thought:
                    first_line = thought.split(chr(10))[0][:80]
                    print(f'  .. {first_line}')

    # Skip 'user' (tool results) and 'result' types - too noisy

    sys.stdout.flush()
"
