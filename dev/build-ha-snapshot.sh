#!/bin/bash
# Build a pre-onboarded HA container image for fast E2E startup.
#
# This creates a "golden" image with HA already onboarded (user created,
# core config set). The wrtmanager integration is NOT pre-configured
# because mock server ports vary per worktree.
#
# Usage:
#   dev/build-ha-snapshot.sh              # Build snapshot image
#   dev/build-ha-snapshot.sh --force      # Rebuild even if exists
#
# The snapshot is used automatically by ha-env.sh if available.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAPSHOT_IMAGE="localhost/ha-wrt-onboarded:latest"
BASE_IMAGE="ghcr.io/home-assistant/home-assistant:stable"
TEMP_CONTAINER="ha-wrt-snapshot-builder"
TEMP_PORT=18999

FORCE=false
if [[ "${1:-}" == "--force" ]]; then
    FORCE=true
fi

# Check if snapshot already exists
if [[ "$FORCE" != true ]] && podman image exists "$SNAPSHOT_IMAGE" 2>/dev/null; then
    echo "Snapshot image already exists: $SNAPSHOT_IMAGE"
    echo "Use --force to rebuild"
    exit 0
fi

echo "=== Building pre-onboarded HA snapshot ==="

# Clean up any previous attempt
podman rm -f "$TEMP_CONTAINER" 2>/dev/null || true

# Start a temporary HA container
echo "Starting temporary HA container..."
podman run -d \
    --name "$TEMP_CONTAINER" \
    -p "$TEMP_PORT:8123" \
    "$BASE_IMAGE"

# Wait for HA to start
echo "Waiting for HA to start..."
for i in $(seq 1 60); do
    if curl -s -o /dev/null "http://localhost:$TEMP_PORT/api/onboarding" 2>/dev/null; then
        echo "HA is ready"
        break
    fi
    if [[ $i -eq 60 ]]; then
        echo "ERROR: HA did not start in time"
        podman rm -f "$TEMP_CONTAINER"
        exit 1
    fi
    sleep 2
done

# Run onboarding only (no integration setup - ports vary per worktree)
echo "Running onboarding..."
python3 "$SCRIPT_DIR/setup-ha.py" \
    --ha-url "http://localhost:$TEMP_PORT" \
    --router-hosts "placeholder:9999" \
    --skip-onboarding 2>/dev/null || true

# Actually onboard
python3 -c "
from dev.setup_ha import wait_for_ha, onboard_ha
wait_for_ha('http://localhost:$TEMP_PORT', timeout=30)
token = onboard_ha('http://localhost:$TEMP_PORT')
print(f'Onboarding complete, token: {token[:20]}...' if token else 'Onboarding failed')
" 2>/dev/null || {
    # Fallback: use setup-ha.py with dummy routers, it will fail on integration but onboarding succeeds
    python3 "$SCRIPT_DIR/setup-ha.py" \
        --ha-url "http://localhost:$TEMP_PORT" \
        --router-hosts "localhost:9999" 2>&1 | grep -v "Failed to add" || true
}

# Stop HA cleanly
echo "Stopping HA for snapshot..."
podman stop "$TEMP_CONTAINER"

# Commit the container as a new image
echo "Creating snapshot image..."
podman commit "$TEMP_CONTAINER" "$SNAPSHOT_IMAGE"

# Clean up
podman rm "$TEMP_CONTAINER"

echo ""
echo "=== Snapshot ready: $SNAPSHOT_IMAGE ==="
echo "HA containers will start pre-onboarded (saves ~15s per worktree)"
