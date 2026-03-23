#!/bin/bash
# HA container lifecycle management for E2E testing.
# Supports per-worktree isolation via unique container names and ports.
#
# Usage:
#   dev/ha-env.sh start [--worktree-path /path] [--ha-port 18123] [--mock-port-file /path/ports.json]
#   dev/ha-env.sh stop  [--worktree-path /path]
#   dev/ha-env.sh status [--worktree-path /path]
#   dev/ha-env.sh logs [--worktree-path /path] [--follow]
#   dev/ha-env.sh clean [--worktree-path /path]  # stop + remove config

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_HA_PORT=18123
HA_BASE_IMAGE="ghcr.io/home-assistant/home-assistant:stable"
HA_SNAPSHOT_IMAGE="localhost/ha-wrt-onboarded:latest"

# Use snapshot if available (pre-onboarded, saves ~15s)
if podman image exists "$HA_SNAPSHOT_IMAGE" 2>/dev/null; then
    HA_IMAGE="$HA_SNAPSHOT_IMAGE"
else
    HA_IMAGE="$HA_BASE_IMAGE"
fi

# --- Helpers ---

usage() {
    echo "Usage: $0 {start|stop|status|logs|clean} [options]"
    echo ""
    echo "Options:"
    echo "  --worktree-path PATH    Path to worktree (default: repo root)"
    echo "  --ha-port PORT          HA port (default: auto-assigned from worktree hash)"
    echo "  --mock-port-file FILE   Path to mock server port mapping JSON"
    echo "  --follow                Follow logs (for 'logs' command)"
    exit 1
}

# Generate a deterministic port from a path (range 18100-18899)
port_from_path() {
    local path="$1"
    local hash
    hash=$(echo -n "$path" | md5sum | head -c 8)
    local num=$((16#$hash % 800 + 18100))
    echo "$num"
}

# Generate container name from worktree path
container_name_from_path() {
    local path="$1"
    local basename
    basename=$(basename "$path")
    # Sanitize for container naming
    echo "ha-wrt-test-${basename//[^a-zA-Z0-9_-]/-}"
}

# --- Config template ---

create_ha_config() {
    local config_dir="$1"
    local mock_port_file="$2"

    mkdir -p "$config_dir"

    # Base configuration.yaml
    cat > "$config_dir/configuration.yaml" <<'YAML'
default_config:

frontend:
  themes: !include_dir_merge_named themes

lovelace:
  mode: storage

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

logger:
  default: info
  logs:
    custom_components.wrtmanager: debug
    custom_components.wrtmanager.coordinator: debug
    custom_components.wrtmanager.binary_sensor: debug
    custom_components.wrtmanager.sensor: debug
    custom_components.wrtmanager.ubus_client: debug
YAML

    # Create required include files
    echo "[]" > "$config_dir/automations.yaml"
    echo "" > "$config_dir/scripts.yaml"
    echo "" > "$config_dir/scenes.yaml"
    mkdir -p "$config_dir/themes"

    echo "HA config created at $config_dir"
}

# --- Commands ---

cmd_start() {
    local worktree_path="$REPO_ROOT"
    local ha_port=""
    local mock_port_file=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --worktree-path) worktree_path="$2"; shift 2 ;;
            --ha-port) ha_port="$2"; shift 2 ;;
            --mock-port-file) mock_port_file="$2"; shift 2 ;;
            *) echo "Unknown option: $1"; usage ;;
        esac
    done

    # Resolve absolute path
    worktree_path="$(cd "$worktree_path" && pwd)"

    # Auto-assign port if not specified
    if [[ -z "$ha_port" ]]; then
        ha_port=$(port_from_path "$worktree_path")
    fi

    local container_name
    container_name=$(container_name_from_path "$worktree_path")
    local config_dir="$worktree_path/.ha-test-config"
    local state_file="$worktree_path/.ha-test-state.json"

    # Check if already running
    if podman ps --format '{{.Names}}' 2>/dev/null | grep -q "^${container_name}$"; then
        echo "Container $container_name is already running on port $ha_port"
        echo "Use '$0 stop' first, or '$0 status' to check"
        return 0
    fi

    # Remove any stopped container with same name
    podman rm "$container_name" 2>/dev/null || true

    # Create config if it doesn't exist
    if [[ ! -f "$config_dir/configuration.yaml" ]]; then
        create_ha_config "$config_dir" "$mock_port_file"
    fi

    echo "Starting HA container: $container_name"
    echo "  Worktree: $worktree_path"
    echo "  HA port: $ha_port"
    echo "  Config: $config_dir"
    echo "  Custom components: $worktree_path/custom_components"

    # Use bridge networking with port mapping so multiple instances can coexist.
    # --add-host=host.containers.internal:host-gateway lets the container reach
    # mock ubus servers running on the host.
    podman run -d \
        --name "$container_name" \
        -p "${ha_port}:8123" \
        -v "$config_dir:/config:Z" \
        -v "$worktree_path/custom_components:/config/custom_components:Z" \
        -v /etc/localtime:/etc/localtime:ro \
        -e TZ=UTC \
        --add-host=host.containers.internal:host-gateway \
        "$HA_IMAGE"

    # Wait for HA to be ready (HA takes ~30-60s to initialize)
    echo "Waiting for HA to start..."
    local max_wait=180
    local waited=0
    while [[ $waited -lt $max_wait ]]; do
        if curl -s -o /dev/null -w '%{http_code}' "http://localhost:${ha_port}/api/" 2>/dev/null | grep -qE '(200|401|403)'; then
            echo "HA is ready at http://localhost:${ha_port}"
            break
        fi
        sleep 3
        waited=$((waited + 3))
        if (( waited % 15 == 0 )); then
            echo "  Still waiting... (${waited}s)"
        fi
    done

    if [[ $waited -ge $max_wait ]]; then
        echo "ERROR: HA did not start within ${max_wait}s"
        echo "Check logs: $0 logs --worktree-path $worktree_path"
        return 1
    fi

    # Save state for other scripts
    cat > "$state_file" <<EOF
{
  "container_name": "$container_name",
  "ha_port": $ha_port,
  "worktree_path": "$worktree_path",
  "config_dir": "$config_dir",
  "ha_url": "http://localhost:$ha_port",
  "mock_port_file": "${mock_port_file:-}"
}
EOF

    echo "State saved to $state_file"
    echo ""
    echo "HA running at http://localhost:${ha_port}"
    echo "Next: run 'dev/setup-ha.py --state-file $state_file' to configure the integration"
}

cmd_stop() {
    local worktree_path="$REPO_ROOT"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --worktree-path) worktree_path="$2"; shift 2 ;;
            *) echo "Unknown option: $1"; usage ;;
        esac
    done

    worktree_path="$(cd "$worktree_path" && pwd)"
    local container_name
    container_name=$(container_name_from_path "$worktree_path")

    if podman ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${container_name}$"; then
        echo "Stopping container: $container_name"
        podman stop "$container_name" 2>/dev/null || true
        podman rm "$container_name" 2>/dev/null || true
        echo "Container stopped and removed"
    else
        echo "No container found: $container_name"
    fi
}

cmd_status() {
    local worktree_path="$REPO_ROOT"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --worktree-path) worktree_path="$2"; shift 2 ;;
            *) echo "Unknown option: $1"; usage ;;
        esac
    done

    worktree_path="$(cd "$worktree_path" && pwd)"
    local container_name
    container_name=$(container_name_from_path "$worktree_path")
    local state_file="$worktree_path/.ha-test-state.json"

    if podman ps --format '{{.Names}}' 2>/dev/null | grep -q "^${container_name}$"; then
        echo "RUNNING"
        if [[ -f "$state_file" ]]; then
            cat "$state_file"
        fi
    elif podman ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${container_name}$"; then
        echo "STOPPED"
    else
        echo "NOT_FOUND"
    fi
}

cmd_logs() {
    local worktree_path="$REPO_ROOT"
    local follow=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --worktree-path) worktree_path="$2"; shift 2 ;;
            --follow) follow="-f"; shift ;;
            *) echo "Unknown option: $1"; usage ;;
        esac
    done

    worktree_path="$(cd "$worktree_path" && pwd)"
    local container_name
    container_name=$(container_name_from_path "$worktree_path")

    podman logs $follow "$container_name"
}

cmd_clean() {
    local worktree_path="$REPO_ROOT"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --worktree-path) worktree_path="$2"; shift 2 ;;
            *) echo "Unknown option: $1"; usage ;;
        esac
    done

    worktree_path="$(cd "$worktree_path" && pwd)"

    cmd_stop --worktree-path "$worktree_path"

    local config_dir="$worktree_path/.ha-test-config"
    local state_file="$worktree_path/.ha-test-state.json"

    if [[ -d "$config_dir" ]]; then
        echo "Removing config: $config_dir"
        rm -rf "$config_dir"
    fi
    rm -f "$state_file"
    echo "Cleaned up"
}

# --- Main ---

if [[ $# -lt 1 ]]; then
    usage
fi

command="$1"
shift

case "$command" in
    start)  cmd_start "$@" ;;
    stop)   cmd_stop "$@" ;;
    status) cmd_status "$@" ;;
    logs)   cmd_logs "$@" ;;
    clean)  cmd_clean "$@" ;;
    *)      echo "Unknown command: $command"; usage ;;
esac
