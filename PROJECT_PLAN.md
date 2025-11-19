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

### Phase 1: Project Foundation (Week 1-2) ✅ COMPLETED
- [x] Create git repository structure
- [x] Initialize basic directory structure
- [x] Create manifest.json and integration skeleton
- [x] Set up testing framework (dev environment with HA container)
- [x] Create documentation structure

### Phase 2: Core Integration Development (Week 3-6) ✅ MOSTLY COMPLETED
- [x] Config flow for router setup
- [x] DataUpdateCoordinator implementation
- [x] HTTP ubus client library
- [x] Basic device entities (binary_sensors for presence)
- [x] **Roaming device correlation logic**
- [x] Error handling and logging
- [x] Multi-router parallel data collection
- [x] Device identification with MAC OUI database
- [x] System monitoring sensors (uptime, memory, load, temperature)

### Phase 3: VLAN Management & Enhanced Features (Week 7-10) ✅ COMPLETED
- [x] VLAN-based device organization (working in HA)
- [x] Advanced device entities (signal, rates, device counts) (working in HA)
- [x] **Roaming pattern tracking** (working in HA)
- [x] **Best signal AP detection** (working in HA)
- [x] Device registry integration (working in HA)
- [x] Performance optimization for multi-AP setups (working in HA)
- [x] VLAN customization UI (options flow) (working in HA)
- [x] Enhanced device naming and vendor identification (working in HA)
- [x] Interface status monitoring (network interfaces binary sensors) (working in HA)
- [x] **SSID Discovery & Auto-Detection** ✅ **WORKING** - Comprehensive wireless status parsing
- [x] **SSID Binary Sensors with Smart Consolidation** ✅ **WORKING** - Multi-band SSIDs unified into single entities
- [x] **Per-Interface Device Counting** ✅ **WORKING** - Device counts per wireless interface/SSID

### Phase 4: Polish & Release (Week 11-12)
- [ ] Complete documentation
- [ ] HACS submission preparation
- [ ] Community announcement
- [ ] v1.0.0 release

## Current Focus: Testing & Validation

### Phase 1: Integration Testing & Quality Assurance
- [ ] **Add comprehensive Home Assistant integration tests**
  - [ ] Test SSID discovery and parsing logic
  - [ ] Test binary sensor entity creation and state updates
  - [ ] Test import error handling and dependency management
  - [ ] Test coordinator data flow and error scenarios
- [ ] **Add SSID consolidation validation tests**
  - [ ] Test multi-radio SSID consolidation logic
  - [ ] Test frequency band detection and naming
  - [ ] Test consolidated vs single-radio SSID attributes
  - [ ] Test SSID binary sensor functionality with real data
- [ ] **Validate SSID binary sensor functionality in Home Assistant**
  - [ ] Test SSID enable/disable state detection
  - [ ] Verify consolidated SSID entity naming and attributes
  - [ ] Test error handling for wireless status parsing failures

#### Phase 2: SSID Monitoring & Analytics
- [ ] **SSID performance monitoring**
  - [ ] Signal quality statistics per SSID
  - [ ] Connection/disconnection event tracking
  - [ ] Peak usage time analytics
  - [ ] Device roaming patterns between SSIDs
- [ ] **Real-time SSID events**
  - [ ] New device connections to specific SSIDs
  - [ ] SSID enable/disable notifications
  - [ ] Unusual activity alerts (mass connections, etc.)

#### Phase 3: SSID Management Services
- [ ] **SSID control services** (Post SSID monitoring working)
  - [ ] Enable/disable SSID service calls
  - [ ] Temporary SSID activation (guest access)
  - [ ] SSID configuration validation
- [ ] **Guest network automation**
  - [ ] Automatic guest SSID activation/deactivation
  - [ ] Time-based guest access scheduling
  - [ ] Guest device approval workflows

#### Phase 4: Advanced SSID Features
- [ ] **SSID-based device management**
  - [ ] Block/unblock devices per SSID
  - [ ] Move devices between SSIDs/VLANs
  - [ ] Device access history by SSID
- [ ] **SSID optimization**
  - [ ] Load balancing recommendations
  - [ ] Optimal SSID placement analysis
  - [ ] Interference detection and mitigation

### Technical Implementation Notes

#### Current Architecture
```
Physical Radios (radio0, radio1)
  ↓ iwinfo (working)
Virtual SSID Interfaces (ap0, ap1, ap2...)
  ↓ network.wireless.status (working - comprehensive SSID data extraction)
Network Interfaces (wlan0, wlan1...)
  ↓ network.interface (working)
Connected Devices per Interface
  ↓ iwinfo assoclist (working)
SSID Consolidation Logic
  ↓ Multi-band SSIDs unified into single entities
```

#### SSID Management Implementation Status
- **SSID Discovery**: ✅ Working - Handles both list and dict interface formats
- **SSID Consolidation**: ✅ Working - Same SSID names across multiple radios are unified
- **Binary Sensors**: ✅ Working - SSID enabled/disabled state monitoring
- **Device Counting**: ✅ Working - Per-interface device count sensors
- **Error Handling**: ✅ Working - Graceful handling of dump AP mode and permission issues

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