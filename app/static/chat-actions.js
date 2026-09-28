/* State-driven action buttons. Dates remain absolute when labels roll over. */
class ChatActionRenderer {
  constructor(holder, onSelect, isBlocked, clock = () => new Date()) {
    this.holder = holder;
    this.onSelect = onSelect;
    this.isBlocked = isBlocked;
    this.clock = clock;
    this.actions = [];
    this.signature = null;
    this.timer = setInterval(() => this.refresh(), 1000);
  }

  render(actions) {
    this.actions = Array.isArray(actions) ? actions : [];
    this.signature = null;
    this.refresh();
  }

  visible(action, now) {
    return !action.expires_at || Date.parse(action.expires_at) > now.getTime();
  }

  label(action, now) {
    if (action.kind !== "date" || !action.date || !action.timezone) return action.label;
    // Use clinic time, never the browser's own calendar day.
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: action.timezone, year: "numeric", month: "2-digit", day: "2-digit"
    }).formatToParts(now);
    const get = type => parts.find(part => part.type === type).value;
    const today = `${get("year")}-${get("month")}-${get("day")}`;
    const day = new Date(`${action.date}T00:00:00Z`);
    const next = new Date(`${today}T00:00:00Z`);
    next.setUTCDate(next.getUTCDate() + 1);
    const prefix = action.date === today ? "Today - " :
      action.date === next.toISOString().slice(0, 10) ? "Tomorrow - " : "";
    const weekday = new Intl.DateTimeFormat("en-US", {weekday: "long", timeZone: "UTC"}).format(day);
    return `${prefix}${weekday} ${action.date}`;
  }

  refresh() {
    const now = this.clock();
    const visible = this.actions.filter(action => this.visible(action, now));
    const signature = JSON.stringify(visible.map(action => [action.message, this.label(action, now)]));
    if (signature === this.signature) return;
    this.signature = signature;
    this.holder.replaceChildren();
    const groups = new Map();
    const titles = {slot: "Choose an appointment", date: "Search by date", period: "Time preference", action: "Next step"};
    for (const action of visible) {
      const kind = ["slot", "date", "period"].includes(action.kind) ? action.kind : "action";
      let group = groups.get(kind);
      if (!group) {
        const section = document.createElement("div");
        section.className = `action-group action-group-${kind}`;
        section.setAttribute("role", "group");
        section.setAttribute("aria-label", titles[kind]);
        const heading = document.createElement("div");
        heading.className = "action-heading";
        heading.textContent = titles[kind];
        group = document.createElement("div");
        group.className = "action-buttons";
        section.append(heading, group);
        this.holder.appendChild(section);
        groups.set(kind, group);
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = action.kind === "primary" ? "action-primary" : "";
      button.textContent = this.label(action, now);
      button.disabled = this.isBlocked();
      button.addEventListener("click", () => {
        // Check again at click time; an idle tab might cross noon.
        if (this.isBlocked()) return;
        if (!this.visible(action, this.clock())) return this.refresh();
        this.onSelect(action.message);
      });
      group.appendChild(button);
    }
    this.holder.hidden = visible.length === 0;
  }

  destroy() { clearInterval(this.timer); }
}
window.ChatActionRenderer = ChatActionRenderer;