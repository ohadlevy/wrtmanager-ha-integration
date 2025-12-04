# Router Traffic Card Guide

This guide explains how to use the WrtManager Router Traffic Card feature (implemented in GitHub issue #87) to monitor your network traffic in Home Assistant.

## What is the Router Traffic Card?

The Router Traffic Card is a comprehensive sensor that aggregates traffic data from all interfaces on your OpenWrt router, providing a unified view of your network activity. This sensor was designed to address the need for a simple, informative card similar to router admin interfaces.

## Sensor Information

**Entity Name**: `sensor.wrtmanager_{router_name}_router_traffic_total`

**State Value**: Total network traffic across all interfaces (in MB)

**Device Class**: Data Size

**State Class**: Total Increasing (for tracking cumulative totals)

## Available Attributes

The sensor provides detailed traffic breakdown through these attributes:

### Total Traffic
- `total_download_mb` - Total downloaded data across all interfaces
- `total_upload_mb` - Total uploaded data across all interfaces

### Interface Type Breakdown
- `wan_download_mb` / `wan_upload_mb` / `wan_total_mb` - Internet/WAN traffic
- `wifi_download_mb` / `wifi_upload_mb` / `wifi_total_mb` - WiFi interface traffic
- `ethernet_download_mb` / `ethernet_upload_mb` / `ethernet_total_mb` - Ethernet interface traffic
- `other_download_mb` / `other_upload_mb` / `other_total_mb` - Other interface traffic

### Device Information
- `total_devices` - Total number of connected devices
- `wifi_devices` - Number of devices connected via WiFi
- `ethernet_devices` - Number of devices connected via Ethernet

### Interface Counts
- `total_interfaces` - Total number of network interfaces
- `wan_interfaces` - Number of WAN interfaces
- `wifi_interfaces` - Number of WiFi interfaces
- `ethernet_interfaces` - Number of Ethernet interfaces
- `other_interfaces` - Number of other interfaces

### Router Information
- `router_name` - Friendly name of the router
- `router_host` - IP address of the router

## Important Notes

### Data Reset Behavior
- Traffic values represent cumulative totals since the last router reboot
- Values reset when the router reboots or when interface counters are reset
- This is normal behavior for network interface statistics

### Units
- All traffic values are in Megabytes (MB)
- Device counts are integers
- Interface counts are integers

### Multi-Router Support
- If you have multiple routers configured, each will have its own traffic sensor
- Entity naming follows the pattern: `sensor.wrtmanager_{router_name}_router_traffic_total`
- You can create cards that compare traffic across multiple routers

## Dashboard Card Examples

### Basic Traffic Card
```yaml
type: entities
title: Router Traffic
entities:
  - entity: sensor.wrtmanager_main_router_router_traffic_total
    name: Total Network Traffic
  - entity: sensor.wrtmanager_main_router_router_traffic_total
    type: attribute
    attribute: wan_total_mb
    name: Internet Traffic
    suffix: " MB"
  - entity: sensor.wrtmanager_main_router_router_traffic_total
    type: attribute
    attribute: total_devices
    name: Connected Devices
```

### Statistic Cards for Dashboard

**Note**: Statistic cards require the `period` parameter to specify the time window for statistics calculation. Common values are `5minute`, `hour`, `day`, `week`, `month`.

```yaml
type: horizontal-stack
cards:
  - type: statistic
    entity: sensor.wrtmanager_main_router_router_traffic_total
    name: Total Traffic
    icon: mdi:router-wireless
    period: hour

  - type: statistic
    entity: sensor.wrtmanager_main_router_router_traffic_total
    attribute: wan_total_mb
    name: Internet
    unit: MB
    icon: mdi:web
    period: hour

  - type: statistic
    entity: sensor.wrtmanager_main_router_router_traffic_total
    attribute: total_devices
    name: Devices
    icon: mdi:devices
    period: hour
```

## Troubleshooting

### Sensor Not Appearing
1. Verify the integration is properly configured
2. Check that the router is responding to network interface queries
3. Ensure the router has active network interfaces with traffic

### Zero Values
- If all values show zero, the router may have recently rebooted
- Check that devices are actively using the network to generate traffic
- Verify that the router's network interfaces are functioning

### Missing Attributes
- Some attributes may not be available if certain interface types are not present
- For example, `ethernet_total_mb` will be zero if no Ethernet interfaces have traffic

## Advanced Usage

### Automations
You can use the sensor in automations to track network usage:

```yaml
automation:
  - alias: "High Network Usage Alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.wrtmanager_main_router_router_traffic_total
        attribute: wan_total_mb
        above: 1000  # Alert when WAN traffic exceeds 1GB
    action:
      - service: notify.mobile_app
        data:
          message: "High network usage detected: {{ states.sensor.wrtmanager_main_router_router_traffic_total.attributes.wan_total_mb }}MB"
```

### Template Sensors
Create derived sensors for specific use cases:

```yaml
template:
  - sensor:
      - name: "Network Usage Ratio"
        state: >
          {% set upload = state_attr('sensor.wrtmanager_main_router_router_traffic_total', 'total_upload_mb') | float %}
          {% set download = state_attr('sensor.wrtmanager_main_router_router_traffic_total', 'total_download_mb') | float %}
          {% if download > 0 %}
            {{ (upload / download * 100) | round(1) }}
          {% else %}
            0
          {% endif %}
        unit_of_measurement: "%"
```

## Getting Help

If you encounter issues with the Router Traffic Card:

1. Check the [main README](../README.md) for general troubleshooting
2. Review the [example configurations](../examples/) for working setups
3. Enable debug logging for the `custom_components.wrtmanager` component
4. Report issues on the [GitHub repository](https://github.com/ohadlevy/wrtmanager-ha-integration/issues)

For more dashboard examples and configurations, see the files in the `examples/` directory.