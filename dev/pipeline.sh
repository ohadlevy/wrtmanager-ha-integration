#!/bin/bash
# Pipeline CLI wrapper
# Usage: dev/pipeline.sh run 131
#        dev/pipeline.sh resume 116 -v
#        dev/pipeline.sh resume 116 --from review
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
exec env PYTHONPATH="$REPO_ROOT" "$REPO_ROOT/.venv/bin/python" -m dev.pipeline "$@"
