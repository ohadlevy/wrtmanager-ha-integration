# SSID Management Card Guide

This guide explains the WrtManager SSID Management feature, which shows all WiFi networks across your routers in a single card and adds per-router SSID pills to the Router Health card.

## What the card shows

### WiFi Networks card (`custom:wifi-networks-card`)

A global table of every SSID visible to WrtManager, with one row per network:

- **Status dot** — green (enabled on all routers), yellow (mixed), red (disabled everywhere)
- **SSID name** — with per-router enabled/disabled chips below
- **Frequency bands** — blue `2.4` chip and/or purple `5GHz` chip
- **Security** — WPA3 / WPA2 / WPA / Open (Open shown in red as a warning)
- **Hidden** — eye-off icon if the SSID is hidden, dash otherwise
- **Devices** — live count of connected clients on this SSID

### Router Health card SSID pills

The existing `custom:router-health-card` now shows small pills at the bottom of each router tile listing all SSIDs active on that router. Each pill shows the SSID name, band summary (`2.4+5`, `2.4`, `5GHz`), and connected device count. Disabled SSIDs appear strikethrough and dimmed.

## Available SSID binary sensor attributes

The `binary_sensor.global_<ssid_name>` entities expose these attributes:

| Attribute | Description |
|-----------|-------------|
| `ssid_name` | Network name (SSID) |
| `frequency_bands` | List of bands: `["2.4GHz", "5GHz"]` |
| `encryption` | Encryption type: `sae-mixed`, `sae`, `psk2`, `psk`, `none` |
| `hidden` | `true` if the SSID is hidden (not broadcast) |
| `enabled_routers` | List of router names where this SSID is enabled |
| `disabled_routers` | List of router names where this SSID is disabled |
| `connected_devices` | Count of currently connected clients across all radios |
| `coverage` | Always `"Global (all routers)"` for global SSID sensors |

## Dashboard YAML

```yaml
- type: custom:wifi-networks-card
```

No configuration needed — the card auto-discovers all global SSID sensors.

## Troubleshooting

### No SSIDs visible in the card

- **Dump AP mode**: Routers in dump/dumb AP mode cannot expose wireless status via ubus. Only routers running as a full OpenWrt router (with ubus accessible) show SSIDs. Check the HA logs for "No wireless SSID data available".
- **Integration not connected**: Verify the WrtManager integration is configured and routers are reachable.
- **ubus ACL**: Error `-32002` in HA logs means ubus access is denied. The router's ACL must allow the WrtManager user to call `network.wireless.status`.

### Device count shows 0

Connected device counts come from `iwinfo.assoclist` (the WiFi association list). If a router is in dump AP mode, association data may not be available. Counts only include currently associated WiFi clients, not wired devices.

### Router Health pills not showing

Pills appear only when global SSID sensors exist for the same router name. The router name used for matching comes from the HA device registry. If you rename a router device in HA, the pills will update automatically.
