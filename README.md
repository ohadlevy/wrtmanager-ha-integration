# WrtManager - Home Assistant Integration

A comprehensive Home Assistant integration for managing OpenWrt networks with advanced features like VLAN organization, roaming detection, and device management.

> **Current Status (v0.8):** Core functionality is stable and working. Device presence tracking, SSID monitoring, and multi-router support are fully functional. Dashboard templates and advanced sensors are in development for v1.0.

## Features

### 🏠 Network Management
- **Multi-Router Support**: Monitor and manage multiple OpenWrt access points and routers
- **VLAN Organization**: Automatically organize devices by network segment (Main, IoT, Guest)
- **IEEE 802.11r Roaming**: Intelligent roaming detection for enterprise wireless setups
- **Real-time Device Tracking**: Binary sensors for device presence with rich attributes

### 🔍 Device Intelligence
- **MAC OUI Identification**: Automatic device type detection using vendor databases
- **Device Correlation**: Merge WiFi, DHCP, and ARP data for complete device visibility
- **Signal Quality Monitoring**: Track signal strength and connection quality
- **Historical Tracking**: Monitor device roaming patterns and connection history

### 🛡️ Security & Performance
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
- Home Assistant 2023.1+
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

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots in the top right
4. Select "Custom repositories"
5. Add repository URL: `https://github.com/ohadlevy/wrtmanager-ha-integration`
6. Category: "Integration"
7. Click "Add"
8. Search for "WrtManager" and install

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
- **Ethernet Backhaul**: Connected APs with consistent SSID/VLAN mapping
- **Mesh Networks**: Support for wireless mesh configurations

### VLAN Segmentation
- **Main Network** (VLAN 1): Primary devices, full access
- **IoT Network** (VLAN 3): Smart home devices, limited access
- **Guest Network** (VLAN 13): Visitor access, isolated
- **Custom VLANs**: Support for additional network segments

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
  - Attributes: IP, MAC, vendor, signal strength, VLAN, roaming info

### Sensors
- **System Monitoring**: Router uptime, memory usage, load average, temperature
- **Network Statistics**: Device counts per VLAN and interface
- **SSID Status**: Binary sensors for SSID enabled/disabled state per router/area

### Future Sensors (v1.0+)
- **Signal Strength**: Real-time signal quality monitoring (currently available as attributes)
- **Roaming Count**: Track device movement between APs
- **Network Summary**: Overall network statistics and performance metrics
- **Device Tracker**: Location-based presence detection

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

### VLAN Mapping

Automatic VLAN detection based on IP ranges:
- `192.168.1.x` → Main Network (VLAN 1)
- `192.168.5.x` → IoT Network (VLAN 3)
- `192.168.13.x` → Guest Network (VLAN 13)

Custom VLAN mappings can be configured in the integration options.

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
- [ ] Advanced sensor entities (signal strength, roaming counts)
- [ ] Pre-built Lovelace dashboards
- [ ] Network topology visualization
- [ ] Performance analytics and monitoring

### v1.1 - Enhanced Management
- [ ] Device disconnection/blocking
- [ ] Guest network management
- [ ] Bandwidth monitoring per device

### v1.2 - Automation Features
- [ ] Device approval workflows
- [ ] New device notifications
- [ ] VLAN assignment automation

### v1.3 - Advanced Analytics
- [ ] Network topology mapping
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