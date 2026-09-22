/**
 * Alarm Center card - a condensed alarm list for dashboards.
 *
 * Plain custom element, no build step, same reasoning as panel.js: native
 * form controls where config needs them, ha-card/ha-icon with CSS fallbacks
 * for everything else. Registered automatically by the integration via
 * frontend.add_extra_module_url, so no manual dashboard resource is needed.
 */

const LEVEL_ICON = {
  critical: "mdi:alert-octagon",
  error: "mdi:alert-circle",
  warning: "mdi:alert",
  notice: "mdi:information-outline",
};

const LEVEL_ORDER = { critical: 0, error: 1, warning: 2, notice: 3 };

const esc = (value) =>
  String(value === undefined || value === null ? "" : value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

class AlarmCenterCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._alarms = [];
    this._config = {};
  }

  // Lovelace calls this with the YAML config before hass is set.
  setConfig(config) {
    this._config = {
      title: "Alarms",
      max_items: 5,
      show_acknowledged: true,
      levels: null, // null = all levels
      show_ack_button: true,
      tap_action: "more-info", // "more-info" | "panel" | "none"
      ...config,
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._subscribed) {
      this._subscribed = true;
      this._subscribe();
    }
  }

  getCardSize() {
    return 1 + Math.min(this._config.max_items || 5, this._visibleAlarms().length || 1);
  }

  static getStubConfig() {
    return { title: "Alarms", max_items: 5 };
  }

  connectedCallback() {
    if (this._hass && !this._subscribed) {
      this._subscribed = true;
      this._subscribe();
    }
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((unsub) => unsub());
      this._unsub = null;
      this._subscribed = false;
    }
  }

  _subscribe() {
    this._unsub = this._hass.connection.subscribeMessage(
      (msg) => {
        this._alarms = msg.alarms || [];
        this._render();
      },
      { type: "alarm_center/subscribe" }
    );
  }

  _visibleAlarms() {
    let alarms = this._alarms;
    if (!this._config.show_acknowledged) {
      alarms = alarms.filter((a) => !a.acknowledged);
    }
    if (this._config.levels && this._config.levels.length) {
      const allowed = new Set(this._config.levels);
      alarms = alarms.filter((a) => allowed.has(a.level));
    }
    // The subscription already sorts unacked-first, most severe first, but
    // re-sort defensively in case a future server version changes that.
    alarms = [...alarms].sort(
      (a, b) =>
        Number(a.acknowledged) - Number(b.acknowledged) ||
        (LEVEL_ORDER[a.level] ?? 9) - (LEVEL_ORDER[b.level] ?? 9) ||
        new Date(b.last_activated_at) - new Date(a.last_activated_at)
    );
    return alarms.slice(0, this._config.max_items || 5);
  }

  _render() {
    if (!this.shadowRoot) return;
    const alarms = this._visibleAlarms();
    const total = this._alarms.length;
    const shown = alarms.length;
    const unacked = this._alarms.filter((a) => !a.acknowledged).length;

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="head">
          <div class="title">${esc(this._config.title || "Alarms")}</div>
          ${unacked
        ? `<span class="pill">${unacked} unacknowledged</span>`
        : total
          ? `<span class="pill pill-ok">All acknowledged</span>`
          : ""
      }
        </div>
        ${shown
        ? `<div class="list">${alarms.map((a) => this._row(a)).join("")}</div>`
        : `<div class="empty">No alarms${this._config.show_acknowledged ? "" : " pending"
        }.</div>`
      }
        ${total > shown
        ? `<div class="more">+${total - shown} more</div>`
        : ""
      }
      </ha-card>
    `;

    this.shadowRoot.querySelector("ha-card").addEventListener("click", (ev) =>
      this._handleClick(ev)
    );
  }

  _row(alarm) {
    const acked = alarm.acknowledged;
    return `
      <div class="row ${acked ? "acked" : ""} ${alarm.active ? "" : "inactive"
      }" data-row="${esc(alarm.id)}" data-entity="${esc(alarm.entity_id || "")}">
        <ha-icon class="lvl level-${esc(alarm.level)}" icon="${LEVEL_ICON[alarm.level] || "mdi:alert"
      }"></ha-icon>
        <div class="name">${esc(alarm.name)}</div>
        ${!acked && this._config.show_ack_button
        ? `<button class="ack" data-ack="${esc(alarm.id)}">Ack</button>`
        : `<span class="dot ${alarm.active ? "" : "dim"}"></span>`
      }
      </div>
    `;
  }

  async _handleClick(ev) {
    const ackBtn = ev.target.closest("[data-ack]");
    if (ackBtn) {
      ev.stopPropagation();
      try {
        await this._hass.callWS({
          type: "alarm_center/acknowledge",
          alarm_id: ackBtn.dataset.ack,
        });
      } catch (err) {
        /* the next push from the subscription will reflect reality either way */
      }
      return;
    }

    const row = ev.target.closest("[data-row]");
    if (!row || this._config.tap_action === "none") return;

    if (this._config.tap_action === "panel") {
      history.pushState(null, "", "/alarm-center");
      this.dispatchEvent(
        new CustomEvent("location-changed", { bubbles: true, composed: true })
      );
      return;
    }

    const entityId = row.dataset.entity;
    if (entityId) {
      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          detail: { entityId },
          bubbles: true,
          composed: true,
        })
      );
    }
  }
}

const STYLES = `
:host { display: block; }
ha-card { padding: 4px 0; }
.head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px 4px;
}
.title { font-size: 16px; font-weight: 500; flex: 1; }
.pill {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--warning-color, #ffa600);
  color: #000;
}
.pill-ok {
  background: transparent;
  color: var(--secondary-text-color);
}
.list > *:not(:last-child) { border-bottom: 1px solid var(--divider-color); }
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 16px;
  cursor: pointer;
}
.row:hover { background: var(--secondary-background-color); }
.lvl { --mdc-icon-size: 20px; flex: none; }
.level-critical, .level-error { color: var(--error-color, #db4437); }
.level-warning { color: var(--warning-color, #ffa600); }
.level-notice { color: var(--info-color, #039be5); }
.name {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row.acked { opacity: .55; }
.row.acked .lvl { color: var(--secondary-text-color); }
.row.inactive .name { font-style: italic; }
.dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--error-color, #db4437);
  flex: none;
}
.dot.dim { background: var(--divider-color); }
.ack {
  border: none;
  border-radius: 4px;
  background: none;
  color: var(--primary-color);
  font-size: 12px;
  font-weight: 500;
  padding: 4px 8px;
  cursor: pointer;
  flex: none;
}
.ack:hover { background: var(--secondary-background-color); }
.empty {
  padding: 16px;
  text-align: center;
  color: var(--secondary-text-color);
  font-size: 14px;
}
.more {
  padding: 4px 16px 8px;
  font-size: 12px;
  color: var(--secondary-text-color);
  text-align: right;
}
/* Works even if ha-card has not been loaded by the frontend yet. */
ha-card:not(:defined) {
  display: block;
  background: var(--ha-card-background, var(--card-background-color, #fff));
  border-radius: var(--ha-card-border-radius, 12px);
  box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0,0,0,.14));
}
`;

const CARD_TYPE = "alarm-center-card";

if (!customElements.get(CARD_TYPE)) {
  customElements.define(CARD_TYPE, AlarmCenterCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
  window.customCards.push({
    type: CARD_TYPE,
    name: "Alarm Center",
    description: "A condensed alarm list from Alarm Center.",
  });
}
