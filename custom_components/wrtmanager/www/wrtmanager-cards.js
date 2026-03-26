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
          connectionType: a.connection_type || "wifi",
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
          if (domain === "wrtmanager") {
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

    // Separate WiFi and wired — wired have no AP and are rendered separately
    const wifiDevices = devices.filter((d) => d.connectionType !== "wired");
    const wiredDevices = devices.filter((d) => d.connectionType === "wired");

    // WiFi: group by AP (existing logic, unchanged)
    const groups = {};
    for (const d of wifiDevices) {
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

    // Wired: group by network name, sorted alphabetically within each group
    const wiredGroups = {};
    for (const d of wiredDevices) {
      const net = d.network || "unknown";
      if (!wiredGroups[net]) wiredGroups[net] = [];
      wiredGroups[net].push(d);
    }
    for (const net in wiredGroups) {
      wiredGroups[net].sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    }

    return { devices, groups, sortedAps, wiredGroups };
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

  _renderWiredSection(wiredGroups) {
    const totalWired = Object.values(wiredGroups).reduce((n, g) => n + g.length, 0);
    if (totalWired === 0) return "";
    const sortedNets = Object.keys(wiredGroups).sort();
    return html`
      <div class="ndc-group">
        <div class="ndc-group-header">
          <span class="ndc-ap-name">
            <ha-icon icon="mdi:ethernet" style="--mdc-icon-size: 20px;"></ha-icon>
            Wired Clients
          </span>
          <span class="ndc-count">(${totalWired})</span>
        </div>
        ${sortedNets.map((net) => html`
          ${sortedNets.length > 1
            ? html`<div class="ndc-wired-net-label">${this._getNetworkLabel(net)}</div>`
            : ""}
          <div class="ndc-list">
            ${wiredGroups[net].map((d) => this._renderWiredRow(d))}
          </div>
        `)}
      </div>
    `;
  }

  _renderWiredRow(d) {
    const networkLabel = this._getNetworkLabel(d.network);
    const subtitle = [d.vendor, d.areaName].filter(Boolean).join(" \u00B7 ");
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
            <ha-icon
              icon="mdi:ethernet"
              style="--mdc-icon-size: 14px; color: var(--secondary-text-color);"
            ></ha-icon>
            ${networkLabel !== "-"
              ? html`<span class="ndc-net">${networkLabel}</span>`
              : ""}
            ${subtitle ? html`<span class="ndc-meta-sub">${subtitle}</span>` : ""}
          </span>
        </div>
      </div>
    `;
  }

  render() {
    const allDevices = this._getDevices();
    const { devices, groups, sortedAps, wiredGroups } = this._getFilteredGroups(allDevices);
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
          ${this._renderWiredSection(wiredGroups)}
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
      .ndc-wired-net-label { font-size: 0.75em; text-transform: uppercase; color: var(--secondary-text-color); padding: 6px 0 2px 2px; letter-spacing: 0.05em; }
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
      const load1m = this.hass.states[`sensor.${prefix}_load_average_1m`];
      const load5m = this.hass.states[`sensor.${prefix}_load_average_5m`];
      const load15m = this.hass.states[`sensor.${prefix}_load_average_15m`];
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
        load1m: parseState(load1m),
        load5m: parseState(load5m),
        load15m: parseState(load15m),
        load1mId: load1m ? `sensor.${prefix}_load_average_1m` : null,
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

  _loadColor(val) {
    if (val == null) return "var(--secondary-text-color)";
    if (val < 0.5) return "#4caf50";
    if (val < 1.0) return "#ff9800";
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

  _findSsidsForRouter(routerName) {
    if (!this.hass || !routerName) return [];
    // Collect all global SSID entities and build set of all known routers
    const globalSsids = [];
    const allKnownRouters = new Set();
    for (const [, state] of Object.entries(this.hass.states)) {
      const attrs = state.attributes || {};
      if (!attrs.ssid_name || attrs.coverage !== "Global (all routers)") continue;
      globalSsids.push(attrs);
      for (const r of (attrs.enabled_routers || [])) allKnownRouters.add(r);
      for (const r of (attrs.disabled_routers || [])) allKnownRouters.add(r);
    }
    if (!allKnownRouters.has(routerName)) return [];
    return globalSsids.map(attrs => {
      const bands = attrs.frequency_bands || [];
      const bandLabel = bands.includes("2.4GHz") && bands.includes("5GHz") ? "2.4+5" :
        bands.includes("2.4GHz") ? "2.4" : bands.includes("5GHz") ? "5GHz" : "";
      const isEnabled = (attrs.enabled_routers || []).includes(routerName);
      return {
        name: attrs.ssid_name,
        bandLabel,
        disabled: !isEnabled,
        devices: isEnabled ? (attrs.connected_devices ?? null) : null,
      };
    }).sort((a, b) => a.name.localeCompare(b.name));
  }

  _renderSsidPills(ssids) {
    if (!ssids || ssids.length === 0) return "";
    return html`
      <div class="rhc-ssids">
        ${ssids.map(s => html`
          <span class="rhc-ssid-pill ${s.disabled ? "rhc-ssid-off" : ""}" title="${s.disabled ? "Not available on this router" : ""}">
            ${s.disabled ? `${s.name} off` : `${s.name}${s.bandLabel ? ` ${s.bandLabel}` : ""}${s.devices != null ? ` · ${s.devices}` : ""}`}
          </span>`)}
      </div>
    `;
  }

  _renderLoadRow(r) {
    const color = this._loadColor(r.load1m);
    const pct = r.load1m != null ? Math.min((r.load1m / 2.0) * 100, 100) : 0;
    return html`
      <div class="rhc-gauge">
        <div class="rhc-gauge-bar">
          <div class="rhc-gauge-fill" style="width: ${pct}%; background: ${color};"></div>
        </div>
        <div class="rhc-gauge-label">
          <span>Load</span>
          <span>
            <span style="color: ${color}">${r.load1m != null ? r.load1m : "-"}</span>
            ${r.load5m != null ? html`<span class="rhc-load-secondary">&nbsp;5m&nbsp;${r.load5m}</span>` : ""}
            ${r.load15m != null ? html`<span class="rhc-load-secondary">&nbsp;15m&nbsp;${r.load15m}</span>` : ""}
          </span>
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
            ${r.uptime != null ? html`
              <span class="rhc-badge rhc-clickable" title="Router uptime" @click=${() => this.showMoreInfo(r.uptimeId)}>
                <ha-icon icon="mdi:timer-outline" style="--mdc-icon-size: 14px;"></ha-icon>
                ${this._formatUptime(r.uptime)}
              </span>` : ""}
          </div>
        </div>
        <div class="rhc-clickable" title="RAM usage" @click=${() => this.showMoreInfo(r.memoryUsageId)}>
          ${this._renderGauge(r.memoryUsage, 100, this._memoryColor(r.memoryUsage), "Memory", "%")}
        </div>
        ${r.load1m != null ? html`
          <div class="rhc-clickable" title="Load average" @click=${() => this.showMoreInfo(r.load1mId)}>
            ${this._renderLoadRow(r)}
          </div>` : ""}
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
        ${this._renderSsidPills(this._findSsidsForRouter(r.name))}
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
      .rhc-load-secondary { font-size: 0.85em; color: var(--secondary-text-color); }
      .rhc-traffic-row { display: flex; align-items: center; gap: 6px; font-size: 0.8em; color: var(--secondary-text-color); }
      .rhc-traffic-label { font-size: 0.85em; opacity: 0.5; margin-left: auto; }
      .rhc-version { font-size: 0.7em; color: var(--disabled-text-color, #666); text-align: right; }
      .rhc-clickable { cursor: pointer; border-radius: 6px; padding: 2px; margin: -2px; }
      .rhc-clickable:hover { background: rgba(var(--rgb-primary-color,255,255,255),0.05); }
      .rhc-ssids { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 2px; }
      .rhc-ssid-pill { font-size: 0.75em; padding: 2px 7px; border-radius: 10px; background: rgba(var(--rgb-primary-color,33,150,243),0.08); border: 1px solid rgba(var(--rgb-primary-color,33,150,243),0.2); white-space: nowrap; }
      .rhc-ssid-off { opacity: 0.45; text-decoration: line-through; }
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
      return html`<ha-card><div class="topo-empty">No routers found. Waiting for WrtManager data...</div></ha-card>`;
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

// =====================================================================
// CARD 6: Interface Health
// =====================================================================

class InterfaceHealthCard extends WrtManagerMixin(LitElement) {
  static get properties() {
    return { hass: { type: Object }, config: { type: Object }, _popover: { type: Object } };
  }

  constructor() {
    super();
    this._popover = null;
  }

  setConfig(config) { this.config = config; }
  static getConfigElement() { return document.createElement("interface-health-card-editor"); }
  static getStubConfig() { return {}; }

  _findRouters() {
    if (!this.hass) return [];
    const routers = [];
    const seen = new Set();

    for (const [id, state] of Object.entries(this.hass.states)) {
      if (!id.endsWith("_interface_health")) continue;
      if (seen.has(id)) continue;
      seen.add(id);

      let routerHost = null;
      let haDevice = null;
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

      const attrs = state.attributes || {};
      routers.push({
        entityId: id,
        routerHost,
        haDevice,
        name: haDevice?.name_by_user || haDevice?.name || attrs.friendly_name || id,
        interfaces: attrs.interfaces || [],
        routerRole: attrs.router_role || "ap",
        hasInternet: attrs.has_internet || false,
        hasDhcp: attrs.has_dhcp || false,
        interfaceCount: attrs.interface_count || 0,
        upCount: attrs.up_count || 0,
      });
    }

    // Sort: internet → dhcp → ap
    const roleOrder = { internet: 0, dhcp: 1, ap: 2 };
    routers.sort((a, b) => (roleOrder[a.routerRole] ?? 2) - (roleOrder[b.routerRole] ?? 2));
    return routers;
  }

  _formatTraffic(mb) {
    if (mb == null) return "-";
    if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
    return `${mb.toFixed(0)} MB`;
  }

  _showPopover(e, members) {
    e.stopPropagation();
    const rect = e.target.getBoundingClientRect();
    this._popover = { members, x: rect.left, y: rect.bottom + 4 };
  }

  _hidePopover() {
    this._popover = null;
  }

  _renderInterface(iface) {
    const statusClass = {
      up: "ihc-dot-up",
      no_carrier: "ihc-dot-no-carrier",
      down: "ihc-dot-down",
    }[iface.status] || "ihc-dot-down";

    const totalErrors = (iface.rx_errors || 0) + (iface.tx_errors || 0);

    const mediaIcons = [];
    if (iface.has_wired) {
      mediaIcons.push(html`
        <ha-icon icon="mdi:ethernet"
          class="ihc-media-icon"
          style="--mdc-icon-size: 14px;"
          @mouseenter=${(e) => iface.bridge_members?.length ? this._showPopover(e, iface.bridge_members) : null}
          @mouseleave=${() => this._hidePopover()}
        ></ha-icon>`);
    }
    if (iface.has_wireless) {
      mediaIcons.push(html`
        <ha-icon icon="mdi:wifi"
          class="ihc-media-icon"
          style="--mdc-icon-size: 14px;"
          @mouseenter=${(e) => iface.bridge_members?.length ? this._showPopover(e, iface.bridge_members) : null}
          @mouseleave=${() => this._hidePopover()}
        ></ha-icon>`);
    }

    const rightIndicator = iface.is_wan
      ? html`<span class="ihc-traffic">
          <ha-icon icon="mdi:arrow-down" style="--mdc-icon-size: 11px; color: #4caf50;"></ha-icon>${this._formatTraffic(iface.rx_bytes_mb)}
          <ha-icon icon="mdi:arrow-up" style="--mdc-icon-size: 11px; color: #2196f3;"></ha-icon>${this._formatTraffic(iface.tx_bytes_mb)}
        </span>`
      : iface.device_count != null
        ? html`<span class="ihc-device-count">${iface.device_count} ⬡</span>`
        : html``;

    return html`
      <div class="ihc-iface-row">
        <span class="ihc-dot ${statusClass}"></span>
        <span class="ihc-logical-name">${iface.logical_name}</span>
        <span class="ihc-ip">${iface.ip || "—"}</span>
        <span class="ihc-phys-name">${iface.physical_name}</span>
        <span class="ihc-media-icons">${mediaIcons}</span>
        <span class="ihc-right">
          ${totalErrors > 0 ? html`<span class="ihc-errors">⚠ ${totalErrors}err</span>` : ""}
          ${rightIndicator}
        </span>
      </div>
    `;
  }

  _renderRouter(r) {
    const icon = (r.routerRole === "ap") ? "mdi:access-point" : "mdi:router-wireless";
    const badges = [];
    if (r.hasInternet) badges.push(html`<span class="ihc-role-badge ihc-role-internet">INTERNET</span>`);
    if (r.hasDhcp) badges.push(html`<span class="ihc-role-badge ihc-role-dhcp">DHCP</span>`);
    if (!r.hasInternet && !r.hasDhcp) badges.push(html`<span class="ihc-role-badge ihc-role-ap">AP</span>`);

    return html`
      <div class="ihc-router">
        <div class="ihc-router-header">
          <div class="ihc-router-title">
            <ha-icon icon="${icon}" style="--mdc-icon-size: 18px; color: var(--primary-color);"></ha-icon>
            <span class="ihc-router-name">${r.name}</span>
          </div>
          <div class="ihc-router-badges">${badges}</div>
        </div>
        <div class="ihc-divider"></div>
        ${r.interfaces.length === 0
          ? html`<div class="ihc-empty">No interface data</div>`
          : r.interfaces.map((iface) => this._renderInterface(iface))
        }
      </div>
    `;
  }

  render() {
    const routers = this._findRouters();
    if (routers.length === 0) {
      return html`<ha-card><div class="ihc" style="text-align:center;padding:24px;color:var(--secondary-text-color);">No interface data</div></ha-card>`;
    }

    return html`
      <ha-card>
        <div class="ihc">
          <div class="ihc-header">
            <ha-icon icon="mdi:lan" style="--mdc-icon-size: 20px;"></ha-icon>
            Interface Health
            <span class="ihc-count">(${routers.length})</span>
          </div>
          <div class="ihc-grid">${routers.map((r) => this._renderRouter(r))}</div>
        </div>
        ${this._popover ? html`
          <div class="ihc-popover" style="left:${this._popover.x}px;top:${this._popover.y}px;" @mouseleave=${() => this._hidePopover()}>
            <div class="ihc-popover-title">Bridge members</div>
            ${this._popover.members.map((m) => {
              const isWifi = (m.includes("phy") && m.includes("ap")) || m.startsWith("wlan");
              const band = m.startsWith("phy0") ? "2.4 GHz" : m.startsWith("phy1") ? "5 GHz" : "";
              return html`<div class="ihc-popover-member">
                <ha-icon icon=${isWifi ? "mdi:wifi" : "mdi:ethernet"} style="--mdc-icon-size: 13px;"></ha-icon>
                <span>${m}</span>
                ${band ? html`<span class="ihc-popover-band">${band}</span>` : ""}
              </div>`;
            })}
          </div>` : ""}
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      .ihc { padding: 16px; }
      .ihc-header { font-size: 1.1em; font-weight: 500; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
      .ihc-count { color: var(--secondary-text-color); font-weight: normal; font-size: 0.85em; }
      .ihc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
      .ihc-router { background: var(--input-fill-color, rgba(255,255,255,0.04)); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; gap: 6px; }
      .ihc-router-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
      .ihc-router-title { display: flex; align-items: center; gap: 6px; min-width: 0; }
      .ihc-router-name { font-weight: 500; font-size: 0.95em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .ihc-router-badges { display: flex; gap: 4px; flex-shrink: 0; }
      .ihc-role-badge { font-size: 0.7em; padding: 1px 5px; border-radius: 4px; font-weight: 600; }
      .ihc-role-internet { background: var(--primary-color); color: white; }
      .ihc-role-dhcp { background: rgba(var(--rgb-primary-color, 3,169,244), 0.2); color: var(--primary-color); }
      .ihc-role-ap { background: rgba(255,255,255,0.08); color: var(--secondary-text-color); }
      .ihc-divider { height: 1px; background: var(--divider-color, rgba(255,255,255,0.1)); margin: 4px 0; }
      .ihc-iface-row { display: flex; align-items: center; gap: 6px; padding: 3px 0; font-size: 0.82em; flex-wrap: wrap; }
      .ihc-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
      .ihc-dot-up { background: #4caf50; }
      .ihc-dot-no-carrier { background: #ff9800; }
      .ihc-dot-down { background: #f44336; }
      .ihc-logical-name { font-weight: 500; min-width: 40px; }
      .ihc-ip { font-family: monospace; color: var(--secondary-text-color); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .ihc-phys-name { font-size: 0.88em; color: var(--disabled-text-color, #888); white-space: nowrap; }
      .ihc-media-icons { display: flex; gap: 2px; color: var(--secondary-text-color); }
      .ihc-media-icon { cursor: default; }
      .ihc-right { display: flex; align-items: center; gap: 4px; margin-left: auto; flex-shrink: 0; }
      .ihc-traffic { display: flex; align-items: center; gap: 3px; font-size: 0.88em; color: var(--secondary-text-color); }
      .ihc-device-count { font-size: 0.88em; color: var(--secondary-text-color); }
      .ihc-errors { font-size: 0.82em; color: #ff9800; }
      .ihc-empty { color: var(--secondary-text-color); font-size: 0.9em; padding: 4px 0; }
      .ihc-popover { position: fixed; background: var(--card-background-color, #1c1c1c); border: 1px solid var(--divider-color); border-radius: 8px; padding: 8px 10px; font-size: 0.82em; z-index: 9999; min-width: 160px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
      .ihc-popover-title { font-weight: 600; margin-bottom: 6px; color: var(--primary-text-color); }
      .ihc-popover-member { display: flex; align-items: center; gap: 6px; padding: 2px 0; color: var(--secondary-text-color); }
      .ihc-popover-band { font-size: 0.85em; color: var(--disabled-text-color, #888); margin-left: auto; }
    `;
  }

  getCardSize() { return 5; }
}

class InterfaceHealthCardEditor extends LitElement {
  static get properties() { return { hass: { type: Object }, _config: { type: Object } }; }
  setConfig(config) { this._config = config; }
  render() {
    return html`<div style="padding:16px;"><p style="color:var(--secondary-text-color);font-size:0.9em;">Shows all network interfaces per router with status, IP address, media type, and health indicators. Routers are sorted by role: Internet → DHCP → AP.</p></div>`;
  }
}

customElements.define("interface-health-card", InterfaceHealthCard);
customElements.define("interface-health-card-editor", InterfaceHealthCardEditor);

// =====================================================================
// CARD 7: WiFi Networks
// =====================================================================

class WifiNetworksCard extends WrtManagerMixin(LitElement) {
  static get properties() {
    return { hass: { type: Object }, config: { type: Object } };
  }

  setConfig(config) { this.config = config; }

  static getConfigElement() {
    return document.createElement("wifi-networks-card-editor");
  }

  static getStubConfig() { return {}; }

  _findSsids() {
    if (!this.hass) return [];
    const ssids = [];
    for (const [, state] of Object.entries(this.hass.states)) {
      const attrs = state.attributes || {};
      if (!attrs.ssid_name || attrs.coverage !== "Global (all routers)") continue;
      ssids.push(attrs);
    }
    return ssids.sort((a, b) => a.ssid_name.localeCompare(b.ssid_name));
  }

  _getAllRouterNames(ssids) {
    const all = new Set();
    for (const s of ssids) {
      for (const r of (s.enabled_routers || [])) all.add(r);
      for (const r of (s.disabled_routers || [])) all.add(r);
    }
    return all;
  }

  _encLabel(enc) {
    if (!enc || enc === "none" || enc === "") return "Open";
    if (enc === "sae" || enc === "sae-mixed") return "WPA3";
    if (enc === "psk2") return "WPA2";
    if (enc === "psk") return "WPA";
    return enc;
  }

  _statusDot(ssid, totalRouters) {
    const enabled = (ssid.enabled_routers || []).length;
    const disabled = (ssid.disabled_routers || []).length;
    const total = totalRouters || (enabled + disabled);
    if (enabled === 0) return { icon: "○", color: "#f44336", title: "Disabled on all routers" };
    if (enabled === total && disabled === 0) return { icon: "●", color: "#4caf50", title: "Enabled on all routers" };
    return { icon: "◑", color: "#ff9800", title: `Enabled: ${enabled} of ${total} routers` };
  }

  _renderSsid(ssid, allRouterNames) {
    const dot = this._statusDot(ssid, allRouterNames ? allRouterNames.size : undefined);
    const enc = this._encLabel(ssid.encryption);
    const isOpen = enc === "Open";
    const bands = ssid.frequency_bands || [];
    const has24 = bands.includes("2.4GHz");
    const has5 = bands.includes("5GHz");
    const deviceCount = ssid.connected_devices ?? "-";
    const enabledSet = new Set(ssid.enabled_routers || []);
    const disabledSet = new Set(ssid.disabled_routers || []);
    // All known routers: show ✓ for enabled, ✗ for disabled or unconfigured
    const routersToShow = allRouterNames && allRouterNames.size > 0 ? allRouterNames : new Set([...enabledSet, ...disabledSet]);

    return html`
      <div class="wnc-row">
        <div class="wnc-cell wnc-status" title="${dot.title}" style="color: ${dot.color};">${dot.icon}</div>
        <div class="wnc-cell wnc-name">
          <span class="wnc-ssid-name">${ssid.ssid_name}</span>
          ${routersToShow.size > 0 ? html`
            <div class="wnc-router-chips">
              ${[...routersToShow].sort().map(r => enabledSet.has(r)
                ? html`<span class="wnc-chip wnc-chip-on" title="Enabled on ${r}">✓ ${r}</span>`
                : html`<span class="wnc-chip wnc-chip-off" title="${disabledSet.has(r) ? "Disabled" : "Not configured"} on ${r}">✗ ${r}</span>`
              )}
            </div>` : ""}
        </div>
        <div class="wnc-cell wnc-bands">
          ${has24 ? html`<span class="wnc-band wnc-band-24">2.4</span>` : ""}
          ${has5 ? html`<span class="wnc-band wnc-band-5">5GHz</span>` : ""}
        </div>
        <div class="wnc-cell wnc-enc" style="${isOpen ? "color: #f44336;" : ""}">${enc}</div>
        <div class="wnc-cell wnc-hidden">
          ${ssid.hidden ? html`<ha-icon icon="mdi:eye-off" style="--mdc-icon-size: 14px; color: var(--secondary-text-color);"></ha-icon>` : html`<span style="color: var(--disabled-text-color, #888);">-</span>`}
        </div>
        <div class="wnc-cell wnc-devices">${deviceCount}</div>
      </div>
    `;
  }

  render() {
    const ssids = this._findSsids();
    const allRouterNames = this._getAllRouterNames(ssids);
    return html`
      <ha-card>
        <div class="wnc">
          <div class="wnc-header">
            <ha-icon icon="mdi:wifi-settings" style="--mdc-icon-size: 20px;"></ha-icon>
            WiFi Networks
            <span class="wnc-count">(${ssids.length})</span>
          </div>
          ${ssids.length === 0 ? html`<div class="wnc-empty">No SSIDs found. Check that WrtManager routers are accessible.</div>` : html`
            <div class="wnc-table">
              <div class="wnc-thead">
                <div class="wnc-cell wnc-status"></div>
                <div class="wnc-cell wnc-name">SSID</div>
                <div class="wnc-cell wnc-bands">Bands</div>
                <div class="wnc-cell wnc-enc">Security</div>
                <div class="wnc-cell wnc-hidden">Hidden</div>
                <div class="wnc-cell wnc-devices">Devices</div>
              </div>
              <div class="wnc-tbody">
                ${ssids.map((s, i) => html`<div class="${i % 2 === 1 ? "wnc-alt" : ""}">${this._renderSsid(s, allRouterNames)}</div>`)}
              </div>
            </div>
            <div class="wnc-legend">
              <span style="color:#4caf50;">●</span> all enabled &nbsp;
              <span style="color:#ff9800;">◑</span> partial &nbsp;
              <span style="color:#f44336;">○</span> all disabled
            </div>
          `}
        </div>
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      .wnc { padding: 16px; }
      .wnc-header { font-size: 1.1em; font-weight: 500; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
      .wnc-count { color: var(--secondary-text-color); font-weight: normal; font-size: 0.85em; }
      .wnc-empty { color: var(--secondary-text-color); font-size: 0.9em; text-align: center; padding: 16px 0; }
      .wnc-table { max-height: 400px; overflow-y: auto; }
      .wnc-thead { display: grid; grid-template-columns: 20px 1fr auto auto auto auto; gap: 8px; padding: 4px 6px 6px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.12)); font-size: 0.75em; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: 0.04em; }
      .wnc-row { display: grid; grid-template-columns: 20px 1fr auto auto auto auto; gap: 8px; padding: 6px; align-items: start; }
      .wnc-alt .wnc-row { background: rgba(var(--rgb-primary-color,33,150,243),0.04); border-radius: 6px; }
      .wnc-cell { display: flex; align-items: center; }
      .wnc-status { font-size: 1.1em; justify-content: center; padding-top: 2px; }
      .wnc-name { flex-direction: column; align-items: flex-start; gap: 3px; min-width: 0; }
      .wnc-ssid-name { font-weight: 500; font-size: 0.9em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; }
      .wnc-router-chips { display: flex; flex-wrap: wrap; gap: 4px; }
      .wnc-chip { font-size: 0.7em; color: var(--secondary-text-color); }
      .wnc-chip-on { color: var(--secondary-text-color); }
      .wnc-chip-off { color: #f44336; opacity: 0.8; }
      .wnc-bands { gap: 3px; }
      .wnc-band { font-size: 0.7em; padding: 1px 5px; border-radius: 4px; white-space: nowrap; }
      .wnc-band-24 { background: rgba(33,150,243,0.15); color: #2196f3; border: 1px solid rgba(33,150,243,0.3); }
      .wnc-band-5 { background: rgba(156,39,176,0.15); color: #9c27b0; border: 1px solid rgba(156,39,176,0.3); }
      .wnc-enc { font-size: 0.8em; white-space: nowrap; }
      .wnc-hidden { justify-content: center; }
      .wnc-devices { font-size: 0.85em; font-variant-numeric: tabular-nums; justify-content: flex-end; min-width: 40px; }
      .wnc-legend { font-size: 0.72em; color: var(--secondary-text-color); margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--divider-color, rgba(255,255,255,0.08)); }
    `;
  }

  getCardSize() { return 4; }
}

class WifiNetworksCardEditor extends LitElement {
  static get properties() { return { hass: { type: Object }, _config: { type: Object } }; }
  setConfig(config) { this._config = config; }
  render() {
    return html`<div style="padding:16px;"><p style="color:var(--secondary-text-color);font-size:0.9em;">Shows all SSIDs with enabled/disabled status per router, frequency bands, encryption type, hidden flag, and connected device count.</p></div>`;
  }
}

customElements.define("wifi-networks-card", WifiNetworksCard);
customElements.define("wifi-networks-card-editor", WifiNetworksCardEditor);

// ─── Card registration ───────────────────────────────────────────────

window.customCards = window.customCards || [];
window.customCards.push(
  { type: "network-devices-card", name: "Network Devices", description: "All network clients — WiFi grouped by AP with signal/disconnect, wired clients grouped by network segment", preview: true },
  { type: "router-health-card", name: "Router Health", description: "Router health overview with memory, load, devices, temperature, traffic", preview: true },
  { type: "network-topology-card", name: "Network Topology", description: "Visual network topology with signal quality color coding", preview: true },
  { type: "signal-heatmap-card", name: "Signal Heatmap", description: "Signal strength list with quality filtering and sorting", preview: true },
  { type: "roaming-activity-card", name: "Roaming Activity", description: "Track device roaming between access points with live event log", preview: true },
  { type: "interface-health-card", name: "Interface Health", description: "Network interface status per router with IP, media type, and health indicators", preview: true },
  { type: "wifi-networks-card", name: "WiFi Networks", description: "SSID overview with per-router status and device counts", preview: true },
);

console.info("%c WrtManager Cards ", "background: #03a9f4; color: white; font-weight: bold;");
