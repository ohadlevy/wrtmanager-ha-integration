/**
 * WrtManager Custom Lovelace Cards
 *
 * Cards:
 *   - network-devices-card    WiFi devices grouped by AP
 *   - router-health-card      Router health overview
 *   - network-topology-card   Visual network topology
 *   - signal-heatmap-card     Signal strength with quality filtering
 *   - roaming-activity-card   Roaming tracker with live event log
 *
 * All cards auto-discover WrtManager routers and devices from the HA
 * device/entity registry — no manual entity configuration required.
 */

// ─── Shared utilities ────────────────────────────────────────────────

const LitElement = Object.getPrototypeOf(customElements.get("ha-panel-lovelace") ?? customElements.get("hui-view"));
const { html, css } = LitElement.prototype;

const fireEvent = (node, type, detail = {}) => {
  node.dispatchEvent(
    new CustomEvent(type, { bubbles: true, composed: true, detail })
  );
};

const TYPE_ICONS = {
  "Mobile Device": "mdi:cellphone",
  Computer: "mdi:laptop",
  "IoT Switch": "mdi:light-switch",
  "Smart Speaker": "mdi:speaker",
  Printer: "mdi:printer",
  "Robot Vacuum": "mdi:robot-vacuum",
  "Network Equipment": "mdi:router-network",
  "Home Appliance": "mdi:home-automation",
  Vehicle: "mdi:car-connected",
  Bridge: "mdi:bridge",
  "Air Conditioner": "mdi:air-conditioner",
  Unknown: "mdi:help-circle-outline",
};

const INTEGRATION_ICONS = {
  shelly: "mdi:flash",
  esphome: "mdi:chip",
  tuya: "mdi:cloud",
  mqtt: "mdi:antenna",
  mobile_app: "mdi:cellphone-link",
  homekit: "mdi:apple",
  hue: "mdi:lightbulb",
  cast: "mdi:cast",
  sonos: "mdi:speaker-wireless",
  roborock: "mdi:robot-vacuum",
};

function signalColor(dbm) {
  if (dbm == null) return "var(--secondary-text-color)";
  if (dbm >= -50) return "#4caf50";
  if (dbm >= -65) return "#8bc34a";
  if (dbm >= -75) return "#ff9800";
  return "#f44336";
}

function signalBar(dbm) {
  if (dbm == null) return "-";
  if (dbm >= -50) return `\u25CF\u25CF\u25CF ${dbm}`;
  if (dbm >= -65) return `\u25CF\u25CF\u25CB ${dbm}`;
  if (dbm >= -75) return `\u25CF\u25CB\u25CB ${dbm}`;
  return `\u25CB\u25CB\u25CB ${dbm}`;
}

function navigateToDevice(deviceId) {
  window.history.pushState(null, "", `/config/devices/device/${deviceId}`);
  window.dispatchEvent(new Event("location-changed"));
}

// ─── WrtManager Mixin ────────────────────────────────────────────────

const WrtManagerMixin = (superClass) =>
  class extends superClass {
    findDeviceByMac(mac) {
      if (!mac || mac === "-" || !this.hass?.devices) return null;
      const macUpper = mac.toUpperCase();
      let fallback = null;
      for (const device of Object.values(this.hass.devices)) {
        if (!device.connections) continue;
        for (const [type, value] of device.connections) {
          if (type === "mac" && value.toUpperCase() === macUpper) {
            // Prefer the device that has wrtmanager identifiers
            if (device.identifiers?.some(([d]) => d === "wrtmanager")) return device;
            if (!fallback) fallback = device;
          }
        }
      }
      return fallback;
    }

    findRouterDevice(routerIp) {
      if (!routerIp || !this.hass?.devices) return null;
      for (const device of Object.values(this.hass.devices)) {
        if (!device.identifiers) continue;
        for (const [domain, id] of device.identifiers) {
          if (domain === "wrtmanager" && id === routerIp) {
            return device;
          }
        }
      }
      return null;
    }

    getApName(apIp) {
      if (this.config?.ap_names?.[apIp]) return this.config.ap_names[apIp];
      const device = this.findRouterDevice(apIp);
      if (device) return device.name_by_user || device.name || apIp;
      return apIp;
    }

    getAreaName(areaId) {
      if (!areaId || !this.hass?.areas) return null;
      return this.hass.areas[areaId]?.name || null;
    }

    getOtherIntegrations(deviceId) {
      if (!deviceId || !this.hass?.entities) return [];
      const integrations = new Set();
      for (const entity of Object.values(this.hass.entities)) {
        if (
          entity.device_id === deviceId &&
          entity.platform !== "wrtmanager" &&
          !entity.disabled_by
        ) {
          integrations.add(entity.platform);
        }
      }
      return [...integrations];
    }

    entityBelongsToDevice(entityId, haDeviceId) {
      if (!entityId || !haDeviceId || !this.hass?.entities) return false;
      const entityReg = this.hass.entities[entityId];
      return entityReg?.device_id === haDeviceId;
    }

    navigateToDevice(deviceId) {
      navigateToDevice(deviceId);
    }

    showMoreInfo(entityId) {
      if (entityId) fireEvent(this, "hass-more-info", { entityId });
    }

    getPresenceDevices({ includeOffline = false } = {}) {
      if (!this.hass) return [];
      const devices = [];
      for (const [id, state] of Object.entries(this.hass.states)) {
        if (!id.startsWith("binary_sensor.") || !id.endsWith("_presence"))
          continue;
        if (!includeOffline && state.state !== "on") continue;
        const a = state.attributes;
        const mac = a.mac_address || "-";

        const haDevice = this.findDeviceByMac(mac);
        const areaName = haDevice ? this.getAreaName(haDevice.area_id) : null;
        const otherIntegrations = haDevice
          ? this.getOtherIntegrations(haDevice.id)
          : [];

        const deviceName =
          haDevice?.name_by_user ||
          a.hostname ||
          haDevice?.name ||
          a.friendly_name?.replace(" Presence", "") ||
          id;

        devices.push({
          entityId: id,
          name: deviceName,
          ip: a.ip || "-",
          ap: a.primary_ap || "unknown",
          signal: a.signal_dbm != null ? Number(a.signal_dbm) : null,
          signalQuality: a.signal_quality || null,
          network: a.network || "-",
          vendor: a.vendor || "",
          deviceType: a.device_type || "Unknown",
          mac,
          roaming: a.roaming_count != null ? Number(a.roaming_count) : 0,
          online: state.state === "on",
          haDeviceId: haDevice?.id || null,
          areaName,
          otherIntegrations,
        });
      }
      return devices;
    }

    getDisconnectEntityId(d) {
      if (!d.haDeviceId || !this.hass?.entities) return null;
      // Find disconnect buttons for this device, prefer the one matching current AP
      let fallback = null;
      for (const [entityId, entity] of Object.entries(this.hass.entities)) {
        if (
          entityId.startsWith("button.") &&
          entity.device_id === d.haDeviceId &&
          entity.platform === "wrtmanager" &&
          entityId.includes("disconnect")
        ) {
          // Check if this button's router matches the device's current AP
          const state = this.hass.states?.[entityId];
          if (state?.attributes?.router === d.ap) return entityId;
          if (!fallback) fallback = entityId;
        }
      }
      return fallback;
    }

    disconnectDevice(e, d) {
      e.stopPropagation();
      const entityId = this.getDisconnectEntityId(d);
      if (!entityId || !this.hass) return;
      this.hass.callService("button", "press", { entity_id: entityId });
    }

    getRouterDevices() {
      if (!this.hass?.devices) return [];
      const routers = [];
      for (const device of Object.values(this.hass.devices)) {
        if (!device.identifiers) continue;
        if (device.manufacturer !== "OpenWrt") continue;
        for (const [domain, id] of device.identifiers) {
          if (
            domain === "wrtmanager" &&
            id.includes(".") &&
            !id.includes(":")
          ) {
            routers.push({
              ...device,
              routerHost: id,
              areaName: this.getAreaName(device.area_id),
            });
            break;
          }
        }
      }
      return routers;
    }
  };

// =====================================================================
// CARD 1: Network Devices
// =====================================================================

class NetworkDevicesCard extends WrtManagerMixin(LitElement) {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      _filter: { type: String },
    };
  }

  constructor() {
    super();
    this._filter = "";
  }

  setConfig(config) {
    this.config = { show_offline: false, ...config };
  }

  static getConfigElement() {
    return document.createElement("network-devices-card-editor");
  }

  static getStubConfig() {
    return {};
  }

  shouldUpdate(changedProps) {
    if (changedProps.has("hass") && changedProps.size === 1) {
      // Only re-render for hass changes if presence sensor states actually changed
      const oldHass = changedProps.get("hass");
      if (!oldHass) return true;
      for (const [k, v] of Object.entries(this.hass.states)) {
        if (k.endsWith("_presence") || k.includes("disconnect")) {
          if (oldHass.states[k] !== v) return true;
        }
      }
      return false;
    }
    return true;
  }

  _getNetworkLabel(networkName) {
    if (this.config.network_labels?.[networkName]) {
      return this.config.network_labels[networkName];
    }
    return networkName;
  }

  _getDevices() {
    return this.getPresenceDevices({
      includeOffline: this.config.show_offline,
    });
  }

  _typeIcon(type) {
    return TYPE_ICONS[type] || TYPE_ICONS["Unknown"];
  }

  _onSearch(e) {
    this._filter = e.target.value.toLowerCase();
  }

  _clearSearch() {
    this._filter = "";
  }

  _onDeviceClick(d) {
    if (d.haDeviceId) {
      this.navigateToDevice(d.haDeviceId);
    } else {
      this.showMoreInfo(d.entityId);
    }
  }

  _onApClick(apIp) {
    const routerDevice = this.findRouterDevice(apIp);
    if (routerDevice) {
      this.navigateToDevice(routerDevice.id);
    }
  }

  _filterByAp(apIp) {
    const apName = this.getApName(apIp);
    if (this._filter === apName.toLowerCase()) {
      this._filter = "";
    } else {
      this._filter = apName.toLowerCase();
    }
  }

  _getFilteredGroups(allDevices) {
    const filter = this._filter;
    const devices = filter
      ? allDevices.filter(
          (d) =>
            d.name.toLowerCase().includes(filter) ||
            d.ip.includes(filter) ||
            d.vendor.toLowerCase().includes(filter) ||
            d.deviceType.toLowerCase().includes(filter) ||
            d.mac.toLowerCase().includes(filter) ||
            (d.areaName || "").toLowerCase().includes(filter) ||
            this.getApName(d.ap).toLowerCase().includes(filter) ||
            this._getNetworkLabel(d.network).toLowerCase().includes(filter) ||
            d.otherIntegrations.some((i) => i.toLowerCase().includes(filter))
        )
      : allDevices;

    const groups = {};
    for (const d of devices) {
      if (!groups[d.ap]) groups[d.ap] = [];
      groups[d.ap].push(d);
    }
    for (const ap in groups) {
      groups[ap].sort((a, b) => (b.signal ?? -999) - (a.signal ?? -999));
    }

    const configOrder = this.config.ap_order || [];
    const sortedAps = Object.keys(groups).sort((a, b) => {
      const ia = configOrder.indexOf(a);
      const ib = configOrder.indexOf(b);
      if (ia !== -1 && ib !== -1) return ia - ib;
      if (ia !== -1) return -1;
      if (ib !== -1) return 1;
      return this.getApName(a).localeCompare(this.getApName(b));
    });

    return { devices, groups, sortedAps };
  }

  _getNetworkSummary(devices) {
    const counts = {};
    for (const d of devices) {
      const net = this._getNetworkLabel(d.network);
      counts[net] = (counts[net] || 0) + 1;
    }
    return Object.entries(counts)
      .map(([k, v]) => `${k}: ${v}`)
      .join(" | ");
  }

  _renderIntegrationBadges(integrations) {
    if (!integrations.length) return "";
    return html`<span class="ndc-integrations">
      ${integrations.map((platform) => {
        const icon = INTEGRATION_ICONS[platform] || "mdi:puzzle";
        return html`<span class="ndc-int-badge" title="${platform}">
          <ha-icon icon=${icon} style="--mdc-icon-size: 12px;"></ha-icon>
        </span>`;
      })}
    </span>`;
  }

  _renderDeviceRow(d) {
    const networkLabel = this._getNetworkLabel(d.network);
    const subtitle = [d.vendor, d.areaName].filter(Boolean).join(" \u00B7 ");
    const disconnectId = this.getDisconnectEntityId(d);
    const canDisconnect = disconnectId && this.hass?.states?.[disconnectId];
    return html`
      <div
        class="ndc-row ndc-clickable ${d.online ? "" : "ndc-offline"}"
        @click=${() => this._onDeviceClick(d)}
        title=${d.haDeviceId ? "Open device page" : "Show entity details"}
      >
        <ha-icon
          icon=${this._typeIcon(d.deviceType)}
          class="ndc-type-icon"
          title=${d.deviceType}
        ></ha-icon>
        <div class="ndc-device-info">
          <span class="ndc-device-name">
            ${d.name}
            ${this._renderIntegrationBadges(d.otherIntegrations)}
          </span>
          <span class="ndc-device-meta">
            ${d.ip !== "-" ? html`<span class="ndc-ip">${d.ip}</span>` : ""}
            <span class="ndc-signal" style="color: ${signalColor(d.signal)}">${signalBar(d.signal)}</span>
            ${networkLabel !== "-" ? html`<span class="ndc-net">${networkLabel}</span>` : ""}
            ${subtitle ? html`<span class="ndc-meta-sub">${subtitle}</span>` : ""}
          </span>
        </div>
        ${canDisconnect ? html`
          <ha-icon
            icon="mdi:wifi-remove"
            class="ndc-disconnect"
            title="Disconnect from AP"
            @click=${(e) => this.disconnectDevice(e, d)}
          ></ha-icon>` : ""}
      </div>
    `;
  }

  _renderApHeader(ap, count) {
    const apName = this.getApName(ap);
    const routerDevice = this.findRouterDevice(ap);
    const area = routerDevice
      ? this.getAreaName(routerDevice.area_id)
      : null;

    return html`
      <div class="ndc-group-header">
        <span
          class="ndc-ap-name ${routerDevice ? "ndc-clickable-inline" : ""}"
          @click=${() => routerDevice && this._onApClick(ap)}
          title=${routerDevice ? "Open router device page" : apName}
        >
          <ha-icon
            icon="mdi:router-wireless"
            style="--mdc-icon-size: 20px;"
          ></ha-icon>
          ${apName}
          ${area ? html`<span class="ndc-ap-area">${area}</span>` : ""}
        </span>
        <span class="ndc-count">(${count})</span>
        <span
          class="ndc-filter-btn ndc-clickable-inline"
          @click=${() => this._filterByAp(ap)}
          title="Filter to this AP"
        >
          <ha-icon icon="mdi:filter-variant" style="--mdc-icon-size: 16px;"></ha-icon>
        </span>
      </div>
    `;
  }

  render() {
    const allDevices = this._getDevices();
    const { devices, groups, sortedAps } = this._getFilteredGroups(allDevices);
    const networkSummary = this._getNetworkSummary(allDevices);

    return html`
      <ha-card>
        <div class="ndc">
          <div class="ndc-summary">
            <b>${allDevices.length} devices</b> \u2014 ${networkSummary}
          </div>

          <div class="ndc-search-wrap">
            <ha-icon icon="mdi:magnify" class="ndc-search-icon"></ha-icon>
            <input
              class="ndc-search"
              type="text"
              placeholder="Search name, IP, vendor, area, integration..."
              .value=${this._filter}
              @input=${this._onSearch}
            />
            ${this._filter
              ? html`<ha-icon
                  icon="mdi:close"
                  class="ndc-search-clear"
                  @click=${this._clearSearch}
                ></ha-icon>`
              : ""}
          </div>

          ${devices.length === 0 && this._filter
            ? html`<div class="ndc-no-results">
                No devices matching "${this._filter}"
              </div>`
            : ""}

          ${sortedAps.map((ap) => {
            const apDevices = groups[ap];
            return html`
              <div class="ndc-group">
                ${this._renderApHeader(ap, apDevices.length)}
                <div class="ndc-list">
                  ${apDevices.map((d) => this._renderDeviceRow(d))}
                </div>
              </div>
            `;
          })}
        </div>
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      :host { --ndc-spacing: 16px; display: block; }
      .ndc { padding: var(--ndc-spacing); }
      .ndc-summary { color: var(--secondary-text-color); margin-bottom: 12px; font-size: 0.95em; }
      .ndc-summary b { color: var(--primary-text-color); }
      .ndc-search-wrap { position: relative; margin-bottom: 16px; }
      .ndc-search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); --mdc-icon-size: 18px; color: var(--secondary-text-color); pointer-events: none; }
      .ndc-search-clear { position: absolute; right: 10px; top: 50%; transform: translateY(-50%); --mdc-icon-size: 18px; color: var(--secondary-text-color); cursor: pointer; }
      .ndc-search-clear:hover { color: var(--primary-text-color); }
      .ndc-search { width: 100%; box-sizing: border-box; padding: 10px 36px; border: 1px solid var(--divider-color, #444); border-radius: 8px; background: var(--input-fill-color, var(--card-background-color, #1c1c1c)); color: var(--primary-text-color); font-size: 0.9em; font-family: inherit; outline: none; }
      .ndc-search:focus { border-color: var(--primary-color); }
      .ndc-search::placeholder { color: var(--secondary-text-color); opacity: 0.6; }
      .ndc-group { margin-bottom: 20px; }
      .ndc-group-header { font-size: 1.05em; font-weight: 500; padding: 8px 0; border-bottom: 2px solid var(--divider-color, #444); margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
      .ndc-ap-name { display: flex; align-items: center; gap: 8px; }
      .ndc-ap-area { font-size: 0.75em; font-weight: normal; color: var(--secondary-text-color); padding: 1px 6px; border-radius: 4px; background: rgba(255,255,255,0.06); }
      .ndc-clickable-inline { cursor: pointer; border-radius: 4px; padding: 2px 4px; margin: -2px -4px; }
      .ndc-clickable-inline:hover { background: rgba(var(--rgb-primary-color,255,255,255),0.08); }
      .ndc-filter-btn { margin-left: auto; color: var(--secondary-text-color); opacity: 0.4; }
      .ndc-filter-btn:hover { opacity: 1; }
      .ndc-count { color: var(--secondary-text-color); font-weight: normal; font-size: 0.85em; }
      .ndc-list { display: flex; flex-direction: column; gap: 2px; }
      .ndc-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 8px; cursor: pointer; }
      .ndc-row:hover { background: rgba(var(--rgb-primary-color,255,255,255),0.05); }
      .ndc-offline { opacity: 0.45; }
      .ndc-type-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); flex-shrink: 0; }
      .ndc-device-info { display: flex; flex-direction: column; min-width: 0; flex: 1; }
      .ndc-device-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: flex; align-items: center; gap: 4px; font-weight: 500; }
      .ndc-device-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 0.8em; color: var(--secondary-text-color); }
      .ndc-meta-sub { opacity: 0.7; }
      .ndc-integrations { display: inline-flex; gap: 2px; flex-shrink: 0; }
      .ndc-int-badge { display: inline-flex; align-items: center; color: var(--primary-color, #03a9f4); opacity: 0.7; }
      .ndc-signal { font-family: monospace; white-space: nowrap; }
      .ndc-ip { font-family: monospace; white-space: nowrap; }
      .ndc-net { padding: 1px 6px; border-radius: 4px; background: rgba(255,255,255,0.08); white-space: nowrap; }
      .ndc-disconnect { --mdc-icon-size: 16px; color: var(--secondary-text-color); opacity: 0.3; cursor: pointer; padding: 4px; border-radius: 4px; flex-shrink: 0; }
      .ndc-disconnect:hover { opacity: 1; color: var(--error-color, #f44336); background: rgba(244,67,54,0.1); }
      .ndc-no-results { color: var(--secondary-text-color); text-align: center; padding: 24px; font-style: italic; }
    `;
  }

  getCardSize() { return 8; }
}

class NetworkDevicesCardEditor extends LitElement {
  static get properties() {
    return { hass: { type: Object }, _config: { type: Object } };
  }
  setConfig(config) { this._config = config; }
  _valueChanged(key, value) {
    fireEvent(this, "config-changed", { config: { ...this._config, [key]: value } });
  }
  render() {
    if (!this._config) return html``;
    return html`
      <div class="editor">
        <p class="hint">This card auto-discovers WrtManager routers and devices. AP names and network labels are read from the device registry.</p>
        <ha-formfield label="Show offline devices">
          <ha-switch .checked=${this._config.show_offline || false} @change=${(e) => this._valueChanged("show_offline", e.target.checked)}></ha-switch>
        </ha-formfield>
      </div>
    `;
  }
  static get styles() {
    return css`.editor { padding: 16px; } .hint { color: var(--secondary-text-color); font-size: 0.9em; margin-bottom: 16px; }`;
  }
}

customElements.define("network-devices-card", NetworkDevicesCard);
customElements.define("network-devices-card-editor", NetworkDevicesCardEditor);

// =====================================================================
// CARD 2: Router Health
// =====================================================================

class RouterHealthCard extends WrtManagerMixin(LitElement) {
  static get properties() {
    return { hass: { type: Object }, config: { type: Object } };
  }

  setConfig(config) { this.config = config; }

  static getConfigElement() {
    return document.createElement("router-health-card-editor");
  }

  static getStubConfig() { return {}; }

  _findRouters() {
    if (!this.hass) return [];
    const routers = [];
    const seen = new Set();

    for (const [id, state] of Object.entries(this.hass.states)) {
      if (!id.includes("_memory_usage")) continue;
      const prefix = id.replace("sensor.", "").replace("_memory_usage", "");
      const deviceCountId = `sensor.${prefix}_connected_devices`;
      if (!this.hass.states[deviceCountId]) continue;
      if (seen.has(prefix)) continue;
      seen.add(prefix);

      const deviceCount = this.hass.states[deviceCountId];
      const memFree = this.hass.states[`sensor.${prefix}_memory_free`];
      const tempId = `sensor.${prefix}_temperature`;
      const temp = this.hass.states[tempId];
      const traffic = this.hass.states[`sensor.${prefix}_total_traffic`];
      const uptimeId = `sensor.${prefix}_uptime`;
      const uptime = this.hass.states[uptimeId];

      let haDevice = null;
      let routerHost = null;
      if (this.hass.entities) {
        const entityReg = this.hass.entities[id];
        if (entityReg?.device_id) {
          haDevice = this.hass.devices?.[entityReg.device_id] || null;
          if (haDevice?.identifiers) {
            for (const [domain, ident] of haDevice.identifiers) {
              if (domain === "wrtmanager") { routerHost = ident; break; }
            }
          }
        }
      }

      const areaName = haDevice ? this.getAreaName(haDevice.area_id) : null;

      let validTemp = temp;
      if (temp && haDevice && this.hass.entities) {
        if (!this.entityBelongsToDevice(tempId, haDevice.id)) validTemp = null;
      }

      let haDeviceCount = null;
      if (haDevice && this.hass.devices) {
        haDeviceCount = 0;
        for (const device of Object.values(this.hass.devices)) {
          if (device.via_device_id === haDevice.id) haDeviceCount++;
        }
      }

      const role = this.config?.router_roles?.[routerHost] || null;
      const parseState = (s) =>
        s && s.state !== "unavailable" && s.state !== "unknown" ? Number(s.state) : null;

      routers.push({
        prefix,
        name: haDevice?.name_by_user || haDevice?.name || state.attributes.friendly_name?.replace(" Memory Usage", "") || prefix,
        role,
        memoryUsage: parseState(state),
        memoryUsageId: id,
        deviceCount: parseState(deviceCount),
        deviceCountId,
        haDeviceCount,
        memFree: parseState(memFree),
        temperature: parseState(validTemp),
        temperatureId: validTemp ? tempId : null,
        totalTraffic: parseState(traffic),
        trafficId: traffic ? `sensor.${prefix}_total_traffic` : null,
        trafficAttrs: traffic?.attributes || {},
        uptime: uptime && uptime.state !== "unavailable" && uptime.state !== "unknown" ? Number(uptime.state) : null,
        uptimeId: uptime ? uptimeId : null,
        uptimeAttrs: uptime?.attributes || {},
        model: haDevice?.model || state.attributes.model || "",
        swVersion: haDevice?.sw_version || state.attributes.sw_version || "",
        haDeviceId: haDevice?.id || null,
        areaName,
        routerHost,
      });
    }
    return routers.sort((a, b) => a.name.localeCompare(b.name));
  }

  _memoryColor(pct) {
    if (pct == null) return "var(--secondary-text-color)";
    if (pct < 60) return "#4caf50";
    if (pct < 80) return "#ff9800";
    return "#f44336";
  }

  _tempColor(temp) {
    if (temp == null) return "var(--secondary-text-color)";
    if (temp < 60) return "#4caf50";
    if (temp < 75) return "#ff9800";
    return "#f44336";
  }

  _formatUptime(seconds) {
    if (seconds == null) return "-";
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  _formatTraffic(mb) {
    if (mb == null) return "-";
    if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
    return `${mb.toFixed(0)} MB`;
  }

  _renderGauge(value, max, color, label, unit) {
    const pct = value != null ? Math.min((value / max) * 100, 100) : 0;
    return html`
      <div class="rhc-gauge">
        <div class="rhc-gauge-bar">
          <div class="rhc-gauge-fill" style="width: ${pct}%; background: ${color};"></div>
        </div>
        <div class="rhc-gauge-label">
          <span>${label}</span>
          <span style="color: ${color}">${value != null ? `${value}${unit}` : "-"}</span>
        </div>
      </div>
    `;
  }

  _renderRouter(r) {
    return html`
      <div class="rhc-router">
        <div class="rhc-router-header">
          <div class="rhc-router-title ${r.haDeviceId ? "rhc-clickable" : ""}"
            @click=${() => r.haDeviceId ? this.navigateToDevice(r.haDeviceId) : null}
            title=${r.haDeviceId ? "Open device page" : ""}>
            <ha-icon icon="mdi:router-wireless" style="--mdc-icon-size: 22px;"></ha-icon>
            <div class="rhc-router-info">
              <span class="rhc-router-name">${r.name}</span>
              ${r.role || r.model || r.areaName
                ? html`<span class="rhc-router-model">${[r.role, r.model, r.areaName].filter(Boolean).join(" \u00B7 ")}</span>`
                : ""}
            </div>
          </div>
          <div class="rhc-router-badges">
            <span class="rhc-badge rhc-clickable"
              title="Connected devices${r.haDeviceCount != null ? ` (${r.haDeviceCount} in HA)` : ""}"
              @click=${() => this.showMoreInfo(r.deviceCountId)}>
              <ha-icon icon="mdi:devices" style="--mdc-icon-size: 14px;"></ha-icon>
              ${r.deviceCount ?? "-"}
            </span>
            ${r.temperature != null ? html`
              <span class="rhc-badge rhc-clickable" style="color: ${this._tempColor(r.temperature)}"
                title="Router CPU temperature" @click=${() => this.showMoreInfo(r.temperatureId)}>
                <ha-icon icon="mdi:thermometer" style="--mdc-icon-size: 14px;"></ha-icon>
                ${r.temperature}\u00B0C
              </span>` : ""}
          </div>
        </div>
        <div class="rhc-clickable" title="RAM usage" @click=${() => this.showMoreInfo(r.memoryUsageId)}>
          ${this._renderGauge(r.memoryUsage, 100, this._memoryColor(r.memoryUsage), "Memory", "%")}
        </div>
        ${r.totalTraffic != null ? html`
          <div class="rhc-traffic rhc-clickable" title="Cumulative traffic since router boot" @click=${() => this.showMoreInfo(r.trafficId)}>
            <div class="rhc-traffic-row">
              <ha-icon icon="mdi:arrow-down" style="--mdc-icon-size: 14px; color: #4caf50;"></ha-icon>
              <span>${this._formatTraffic(r.trafficAttrs.total_download_mb)}</span>
              <ha-icon icon="mdi:arrow-up" style="--mdc-icon-size: 14px; color: #2196f3;"></ha-icon>
              <span>${this._formatTraffic(r.trafficAttrs.total_upload_mb)}</span>
              <span class="rhc-traffic-label">since boot</span>
            </div>
          </div>` : ""}
        ${r.uptime != null ? html`
          <div class="rhc-uptime rhc-clickable" title="Router uptime" @click=${() => this.showMoreInfo(r.uptimeId)}>
            <ha-icon icon="mdi:timer-outline" style="--mdc-icon-size: 14px;"></ha-icon>
            <span>Up ${this._formatUptime(r.uptime)}</span>
          </div>` : ""}
        ${r.swVersion ? html`<div class="rhc-version">${r.swVersion}</div>` : ""}
      </div>
    `;
  }

  render() {
    const routers = this._findRouters();
    if (routers.length === 0) {
      return html`<ha-card><div class="rhc" style="text-align:center;padding:24px;color:var(--secondary-text-color);">No routers found</div></ha-card>`;
    }
    return html`
      <ha-card>
        <div class="rhc">
          <div class="rhc-header">
            <ha-icon icon="mdi:router-network" style="--mdc-icon-size: 20px;"></ha-icon>
            Router Health
            <span class="rhc-count">(${routers.length})</span>
          </div>
          <div class="rhc-grid">${routers.map((r) => this._renderRouter(r))}</div>
        </div>
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      .rhc { padding: 16px; }
      .rhc-header { font-size: 1.1em; font-weight: 500; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
      .rhc-count { color: var(--secondary-text-color); font-weight: normal; font-size: 0.85em; }
      .rhc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
      .rhc-router { background: var(--input-fill-color, rgba(255,255,255,0.04)); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; gap: 10px; }
      .rhc-router-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
      .rhc-router-title { display: flex; align-items: center; gap: 8px; min-width: 0; }
      .rhc-router-info { display: flex; flex-direction: column; min-width: 0; }
      .rhc-router-name { font-weight: 500; font-size: 1em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .rhc-router-model { font-size: 0.75em; color: var(--secondary-text-color); }
      .rhc-router-badges { display: flex; gap: 8px; flex-shrink: 0; }
      .rhc-badge { display: flex; align-items: center; gap: 3px; font-size: 0.85em; padding: 2px 6px; border-radius: 6px; background: rgba(255,255,255,0.06); white-space: nowrap; }
      .rhc-gauge { display: flex; flex-direction: column; gap: 4px; }
      .rhc-gauge-bar { height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; overflow: hidden; }
      .rhc-gauge-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
      .rhc-gauge-label { display: flex; justify-content: space-between; font-size: 0.8em; color: var(--secondary-text-color); }
      .rhc-traffic-row { display: flex; align-items: center; gap: 6px; font-size: 0.8em; color: var(--secondary-text-color); }
      .rhc-traffic-label { font-size: 0.85em; opacity: 0.5; margin-left: auto; }
      .rhc-uptime { display: flex; align-items: center; gap: 4px; font-size: 0.8em; color: var(--secondary-text-color); }
      .rhc-version { font-size: 0.7em; color: var(--disabled-text-color, #666); text-align: right; }
      .rhc-clickable { cursor: pointer; border-radius: 6px; padding: 2px; margin: -2px; }
      .rhc-clickable:hover { background: rgba(var(--rgb-primary-color,255,255,255),0.05); }
    `;
  }

  getCardSize() { return 4; }
}

class RouterHealthCardEditor extends LitElement {
  static get properties() { return { hass: { type: Object }, _config: { type: Object } }; }
  setConfig(config) { this._config = config; }
  render() {
    if (!this._config) return html``;
    return html`<div style="padding:16px;"><p style="color:var(--secondary-text-color);font-size:0.9em;">This card auto-discovers WrtManager routers. Router names, models, and areas are read from the HA device registry.</p></div>`;
  }
}

customElements.define("router-health-card", RouterHealthCard);
customElements.define("router-health-card-editor", RouterHealthCardEditor);

// =====================================================================
// CARD 3: Network Topology
// =====================================================================

class NetworkTopologyCard extends WrtManagerMixin(LitElement) {
  static get properties() {
    return { hass: { type: Object }, config: { type: Object }, _width: { type: Number }, _tooltip: { type: Object } };
  }

  constructor() {
    super();
    this._width = 600;
    this._tooltip = null;
    this._resizeObserver = null;
  }

  setConfig(config) { this.config = config; }
  static getConfigElement() { return document.createElement("network-topology-card-editor"); }
  static getStubConfig() { return {}; }

  firstUpdated() { this._observeResize(); }

  updated(changed) {
    if (changed.has("hass") && !this._resizeObserver) this._observeResize();
  }

  _observeResize() {
    const container = this.shadowRoot?.querySelector(".topo-container");
    if (!container) return;
    this._width = container.clientWidth || 600;
    this._resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) this._width = entry.contentRect.width || 600;
    });
    this._resizeObserver.observe(container);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._resizeObserver?.disconnect();
    this._resizeObserver = null;
  }

  _buildGraph() {
    if (!this.hass) return { routerNodes: [], deviceNodes: [], links: [] };
    const routerDevices = this.getRouterDevices();
    if (!routerDevices.length) return { routerNodes: [], deviceNodes: [], links: [] };

    const presenceDevices = this.getPresenceDevices({ includeOffline: this.config?.show_offline || false });
    const routerNodes = routerDevices.map((rd) => ({
      id: rd.id, name: rd.name_by_user || rd.name || rd.routerHost,
      routerHost: rd.routerHost, model: rd.model || "", areaName: rd.areaName,
      deviceCount: 0, isRouter: true,
    }));

    const hostToId = {};
    for (const rn of routerNodes) hostToId[rn.routerHost] = rn.id;

    const deviceNodes = [];
    const links = [];

    for (const d of presenceDevices) {
      const routerId = hostToId[d.ap];
      if (!routerId) continue;
      deviceNodes.push({
        id: d.haDeviceId || d.entityId, entityId: d.entityId, haDeviceId: d.haDeviceId,
        name: d.name, signal: d.signal, signalQuality: d.signalQuality,
        deviceType: d.deviceType, vendor: d.vendor, ip: d.ip, online: d.online,
        areaName: d.areaName, routerId,
      });
      links.push({ source: routerId, target: d.haDeviceId || d.entityId });
      const rn = routerNodes.find((r) => r.id === routerId);
      if (rn) rn.deviceCount++;
    }
    return { routerNodes, deviceNodes, links };
  }

  _computeLayout(routerNodes, deviceNodes) {
    const w = this._width;
    const positions = {};
    const routerCount = routerNodes.length;
    if (!routerCount) return { positions, height: 100 };

    const cx = w / 2;
    const routerRadius = Math.min(w * 0.32, 350);
    const cy = routerRadius + 80;
    const deviceRadius = Math.max(80, routerRadius * 0.5);

    routerNodes.forEach((r, i) => {
      const angle = (2 * Math.PI * i) / routerCount - Math.PI / 2;
      positions[r.id] = { x: cx + routerRadius * Math.cos(angle), y: cy + routerRadius * Math.sin(angle) };
    });

    const devicesByRouter = {};
    for (const d of deviceNodes) {
      if (!devicesByRouter[d.routerId]) devicesByRouter[d.routerId] = [];
      devicesByRouter[d.routerId].push(d);
    }

    for (const rn of routerNodes) {
      const devices = devicesByRouter[rn.id] || [];
      if (!devices.length) continue;
      const rPos = positions[rn.id];
      const baseAngle = Math.atan2(rPos.y - cy, rPos.x - cx);
      const spreadAngle = Math.min(Math.PI * 0.8, devices.length * 0.18);
      devices.forEach((d, i) => {
        const t = devices.length === 1 ? 0 : (i / (devices.length - 1)) * 2 - 1;
        const angle = baseAngle + t * (spreadAngle / 2);
        positions[d.id] = { x: rPos.x + deviceRadius * Math.cos(angle), y: rPos.y + deviceRadius * Math.sin(angle) };
      });
    }

    let minY = Infinity, maxY = -Infinity;
    for (const pos of Object.values(positions)) {
      minY = Math.min(minY, pos.y);
      maxY = Math.max(maxY, pos.y);
    }
    const padding = 50;
    const height = maxY - minY + padding * 2;
    const offsetY = padding - minY;
    for (const pos of Object.values(positions)) pos.y += offsetY;

    return { positions, height: Math.max(height, 400) };
  }

  _onNodeClick(node) {
    if (node.isRouter) this.navigateToDevice(node.id);
    else if (node.haDeviceId) this.navigateToDevice(node.haDeviceId);
    else if (node.entityId) this.showMoreInfo(node.entityId);
  }

  _showTooltip(node, e) {
    const rect = this.shadowRoot.querySelector(".topo-container")?.getBoundingClientRect();
    if (!rect) return;
    this._tooltip = { node, x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  _hideTooltip() { this._tooltip = null; }

  _renderTooltip() {
    if (!this._tooltip) return "";
    const { node, x, y } = this._tooltip;
    const lines = [node.name];
    if (node.isRouter) {
      if (node.model) lines.push(node.model);
      if (node.areaName) lines.push(node.areaName);
      lines.push(`${node.deviceCount} devices`);
    } else {
      if (node.vendor) lines.push(node.vendor);
      if (node.deviceType && node.deviceType !== "Unknown") lines.push(node.deviceType);
      if (node.ip && node.ip !== "-") lines.push(node.ip);
      if (node.signal != null) lines.push(`Signal: ${node.signal} dBm`);
      if (node.areaName) lines.push(node.areaName);
    }
    const left = x > this._width - 160 ? x - 150 : x + 15;
    const top = Math.max(10, y - lines.length * 9);
    return html`<div class="topo-tooltip" style="left:${left}px;top:${top}px;">${lines.map((l) => html`<div>${l}</div>`)}</div>`;
  }

  render() {
    const { routerNodes, deviceNodes, links } = this._buildGraph();
    if (!routerNodes.length) {
      return html`<ha-card><div class="topo-empty">No WrtManager routers found</div></ha-card>`;
    }
    const { positions, height } = this._computeLayout(routerNodes, deviceNodes);

    return html`
      <ha-card>
        <div class="topo-header">
          <ha-icon icon="mdi:lan" style="--mdc-icon-size: 20px;"></ha-icon>
          Network Topology
          <span class="topo-count">${routerNodes.length} routers \u00B7 ${deviceNodes.length} devices</span>
        </div>
        <div class="topo-legend">
          <span class="topo-legend-item"><span class="topo-dot" style="background:#4caf50;"></span>\u2265 -50</span>
          <span class="topo-legend-item"><span class="topo-dot" style="background:#8bc34a;"></span>\u2265 -65</span>
          <span class="topo-legend-item"><span class="topo-dot" style="background:#ff9800;"></span>\u2265 -75</span>
          <span class="topo-legend-item"><span class="topo-dot" style="background:#f44336;"></span>&lt; -75</span>
          <span class="topo-legend-item" style="margin-left:auto;font-size:0.9em;">dBm</span>
        </div>
        <div class="topo-container" style="height:${height}px;" @mouseleave=${() => this._hideTooltip()}>
          <svg class="topo-svg" viewBox="0 0 ${this._width} ${height}" preserveAspectRatio="xMidYMid meet">
            ${links.map((link) => {
              const s = positions[link.source], t = positions[link.target];
              if (!s || !t) return "";
              const device = deviceNodes.find((d) => d.id === link.target);
              const color = device ? signalColor(device.signal) : "var(--divider-color, #444)";
              return html`<line x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}" stroke="${color}" stroke-width="1.5" stroke-opacity="0.35"/>`;
            })}
          </svg>
          ${routerNodes.map((r) => {
            const pos = positions[r.id];
            if (!pos) return "";
            return html`
              <div class="topo-node topo-router" style="left:${pos.x}px;top:${pos.y}px;"
                @click=${() => this._onNodeClick(r)}
                @mouseenter=${(e) => this._showTooltip(r, e)}
                @mouseleave=${() => this._hideTooltip()}>
                <ha-icon icon="mdi:router-wireless" style="--mdc-icon-size: 22px;"></ha-icon>
                <span class="topo-router-label">${r.name}</span>
                <span class="topo-router-count">${r.deviceCount}</span>
              </div>`;
          })}
          ${deviceNodes.map((d) => {
            const pos = positions[d.id];
            if (!pos) return "";
            const color = signalColor(d.signal);
            return html`
              <div class="topo-node topo-device ${d.online ? "" : "topo-offline"}" style="left:${pos.x}px;top:${pos.y}px;"
                @click=${() => this._onNodeClick(d)}
                @mouseenter=${(e) => this._showTooltip(d, e)}
                @mouseleave=${() => this._hideTooltip()}>
                <div class="topo-device-dot" style="background:${color};"></div>
              </div>`;
          })}
          ${this._renderTooltip()}
        </div>
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      :host { display: block; }
      .topo-header { padding: 16px 16px 8px; font-size: 1.1em; font-weight: 500; display: flex; align-items: center; gap: 8px; }
      .topo-count { color: var(--secondary-text-color); font-weight: normal; font-size: 0.8em; margin-left: auto; }
      .topo-legend { padding: 0 16px 8px; display: flex; gap: 12px; font-size: 0.75em; color: var(--secondary-text-color); }
      .topo-legend-item { display: flex; align-items: center; gap: 4px; }
      .topo-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
      .topo-container { position: relative; overflow: hidden; margin: 0 8px 16px; }
      .topo-svg { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }
      .topo-node { position: absolute; transform: translate(-50%, -50%); cursor: pointer; z-index: 1; }
      .topo-router { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 14px; background: var(--input-fill-color, rgba(255,255,255,0.06)); border-radius: 12px; border: 2px solid var(--primary-color, #03a9f4); transition: transform 0.15s; z-index: 2; }
      .topo-router:hover { transform: translate(-50%, -50%) scale(1.1); z-index: 10; background: rgba(var(--rgb-primary-color, 3,169,244),0.15); }
      .topo-router-label { font-size: 0.72em; font-weight: 500; white-space: nowrap; max-width: 90px; overflow: hidden; text-overflow: ellipsis; }
      .topo-router-count { font-size: 0.65em; color: var(--secondary-text-color); }
      .topo-device { width: 16px; height: 16px; display: flex; align-items: center; justify-content: center; transition: transform 0.15s; }
      .topo-device:hover { transform: translate(-50%, -50%) scale(2); z-index: 10; }
      .topo-device-dot { width: 10px; height: 10px; border-radius: 50%; border: 1.5px solid rgba(255,255,255,0.2); box-shadow: 0 0 4px rgba(0,0,0,0.3); }
      .topo-offline { opacity: 0.25; }
      .topo-tooltip { position: absolute; z-index: 100; background: var(--card-background-color, #1c1c1c); border: 1px solid var(--divider-color, #444); border-radius: 8px; padding: 8px 12px; font-size: 0.8em; pointer-events: none; box-shadow: 0 2px 8px rgba(0,0,0,0.4); line-height: 1.5; white-space: nowrap; }
      .topo-tooltip div:first-child { font-weight: 500; }
      .topo-tooltip div:not(:first-child) { color: var(--secondary-text-color); font-size: 0.9em; }
      .topo-empty { text-align: center; padding: 24px; color: var(--secondary-text-color); }
    `;
  }

  getCardSize() { return 6; }
}

class NetworkTopologyCardEditor extends LitElement {
  static get properties() { return { hass: { type: Object }, _config: { type: Object } }; }
  setConfig(config) { this._config = config; }
  _valueChanged(key, value) {
    fireEvent(this, "config-changed", { config: { ...this._config, [key]: value } });
  }
  render() {
    if (!this._config) return html``;
    return html`
      <div style="padding:16px;">
        <p style="color:var(--secondary-text-color);font-size:0.9em;margin-bottom:16px;">Auto-discovers WrtManager routers and connected devices. Shows network topology with signal quality color coding.</p>
        <ha-formfield label="Show offline devices">
          <ha-switch .checked=${this._config.show_offline || false} @change=${(e) => this._valueChanged("show_offline", e.target.checked)}></ha-switch>
        </ha-formfield>
      </div>`;
  }
}

customElements.define("network-topology-card", NetworkTopologyCard);
customElements.define("network-topology-card-editor", NetworkTopologyCardEditor);

// =====================================================================
// CARD 4: Signal Heatmap
// =====================================================================

class SignalHeatmapCard extends WrtManagerMixin(LitElement) {
  static get properties() {
    return { hass: { type: Object }, config: { type: Object }, _sortBy: { type: String }, _filterQuality: { type: String } };
  }

  constructor() {
    super();
    this._sortBy = "signal";
    this._filterQuality = "all";
  }

  setConfig(config) { this.config = config; }
  static getConfigElement() { return document.createElement("signal-heatmap-card-editor"); }
  static getStubConfig() { return {}; }

  _signalQuality(dbm) {
    if (dbm == null) return "unknown";
    if (dbm >= -50) return "excellent";
    if (dbm >= -65) return "good";
    if (dbm >= -75) return "fair";
    return "poor";
  }

  _signalBg(dbm) {
    if (dbm == null) return "transparent";
    if (dbm >= -50) return "rgba(76,175,80,0.25)";
    if (dbm >= -65) return "rgba(139,195,58,0.20)";
    if (dbm >= -75) return "rgba(255,152,0,0.25)";
    return "rgba(244,67,54,0.25)";
  }

  _buildData() {
    const devices = this.getPresenceDevices();
    const routerDevices = this.getRouterDevices();
    const aps = routerDevices.map((rd) => ({
      id: rd.routerHost, name: rd.name_by_user || rd.name || rd.routerHost, haDeviceId: rd.id,
    }));
    aps.sort((a, b) => a.name.localeCompare(b.name));

    const rows = devices
      .filter((d) => d.signal != null)
      .map((d) => ({ ...d, quality: this._signalQuality(d.signal), apSignals: { [d.ap]: d.signal } }));

    return { aps, rows };
  }

  _getFilteredRows(rows) {
    let filtered = rows;
    if (this._filterQuality !== "all") filtered = filtered.filter((r) => r.quality === this._filterQuality);
    if (this._sortBy === "signal") filtered.sort((a, b) => (a.signal ?? 0) - (b.signal ?? 0));
    else filtered.sort((a, b) => a.name.localeCompare(b.name));
    return filtered;
  }

  _qualityCounts(rows) {
    const counts = { excellent: 0, good: 0, fair: 0, poor: 0 };
    for (const r of rows) if (counts[r.quality] !== undefined) counts[r.quality]++;
    return counts;
  }

  _onDeviceClick(d) {
    if (d.haDeviceId) this.navigateToDevice(d.haDeviceId);
    else this.showMoreInfo(d.entityId);
  }

  render() {
    const { aps, rows } = this._buildData();
    const counts = this._qualityCounts(rows);
    const filtered = this._getFilteredRows(rows);

    return html`
      <ha-card>
        <div class="shm">
          <div class="shm-header">
            <ha-icon icon="mdi:signal-cellular-3" style="--mdc-icon-size: 20px;"></ha-icon>
            Signal Heatmap
            <span class="shm-count">${rows.length} devices</span>
          </div>
          <div class="shm-controls">
            <div class="shm-quality-chips">
              ${[
                ["all", `All (${rows.length})`, ""],
                ["poor", `Poor (${counts.poor})`, "#f44336"],
                ["fair", `Fair (${counts.fair})`, "#ff9800"],
                ["good", `Good (${counts.good})`, "#8bc34a"],
                ["excellent", `Excellent (${counts.excellent})`, "#4caf50"],
              ].map(([key, label, color]) => html`
                <span class="shm-chip ${this._filterQuality === key ? "shm-chip-active" : ""}"
                  style="${color ? `--chip-color:${color}` : ""}"
                  @click=${() => { this._filterQuality = this._filterQuality === key ? "all" : key; }}>
                  ${color ? html`<span class="shm-chip-dot" style="background:${color};"></span>` : ""}
                  ${label}
                </span>`)}
            </div>
            <span class="shm-sort" @click=${() => { this._sortBy = this._sortBy === "signal" ? "name" : "signal"; }} title="Toggle sort">
              <ha-icon icon=${this._sortBy === "signal" ? "mdi:sort-numeric-ascending" : "mdi:sort-alphabetical-ascending"} style="--mdc-icon-size: 16px;"></ha-icon>
              ${this._sortBy === "signal" ? "Worst first" : "A\u2013Z"}
            </span>
          </div>
          ${filtered.length === 0
            ? html`<div class="shm-empty">No devices matching filter</div>`
            : html`<div class="shm-list">
                ${filtered.map((d) => html`
                  <div class="shm-row" @click=${() => this._onDeviceClick(d)}>
                    <ha-icon icon=${TYPE_ICONS[d.deviceType] || TYPE_ICONS["Unknown"]} style="--mdc-icon-size: 18px; color: var(--secondary-text-color);"></ha-icon>
                    <div class="shm-device-info">
                      <span class="shm-device-name">${d.name}</span>
                      <span class="shm-device-sub">
                        <ha-icon icon="mdi:router-wireless" style="--mdc-icon-size: 12px;"></ha-icon>
                        ${this.getApName(d.ap)}${d.vendor ? html` \u00B7 ${d.vendor}` : ""}
                      </span>
                    </div>
                    <div class="shm-signal-badge" style="background:${this._signalBg(d.signal)};color:${signalColor(d.signal)};">${d.signal} dBm</div>
                    ${this.getDisconnectEntityId(d) ? html`
                      <ha-icon icon="mdi:wifi-remove" class="shm-disconnect"
                        title="Disconnect from AP"
                        @click=${(e) => this.disconnectDevice(e, d)}
                      ></ha-icon>` : ""}
                  </div>`)}
              </div>`}
        </div>
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      .shm { padding: 16px; }
      .shm-header { font-size: 1.1em; font-weight: 500; display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
      .shm-count { color: var(--secondary-text-color); font-weight: normal; font-size: 0.8em; margin-left: auto; }
      .shm-controls { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
      .shm-quality-chips { display: flex; gap: 6px; flex-wrap: wrap; }
      .shm-chip { display: flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 16px; font-size: 0.75em; cursor: pointer; background: rgba(255,255,255,0.06); user-select: none; transition: background 0.15s; }
      .shm-chip:hover { background: rgba(255,255,255,0.12); }
      .shm-chip-active { background: rgba(var(--rgb-primary-color,3,169,244),0.2); outline: 1px solid var(--primary-color, #03a9f4); }
      .shm-chip-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
      .shm-sort { display: flex; align-items: center; gap: 4px; font-size: 0.75em; color: var(--secondary-text-color); cursor: pointer; margin-left: auto; padding: 4px 8px; border-radius: 8px; }
      .shm-sort:hover { background: rgba(255,255,255,0.08); }
      .shm-list { display: flex; flex-direction: column; gap: 4px; }
      .shm-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 8px; cursor: pointer; background: var(--input-fill-color, rgba(255,255,255,0.04)); }
      .shm-row:hover { background: rgba(var(--rgb-primary-color,255,255,255),0.06); }
      .shm-device-info { display: flex; flex-direction: column; min-width: 0; flex: 1; }
      .shm-device-name { font-size: 0.9em; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .shm-device-sub { display: flex; align-items: center; gap: 4px; font-size: 0.75em; color: var(--secondary-text-color); }
      .shm-signal-badge { font-family: monospace; font-size: 0.82em; font-weight: 600; padding: 4px 10px; border-radius: 8px; white-space: nowrap; flex-shrink: 0; }
      .shm-disconnect { --mdc-icon-size: 16px; color: var(--secondary-text-color); opacity: 0.3; cursor: pointer; padding: 4px; border-radius: 4px; flex-shrink: 0; }
      .shm-disconnect:hover { opacity: 1; color: var(--error-color, #f44336); background: rgba(244,67,54,0.1); }
      .shm-empty { text-align: center; padding: 24px; color: var(--secondary-text-color); font-style: italic; }
    `;
  }

  getCardSize() { return 8; }
}

class SignalHeatmapCardEditor extends LitElement {
  static get properties() { return { hass: { type: Object }, _config: { type: Object } }; }
  setConfig(config) { this._config = config; }
  render() {
    return html`<div style="padding:16px;"><p style="color:var(--secondary-text-color);font-size:0.9em;">Shows signal strength for each device. Devices only report signal on their current AP.</p></div>`;
  }
}

customElements.define("signal-heatmap-card", SignalHeatmapCard);
customElements.define("signal-heatmap-card-editor", SignalHeatmapCardEditor);

// =====================================================================
// CARD 5: Roaming Activity
// =====================================================================

class RoamingActivityCard extends WrtManagerMixin(LitElement) {
  static get properties() {
    return { hass: { type: Object }, config: { type: Object }, _roamingLog: { type: Array } };
  }

  constructor() {
    super();
    this._roamingLog = [];
    this._previousAps = {};
  }

  setConfig(config) { this.config = { max_log_entries: 30, ...config }; }
  static getConfigElement() { return document.createElement("roaming-activity-card-editor"); }
  static getStubConfig() { return {}; }

  updated(changed) {
    if (!changed.has("hass") || !this.hass) return;
    for (const [id, state] of Object.entries(this.hass.states)) {
      if (!id.startsWith("binary_sensor.") || !id.endsWith("_presence")) continue;
      if (state.state !== "on") continue;
      const ap = state.attributes.primary_ap;
      if (!ap) continue;
      const prevAp = this._previousAps[id];
      this._previousAps[id] = ap;
      if (prevAp && prevAp !== ap) {
        const name = state.attributes.hostname || state.attributes.friendly_name?.replace(" Presence", "") || id;
        this._roamingLog = [
          { timestamp: new Date(), entityId: id, name, fromAp: prevAp, toAp: ap, signal: state.attributes.signal_dbm, deviceType: state.attributes.device_type || "Unknown" },
          ...this._roamingLog.slice(0, this.config.max_log_entries - 1),
        ];
      }
    }
  }

  _getActiveRoamers() {
    return this.getPresenceDevices().filter((d) => d.roaming > 0).sort((a, b) => b.roaming - a.roaming);
  }

  _formatTime(date) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  _formatTimeAgo(date) {
    const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
  }

  _onDeviceClick(d) {
    if (d.haDeviceId) this.navigateToDevice(d.haDeviceId);
    else this.showMoreInfo(d.entityId);
  }

  render() {
    const roamers = this._getActiveRoamers();
    const totalRoaming = roamers.reduce((sum, d) => sum + d.roaming, 0);

    return html`
      <ha-card>
        <div class="roa">
          <div class="roa-header">
            <ha-icon icon="mdi:swap-horizontal" style="--mdc-icon-size: 20px;"></ha-icon>
            Roaming Activity
            <span class="roa-count">${totalRoaming} events \u00B7 ${roamers.length} devices</span>
          </div>

          <div class="roa-section-title">
            <ha-icon icon="mdi:account-switch" style="--mdc-icon-size: 16px;"></ha-icon>
            Active Roamers
          </div>

          ${roamers.length === 0
            ? html`<div class="roa-empty">No devices have roamed since last restart</div>`
            : html`<div class="roa-roamers">
                ${roamers.map((d) => html`
                  <div class="roa-roamer" @click=${() => this._onDeviceClick(d)}>
                    <ha-icon icon=${TYPE_ICONS[d.deviceType] || TYPE_ICONS["Unknown"]} style="--mdc-icon-size: 18px; color: var(--secondary-text-color);"></ha-icon>
                    <div class="roa-roamer-info">
                      <span class="roa-roamer-name">${d.name}</span>
                      <span class="roa-roamer-ap">
                        <ha-icon icon="mdi:router-wireless" style="--mdc-icon-size: 12px;"></ha-icon>
                        ${this.getApName(d.ap)}
                        <span class="roa-signal" style="color:${signalColor(d.signal)}">${d.signal != null ? `${d.signal} dBm` : ""}</span>
                      </span>
                    </div>
                    <span class="roa-badge">${d.roaming}</span>
                    ${this.getDisconnectEntityId(d) ? html`
                      <ha-icon icon="mdi:wifi-remove" class="roa-disconnect"
                        title="Disconnect from AP"
                        @click=${(e) => this.disconnectDevice(e, d)}
                      ></ha-icon>` : ""}
                  </div>`)}
              </div>`}

          <div class="roa-section-title" style="margin-top:16px;">
            <ha-icon icon="mdi:history" style="--mdc-icon-size: 16px;"></ha-icon>
            Live Roaming Log
            ${this._roamingLog.length > 0 ? html`<span class="roa-log-count">(${this._roamingLog.length})</span>` : ""}
          </div>

          ${this._roamingLog.length === 0
            ? html`<div class="roa-empty">Watching for AP changes \u2014 events appear here in real time</div>`
            : html`<div class="roa-log">
                ${this._roamingLog.map((evt) => html`
                  <div class="roa-log-entry" @click=${() => this.showMoreInfo(evt.entityId)}>
                    <span class="roa-log-time" title=${this._formatTime(evt.timestamp)}>${this._formatTimeAgo(evt.timestamp)}</span>
                    <ha-icon icon=${TYPE_ICONS[evt.deviceType] || TYPE_ICONS["Unknown"]} style="--mdc-icon-size: 14px; color: var(--secondary-text-color);"></ha-icon>
                    <span class="roa-log-name">${evt.name}</span>
                    <span class="roa-log-route">
                      ${this.getApName(evt.fromAp)}
                      <ha-icon icon="mdi:arrow-right" style="--mdc-icon-size: 14px;"></ha-icon>
                      ${this.getApName(evt.toAp)}
                    </span>
                    ${evt.signal != null ? html`<span class="roa-log-signal" style="color:${signalColor(evt.signal)}">${evt.signal}</span>` : ""}
                  </div>`)}
              </div>`}
        </div>
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      .roa { padding: 16px; }
      .roa-header { font-size: 1.1em; font-weight: 500; display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
      .roa-count { color: var(--secondary-text-color); font-weight: normal; font-size: 0.8em; margin-left: auto; }
      .roa-section-title { display: flex; align-items: center; gap: 6px; font-size: 0.85em; font-weight: 500; color: var(--secondary-text-color); text-transform: uppercase; margin-bottom: 8px; }
      .roa-log-count { font-weight: normal; font-size: 0.9em; }
      .roa-empty { color: var(--secondary-text-color); font-size: 0.85em; font-style: italic; padding: 12px 0; }
      .roa-roamers { display: flex; flex-direction: column; gap: 4px; }
      .roa-roamer { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 8px; cursor: pointer; background: var(--input-fill-color, rgba(255,255,255,0.04)); }
      .roa-roamer:hover { background: rgba(var(--rgb-primary-color,255,255,255),0.06); }
      .roa-roamer-info { display: flex; flex-direction: column; min-width: 0; flex: 1; }
      .roa-roamer-name { font-size: 0.9em; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .roa-roamer-ap { display: flex; align-items: center; gap: 4px; font-size: 0.75em; color: var(--secondary-text-color); }
      .roa-signal { font-family: monospace; font-size: 0.9em; }
      .roa-disconnect { --mdc-icon-size: 16px; color: var(--secondary-text-color); opacity: 0.3; cursor: pointer; padding: 4px; border-radius: 4px; flex-shrink: 0; }
      .roa-disconnect:hover { opacity: 1; color: var(--error-color, #f44336); background: rgba(244,67,54,0.1); }
      .roa-badge { background: rgba(var(--rgb-primary-color,3,169,244),0.2); color: var(--primary-color, #03a9f4); font-size: 0.8em; font-weight: 600; padding: 2px 8px; border-radius: 12px; flex-shrink: 0; }
      .roa-log { display: flex; flex-direction: column; gap: 2px; max-height: 400px; overflow-y: auto; }
      .roa-log-entry { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; cursor: pointer; font-size: 0.82em; }
      .roa-log-entry:hover { background: rgba(var(--rgb-primary-color,255,255,255),0.04); }
      .roa-log-time { font-size: 0.85em; color: var(--secondary-text-color); min-width: 55px; font-family: monospace; }
      .roa-log-name { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 120px; }
      .roa-log-route { display: flex; align-items: center; gap: 4px; color: var(--secondary-text-color); white-space: nowrap; margin-left: auto; }
      .roa-log-signal { font-family: monospace; font-size: 0.9em; min-width: 30px; text-align: right; }
    `;
  }

  getCardSize() { return 6; }
}

class RoamingActivityCardEditor extends LitElement {
  static get properties() { return { hass: { type: Object }, _config: { type: Object } }; }
  setConfig(config) { this._config = config; }
  render() {
    return html`<div style="padding:16px;"><p style="color:var(--secondary-text-color);font-size:0.9em;">Shows devices that have roamed between APs. The live log tracks AP changes in real time while the card is open. Roaming counts reset on HA restart.</p></div>`;
  }
}

customElements.define("roaming-activity-card", RoamingActivityCard);
customElements.define("roaming-activity-card-editor", RoamingActivityCardEditor);

// ─── Card registration ───────────────────────────────────────────────

window.customCards = window.customCards || [];
window.customCards.push(
  { type: "network-devices-card", name: "Network Devices", description: "WiFi devices grouped by access point with HA cross-linking", preview: true },
  { type: "router-health-card", name: "Router Health", description: "Router health overview with memory, devices, temperature, traffic", preview: true },
  { type: "network-topology-card", name: "Network Topology", description: "Visual network topology with signal quality color coding", preview: true },
  { type: "signal-heatmap-card", name: "Signal Heatmap", description: "Signal strength list with quality filtering and sorting", preview: true },
  { type: "roaming-activity-card", name: "Roaming Activity", description: "Track device roaming between access points with live event log", preview: true },
);

console.info("%c WrtManager Cards ", "background: #03a9f4; color: white; font-weight: bold;");
