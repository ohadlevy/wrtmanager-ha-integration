# WrtManager - Home Assistant Integration Project Plan

## Project Overview
**Name:** WrtManager
**Domain:** `wrtmanager`
**Repository:** `wrtmanager-ha-integration`
**Focus:** OpenWrt network management (not just monitoring) with VLAN organization, device control, and future management capabilities

## Key Research Findings

### Naming Decision
- **PROBLEM:** "openwrt" domain is already taken by official HA integrations (`ubus` and `luci`)
- **SOLUTION:** Chose "WrtManager" to emphasize management capabilities (not just monitoring)
- **Domain:** `wrtmanager` (lowercase, HA compliant)

### Market Reality (Being Honest)
- **Existing OpenWRT HA users:** ~600-700 people across all integrations
- **Realistic Year 1 targets:**
  - Month 3: 20-40 early adopters
  - Month 6: 50-100 active users
  - Month 12: 100-200 users (exceptional success for this niche)
- **Key differentiator:** VLAN organization, enterprise roaming support, and management capabilities

### Existing Competition
- Official HA integrations: `ubus` (100 users), `luci` (522 users)
- Custom HACS: `kvj/hass_openwrt` (159 GitHub stars), others
- **Our advantage:** Superior VLAN management + roaming device handling + comprehensive device organization

## Network Architecture Understanding

### Target Network Topology
- **IEEE 802.11r (Fast BSS Transition)** - seamless roaming between access points
- **Ethernet-connected APs** - distributed AP setup, not wireless mesh
- **Same SSIDs across all APs** - devices roam seamlessly between locations
- **Multiple SSIDs mapped to VLANs** - network segmentation (Main, IoT, Guest)
- **VLAN trunking** - consistent VLAN configuration across all APs
- **Non-WiFi devices on VLANs** - wired devices must be tracked too

### Roaming Device Challenges
Most existing OpenWrt integrations don't handle enterprise-style roaming well:
- **Device "movement"** - same device appears on different routers as it roams
- **Signal overlap** - device may be visible to multiple APs simultaneously
- **Identity consistency** - device keeps same IP/VLAN during roaming
- **Historical tracking** - need to track roaming patterns over time

## Technical Foundation

### Current Working Tools
From previous development, we have these working components:
- **HTTP ubus authentication:** Working setup script and validation
- **Enhanced WiFi scanner:** Multi-router parallel data collection
- **Device identification:** MAC OUI database integration
- **VLAN detection:** Multi-VLAN network topology understanding

### Integration Architecture
- **Data source:** HTTP ubus API (no SSH required)
- **Authentication:** Dedicated `hass` user with limited permissions
- **Data collection:** iwinfo + DHCP + ARP correlation
- **Update pattern:** DataUpdateCoordinator for efficient polling
- **UI:** Config flow (no YAML configuration)
- **Roaming handling:** Device correlation across multiple APs

## Implementation Plan

### Phase 1: Project Foundation (Week 1-2)
- [x] Create git repository structure
- [x] Initialize basic directory structure
- [ ] Create manifest.json and integration skeleton
- [ ] Set up testing framework
- [ ] Create documentation structure

### Phase 2: Core Integration Development (Week 3-6)
- [ ] Config flow for router setup
- [ ] DataUpdateCoordinator implementation
- [ ] HTTP ubus client library
- [ ] Basic device entities (binary_sensors for presence)
- [ ] **Roaming device correlation logic**
- [ ] Error handling and logging

### Phase 3: VLAN Management & Enhanced Features (Week 7-10)
- [ ] VLAN-based device organization
- [ ] SSID to VLAN mapping and auto-discovery
- [ ] Advanced device entities (signal, rates, etc.)
- [ ] **Roaming pattern tracking**
- [ ] **Best signal AP detection**
- [ ] Device registry integration
- [ ] Performance optimization for multi-AP setups

### Phase 4: Polish & Release (Week 11-12)
- [ ] Complete documentation
- [ ] HACS submission preparation
- [ ] Community announcement
- [ ] v1.0.0 release

## Future Management Features (Post v1.0)
- Device disconnection/blocking
- Guest network management
- Device approval workflows
- VLAN reassignment
- **Firmware lifecycle tracking and notifications**
- Roaming optimization insights
- Network performance analytics

## Key Technical Decisions

### Integration Structure
```
custom_components/wrtmanager/
├── __init__.py              # Integration setup
├── manifest.json            # Integration metadata
├── config_flow.py          # UI configuration
├── const.py                # Constants
├── coordinator.py          # Data update coordinator
├── ubus_client.py          # HTTP ubus communication
├── device_manager.py       # Device tracking and roaming correlation
├── vlan_manager.py         # VLAN organization and SSID mapping
├── binary_sensor.py        # Device presence sensors
├── sensor.py               # Signal strength, roaming stats, etc.
└── translations/           # UI translations
    └── en.json
```

### Roaming Device Handling
**Challenge:** Same device appears on multiple routers during roaming
**Solution:**
1. **Device Identity:** Use MAC address as primary key
2. **Signal Aggregation:** Track signal strength from all APs
3. **Primary AP Logic:** Determine "best connected" AP based on signal/association
4. **State Management:** Single HA device entity that updates as device roams
5. **Historical Data:** Track roaming patterns and AP preferences

### Data Flow
1. **Discovery:** User enters router details via config flow
2. **Authentication:** Establish ubus session with `hass` user on each AP
3. **Data Collection:** Parallel collection from multiple routers
   - iwinfo (WiFi device associations)
   - DHCP (IP assignments and hostnames) - from main router
   - ARP (multi-VLAN device visibility)
4. **Device Correlation:** Merge same devices seen on multiple APs
5. **Signal Analysis:** Determine primary AP and roaming status
6. **VLAN Organization:** Group devices by network segment
7. **Entities:** Create HA entities for device tracking and roaming info

### Security Model
- Dedicated `hass` user on each OpenWrt router
- Limited ACL permissions (read-only for most operations)
- HTTP (not SSH) for better security isolation
- Session management with automatic reconnection
- Firmware update persistence (requires further research)

## Success Metrics

### Technical Goals
- Support 5+ AP network without performance impact
- <2 second update cycles for device state changes
- >95% device identification success rate
- Accurate roaming detection and tracking
- Zero configuration after initial setup

### Community Goals (Realistic)
- 50+ users by month 6
- Active GitHub issue/PR engagement
- HACS store listing
- Forum recognition as superior OpenWrt solution
- **Differentiation:** "The only HA integration that handles enterprise roaming properly"

## Risk Mitigation

### Technical Risks
- **ubus API changes:** Use version detection and fallbacks
- **Performance on large networks:** Implement efficient polling and caching
- **Router firmware compatibility:** Support multiple OpenWrt versions
- **Roaming detection accuracy:** Implement robust signal-based logic
- **Firmware updates:** Research config persistence mechanisms

### Community Risks
- **Small market:** Focus on quality over quantity
- **Existing solutions:** Emphasize unique roaming + VLAN management features
- **Maintenance burden:** Design for minimal ongoing maintenance

## Research Items (Future Investigation)
- [ ] OpenWrt config persistence across firmware updates
- [ ] Post-firmware-flash checklist and automation
- [ ] Firmware lifecycle tracking and notification mechanisms
- [ ] IEEE 802.11r roaming optimization insights
- [ ] VLAN trunk configuration validation across APs

## Open Source Principles
- Zero hardcoded personal network details
- Comprehensive documentation for contributors
- MIT license for maximum adoption
- Community-friendly contribution guidelines
- Transparent development process

---

*Last updated: 2024-11-17*
*Context: This preserves our research and decisions to prevent loss during development*
*Network: IEEE 802.11r roaming setup with ethernet-connected APs and VLAN segmentation*