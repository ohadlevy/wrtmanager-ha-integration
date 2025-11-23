"""Constants for the WrtManager integration."""

# Integration domain
DOMAIN = "wrtmanager"

# Config flow constants
CONF_ROUTERS = "routers"
CONF_ROUTER_HOST = "host"
CONF_ROUTER_NAME = "name"
CONF_ROUTER_USERNAME = "username"
CONF_ROUTER_PASSWORD = "password"
CONF_ROUTER_DESCRIPTION = "description"
CONF_ROUTER_USE_HTTPS = "use_https"
CONF_ROUTER_VERIFY_SSL = "verify_ssl"
CONF_VLAN_NAMES = "vlan_names"

# Default values
DEFAULT_USERNAME = "hass"
DEFAULT_USE_HTTPS = False
DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_TIMEOUT = 10

# API methods
API_METHOD_HTTP_UBUS = "http_ubus"
API_METHOD_SSH_UBUS = "ssh_ubus"
API_METHOD_SHELL = "shell"

# Device attributes
ATTR_MAC = "mac_address"
ATTR_IP = "ip_address"
ATTR_HOSTNAME = "hostname"
ATTR_VENDOR = "vendor"
ATTR_DEVICE_TYPE = "device_type"
ATTR_SIGNAL_DBM = "signal_dbm"
ATTR_ROUTER = "router"
ATTR_INTERFACE = "interface"
ATTR_VLAN_ID = "vlan_id"
ATTR_SSID = "ssid"
ATTR_CONNECTED = "connected"
ATTR_LAST_SEEN = "last_seen"
ATTR_DATA_SOURCE = "data_source"
ATTR_ROAMING_COUNT = "roaming_count"
ATTR_PRIMARY_AP = "primary_ap"

# SSID-related attributes
ATTR_SSID_NAME = "ssid_name"
ATTR_SSID_INTERFACE = "ssid_interface"
ATTR_RADIO = "radio"
ATTR_ENCRYPTION = "encryption"
ATTR_HIDDEN = "hidden"
ATTR_CLIENT_ISOLATION = "client_isolation"
ATTR_SSID_MODE = "ssid_mode"
ATTR_SSID_DISABLED = "ssid_disabled"
ATTR_NETWORK_INTERFACE = "network_interface"

# Entity types
ENTITY_TYPE_DEVICE_PRESENCE = "device_presence"
ENTITY_TYPE_SIGNAL_STRENGTH = "signal_strength"

# VLAN mapping
VLAN_MAIN = 1
VLAN_IOT = 3
VLAN_GUEST = 13

VLAN_NAMES = {
    1: "Main Network",
    2: "Management Network",
    3: "IoT Network",
    10: "Secondary Network",
    20: "Work Network",
    100: "Guest Network",
    # Add your custom VLANs here
}

# Device types
DEVICE_TYPE_IOT_SWITCH = "IoT Switch"
DEVICE_TYPE_MOBILE = "Mobile Device"
DEVICE_TYPE_COMPUTER = "Computer"
DEVICE_TYPE_SMART_SPEAKER = "Smart Speaker"
DEVICE_TYPE_HOME_APPLIANCE = "Home Appliance"
DEVICE_TYPE_VEHICLE = "Vehicle"
DEVICE_TYPE_PRINTER = "Printer"
DEVICE_TYPE_ROBOT_VACUUM = "Robot Vacuum"
DEVICE_TYPE_NETWORK_EQUIPMENT = "Network Equipment"
DEVICE_TYPE_BRIDGE = "Network Bridge"
DEVICE_TYPE_UNKNOWN = "Unknown Device"

# Data sources
DATA_SOURCE_STATIC_DHCP = "static_dhcp"
DATA_SOURCE_DYNAMIC_DHCP = "dynamic_dhcp"
DATA_SOURCE_LIVE_ARP = "live_arp"
DATA_SOURCE_HISTORICAL_ARP = "historical_arp"
DATA_SOURCE_WIFI_ONLY = "wifi_only"

# Signal strength ranges
SIGNAL_EXCELLENT = -50
SIGNAL_GOOD = -60
SIGNAL_FAIR = -70

# Update intervals
UPDATE_INTERVAL_FAST = 15  # seconds, for active monitoring
UPDATE_INTERVAL_NORMAL = 30  # seconds, default
UPDATE_INTERVAL_SLOW = 60  # seconds, for less critical data

# Error messages
ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_AUTH = "invalid_auth"
ERROR_UNKNOWN = "unknown"
ERROR_TIMEOUT = "timeout"
ERROR_ALREADY_CONFIGURED = "already_configured"

# IEEE 802.11r roaming detection
ROAMING_DETECTION_THRESHOLD = 10  # seconds between AP changes to detect roaming
ROAMING_SIGNAL_HYSTERESIS = 10  # dBm difference to prefer new AP
