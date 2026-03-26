# Wired Client Detection

WrtManager tracks wired (Ethernet) clients by querying `luci-rpc.getHostHints`
from the main/DHCP router, complementing WiFi detection from the assoclist.

## What it catches

| Source              | What is visible                              |
|---------------------|----------------------------------------------|
| WiFi assoclist      | Devices actively associated with an AP       |
| DHCP leases         | Devices that received an IP via DHCP         |
| getHostHints (ARP)  | All of the above + static-IP-only devices    |

Devices with manually configured static IPs (servers, IoT hubs, NAS) never
appear in DHCP leases but are visible via ARP as soon as they communicate.

## Security model

`luci-rpc.getHostHints` is a structured dnsmasq query — no file system access.
`rpcd-mod-file` is not installed or used by WrtManager.

## Network/VLAN assignment

The `getHostHints` response includes IP but not bridge interface. Network segment
is derived by matching the device IP against known subnets from
`network.interface dump` (collected each poll cycle). This correctly handles
all common VLAN setups where each segment uses a distinct subnet.

## Hostname resolution

| `data_source` attribute | Hostname source                                    |
|------------------------|-----------------------------------------------------|
| `static_dhcp`          | Name from DHCP static reservation (most reliable)  |
| `dynamic_dhcp`         | Hostname sent in DHCP request                      |
| `live_arp`             | dnsmasq name (may be empty for pure static-IP)     |

## Only reads from the main router

`getHostHints` is only called on the DHCP server (main router). As the network
gateway, it sees all clients across all VLANs in its dnsmasq host table.
Dump APs are not queried for the client list.

## Prerequisites

- `luci-rpc` package on the main router (same requirement as DHCP lease tracking)
- `getHostHints` permission in ACL — added by the setup script automatically

Re-run the setup script to update ACL on existing installations:

    ./setup_openwrt_ha_integration.sh <main-router-ip>

## Troubleshooting

**Wired devices not appearing**
- Verify luci-rpc is available: the DHCP lease tracking should also be working
- Enable debug logging: `custom_components.wrtmanager: debug` in logger config
- Check HA logs for "host hints: 0 entries" — indicates getHostHints returned empty

**Device shows unexpected network name**
- Check `network.interface dump` on router: `ubus call network.interface dump`
- Confirm subnets are distinct per VLAN (overlapping subnets are not supported)

**Device disappears intermittently**
- dnsmasq removes ARP entries after inactivity — normal for idle devices
- The device reappears automatically when it next communicates
