#!/bin/bash

# OpenWrt Home Assistant Integration Setup Script
# This script configures OpenWrt routers for WrtManager Home Assistant integration
#
# Usage: ./setup_openwrt_ha_integration.sh <router_hostname_or_ip> [password]
#
# Requirements:
# - SSH access to OpenWrt router as root
# - Router must have internet access for package installation
# - mkpasswd or openssl available on the machine running this script
#
# IMPORTANT FIXES APPLIED (based on community research):
# - Uses 'list' not 'option' syntax in UCI rpcd configuration
# - Ensures ACL role name matches rpcd configuration exactly
# - Tests both iwinfo and hostapd API methods for device discovery
# - Provides comprehensive API validation and troubleshooting

set -e

ROUTER_HOST="${1:-}"
HASS_PASSWORD="${2:-}"
HASS_IPS="${3:-}"

if [[ -z "$ROUTER_HOST" ]]; then
    echo "Usage: $0 <router_hostname_or_ip> [hass_password] [hass_ips]"
    echo ""
    echo "Examples:"
    echo "  $0 192.168.1.1"
    echo "  $0 main-router MySecurePassword123"
    echo "  $0 192.168.1.1 MyPassword '192.168.1.100,192.168.1.101'"
    echo ""
    echo "This script can be used for both new installations and updates."
    echo "Home Assistant IPs are optional but recommended for security."
    exit 1
fi

# Prompt for password if not provided
if [[ -z "$HASS_PASSWORD" ]]; then
    echo -n "Enter password for 'hass' user: "
    read -s HASS_PASSWORD
    echo
    if [[ -z "$HASS_PASSWORD" ]]; then
        echo "❌ Password cannot be empty"
        exit 1
    fi
fi

# Prompt for Home Assistant IPs for security restrictions (optional)
if [[ -z "$HASS_IPS" ]]; then
    echo ""
    echo "🔒 Security Enhancement: Restrict ubus access to specific Home Assistant IPs"
    echo "Enter one or more IP addresses (comma-separated for multiple):"
    echo "Examples: 192.168.1.100  or  192.168.1.100,192.168.1.101"
    echo -n "Home Assistant IP(s) (or press Enter to skip): "
    read HASS_IPS
fi

# Validate and parse IP addresses
VALID_IPS=()
if [[ -n "$HASS_IPS" ]]; then
    IFS=',' read -ra IP_ARRAY <<< "$HASS_IPS"
    for ip in "${IP_ARRAY[@]}"; do
        # Trim whitespace
        ip=$(echo "$ip" | xargs)
        # Basic IP validation
        if [[ "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
            VALID_IPS+=("$ip")
        else
            echo "⚠️  Invalid IP format: $ip (skipping)"
        fi
    done

    if [[ ${#VALID_IPS[@]} -eq 0 ]]; then
        echo "⚠️  No valid IPs provided. Skipping IP restrictions."
    else
        echo "✅ Will restrict access to: ${VALID_IPS[*]}"
    fi
fi

echo "Setting up WrtManager integration on $ROUTER_HOST..."
echo "This will configure HTTP ubus access for Home Assistant"
echo ""

# Function to run commands on router
run_on_router() {
    ssh -x root@"$ROUTER_HOST" "$1"
}

# Test SSH connectivity first
echo "Testing SSH connectivity..."
if ! run_on_router "echo 'SSH connection successful'" >/dev/null 2>&1; then
    echo "❌ Cannot connect to $ROUTER_HOST via SSH"
    echo "Please ensure:"
    echo "  - SSH is enabled on the router"
    echo "  - You can connect as root user"
    echo "  - Network connectivity is working"
    exit 1
fi

echo "✅ SSH connection successful"

# 1. Check and install required packages
echo ""
echo "Step 1: Checking required packages..."

# Check if packages are already installed
PACKAGES_NEEDED=$(run_on_router "
    missing_packages=''
    if ! opkg list-installed | grep -q '^rpcd-mod-file '; then
        missing_packages=\$missing_packages' rpcd-mod-file'
    fi
    if ! opkg list-installed | grep -q '^uhttpd-mod-ubus '; then
        missing_packages=\$missing_packages' uhttpd-mod-ubus'
    fi
    echo \$missing_packages
")

if [[ -n "$PACKAGES_NEEDED" ]]; then
    echo "Installing missing packages:$PACKAGES_NEEDED"
    run_on_router "opkg update && opkg install$PACKAGES_NEEDED"
    echo "✅ Packages installed successfully"
else
    echo "✅ All required packages are already installed"
fi

# 2. Enable ubus HTTP endpoint
echo "Step 2: Checking ubus HTTP endpoint configuration..."

UBUS_ENABLED=$(run_on_router "uci get uhttpd.main.ubus_prefix 2>/dev/null || echo 'not_set'")
if [[ "$UBUS_ENABLED" != "/ubus" ]]; then
    echo "Enabling ubus HTTP endpoint..."
    run_on_router "uci set uhttpd.main.ubus_prefix='/ubus' && uci commit uhttpd"
    echo "✅ ubus HTTP endpoint enabled"
else
    echo "✅ ubus HTTP endpoint already configured"
fi

# 3. Generate password hash locally
echo "Step 3: Generating password hash..."
HASH=$(echo "$HASS_PASSWORD" | mkpasswd -m md5 -s 2>/dev/null || echo "$HASS_PASSWORD" | openssl passwd -1 -stdin 2>/dev/null || echo "x")
if [[ "$HASH" == "x" ]]; then
    echo "❌ Cannot generate password hash"
    echo "Please install either 'mkpasswd' or 'openssl' on this machine"
    echo ""
    echo "Ubuntu/Debian: sudo apt install whois"
    echo "CentOS/RHEL:   sudo yum install mkpasswd"
    echo "macOS:         brew install mkpasswd"
    exit 1
fi

# 4. Create hass user
echo "Step 4: Checking 'hass' user account..."

USER_EXISTS=$(run_on_router "grep '^hass:' /etc/passwd >/dev/null 2>&1 && echo 'yes' || echo 'no'")
if [[ "$USER_EXISTS" == "no" ]]; then
    echo "Creating 'hass' user account..."
    run_on_router "
        # Add hass user to passwd and shadow
        echo 'hass:x:10001:10001:Home Assistant ubus user:/var:/bin/false' >> /etc/passwd
        echo 'hass:$HASH:0:0:99999:7:::' >> /etc/shadow
    "
    echo "✅ User 'hass' created successfully"
else
    echo "User 'hass' already exists, updating password..."
    run_on_router "
        # Update password in shadow file
        sed -i '/^hass:/d' /etc/shadow
        echo 'hass:$HASH:0:0:99999:7:::' >> /etc/shadow
    "
    echo "✅ User 'hass' password updated"
fi

# 5. Configure rpcd for hass user
echo "Step 5: Configuring rpcd authentication..."
run_on_router "
    # Create rpcd config if it doesn't exist
    touch /etc/config/rpcd

    # Remove existing hass config
    uci delete rpcd.hass 2>/dev/null || true

    # Add hass user configuration (CRITICAL: use 'list' not 'option' for read/write)
    uci set rpcd.hass=login
    uci set rpcd.hass.username='hass'
    uci set rpcd.hass.password='$HASH'
    uci add_list rpcd.hass.read='hass'
    uci add_list rpcd.hass.write='hass'
    uci commit rpcd
"

# 6. Create ACL permissions file
echo "Step 6: Setting up access control permissions..."
run_on_router "
    mkdir -p /usr/share/rpcd/acl.d

    cat > /usr/share/rpcd/acl.d/hass.json << 'EOF'
{
    \"hass\": {
        \"description\": \"WrtManager Home Assistant integration access\",
        \"read\": {
            \"ubus\": {
                \"hostapd.*\": [ \"get_clients\" ],
                \"iwinfo\": [ \"assoclist\", \"devices\", \"info\" ],
                \"system\": [ \"board\", \"info\" ],
                \"uci\": [ \"get\" ],
                \"network.wireless\": [ \"status\" ],
                \"network.device\": [ \"status\" ],
                \"dhcp\": [ \"ipv4leases\", \"ipv6leases\" ]
            }
        },
        \"write\": {
            \"ubus\": {
                \"session\": [ \"login\", \"access\" ]
            }
        }
    }
}
EOF
"

# 7. Configure IP-based access restrictions (if IPs provided)
if [[ ${#VALID_IPS[@]} -gt 0 ]]; then
    echo "Step 7: Configuring IP-based access restrictions..."

    # Build UCI commands for allowed IPs
    IP_RESTRICTIONS=""
    for allowed_ip in "${VALID_IPS[@]}"; do
        IP_RESTRICTIONS="${IP_RESTRICTIONS}
    uci add_list uhttpd.main.hass_allow='${allowed_ip}'"
    done

    run_on_router "
    # Remove existing hass_allow entries
    while uci delete uhttpd.main.hass_allow 2>/dev/null; do :; done

    # Add new allowed IPs
    ${IP_RESTRICTIONS}

    # Commit changes
    uci commit uhttpd
    "
    echo "✅ Restricted ubus access to: ${VALID_IPS[*]}"
else
    echo "Step 7: Skipping IP restrictions (no IPs provided)"
fi

# 8. Restart services
echo "Step 8: Restarting services..."
run_on_router "/etc/init.d/rpcd restart && /etc/init.d/uhttpd restart"

# 9. Test the setup
echo "Step 9: Testing authentication and API access..."

# Get router's IP address
ROUTER_IP=$(run_on_router "ip addr show br-lan | grep 'inet ' | head -1 | awk '{print \$2}' | cut -d'/' -f1" 2>/dev/null || echo "$ROUTER_HOST")

# Auto-detect HTTP vs HTTPS
echo "Auto-detecting HTTP/HTTPS protocol..."
PROTOCOL="http"

# Try HTTPS first (more secure)
HTTPS_TEST=$(curl -s -k -X POST "https://$ROUTER_IP/ubus" \
    -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"call\",\"params\":[\"00000000000000000000000000000000\",\"session\",\"login\",{\"username\":\"hass\",\"password\":\"$HASS_PASSWORD\"}]}" \
    2>/dev/null || echo "HTTPS_FAILED")

if echo "$HTTPS_TEST" | grep -q '"ubus_rpc_session"'; then
    PROTOCOL="https"
    echo "✅ Router is using HTTPS"
else
    echo "→ HTTPS not available, using HTTP"
fi

echo "Testing $PROTOCOL ubus authentication on $ROUTER_IP..."

# Test authentication
RESPONSE=$(curl -s $([ "$PROTOCOL" = "https" ] && echo "-k") -X POST "${PROTOCOL}://$ROUTER_IP/ubus" \
    -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"call\",\"params\":[\"00000000000000000000000000000000\",\"session\",\"login\",{\"username\":\"hass\",\"password\":\"$HASS_PASSWORD\"}]}" \
    2>/dev/null || echo "CURL_FAILED")

if [[ "$RESPONSE" == "CURL_FAILED" ]]; then
    echo "❌ HTTP request failed - check network connectivity to $ROUTER_IP"
    echo "   Ensure router's HTTP server is accessible"
    exit 1
elif echo "$RESPONSE" | grep -q '"ubus_rpc_session"'; then
    echo "✅ Authentication successful!"
    SESSION_ID=$(echo "$RESPONSE" | sed -n 's/.*"ubus_rpc_session":"\([^"]*\)".*/\1/p')

    # Test iwinfo devices call (required for WrtManager)
    echo "Testing iwinfo devices API call..."
    TEST_RESPONSE=$(curl -s $([ "$PROTOCOL" = "https" ] && echo "-k") -X POST "${PROTOCOL}://$ROUTER_IP/ubus" \
        -H "Content-Type: application/json" \
        -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"call\",\"params\":[\"$SESSION_ID\",\"iwinfo\",\"devices\",{}]}" \
        2>/dev/null || echo "TEST_FAILED")

    if echo "$TEST_RESPONSE" | grep -q '"devices"'; then
        echo "✅ iwinfo devices API working!"

        # Test iwinfo assoclist on first device (comprehensive test)
        FIRST_DEVICE=$(echo "$TEST_RESPONSE" | grep -o '"[^"]*phy[^"]*"' | head -1 | tr -d '"')
        if [ -n "$FIRST_DEVICE" ]; then
            echo "Testing iwinfo assoclist on $FIRST_DEVICE..."
            ASSOC_RESPONSE=$(curl -s $([ "$PROTOCOL" = "https" ] && echo "-k") -X POST "${PROTOCOL}://$ROUTER_IP/ubus" \
                -H "Content-Type: application/json" \
                -d "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"call\",\"params\":[\"$SESSION_ID\",\"iwinfo\",\"assoclist\",{\"device\":\"$FIRST_DEVICE\"}]}" \
                2>/dev/null)

            if echo "$ASSOC_RESPONSE" | grep -q '"results"'; then
                echo "✅ iwinfo assoclist working!"
            else
                echo "⚠️  iwinfo assoclist failed - device discovery may be limited"
            fi

            # Test hostapd get_clients (official HA method)
            echo "Testing hostapd get_clients on hostapd.$FIRST_DEVICE..."
            HOSTAPD_RESPONSE=$(curl -s $([ "$PROTOCOL" = "https" ] && echo "-k") -X POST "${PROTOCOL}://$ROUTER_IP/ubus" \
                -H "Content-Type: application/json" \
                -d "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"call\",\"params\":[\"$SESSION_ID\",\"hostapd.$FIRST_DEVICE\",\"get_clients\",{}]}" \
                2>/dev/null)

            if echo "$HOSTAPD_RESPONSE" | grep -q '"clients"'; then
                echo "✅ hostapd get_clients working!"
            else
                echo "⚠️  hostapd get_clients failed - using iwinfo fallback"
            fi
        fi
    else
        echo "⚠️  iwinfo API call failed - check wireless configuration"
        echo "   This may affect device discovery in WrtManager"
    fi

    # Test DHCP leases call (optional - only works on DHCP servers, not APs)
    echo "Testing DHCP leases API call..."
    DHCP_RESPONSE=$(curl -s $([ "$PROTOCOL" = "https" ] && echo "-k") -X POST "${PROTOCOL}://$ROUTER_IP/ubus" \
        -H "Content-Type: application/json" \
        -d "{\"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"call\",\"params\":[\"$SESSION_ID\",\"dhcp\",\"ipv4leases\",{}]}" \
        2>/dev/null || echo "DHCP_FAILED")

    if echo "$DHCP_RESPONSE" | grep -q '"device"'; then
        echo "✅ DHCP API access working!"
    else
        echo "ℹ️  DHCP API not available (normal for APs)"
        echo "   Device IP addresses will be detected via ARP instead"
    fi

else
    echo "❌ Authentication failed"
    echo "Response: $RESPONSE"
    echo ""
    echo "Troubleshooting:"
    echo "  - Check that uhttpd and rpcd services are running"
    echo "  - Verify password was set correctly"
    echo "  - Check /tmp/log/messages on router for errors"
    exit 1
fi

echo ""
echo "🎉 Setup completed successfully!"
echo ""
echo "Router configuration summary:"
echo "  Router: $ROUTER_HOST ($ROUTER_IP)"
echo "  Username: hass"
echo "  Password: [configured]"
echo "  Protocol: ${PROTOCOL^^}"
echo "  ubus endpoint: ${PROTOCOL}://$ROUTER_IP/ubus"
if [[ ${#VALID_IPS[@]} -gt 0 ]]; then
    echo "  IP Restrictions: ${VALID_IPS[*]}"
else
    echo "  IP Restrictions: None (open to all IPs)"
fi
echo ""
echo "To configure this router in WrtManager:"
echo "  1. Add the WrtManager integration in Home Assistant"
echo "  2. Enter the following details:"
echo "     Host: $ROUTER_IP"
echo "     Username: hass"
echo "     Password: $HASS_PASSWORD"
echo ""
echo "Important notes:"
echo "  • This configuration persists across router reboots"
echo "  • Re-run this script after firmware updates"
echo "  • For multiple routers, run this script on each one"
echo "  • Consider using a stronger password for production"

echo ""
echo "Next steps:"
echo "  1. Install WrtManager via HACS in Home Assistant"
echo "  2. Add integration: Settings → Devices & Services → Add Integration"
echo "  3. Search for 'WrtManager' and configure your routers"