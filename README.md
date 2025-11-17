# WrtManager - Home Assistant Integration

A comprehensive Home Assistant integration for managing OpenWrt networks with advanced features like VLAN organization, roaming detection, and device management.

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

First, configure each of your OpenWrt routers to allow Home Assistant access:

```bash
# Download and run the setup script on each router
wget https://raw.githubusercontent.com/ohadlevy/wrtmanager-ha-integration/main/scripts/setup_openwrt_ha_integration.sh
chmod +x setup_openwrt_ha_integration.sh
./setup_openwrt_ha_integration.sh
```

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

### Sensors (Future)
- **Signal Strength**: Real-time signal quality monitoring
- **Roaming Count**: Track device movement between APs
- **Network Summary**: Overall network statistics

### Device Tracker (Future)
- **Location Tracking**: Determine which AP/area device is connected to
- **Presence Detection**: Enhanced presence with location context

## Configuration

### Router Setup Options

The integration supports multiple authentication methods:

```yaml
# Example router configuration
routers:
  main_router:
    host: "192.168.1.1"
    username: "hass"
    password: "secure_password"
    description: "Main Router"

  living_room_ap:
    host: "192.168.1.10"
    username: "hass"
    password: "secure_password"
    description: "Living Room AP"
```

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

### Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Testing

```bash
# Install development dependencies
pip install -r requirements_dev.txt

# Run tests
pytest tests/

# Run with coverage
pytest tests/ --cov=custom_components.wrtmanager
```

### Debugging

Use the validation script to test router connectivity:

```bash
# Test all routers in your configuration
cd tools/
ruby validate_http_ubus.rb ../config/router_config.yml
```

## Roadmap

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