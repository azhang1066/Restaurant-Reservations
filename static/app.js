const dayNames = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const elements = {
  restaurantList: document.getElementById("restaurant-list"),
  restaurantCount: document.getElementById("restaurant-count"),
  activityLog: document.getElementById("activity-log"),
  settingsForm: document.getElementById("settings-form"),
  settingsMessage: document.getElementById("settings-message"),
  restaurantForm: document.getElementById("restaurant-form"),
  venueUrl: document.getElementById("venue-url"),
  resolveResult: document.getElementById("resolve-result"),
  resolveUrlButton: document.getElementById("resolve-url"),
  restaurantName: document.getElementById("restaurant-name"),
  restaurantSource: document.getElementById("restaurant-source"),
  resyIdGroup: document.getElementById("resy-id-group"),
  opentableIdGroup: document.getElementById("opentable-id-group"),
  resyId: document.getElementById("resy-id"),
  opentableId: document.getElementById("opentable-id"),
  partySizes: document.getElementById("party-sizes"),
  daysTimeGrid: document.getElementById("days-time-grid"),
  timeEarliest: document.getElementById("time-earliest"),
  timeLatest: document.getElementById("time-latest"),
};

function showMessage(element, text, type = "success") {
  element.classList.remove("error", "success");
  element.classList.add(type);
  element.textContent = text;
  element.hidden = false;
  setTimeout(() => {
    element.hidden = true;
  }, 5000);
}

function buildDaysTimeGrid(container, selectedDays = [], timeRanges = {}) {
  container.innerHTML = "";
  dayNames.forEach((day) => {
    const dayDiv = document.createElement("div");
    dayDiv.className = "day-time-row";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = day;
    checkbox.checked = selectedDays.includes(day);
    const label = document.createElement("label");
    label.textContent = day;
    const earliestInput = document.createElement("input");
    earliestInput.type = "time";
    earliestInput.placeholder = "Earliest";
    const latestInput = document.createElement("input");
    latestInput.type = "time";
    latestInput.placeholder = "Latest";
    if (timeRanges[day]) {
      earliestInput.value = timeRanges[day][0] || "";
      latestInput.value = timeRanges[day][1] || "";
    }
    dayDiv.appendChild(checkbox);
    dayDiv.appendChild(label);
    dayDiv.appendChild(earliestInput);
    dayDiv.appendChild(latestInput);
    container.appendChild(dayDiv);
  });
}

function getSelectedDaysAndTimes(container) {
  const days = [];
  const timeRanges = {};
  container.querySelectorAll(".day-time-row").forEach((row) => {
    const checkbox = row.querySelector("input[type=checkbox]");
    const inputs = row.querySelectorAll("input[type=time]");
    if (checkbox.checked) {
      days.push(checkbox.value);
      const earliest = inputs[0].value;
      const latest = inputs[1].value;
      if (earliest || latest) {
        timeRanges[checkbox.value] = [earliest, latest];
      }
    }
  });
  return { days, timeRanges };
}

function normalizePartySizes(value) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map(Number)
    .filter((value) => !Number.isNaN(value));
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  return response.json();
}

function renderRestaurantCard(restaurant) {
  const card = document.createElement("div");
  card.className = "restaurant-card";
  card.dataset.id = restaurant.id;

  const header = document.createElement("div");
  header.className = "card-header";
  header.innerHTML = `
    <div>
      <strong>${restaurant.name}</strong>
      <span class="platform-badge">${restaurant.source.toUpperCase()}</span>
    </div>
    <div class="edit-actions">
      <button class="button button-secondary toggle-btn">${restaurant.enabled ? "On" : "Off"}</button>
      <button class="button button-secondary delete-btn">Delete</button>
      <button class="button button-secondary edit-btn">Edit</button>
    </div>
  `;

  const body = document.createElement("div");
  body.className = "card-body";
  const timeRangesText = Object.entries(restaurant.time_ranges || {}).map(([day, times]) => `${day}: ${times ? times.join(' — ') : 'Any'}`).join(', ') || 'Any';
  body.innerHTML = `
    <div class="summary-row">
      <div class="summary-item"><strong>Party sizes</strong><br>${restaurant.party_sizes.join(", ")}</div>
      <div class="summary-item"><strong>Days</strong><br>${restaurant.days.join(", ")}</div>
      <div class="summary-item"><strong>Time ranges</strong><br>${timeRangesText}</div>
    </div>
  `;

  const editPanel = document.createElement("div");
  editPanel.className = "edit-panel hidden";
  editPanel.innerHTML = `
    <div class="form-group">
      <label>Name</label>
      <input class="edit-name" value="${restaurant.name}" />
    </div>
    <div class="form-group">
      <label>Party sizes</label>
      <input class="edit-party-sizes" value="${restaurant.party_sizes.join(", ")}" />
    </div>
    <div class="form-group">
      <label>Days and Time Ranges</label>
      <div class="days-time-grid edit-days-time"></div>
    </div>
    <div class="edit-actions">
      <button class="button button-primary save-btn">Save</button>
      <button class="button button-secondary cancel-btn">Cancel</button>
    </div>
  `;

  body.appendChild(editPanel);
  card.appendChild(header);
  card.appendChild(body);

  const editDaysTime = editPanel.querySelector(".edit-days-time");
  buildDaysTimeGrid(editDaysTime, restaurant.days, restaurant.time_ranges);

  header.querySelector(".toggle-btn").addEventListener("click", async () => {
    const updated = await apiFetch(`/api/restaurants/${restaurant.id}`, {
      method: "PUT",
      body: JSON.stringify({ ...restaurant, enabled: !restaurant.enabled }),
    });
    if (updated.success) loadRestaurants();
  });

  header.querySelector(".delete-btn").addEventListener("click", async () => {
    if (!confirm(`Delete ${restaurant.name}?`)) return;
    await apiFetch(`/api/restaurants/${restaurant.id}`, { method: "DELETE" });
    loadRestaurants();
  });

  header.querySelector(".edit-btn").addEventListener("click", () => {
    editPanel.classList.toggle("hidden");
  });

  editPanel.querySelector(".cancel-btn").addEventListener("click", () => {
    editPanel.classList.add("hidden");
  });

  editPanel.querySelector(".save-btn").addEventListener("click", async () => {
    const { days, timeRanges } = getSelectedDaysAndTimes(editDaysTime);
    const payload = {
      name: editPanel.querySelector(".edit-name").value.trim(),
      party_sizes: normalizePartySizes(editPanel.querySelector(".edit-party-sizes").value),
      days: days,
      time_ranges: timeRanges,
      enabled: restaurant.enabled,
    };
    await apiFetch(`/api/restaurants/${restaurant.id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    loadRestaurants();
  });

  return card;
}

async function loadRestaurants() {
  const restaurants = await apiFetch("/api/restaurants");
  elements.restaurantList.innerHTML = "";
  elements.restaurantCount.textContent = `${restaurants.length} restaurants`;
  restaurants.forEach((restaurant) => {
    elements.restaurantList.appendChild(renderRestaurantCard(restaurant));
  });
}

async function loadLogs() {
  const logs = await apiFetch("/api/logs");
  elements.activityLog.innerHTML = "";
  logs.forEach((log) => {
    const item = document.createElement("div");
    item.className = `log-item ${log.highlight ? "highlight" : ""}`;
    item.innerHTML = `
      <time>${new Date(log.timestamp).toLocaleString()}</time>
      <p>${log.message}</p>
    `;
    elements.activityLog.appendChild(item);
  });
}

async function loadSettings() {
  const settings = await apiFetch("/api/settings");
  document.getElementById("smtp-host").value = settings.SMTP_HOST || "";
  document.getElementById("smtp-port").value = settings.SMTP_PORT || "";
  document.getElementById("smtp-user").value = settings.SMTP_USER || "";
  document.getElementById("smtp-pass").value = settings.SMTP_PASS || "";
  document.getElementById("notify-email").value = settings.NOTIFY_EMAIL || "";
  document.getElementById("from-email").value = settings.FROM_EMAIL || "";
  document.getElementById("pushover-token").value = settings.PUSHOVER_TOKEN || "";
  document.getElementById("pushover-user").value = settings.PUSHOVER_USER || "";
  document.getElementById("resy-api-key").value = settings.RESY_API_KEY || "";
  document.getElementById("resy-auth-token").value = settings.RESY_AUTH_TOKEN || "";
}

async function resolveUrl() {
  const url = elements.venueUrl.value.trim();
  if (!url) {
    showMessage(elements.resolveResult, "Please paste a Resy or OpenTable URL.", "error");
    return;
  }

  const response = await fetch("/api/resolve-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  const json = await response.json();

  if (response.ok) {
    elements.restaurantSource.value = json.source;
    elements.restaurantName.value = json.name || "";
    elements.resyId.value = json.resy_venue_id || "";
    elements.opentableId.value = json.opentable_rid || "";
    handleSourceChange();
    showMessage(elements.resolveResult, "URL resolved. Review and add the restaurant.", "success");
  } else {
    showMessage(elements.resolveResult, json.error || "Could not resolve URL.", "error");
  }
}

function handleSourceChange() {
  const source = elements.restaurantSource.value;
  elements.resyIdGroup.hidden = source !== "resy";
  elements.opentableIdGroup.hidden = source !== "opentable";
}

async function submitRestaurantForm(event) {
  event.preventDefault();

  const { days, timeRanges } = getSelectedDaysAndTimes(elements.daysTimeGrid);

  const payload = {
    name: elements.restaurantName.value.trim(),
    source: elements.restaurantSource.value,
    resy_venue_id: elements.restaurantSource.value === "resy" ? elements.resyId.value.trim() : null,
    opentable_rid: elements.restaurantSource.value === "opentable" ? elements.opentableId.value.trim() : null,
    party_sizes: normalizePartySizes(elements.partySizes.value),
    days: days,
    time_ranges: timeRanges,
    enabled: true,
  };

  if (!payload.name) {
    showMessage(elements.resolveResult, "Restaurant name is required.", "error");
    return;
  }
  if (!payload.days.length) {
    showMessage(elements.resolveResult, "Select at least one day.", "error");
    return;
  }
  if (payload.source === "resy" && !payload.resy_venue_id) {
    showMessage(elements.resolveResult, "Resy venue ID is required.", "error");
    return;
  }
  if (payload.source === "opentable" && !payload.opentable_rid) {
    showMessage(elements.resolveResult, "OpenTable restaurant ID is required.", "error");
    return;
  }

  await apiFetch("/api/restaurants", {
    method: "POST",
    body: JSON.stringify(payload),
  });

  showMessage(elements.resolveResult, "Restaurant added successfully.", "success");
  elements.restaurantForm.reset();
  buildDaysTimeGrid(elements.daysTimeGrid);
  handleSourceChange();
  loadRestaurants();
}

async function saveSettings(event) {
  event.preventDefault();
  const payload = {
    SMTP_HOST: document.getElementById("smtp-host").value.trim(),
    SMTP_PORT: document.getElementById("smtp-port").value.trim(),
    SMTP_USER: document.getElementById("smtp-user").value.trim(),
    SMTP_PASS: document.getElementById("smtp-pass").value.trim(),
    NOTIFY_EMAIL: document.getElementById("notify-email").value.trim(),
    FROM_EMAIL: document.getElementById("from-email").value.trim(),
    PUSHOVER_TOKEN: document.getElementById("pushover-token").value.trim(),
    PUSHOVER_USER: document.getElementById("pushover-user").value.trim(),
    RESY_API_KEY: document.getElementById("resy-api-key").value.trim(),
    RESY_AUTH_TOKEN: document.getElementById("resy-auth-token").value.trim(),
  };
  await apiFetch("/api/settings", { method: "POST", body: JSON.stringify(payload) });
  showMessage(elements.settingsMessage, "Notification settings saved.", "success");
}

async function initialize() {
  buildDaysTimeGrid(elements.daysTimeGrid);
  handleSourceChange();
  loadRestaurants();
  loadLogs();
  loadSettings();
  elements.resolveUrlButton.addEventListener("click", resolveUrl);
  elements.restaurantSource.addEventListener("change", handleSourceChange);
  elements.restaurantForm.addEventListener("submit", submitRestaurantForm);
  elements.settingsForm.addEventListener("submit", saveSettings);

  setInterval(loadLogs, 30000);
}

initialize();
