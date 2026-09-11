/**
 * Alarm Center panel.
 *
 * Plain custom element - no build step. Form controls are native elements
 * styled with the theme's CSS variables, because Home Assistant lazy loads
 * ha-textfield and friends and they are not guaranteed to be defined here.
 * ha-card, ha-icon and ha-icon-button are used where they are reliable, with
 * CSS fallbacks, and ha-entity-picker is used when the frontend has loaded it.
 */

const LEVELS = ["critical", "error", "warning", "notice"];

const LEVEL_LABEL = {
  critical: "Critical",
  error: "Error",
  warning: "Warning",
  notice: "Notice",
};

const TTS_STREAM_LABEL = {
  off: "Off",
  alarm_stream: "Alarm stream",
  alarm_stream_max: "Alarm stream (max volume)",
};

const LEVEL_ICON = {
  critical: "mdi:alert-octagon",
  error: "mdi:alert-circle",
  warning: "mdi:alert",
  notice: "mdi:information-outline",
};

const KIND_LABEL = {
  problem: "Problem entity",
  numeric: "Numeric value",
  state: "State",
  template: "Template",
};

const VIEWS = [
  { id: "alarms", label: "Alarms", icon: "mdi:alarm-light" },
  { id: "history", label: "History", icon: "mdi:history" },
  { id: "rules", label: "Rules", icon: "mdi:playlist-check" },
  { id: "settings", label: "Settings", icon: "mdi:cog" },
];

const ACTION_SELECTOR = [
  "[data-ack]",
  "[data-ack-all]",
  "[data-more]",
  "[data-edit]",
  "[data-delete]",
  "[data-new-rule]",
  "[data-cancel]",
  "[data-save-rule]",
  "[data-save-settings]",
  "[data-show-trash]",
  "[data-hide-trash]",
  "[data-restore]",
  "[data-purge]",
].join(",");

const esc = (value) =>
  String(value === undefined || value === null ? "" : value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

class AlarmCenterPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._view = "alarms";
    this._alarms = [];
    this._counts = {};
    this._rules = [];
    this._trash = [];
    this._showTrash = false;
    this._history = [];
    this._config = null;
    this._people = [];
    this._editing = null;
    this._ready = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._ready) {
      this._ready = true;
      this._setup();
    }
  }

  set narrow(value) {
    this._narrow = value;
    if (this.shadowRoot.host) this.toggleAttribute("narrow", !!value);
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((unsub) => unsub());
      this._unsub = null;
    }
  }

  // -- setup -----------------------------------------------------------

  async _setup() {
    await this._loadHaComponents();
    this._renderShell();
    this._unsub = this._hass.connection.subscribeMessage(
      (msg) => {
        this._alarms = msg.alarms || [];
        this._counts = msg.counts || {};
        if (this._view === "alarms") this._renderView();
        this._renderCounts();
      },
      { type: "alarm_center/subscribe" }
    );
    await this._loadRules();
    await this._loadTrash();
    await this._loadConfig();
  }

  /**
   * Home Assistant lazy loads most of its form elements. Creating a card and
   * asking for its config element pulls in that bundle, which is what defines
   * ha-entity-picker. Everything below still works if this fails - the inputs
   * are native elements and the entity field falls back to a datalist.
   */
  async _loadHaComponents() {
    try {
      const helpers = await window.loadCardHelpers();
      const card = await helpers.createCardElement({ type: "entities", entities: [] });
      if (card && card.constructor.getConfigElement) {
        await card.constructor.getConfigElement();
      }
    } catch (err) {
      /* ignore - fallbacks handle it */
    }
  }

  _call(type, payload = {}) {
    return this._hass.callWS({ type, ...payload });
  }

  async _loadRules() {
    const res = await this._call("alarm_center/rules");
    this._rules = res.rules || [];
    if (this._view === "rules") this._renderView();
  }

  async _loadTrash() {
    const res = await this._call("alarm_center/rules/trash");
    this._trash = res.trash || [];
    if (this._view === "rules") this._renderView();
  }

  async _loadConfig() {
    this._config = await this._call("alarm_center/config");
    const res = await this._call("alarm_center/notify_targets");
    this._people = res.targets || [];
    if (this._view === "settings") this._renderView();
  }

  async _loadHistory() {
    const res = await this._call("alarm_center/history", { limit: 200 });
    this._history = res.history || [];
    if (this._view === "history") this._renderView();
  }

  // -- shell -----------------------------------------------------------

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="header">
        <ha-icon-button class="menu" label="Menu">
          <ha-icon icon="mdi:menu"></ha-icon>
        </ha-icon-button>
        <div class="title">Alarm Center</div>
        <div class="counts" id="counts"></div>
      </div>
      <div class="tabs" id="tabs">
        ${VIEWS.map(
          (v) => `<button class="tab" data-view="${v.id}">
             <ha-icon icon="${v.icon}"></ha-icon><span>${v.label}</span>
           </button>`
        ).join("")}
      </div>
      <div class="error" id="error" hidden></div>
      <div class="content" id="content"></div>
    `;

    this.shadowRoot.querySelector(".menu").addEventListener("click", () => {
      this.dispatchEvent(
        new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true })
      );
    });

    this.shadowRoot.querySelector("#tabs").addEventListener("click", (ev) => {
      const tab = ev.target.closest(".tab");
      if (!tab) return;
      this._view = tab.dataset.view;
      this._editing = null;
      if (this._view === "history") this._loadHistory();
      this._renderView();
    });

    const content = this.shadowRoot.querySelector("#content");
    content.addEventListener("click", (ev) => this._handleClick(ev));
    content.addEventListener("change", (ev) => this._handleChange(ev));

    this._renderView();
    this._renderCounts();
  }

  _renderCounts() {
    const el = this.shadowRoot.querySelector("#counts");
    if (!el) return;
    const active = this._counts.active || 0;
    const unacked = this._counts.unacknowledged || 0;
    el.innerHTML = `
      <span class="pill ${active ? "pill-active" : ""}">${active} active</span>
      <span class="pill ${unacked ? "pill-unacked" : ""}">${unacked} unacknowledged</span>
    `;
  }

  _renderView() {
    const content = this.shadowRoot.querySelector("#content");
    if (!content) return;
    this.shadowRoot.querySelectorAll(".tab").forEach((tab) => {
      tab.classList.toggle("selected", tab.dataset.view === this._view);
    });

    let html = "";
    if (this._view === "alarms") html += this._alarmsView();
    else if (this._view === "history") html += this._historyView();
    else if (this._view === "rules") html += this._rulesView();
    else html += this._settingsView();
    content.innerHTML = html;
    this._hydrate();
  }

  get _isAdmin() {
    return !!(this._hass && this._hass.user && this._hass.user.is_admin);
  }

  // -- alarms ----------------------------------------------------------

  _alarmsView() {
    if (!this._alarms.length) {
      return `<ha-card class="empty">
        <ha-icon icon="mdi:check-circle-outline"></ha-icon>
        <p>No alarms right now.</p>
      </ha-card>`;
    }
    const unacked = this._alarms.filter((a) => !a.acknowledged).length;
    return `
      ${
        unacked > 1
          ? `<div class="toolbar"><button class="btn" data-ack-all>Acknowledge all (${unacked})</button></div>`
          : ""
      }
      <ha-card>
        <div class="list">
          ${this._alarms.map((a) => this._alarmRow(a)).join("")}
        </div>
      </ha-card>
    `;
  }

  _alarmRow(alarm) {
    const acked = alarm.acknowledged;
    const meta = [];
    meta.push(`Active since ${this._formatTime(alarm.activated_at)}`);
    if (!alarm.active && alarm.deactivated_at) {
      meta.push(`Inactive since ${this._formatTime(alarm.deactivated_at)}`);
    }
    if (alarm.activation_count > 1) {
      meta.push(`${alarm.activation_count} activations`);
    }
    if (acked) {
      meta.push(
        `Acknowledged by ${esc(alarm.acknowledged_by_name || "unknown")} ${this._formatTime(
          alarm.acknowledged_at
        )}`
      );
    }

    return `
      <div class="alarm level-${esc(alarm.level)} ${acked ? "acked" : ""} ${
        alarm.active ? "" : "inactive"
      }">
        <div class="stripe"></div>
        <ha-icon class="lvl" icon="${LEVEL_ICON[alarm.level] || "mdi:alert"}"></ha-icon>
        <div class="body">
          <div class="name">${esc(alarm.name)}</div>
          <div class="meta">${meta.map(esc).join(" · ")}</div>
          ${alarm.message ? `<div class="msg">${esc(alarm.message)}</div>` : ""}
        </div>
        <div class="badges">
          ${
            alarm.active
              ? `<span class="badge badge-active">Active</span>`
              : `<span class="badge">Inactive</span>`
          }
        </div>
        <div class="actions">
          ${
            acked
              ? ""
              : `<button class="btn" data-ack="${esc(alarm.id)}">Acknowledge</button>`
          }
          ${
            alarm.entity_id
              ? `<ha-icon-button data-more="${esc(
                  alarm.entity_id
                )}" label="Show entity"><ha-icon icon="mdi:open-in-new"></ha-icon></ha-icon-button>`
              : ""
          }
        </div>
      </div>
    `;
  }

  // -- history ---------------------------------------------------------

  _historyView() {
    if (!this._history.length) {
      return `<ha-card class="empty"><p>History is empty.</p></ha-card>`;
    }
    return `<ha-card><div class="list">
      ${this._history
        .map(
          (a) => `
        <div class="alarm level-${esc(a.level)} acked">
          <div class="stripe"></div>
          <ha-icon class="lvl" icon="${LEVEL_ICON[a.level] || "mdi:alert"}"></ha-icon>
          <div class="body">
            <div class="name">${esc(a.name)}</div>
            <div class="meta">${esc(
              `${this._formatTime(a.activated_at)} – ${this._formatTime(
                a.deactivated_at
              )} · acknowledged by ${a.acknowledged_by_name || "unknown"}`
            )}</div>
          </div>
          <div class="badges"><span class="badge">${esc(
            LEVEL_LABEL[a.level] || a.level
          )}</span></div>
        </div>`
        )
        .join("")}
    </div></ha-card>`;
  }

  // -- rules -----------------------------------------------------------

  _rulesView() {
    if (this._editing) return this._ruleEditor(this._editing);
    if (this._showTrash) return this._trashView();

    const rows = this._rules
      .map(
        (rule) => `
      <div class="rule ${rule.enabled ? "" : "disabled"}">
        <input type="checkbox" class="toggle" data-toggle="${esc(rule.id)}" ${
          rule.enabled ? "checked" : ""
        } ${this._isAdmin ? "" : "disabled"} title="${
          rule.enabled ? "Monitoring" : "Disabled"
        }">
        <div class="body">
          <div class="name">${esc(rule.name)}
            ${rule.auto ? `<span class="chip">auto</span>` : ""}
            <span class="chip chip-${esc(rule.level)}">${esc(
              LEVEL_LABEL[rule.level] || rule.level
            )}</span>
          </div>
          <div class="meta">${esc(this._ruleSummary(rule))}</div>
        </div>
        <div class="actions">
          ${
            this._isAdmin
              ? `<ha-icon-button data-edit="${esc(
                  rule.id
                )}" label="Edit"><ha-icon icon="mdi:pencil"></ha-icon></ha-icon-button>
                 <ha-icon-button data-delete="${esc(
                   rule.id
                 )}" label="Delete"><ha-icon icon="mdi:delete"></ha-icon></ha-icon-button>`
              : ""
          }
        </div>
      </div>`
      )
      .join("");

    return `
      <div class="toolbar">
        ${
          this._isAdmin
            ? `<button class="btn" data-new-rule>New rule</button>`
            : "<span></span>"
        }
        <button class="btn ghost" data-show-trash>
          <ha-icon icon="mdi:trash-can-outline"></ha-icon> Trash${
            this._trash.length ? ` (${this._trash.length})` : ""
          }
        </button>
      </div>
      <ha-card><div class="list">${
        rows || `<div class="empty"><p>No rules yet.</p></div>`
      }</div></ha-card>
      <p class="hint">Rules for problem entities are created automatically.
      Turn a rule off to stop monitoring the entity without deleting it.</p>
    `;
  }

  _trashView() {
    const rows = this._trash
      .map(
        (rule) => `
      <div class="rule">
        <div class="body">
          <div class="name">${esc(rule.name)}
            ${rule.auto ? `<span class="chip">auto</span>` : ""}
            <span class="chip chip-${esc(rule.level)}">${esc(
              LEVEL_LABEL[rule.level] || rule.level
            )}</span>
          </div>
          <div class="meta">${esc(this._ruleSummary(rule))} · deleted ${this._formatTime(
            rule.deleted_at
          )}</div>
        </div>
        <div class="actions">
          ${
            this._isAdmin
              ? `<button class="btn" data-restore="${esc(rule.id)}">Restore</button>
                 <ha-icon-button data-purge="${esc(
                   rule.id
                 )}" label="Delete permanently"><ha-icon icon="mdi:delete-forever"></ha-icon></ha-icon-button>`
              : ""
          }
        </div>
      </div>`
      )
      .join("");

    return `
      <div class="toolbar">
        <button class="btn ghost" data-hide-trash>
          <ha-icon icon="mdi:arrow-left"></ha-icon> Back to rules
        </button>
      </div>
      <ha-card><div class="list">${
        rows || `<div class="empty"><p>Trash is empty.</p></div>`
      }</div></ha-card>
      <p class="hint">Deleted rules are kept here so they can be restored -
      including automatically generated ones for problem entities, which
      would otherwise be recreated the next time they're seen. Nothing here
      is removed permanently unless you choose to.</p>
    `;
  }

  _ruleSummary(rule) {
    const parts = [KIND_LABEL[rule.kind] || rule.kind];
    if (rule.entity_id) parts.push(rule.entity_id);
    if (rule.kind === "numeric") {
      if (rule.above !== null && rule.above !== undefined)
        parts.push(`above ${rule.above}`);
      if (rule.below !== null && rule.below !== undefined)
        parts.push(`below ${rule.below}`);
      if (rule.hysteresis) parts.push(`hysteresis ${rule.hysteresis}`);
    }
    if (rule.kind === "template") parts.push(rule.template || "");
    if (rule.for_seconds) parts.push(`after ${rule.for_seconds}s`);
    if ((rule.on_acknowledge || []).length)
      parts.push(`${rule.on_acknowledge.length} action(s) on acknowledge`);
    return parts.filter(Boolean).join(" · ");
  }

  _ruleEditor(rule) {
    const kind = rule.kind || "problem";
    const ackText =
      rule._ackRaw !== undefined
        ? rule._ackRaw
        : JSON.stringify(rule.on_acknowledge || [], null, 2);

    let condition = "";
    if (kind === "template") {
      condition = `
        <div class="field">
          <label class="lbl" for="f-template">Template</label>
          <textarea id="f-template" class="code" rows="3" spellcheck="false"
            placeholder="{{ states('sensor.battery') | float(100) < 20 }}">${esc(
              rule.template || ""
            )}</textarea>
          <div class="hint inline">Jinja that should evaluate to true or
          false. The alarm follows the result, and entities used in the
          template are tracked automatically.</div>
        </div>`;
    } else {
      condition = this._entityField(
        "f-entity",
        "Entity",
        rule.entity_id,
        kind === "problem"
          ? ["binary_sensor"]
          : kind === "numeric"
            ? ["sensor", "number", "input_number"]
            : []
      );
      if (kind === "numeric") {
        condition += `
          <div class="row">
            ${this._input("f-above", "Alarm above", rule.above)}
            ${this._input("f-below", "Alarm below", rule.below)}
            ${this._input("f-hyst", "Hysteresis", rule.hysteresis || 0)}
          </div>
          <div class="hint inline">Hysteresis keeps the alarm active until
          the value passes back beyond the threshold plus or minus the
          hysteresis.</div>`;
      }
      if (kind === "state") {
        condition += this._input("f-state", "Alarm when the state is", rule.state, {
          placeholder: "on",
        });
      }
    }

    return `
      <ha-card class="editor">
        <div class="editor-head">${rule.id ? "Edit rule" : "New rule"}</div>
        <div class="form">
          ${this._input("f-name", "Name", rule.name)}
          <div class="row">
            ${this._select("f-level", "Level", rule.level || "warning", LEVELS.map((l) => [l, LEVEL_LABEL[l]]))}
            ${this._select("f-kind", "Type", kind, Object.keys(KIND_LABEL).map((k) => [k, KIND_LABEL[k]]))}
          </div>
          ${condition}
          <div class="row">
            ${this._input("f-for", "Delay before alarm (s)", rule.for_seconds || 0)}
            ${this._input("f-archive", "Archive delay (s)", rule.archive_delay, {
              placeholder: "global",
            })}
          </div>
          ${this._input("f-message", "Message", rule.message)}

          ${
            kind === "template"
              ? ""
              : `<label class="check"><input type="checkbox" id="f-unavail" ${
                  rule.unavailable_is_problem ? "checked" : ""
                }> Unavailable entity counts as an alarm</label>`
          }
          <label class="check"><input type="checkbox" id="f-notify" ${
            rule.notify === false ? "" : "checked"
          }> Send a notification when the alarm appears</label>

          <div class="field">
            <label class="lbl" for="f-ack-actions">Actions on acknowledge</label>
            <textarea id="f-ack-actions" class="code" rows="6" spellcheck="false">${esc(
              ackText
            )}</textarea>
            <div class="hint inline">JSON in Home Assistant's action syntax,
            e.g.
            <code>[{"action": "switch.turn_off", "target": {"entity_id": "switch.pump"}}]</code>.
            <code>alarm</code> and <code>rule</code> are available as
            variables.</div>
          </div>
        </div>
        <div class="editor-actions">
          <button class="btn ghost" data-cancel>Cancel</button>
          <button class="btn" data-save-rule>Save rule</button>
        </div>
      </ha-card>
    `;
  }

  // -- form building ---------------------------------------------------

  _input(id, label, value, opts = {}) {
    const shown = value === null || value === undefined ? "" : value;
    return `<div class="field">
      <label class="lbl" for="${id}">${esc(label)}</label>
      <input class="native" id="${id}" type="text" value="${esc(shown)}"
        autocomplete="off" ${
          opts.placeholder ? `placeholder="${esc(opts.placeholder)}"` : ""
        }>
    </div>`;
  }

  _select(id, label, value, options) {
    return `<div class="field">
      <label class="lbl" for="${id}">${esc(label)}</label>
      <select class="native" id="${id}">
        ${options
          .map(
            ([v, text]) =>
              `<option value="${esc(v)}" ${v === value ? "selected" : ""}>${esc(
                text
              )}</option>`
          )
          .join("")}
      </select>
    </div>`;
  }

  /**
   * Uses ha-entity-picker when the frontend has it loaded, otherwise a plain
   * input backed by a datalist of matching entities.
   */
  _entityField(id, label, value, domains) {
    if (customElements.get("ha-entity-picker")) {
      return `<div class="field">
        <label class="lbl">${esc(label)}</label>
        <div data-picker="${id}" data-domains="${esc(domains.join(","))}"
             data-value="${esc(value || "")}"></div>
      </div>`;
    }
    const options = this._entityOptions(domains)
      .map((e) => `<option value="${esc(e)}"></option>`)
      .join("");
    return `<div class="field">
      <label class="lbl" for="${id}">${esc(label)}</label>
      <input class="native" id="${id}" list="${id}-list" value="${esc(value || "")}"
        autocomplete="off" placeholder="binary_sensor.example">
      <datalist id="${id}-list">${options}</datalist>
    </div>`;
  }

  _entityOptions(domains) {
    const states = (this._hass && this._hass.states) || {};
    return Object.keys(states)
      .filter((id) => !domains.length || domains.includes(id.split(".")[0]))
      .sort();
  }

  _hydrate() {
    this.shadowRoot.querySelectorAll("[data-picker]").forEach((slot) => {
      if (slot.firstElementChild) return;
      const picker = document.createElement("ha-entity-picker");
      picker.hass = this._hass;
      picker.value = slot.dataset.value || "";
      picker.allowCustomEntity = true;
      const domains = (slot.dataset.domains || "").split(",").filter(Boolean);
      if (domains.length) picker.includeDomains = domains;
      picker.addEventListener("value-changed", (ev) => {
        slot.dataset.value = (ev.detail && ev.detail.value) || "";
      });
      slot.appendChild(picker);
    });
  }

  _entityValue(id) {
    const slot = this.shadowRoot.querySelector(`[data-picker="${id}"]`);
    if (slot) {
      const picker = slot.firstElementChild;
      return (picker && picker.value) || slot.dataset.value || "";
    }
    return this._value(`#${id}`);
  }

  // -- settings --------------------------------------------------------

  _settingsView() {
    if (!this._config) return `<ha-card class="empty"><p>Loading…</p></ha-card>`;
    const auto = this._config.auto_rules || {};
    const notify = this._config.notify || {};
    const targets = notify.targets || [];
    const reminders = notify.reminders || {};
    const digest = reminders.digest || {};
    const repeat = reminders.repeat || {};
    const quiet = notify.quiet_hours || {};
    const targetFor = (person) => targets.find((t) => t.person === person) || null;

    return `
      <ha-card>
        <div class="section-title">Alarm list</div>
        <div class="form">
          ${this._input("s-archive", "Archive delay (s)", this._config.archive_delay)}
          <div class="hint inline">How long an acknowledged, inactive alarm
          stays before moving to history.</div>
        </div>
      </ha-card>

      <ha-card>
        <div class="section-title">Automatic rules</div>
        <div class="form">
          <label class="check"><input type="checkbox" id="s-auto-enabled" ${
            auto.enabled === false ? "" : "checked"
          }> Create rules for new problem entities</label>
          <label class="check"><input type="checkbox" id="s-auto-start" ${
            auto.start_enabled === false ? "" : "checked"
          }> New rules are enabled immediately</label>
          ${this._select(
            "s-auto-level",
            "Level for new rules",
            auto.default_level || "warning",
            LEVELS.map((l) => [l, LEVEL_LABEL[l]])
          )}
          ${
            (auto.ignored || []).length
              ? `<div class="hint inline">Ignored entities: ${esc(
                  (auto.ignored || []).join(", ")
                )}</div>`
              : ""
          }
        </div>
      </ha-card>

      <ha-card>
        <div class="section-title">Notifications</div>
        <div class="form">
          <label class="check"><input type="checkbox" id="s-notify-enabled" ${
            notify.enabled === false ? "" : "checked"
          }> Send notifications for new alarms</label>
          ${
            this._people.length
              ? this._people
                  .map((person) => {
                    const target = targetFor(person.person);
                    const level = (target && target.min_level) || "warning";
                    const services =
                      target && target.services && target.services.length
                        ? target.services
                        : person.services;
                    return `
              <div class="person" data-person="${esc(person.person)}">
                <label class="check">
                  <input type="checkbox" class="p-enabled" ${
                    target && target.enabled !== false ? "checked" : ""
                  }>
                  <span class="pname">${esc(person.name)}</span>
                </label>
                <label class="check">
                  <input type="checkbox" class="p-tts" ${
                    target && target.tts ? "checked" : ""
                  }>
                  <span>Read aloud</span>
                </label>
                <select class="native p-level">
                  ${LEVELS.map(
                    (l) =>
                      `<option value="${l}" ${
                        level === l ? "selected" : ""
                      }>From ${esc(LEVEL_LABEL[l].toLowerCase())}</option>`
                  ).join("")}
                </select>
                <div class="field wide">
                  <label class="lbl">Notify services</label>
                  <input class="native p-services" type="text" autocomplete="off"
                    value="${esc(services.join(", "))}"
                    placeholder="mobile_app_phone">
                  <div class="hint inline">Auto-detected: ${esc(
                    person.services.join(", ") || "none"
                  )}</div>
                </div>
              </div>`;
                  })
                  .join("")
              : `<div class="hint inline">No people found.</div>`
          }
        </div>
      </ha-card>

      <ha-card>
        <div class="section-title">Reminders</div>
        <div class="form">
          <label class="check"><input type="checkbox" id="s-digest-enabled" ${
            digest.enabled ? "checked" : ""
          }> Send a daily summary of what is still active</label>
          <div class="row">
            ${this._input("s-digest-time", "Time of day (HH:MM)", digest.time || "07:00")}
            ${this._select(
              "s-digest-level",
              "Include from level",
              digest.min_level || "warning",
              LEVELS.map((l) => [l, LEVEL_LABEL[l]])
            )}
          </div>
          <div class="hint inline">One notification listing every alarm that
          is still active. Nothing is sent if the list is empty.</div>

          <div class="lbl">Repeat unacknowledged alarms every (minutes,
          0 = off)</div>
          <div class="row">
            ${LEVELS.map((level) =>
              this._input(
                `s-repeat-${level}`,
                LEVEL_LABEL[level],
                Math.round((repeat[level] || 0) / 60)
              )
            ).join("")}
          </div>
          <div class="hint inline">Only alarms that are both active and
          unacknowledged are repeated - acknowledging one stops its
          reminders. The previous notification is cleared before the new one
          is sent, so the phone keeps one current notification per alarm
          rather than a growing pile.</div>
        </div>
      </ha-card>

      <ha-card>
        <div class="section-title">Quiet hours</div>
        <div class="form">
          <label class="check"><input type="checkbox" id="s-quiet-enabled" ${
            quiet.enabled ? "checked" : ""
          }> Hold back notifications during a time window</label>
          <div class="row">
            ${this._input("s-quiet-start", "From (HH:MM)", quiet.start || "22:00")}
            ${this._input("s-quiet-end", "To (HH:MM)", quiet.end || "07:00")}
          </div>
          <div class="lbl">Levels to silence</div>
          <div class="row">
            ${LEVELS.map(
              (level) => `<label class="check">
                <input type="checkbox" class="q-level" data-level="${level}" ${
                  (quiet.levels || []).includes(level) ? "checked" : ""
                }> ${esc(LEVEL_LABEL[level])}
              </label>`
            ).join("")}
          </div>
          <label class="check"><input type="checkbox" id="s-quiet-after" ${
            quiet.send_after === false ? "" : "checked"
          }> Send what was held back when the window ends</label>
          <div class="hint inline">Levels left unticked always get through
          immediately. Held-back alarms that resolved or were acknowledged
          before the window ended are dropped rather than delivered late.
          A window crossing midnight (22:00 to 07:00) works as expected.</div>
        </div>
      </ha-card>

      <ha-card>
        <div class="section-title">Text-to-speech (TTS)</div>
        <div class="form">
          <label class="check"><input type="checkbox" id="s-tts-enabled" ${
            this._config.notify &&
            this._config.notify.tts &&
            this._config.notify.tts.enabled
              ? "checked"
              : ""
          }> Read alarms aloud with text-to-speech for those who enabled it</label>
          <div class="row">
            ${Object.keys(LEVEL_LABEL)
              .map((level) =>
                this._select(
                  `s-tts-${level}`,
                  LEVEL_LABEL[level],
                  ((this._config.notify &&
                    this._config.notify.tts &&
                    this._config.notify.tts.streams) ||
                    {})[level] || "off",
                  Object.keys(TTS_STREAM_LABEL).map((s) => [s, TTS_STREAM_LABEL[s]])
                )
              )
              .join("")}
          </div>
          <div class="hint inline">"Alarm stream (max volume)" plays through
          Android's alarm stream and is heard even if the phone is muted or
          in Do Not Disturb. Requires the app to have that permission.</div>
        </div>
        <div class="editor-actions">
          <button class="btn" data-save-settings>Save settings</button>
        </div>
      </ha-card>
    `;
  }

  // -- interaction -----------------------------------------------------

  _showError(message) {
    const el = this.shadowRoot.querySelector("#error");
    if (!el) return;
    el.textContent = message;
    el.hidden = false;
  }

  _clearError() {
    const el = this.shadowRoot.querySelector("#error");
    if (el) el.hidden = true;
  }

  async _handleChange(ev) {
    const el = ev.target;
    if (!el || !el.closest) return;

    // Switching rule type keeps what is already typed and re-renders the
    // fields that belong to the new type.
    if (el.id === "f-kind") {
      const draft = this._collectRuleForm();
      draft.kind = el.value;
      this._editing = draft;
      this._renderView();
      return;
    }

    const toggle = el.closest("[data-toggle]");
    if (!toggle) return;
    this._clearError();
    try {
      await this._call("alarm_center/rules/set_enabled", {
        rule_id: toggle.dataset.toggle,
        enabled: !!toggle.checked,
      });
      await this._loadRules();
    } catch (err) {
      this._showError(this._errorText(err));
    }
  }

  async _handleClick(ev) {
    // Look the action element up once. Clicks on anything else - checkboxes,
    // selects, text fields - must not touch the DOM, or the form resets while
    // it is being filled in.
    const el = ev.target && ev.target.closest ? ev.target.closest(ACTION_SELECTOR) : null;
    if (!el) return;

    this._clearError();
    try {
      if (el.hasAttribute("data-ack")) {
        await this._call("alarm_center/acknowledge", { alarm_id: el.dataset.ack });
      } else if (el.hasAttribute("data-ack-all")) {
        await this._call("alarm_center/acknowledge_all");
      } else if (el.hasAttribute("data-more")) {
        this.dispatchEvent(
          new CustomEvent("hass-more-info", {
            detail: { entityId: el.dataset.more },
            bubbles: true,
            composed: true,
          })
        );
      } else if (el.hasAttribute("data-edit")) {
        this._editing = this._rules.find((r) => r.id === el.dataset.edit);
        this._renderView();
      } else if (el.hasAttribute("data-delete")) {
        if (!confirm("Delete this rule? You can restore it from the trash.")) return;
        await this._call("alarm_center/rules/delete", { rule_id: el.dataset.delete });
        await this._loadRules();
        await this._loadTrash();
        this._renderView();
      } else if (el.hasAttribute("data-new-rule")) {
        this._editing = {
          name: "",
          kind: "problem",
          level: "warning",
          enabled: true,
        };
        this._renderView();
      } else if (el.hasAttribute("data-cancel")) {
        this._editing = null;
        this._renderView();
      } else if (el.hasAttribute("data-save-rule")) {
        await this._saveRule();
      } else if (el.hasAttribute("data-save-settings")) {
        await this._saveSettings();
      } else if (el.hasAttribute("data-show-trash")) {
        this._showTrash = true;
        await this._loadTrash();
        this._renderView();
      } else if (el.hasAttribute("data-hide-trash")) {
        this._showTrash = false;
        this._renderView();
      } else if (el.hasAttribute("data-restore")) {
        await this._call("alarm_center/rules/restore", { rule_id: el.dataset.restore });
        await this._loadRules();
        await this._loadTrash();
        this._renderView();
      } else if (el.hasAttribute("data-purge")) {
        if (!confirm("Permanently delete this rule? This cannot be undone.")) return;
        await this._call("alarm_center/rules/purge", { rule_id: el.dataset.purge });
        await this._loadTrash();
        this._renderView();
      }
    } catch (err) {
      // Show the error without re-rendering, so nothing typed is lost.
      this._showError(this._errorText(err));
    }
  }

  _errorText(err) {
    if (!err) return "Unknown error";
    return err.message || err.error || String(err);
  }

  _value(selector) {
    const el = this.shadowRoot.querySelector(selector);
    if (!el) return "";
    const value = el.value;
    return value === undefined || value === null ? "" : String(value);
  }

  _checked(selector) {
    const el = this.shadowRoot.querySelector(selector);
    return el ? !!el.checked : false;
  }

  _number(selector) {
    const raw = this._value(selector).trim();
    if (raw === "") return null;
    const parsed = Number(raw);
    return Number.isNaN(parsed) ? null : parsed;
  }

  /**
   * Read the editor into a rule object. Fields that are not rendered for the
   * current rule type keep whatever the rule already had.
   */
  _collectRuleForm() {
    const draft = { ...this._editing };
    const has = (selector) => !!this.shadowRoot.querySelector(selector);

    if (has("#f-name")) draft.name = this._value("#f-name").trim();
    if (has("#f-level")) draft.level = this._value("#f-level");
    if (has("#f-kind")) draft.kind = this._value("#f-kind");
    if (has("#f-template")) draft.template = this._value("#f-template").trim() || null;
    if (has('[data-picker="f-entity"]') || has("#f-entity")) {
      draft.entity_id = this._entityValue("f-entity").trim() || null;
    }
    if (has("#f-above")) draft.above = this._number("#f-above");
    if (has("#f-below")) draft.below = this._number("#f-below");
    if (has("#f-hyst")) draft.hysteresis = this._number("#f-hyst") || 0;
    if (has("#f-state")) draft.state = this._value("#f-state").trim() || null;
    if (has("#f-for")) draft.for_seconds = this._number("#f-for") || 0;
    if (has("#f-archive")) draft.archive_delay = this._number("#f-archive");
    if (has("#f-message")) draft.message = this._value("#f-message").trim() || null;
    if (has("#f-unavail")) draft.unavailable_is_problem = this._checked("#f-unavail");
    if (has("#f-notify")) draft.notify = this._checked("#f-notify");

    if (has("#f-ack-actions")) {
      const raw = this._value("#f-ack-actions");
      draft._ackRaw = raw;
      try {
        draft.on_acknowledge = JSON.parse(raw || "[]");
        delete draft._ackRaw;
      } catch (err) {
        /* keep the raw text so it is not lost when the type changes */
      }
    }
    return draft;
  }

  async _saveRule() {
    const draft = this._collectRuleForm();

    if (draft._ackRaw !== undefined) {
      this._editing = draft;
      this._showError("Actions are not valid JSON.");
      return;
    }
    if (!draft.name) {
      this._showError("The rule needs a name.");
      return;
    }
    if (draft.kind === "template" && !draft.template) {
      this._showError("A template rule needs a template.");
      return;
    }
    if (draft.kind !== "template" && !draft.entity_id) {
      this._showError("Choose an entity.");
      return;
    }
    if (draft.kind === "numeric" && draft.above === null && draft.below === null) {
      this._showError("Enter a threshold, above or below.");
      return;
    }

    const rule = {
      ...(draft.id ? { id: draft.id } : {}),
      name: draft.name,
      level: draft.level || "warning",
      kind: draft.kind || "problem",
      enabled: draft.enabled !== false,
      entity_id: draft.kind === "template" ? null : draft.entity_id,
      above: draft.above ?? null,
      below: draft.below ?? null,
      hysteresis: draft.hysteresis || 0,
      state: draft.state || null,
      template: draft.kind === "template" ? draft.template : null,
      for_seconds: draft.for_seconds || 0,
      archive_delay: draft.archive_delay ?? null,
      message: draft.message || null,
      unavailable_is_problem: !!draft.unavailable_is_problem,
      notify: draft.notify !== false,
      on_acknowledge: draft.on_acknowledge || [],
      on_activate: draft.on_activate || [],
      on_clear: draft.on_clear || [],
      auto: !!draft.auto,
      source_entity_id: draft.source_entity_id || null,
    };

    await this._call("alarm_center/rules/save", { rule });
    this._editing = null;
    await this._loadRules();
    this._renderView();
  }

  async _saveSettings() {
    const targets = [];
    this.shadowRoot.querySelectorAll(".person").forEach((row) => {
      const servicesEl = row.querySelector(".p-services");
      const enabledEl = row.querySelector(".p-enabled");
      const levelEl = row.querySelector(".p-level");
      const ttsEl = row.querySelector(".p-tts");
      const services = ((servicesEl && servicesEl.value) || "")
        .split(",")
        .map((service) => service.trim())
        .filter(Boolean);
      targets.push({
        person: row.dataset.person,
        enabled: enabledEl ? !!enabledEl.checked : false,
        tts: ttsEl ? !!ttsEl.checked : false,
        min_level: (levelEl && levelEl.value) || "warning",
        services,
      });
    });

    const ttsStreams = {};
    Object.keys(LEVEL_LABEL).forEach((level) => {
      ttsStreams[level] = this._value(`#s-tts-${level}`) || "off";
    });

    // Repeat intervals are entered in minutes and stored in seconds.
    const repeat = {};
    LEVELS.forEach((level) => {
      const minutes = this._number(`#s-repeat-${level}`) ?? 0;
      repeat[level] = Math.max(0, Math.round(minutes * 60));
    });

    const quietLevels = [];
    this.shadowRoot.querySelectorAll(".q-level").forEach((el) => {
      if (el.checked) quietLevels.push(el.dataset.level);
    });

    const config = {
      archive_delay: this._number("#s-archive") ?? 60,
      auto_rules: {
        enabled: this._checked("#s-auto-enabled"),
        start_enabled: this._checked("#s-auto-start"),
        default_level: this._value("#s-auto-level") || "warning",
      },
      notify: {
        enabled: this._checked("#s-notify-enabled"),
        targets,
        tts: {
          enabled: this._checked("#s-tts-enabled"),
          streams: ttsStreams,
        },
        reminders: {
          digest: {
            enabled: this._checked("#s-digest-enabled"),
            time: this._value("#s-digest-time") || "07:00",
            min_level: this._value("#s-digest-level") || "warning",
          },
          repeat,
        },
        quiet_hours: {
          enabled: this._checked("#s-quiet-enabled"),
          start: this._value("#s-quiet-start") || "22:00",
          end: this._value("#s-quiet-end") || "07:00",
          levels: quietLevels,
          send_after: this._checked("#s-quiet-after"),
        },
      },
    };
    await this._call("alarm_center/config/save", { config });
    await this._loadConfig();
    await this._loadRules();
    this._renderView();
  }

  // -- helpers ---------------------------------------------------------

  _formatTime(iso) {
    if (!iso) return "–";
    const date = new Date(iso);
    const locale =
      (this._hass && this._hass.locale && this._hass.locale.language) || "en-US";
    const diff = (Date.now() - date.getTime()) / 1000;
    if (diff < 60) return "just now";
    if (diff < 86400) {
      return date.toLocaleTimeString(locale, {
        hour: "2-digit",
        minute: "2-digit",
      });
    }
    return date.toLocaleString(locale, {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  }
}

const STYLES = `
:host {
  display: block;
  background: var(--primary-background-color);
  color: var(--primary-text-color);
  min-height: 100vh;
  font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
}
.header {
  display: flex;
  align-items: center;
  gap: 8px;
  height: var(--header-height, 56px);
  padding: 0 12px;
  background: var(--app-header-background-color, var(--primary-color));
  color: var(--app-header-text-color, #fff);
  position: sticky;
  top: 0;
  z-index: 2;
}
.header .title { font-size: 20px; font-weight: 400; flex: 1; }
.counts { display: flex; gap: 6px; }
.pill {
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 12px;
  background: rgba(255,255,255,.18);
  white-space: nowrap;
}
.pill-active { background: var(--error-color, #db4437); }
.pill-unacked { background: var(--warning-color, #ffa600); color: #000; }

.tabs {
  display: flex;
  background: var(--app-header-background-color, var(--primary-color));
  color: var(--app-header-text-color, #fff);
  overflow-x: auto;
  position: sticky;
  top: var(--header-height, 56px);
  z-index: 2;
}
.tab {
  flex: 1;
  min-width: 90px;
  border: 0;
  background: none;
  color: inherit;
  opacity: .75;
  padding: 8px 4px;
  font-size: 13px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.tab.selected { opacity: 1; border-bottom-color: currentColor; }

.content { padding: 12px; max-width: 1100px; margin: 0 auto; }
ha-card { display: block; margin-bottom: 12px; }
.section-title {
  padding: 16px 16px 0;
  font-size: 16px;
  font-weight: 500;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  gap: 8px;
}
.list > *:not(:last-child) { border-bottom: 1px solid var(--divider-color); }

.alarm, .rule {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px 12px 12px;
  position: relative;
}
.alarm .stripe {
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 4px;
  background: var(--level-color);
}
.alarm .lvl { color: var(--level-color); }
.level-critical { --level-color: var(--error-color, #db4437); }
.level-error { --level-color: var(--error-color, #db4437); }
.level-warning { --level-color: var(--warning-color, #ffa600); }
.level-notice { --level-color: var(--info-color, #039be5); }

.alarm .body, .rule .body { flex: 1; min-width: 0; }
.name { font-size: 15px; font-weight: 500; }
.meta { font-size: 12px; color: var(--secondary-text-color); margin-top: 2px; }
.msg { font-size: 13px; margin-top: 4px; }

/* Acknowledged alarms stay in the list but step back visually. */
.alarm.acked { opacity: .55; }
.alarm.acked .stripe { background: var(--divider-color); }
.alarm.acked .lvl { color: var(--secondary-text-color); }
.alarm.acked .name { font-weight: 400; }
.alarm.inactive .name { text-decoration: none; font-style: italic; }

.badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid var(--divider-color);
  color: var(--secondary-text-color);
  white-space: nowrap;
}
.badge-active {
  border-color: var(--level-color);
  color: var(--level-color);
}
.chip {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  background: var(--divider-color);
  color: var(--secondary-text-color);
  margin-left: 6px;
  vertical-align: middle;
}
.chip-critical, .chip-error { background: var(--error-color); color: #fff; }
.chip-warning { background: var(--warning-color); color: #000; }

.actions { display: flex; align-items: center; gap: 4px; }
.rule.disabled { opacity: .5; }

.btn {
  border: none;
  border-radius: 4px;
  background: var(--primary-color);
  color: var(--text-primary-color, #fff);
  padding: 8px 16px;
  font-size: 14px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.btn.ghost { background: transparent; color: var(--primary-color); }
.btn:hover { filter: brightness(1.1); }

.empty { text-align: center; padding: 32px 16px; color: var(--secondary-text-color); }
.empty ha-icon { --mdc-icon-size: 40px; }
.hint { font-size: 12px; color: var(--secondary-text-color); margin: 8px 16px 16px; }
#error { margin: 12px 12px 0; }
.error {
  background: var(--error-color);
  color: #fff;
  padding: 12px 16px;
  border-radius: 4px;
  margin-bottom: 12px;
}

.form { display: flex; flex-direction: column; gap: 14px; padding: 16px; }
.field { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 140px; }
.field.wide { grid-column: 1 / -1; }
.row { display: flex; gap: 12px; flex-wrap: wrap; }
.lbl { font-size: 12px; color: var(--secondary-text-color); }
.hint.inline { margin: 0; }
input.native, select.native, textarea.code { width: 100%; box-sizing: border-box; }
.native:focus, .code:focus {
  outline: none;
  border-color: var(--primary-color);
}
/* Native toggle painted to match the Home Assistant switch. */
.toggle {
  appearance: none;
  -webkit-appearance: none;
  width: 36px;
  height: 20px;
  flex: none;
  border-radius: 10px;
  background: var(--switch-unchecked-track-color, #9e9e9e);
  position: relative;
  cursor: pointer;
  transition: background .2s;
  margin: 0;
}
.toggle::after {
  content: "";
  position: absolute;
  top: 2px; left: 2px;
  width: 16px; height: 16px;
  border-radius: 50%;
  background: #fff;
  transition: transform .2s;
  box-shadow: 0 1px 3px rgba(0,0,0,.3);
}
.toggle:checked { background: var(--switch-checked-track-color, var(--primary-color)); }
.toggle:checked::after { transform: translateX(16px); }
.toggle:disabled { opacity: .5; cursor: default; }
/* Works even if ha-card has not been loaded by the frontend yet. */
ha-card:not(:defined) {
  display: block;
  background: var(--ha-card-background, var(--card-background-color, #fff));
  border-radius: var(--ha-card-border-radius, 12px);
  box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0,0,0,.14));
}
.native {
  padding: 10px;
  border-radius: 4px;
  border: 1px solid var(--divider-color);
  background: var(--card-background-color);
  color: var(--primary-text-color);
  font-size: 14px;
}
.check { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.code {
  font-family: var(--code-font-family, monospace);
  font-size: 13px;
  padding: 8px;
  border-radius: 4px;
  border: 1px solid var(--divider-color);
  background: var(--card-background-color);
  color: var(--primary-text-color);
  resize: vertical;
}
.editor-head { padding: 16px 16px 0; font-size: 18px; }
.editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 0 16px 16px;
}
.person {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 8px 12px;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid var(--divider-color);
}
.person .pname { font-size: 14px; }
@media (max-width: 600px) {
  .person { grid-template-columns: 1fr auto; }
}

@media (max-width: 600px) {
  .content { padding: 8px; }
  .alarm { flex-wrap: wrap; }
  .alarm .actions { width: 100%; justify-content: flex-end; }
  .badges { order: 3; }
  .person { grid-template-columns: 1fr; }
}
`;

customElements.define("alarm-center-panel", AlarmCenterPanel);
