# WrtManager - Home Assistant Integration

A comprehensive Home Assistant integration for managing OpenWrt networks with multi-AP roaming detection, network topology visualization, and custom Lovelace cards.

## Features

### Network Management
- **Multi-Router Support**: Monitor and manage multiple OpenWrt access points and routers
- **Network Organization**: Automatically organize devices by OpenWrt network name
- **IEEE 802.11r Roaming**: Intelligent roaming detection for enterprise wireless setups
- **Real-time Device Tracking**: Binary sensors for device presence with rich attributes
- **WiFi Client Disconnect**: Disconnect devices from specific APs via button entities

### Device Intelligence
- **MAC OUI Identification**: Automatic device type detection using vendor databases
- **Device Correlation**: Merge WiFi, DHCP, and ARP data for complete device visibility
- **Signal Quality Monitoring**: Track signal strength and connection quality
- **Historical Tracking**: Monitor device roaming patterns and connection history

### Custom Lovelace Cards
- **Network Devices**: Devices grouped by AP with search, signal bars, and disconnect action
- **Router Health**: Memory, temperature, traffic, and device count per router
- **Network Topology**: Visual radial layout with signal quality color coding
- **Signal Heatmap**: Signal strength list with quality filtering
- **Roaming Activity**: Live roaming event log tracking AP changes in real time

### Security & Performance
- **HTTP ubus API**: Secure communication without SSH access required
- **Dedicated Authentication**: Uses limited-privilege `hass` user account
- **Parallel Data Collection**: Efficient scanning across multiple routers
- **Automatic Reconnection**: Robust session management and error recovery

## Prerequisites

### OpenWrt Router Requirements
- OpenWrt 21.02+ (recommended)
- `uhttpd-mod-ubus` package installed
- `rpcd` package installed (usually pre-installed)

### Home Assistant Requirements
- Home Assistant 2025.11.0+
- HACS (for easy installation)

## Installation

### Step 1: Setup OpenWrt Routers

Configure each of your OpenWrt routers from a Linux machine with SSH root access:

```bash
# Download the setup script once on your Linux machine
wget https://raw.githubusercontent.com/ohadlevy/wrtmanager-ha-integration/main/scripts/setup_openwrt_ha_integration.sh
chmod +x setup_openwrt_ha_integration.sh

# Run it for each router (provide router IP and hass user password)
./setup_openwrt_ha_integration.sh 192.168.1.1 MySecurePassword123
./setup_openwrt_ha_integration.sh 192.168.1.10 MySecurePassword123
# ... repeat for each router

# Alternative: Let the script prompt for password
./setup_openwrt_ha_integration.sh 192.168.1.1
# (script will ask: "Enter password for 'hass' user:")
```

**Requirements:**
- Linux machine with SSH access to your routers
- Root SSH access to each OpenWrt router
- Internet access on routers for package installation

This script will:
- Install required packages (`uhttpd-mod-ubus`, `rpcd`)
- Create a dedicated `hass` user with limited permissions
- Configure ACL permissions for ubus access
- Set up secure authentication

### Step 2: Install Integration via HACS

**Note**: WrtManager is currently available as a custom repository in HACS while we prepare for official submission.

#### Option A: HACS Custom Repository (Current)
1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the **three dots (⋮)** in the top right corner
4. Select **"Custom repositories"**
5. Add repository URL: `https://github.com/ohadlevy/wrtmanager-ha-integration`
6. Set Category: **"Integration"**
7. Click **"Add"**
8. **Restart Home Assistant** (required for custom repository detection)
9. Return to HACS → Integrations
10. Search for **"WrtManager"** and click **"Download"**
11. **Restart Home Assistant** again after installation

#### Option B: Official HACS Repository (Coming Soon)
Once submitted to the official HACS repository, you'll be able to find WrtManager directly in the HACS integration list without adding a custom repository.

### Step 3: Configure Integration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for **WrtManager**
4. Enter your router details:
   - **Host**: Router IP address or hostname
   - **Name**: Friendly name (e.g., "Main Router")
   - **Username**: `hass` (default)
   - **Password**: Password you set during router setup
5. Repeat for additional routers in your network

## Network Architecture Support

WrtManager is designed for modern network setups including:

### Multi-AP Networks
- **IEEE 802.11r Fast Roaming**: Seamless device handoff between access points
- **Ethernet Backhaul**: Connected APs with consistent SSID mapping
- **Mesh Networks**: Support for wireless mesh configurations

### Network Segmentation
- Devices are organized by their OpenWrt network name (e.g., `lan`, `guest`, `iot`)
- Network names are automatically detected from the router configuration

### Device Types
Automatically identifies and categorizes:
- Mobile devices (phones, tablets)
- IoT switches and sensors
- Home appliances
- Network equipment
- Computers and servers
- Smart speakers
- Robot vacuums
- And more...

## Entities Created

### Binary Sensors
- **Device Presence**: `binary_sensor.{device_name}_presence`
  - State: Connected/Disconnected
  - Attributes: IP, MAC, vendor, signal strength, network, roaming info

### Sensors
- **System Monitoring**: Router uptime, memory usage, CPU usage, load average (1m/5m/15m), temperature
- **Network Statistics**: Device counts per network and interface, signal strength per interface
- **Router Traffic**: Comprehensive network traffic monitoring with breakdown by interface type
- **SSID Status**: Binary sensors for SSID enabled/disabled state per router/area

#### Router Traffic Sensor
- **Entity**: `sensor.{router_name}_total_traffic`
- **Function**: Aggregates traffic data from all router interfaces for comprehensive network monitoring
- **Unit**: Megabytes (MB) - cumulative totals since last router reboot
- **Documentation**: See [Router Traffic Card Guide](docs/router-traffic-card.md) for detailed usage instructions
- **Attributes**:
  - Total traffic breakdown: `total_download_mb`, `total_upload_mb`
  - WAN/Internet traffic: `wan_download_mb`, `wan_upload_mb`, `wan_total_mb`
  - WiFi traffic: `wifi_download_mb`, `wifi_upload_mb`, `wifi_total_mb`
  - Ethernet traffic: `ethernet_download_mb`, `ethernet_upload_mb`, `ethernet_total_mb`
  - Other interfaces traffic: `other_download_mb`, `other_upload_mb`, `other_total_mb`
  - Interface counts: `wan_interfaces`, `wifi_interfaces`, `ethernet_interfaces`, `other_interfaces`, `total_interfaces`
  - Connected devices: `total_devices`, `wifi_devices`, `ethernet_devices`
  - Router information: `router_name`, `router_host`

### Buttons
- **Disconnect**: `button.{device_name}_disconnect_from_{router_name}` — Disconnect a WiFi client from a specific AP

## Configuration

### Adding Additional Routers (Optional)

**Single Router Setup**: The integration works perfectly with just one router - this covers most home setups.

**Multiple Router Setup**: If you have multiple OpenWrt routers or access points that you want to monitor:

1. **After setting up your first router** (following the steps above)
2. **To add more routers**:
   - Go to **Settings** → **Devices & Services**
   - Find your existing **WrtManager** integration
   - Click **Configure**
   - Select **Add another router**
   - Enter the additional router's details

**Benefits of Multiple Router Monitoring**:
- Devices automatically merge across routers (one device entity even if it moves between APs)
- Track roaming patterns in mesh/multi-AP setups
- Monitor different network segments (main router + guest AP, etc.)

## Custom Lovelace Cards

WrtManager ships with 5 custom Lovelace cards that auto-register on integration setup. All cards auto-discover your routers and devices from the HA device registry — no manual entity configuration needed.

| Card | Description |
|------|-------------|
| `custom:network-devices-card` | WiFi devices grouped by AP with search, signal bars, cross-integration badges, and disconnect action |
| `custom:router-health-card` | Router health overview — memory, CPU usage, load average, temperature, traffic, device count per router |
| `custom:network-topology-card` | Visual radial network topology with signal quality color coding |
| `custom:signal-heatmap-card` | Signal strength list with quality filter chips (Poor/Fair/Good/Excellent) |
| `custom:roaming-activity-card` | Active roamers and live roaming event log tracking AP changes in real time |

### Quick Start

Add cards to any dashboard — zero config required:

```yaml
views:
  - title: Network
    cards:
      - type: custom:network-devices-card
      - type: custom:router-health-card
      - type: custom:signal-heatmap-card
      - type: custom:roaming-activity-card

  - title: Topology
    panel: true
    cards:
      - type: custom:network-topology-card
```

### Card Options

```yaml
# Network Devices — optional overrides
type: custom:network-devices-card
show_offline: true
ap_order:
  - 192.168.1.1
  - 192.168.1.2
network_labels:
  lan: "Main LAN"
  guest: "Guest"

# Router Health — optional role labels
type: custom:router-health-card
router_roles:
  192.168.1.1: "Main Router"
  192.168.1.2: "AP - Bedroom"

# Roaming Activity — custom log size
type: custom:roaming-activity-card
max_log_entries: 50
```

### Full Dashboard Example

See [`examples/dashboard.yaml`](examples/dashboard.yaml) for a complete dashboard with all custom cards and traffic monitoring.

## Troubleshooting

### Connection Issues

**Authentication Failed**
```bash
# Verify hass user exists on router
ssh root@router "grep hass /etc/passwd"

# Check ACL permissions
ssh root@router "cat /usr/share/rpcd/acl.d/hass.json"
```

**Cannot Connect**
```bash
# Test HTTP ubus endpoint
curl -X POST http://router/ubus \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"call","params":["00000000000000000000000000000000","session","login",{"username":"hass","password":"your_password"}]}'
```

### Debug Logging

Enable debug logging in Home Assistant:

```yaml
logger:
  default: info
  logs:
    custom_components.wrtmanager: debug
```

### Common Issues

1. **No devices found**: Check that wireless interfaces are active and have connected devices
2. **DHCP data missing**: Ensure main router is configured as DHCP server
3. **Roaming not detected**: Verify IEEE 802.11r is enabled and working
4. **Firmware compatibility**: Some OpenWrt versions may have different ubus interfaces

## Development

**Want to contribute?** See [CONTRIBUTING.md](CONTRIBUTING.md) for complete development setup, testing guidelines, and contribution workflow.

Quick start for developers:
```bash
./dev-setup.sh  # Sets up everything automatically
make help       # See all available commands
```

## Roadmap

### v1.0 - Complete User Experience (In Progress)
- [x] Advanced sensor entities (signal strength, roaming counts)
- [x] Pre-built Lovelace cards (5 custom cards bundled with integration)
- [x] Network topology visualization
- [x] Device disconnection
- [ ] Performance analytics and monitoring

### v1.1 - Enhanced Management
- [ ] Guest network management
- [ ] Bandwidth monitoring per device

### v1.2 - Automation Features
- [ ] Device approval workflows
- [ ] New device notifications

### v1.3 - Advanced Analytics
- [ ] Performance analytics dashboard
- [ ] Firmware update notifications

## Support

- **Documentation**: [GitHub Wiki](https://github.com/ohadlevy/wrtmanager-ha-integration/wiki)
- **Issues**: [GitHub Issues](https://github.com/ohadlevy/wrtmanager-ha-integration/issues)
- **Discussions**: [Home Assistant Community](https://community.home-assistant.io/)

## License

MIT License - see [LICENSE](LICENSE) for details.

## Credits

- Built for the Home Assistant community
- Inspired by existing OpenWrt integrations
- MAC OUI database provided by [nmap project](https://nmap.org/)
- Special thanks to OpenWrt developers for the excellent ubus API

---

**Note**: This integration focuses on comprehensive network management rather than basic device tracking. If you just need simple router monitoring, consider the built-in OpenWrt integrations (`ubus`, `luci`).