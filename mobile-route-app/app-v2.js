const state = {
  routes: null,
  selectedZone: null,
  currentPhase: "install",
  runnerStopIndex: 0,
  runnerSegmentsExpanded: false,
  adminSegmentsExpanded: false,
  runnerShowAllStops: false,
  adminAddressesExpanded: false,
  adminIssuesExpanded: false,
  adminClosedIssuesExpanded: false,
};

const context = window.APP_CONTEXT || {};
const pageParams = new URLSearchParams(window.location.search);
const runnerFilter = (context.runnerFilter || pageParams.get("runner") || "").trim();
const runnerAccess = (context.runnerAccess || pageParams.get("access") || "").trim();
const requestedPhase = (context.requestedPhase || pageParams.get("phase") || "").trim().toLowerCase();
const isAdmin = Boolean(context.isAdmin);
const isRunnerView = Boolean(context.isRunnerView);

function isoToday() {
  return new Date().toISOString().slice(0, 10);
}

function inferPhase(routes) {
  if (requestedPhase === "install" || requestedPhase === "pickup") {
    return requestedPhase;
  }
  if (isRunnerView) {
    return "";
  }
  if (routes?.return_date && isoToday() >= routes.return_date) {
    return "pickup";
  }
  return "install";
}

function phaseLabel(phase) {
  return phase === "pickup" ? "Pickup Day" : "Emplace Day";
}

function phaseRouteDate(phase) {
  if (!state.routes) {
    return "";
  }
  return phase === "pickup" ? (state.routes.return_date || "") : (state.routes.pickup_date || "");
}

function formatRouteDate(value) {
  if (!value) {
    return "";
  }
  const parsed = new Date(`${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function phaseLabelWithDate(phase) {
  const routeDate = formatRouteDate(phaseRouteDate(phase));
  return routeDate ? `${phaseLabel(phase)} - ${routeDate}` : phaseLabel(phase);
}

function phaseVerb(phase) {
  return phase === "pickup" ? "picked up" : "emplaced";
}

function isPhaseSelected() {
  return state.currentPhase === "install" || state.currentPhase === "pickup";
}

function formatDateTime(value) {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function stopMapLink(stop) {
  const address = String(stop.address || "").trim();
  if (address) {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`;
  }
  if (stop.lat && stop.lng) {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${stop.lat},${stop.lng}`)}`;
  }
  return "https://www.google.com/maps";
}

function stopPreviewEmbedLink(stop) {
  if (!(stop.lat && stop.lng)) {
    return "";
  }
  const lat = Number(stop.lat);
  const lng = Number(stop.lng);
  if (Number.isNaN(lat) || Number.isNaN(lng)) {
    return "";
  }
  const pad = 0.006;
  const left = lng - pad;
  const bottom = lat - pad;
  const right = lng + pad;
  const top = lat + pad;
  return `https://www.openstreetmap.org/export/embed.html?bbox=${left}%2C${bottom}%2C${right}%2C${top}&layer=mapnik&marker=${lat}%2C${lng}`;
}

function installCount(zone) {
  return (zone?.stops || []).filter((stop) => stop.install_status === "installed").length;
}

function pickedUpCount(zone) {
  return (zone?.stops || []).filter((stop) => stop.install_status === "installed" && stop.pickup_status === "picked_up").length;
}

function currentlyOutCount(zone) {
  return installCount(zone) - pickedUpCount(zone);
}

function notInstalledCount(zone) {
  return (zone?.stops || []).length - installCount(zone);
}

function visibleStops(zone) {
  if (!zone) {
    return [];
  }
  return zone.stops || [];
}

function overallVisibleStopCount(routes) {
  return (routes?.zones || []).reduce((total, zone) => total + visibleStops(zone).length, 0);
}

function activeZone() {
  return state.routes?.zones.find((zone) => zone.zone === state.selectedZone) || null;
}

function activeRunnerStop(zone) {
  const stops = visibleStops(zone);
  if (!stops.length) {
    return null;
  }
  if (state.runnerStopIndex >= stops.length) {
    state.runnerStopIndex = stops.length - 1;
  }
  return stops[state.runnerStopIndex];
}

function setStatus(message, tone = "info") {
  const panel = document.getElementById("status-panel");
  panel.textContent = message;
  panel.dataset.tone = tone;
}

async function fetchRoutes() {
  let apiUrl = "/api/routes";
  if (runnerFilter) {
    apiUrl += `?runner=${encodeURIComponent(runnerFilter)}`;
    if (runnerAccess) {
      apiUrl += `&access=${encodeURIComponent(runnerAccess)}`;
    }
  }
  const response = await fetch(apiUrl, { cache: "no-store" });
  if (!response.ok) {
    throw new Error("Could not load route data.");
  }
  return response.json();
}

async function postStopStatus(payload) {
  const response = await fetch("/api/stop-status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error("Could not save stop status.");
  }
  return response.json();
}

async function postStopNote(payload) {
  const response = await fetch("/api/stop-note", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error("Could not save stop note.");
  }
  return response.json();
}

async function postIssueResolution(payload) {
  const response = await fetch("/api/resolve-issue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error("Could not update issue status.");
  }
  return response.json();
}

function updatePhaseInUrl() {
  const url = new URL(window.location.href);
  if (isPhaseSelected()) {
    url.searchParams.set("phase", state.currentPhase);
  } else {
    url.searchParams.delete("phase");
  }
  history.replaceState({}, "", url);
}

function renderSummary() {
  document.getElementById("generated-at").textContent = state.routes.generated_at || "No route run found";
  document.getElementById("summary-count-label").textContent = state.currentPhase === "pickup" ? "Pickup Stops" : "Route Stops";
  document.getElementById("summary-count").textContent = String(overallVisibleStopCount(state.routes));
}

function showLaunchScreen() {
  const launchPanel = document.getElementById("launch-panel");
  const launchActions = document.getElementById("launch-actions");
  launchActions.innerHTML = "";
  launchPanel.hidden = false;

  const phases = [
    { key: "install", label: "Emplacing Flags" },
    { key: "pickup", label: "Picking Up Flags" },
  ];

  for (const phase of phases) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "phase-launch-button";
    const routeDate = formatRouteDate(phaseRouteDate(phase.key));
    button.textContent = routeDate ? `${phase.label} - ${routeDate}` : phase.label;
    button.addEventListener("click", () => {
      state.currentPhase = phase.key;
      state.runnerStopIndex = 0;
      updatePhaseInUrl();
      renderAppShell();
    });
    launchActions.appendChild(button);
  }
}

function renderSessionToggle() {
  const panel = document.getElementById("session-panel");
  const container = document.getElementById("session-toggle");
  const heading = document.getElementById("session-heading");
  const subhead = document.getElementById("session-subhead");
  container.innerHTML = "";

  heading.textContent = phaseLabelWithDate(state.currentPhase || "install");
  subhead.textContent = state.currentPhase === "pickup"
    ? "Check each address after the flag has been picked up."
    : "Check each address after the flag has been emplaced.";

  if (isRunnerView) {
    panel.classList.add("is-runner-locked");
    panel.querySelector(".eyebrow").textContent = "Runner Session";
    const zone = activeZone();
    const viewToggle = document.createElement("button");
    viewToggle.type = "button";
    viewToggle.className = "ghost-button";
    viewToggle.textContent = state.runnerShowAllStops ? "Show One Address" : "Show All Addresses";
    viewToggle.addEventListener("click", () => {
      state.runnerShowAllStops = !state.runnerShowAllStops;
      renderStops();
    });
    container.appendChild(viewToggle);

    if (zone) {
      const markAllPlacedButton = document.createElement("button");
      markAllPlacedButton.type = "button";
      markAllPlacedButton.className = "ghost-button";
      markAllPlacedButton.textContent = "Mark All Flags Placed";
      markAllPlacedButton.addEventListener("click", () => {
        selectAllEmplacedInZone(zone);
      });
      container.appendChild(markAllPlacedButton);
    }
    const returnButton = document.createElement("button");
    returnButton.type = "button";
    returnButton.className = "ghost-button";
    returnButton.textContent = "Return to Launch Screen";
    returnButton.addEventListener("click", () => {
      state.currentPhase = "";
      state.runnerStopIndex = 0;
      updatePhaseInUrl();
      renderAppShell();
    });
    container.appendChild(returnButton);
    return;
  }

  panel.classList.remove("is-runner-locked");
  panel.querySelector(".eyebrow").textContent = "Session";

  for (const phase of ["install", "pickup"]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `phase-button${phase === state.currentPhase ? " is-active" : ""}`;
    button.textContent = phaseLabelWithDate(phase);
    button.addEventListener("click", () => {
      if (state.currentPhase === phase) {
        return;
      }
      state.currentPhase = phase;
      state.runnerStopIndex = 0;
      updatePhaseInUrl();
      renderSummary();
      renderSessionToggle();
      renderTabs();
      renderRunnerSummary();
      renderAdminDashboard();
      renderAdminIssues();
      renderAdminAddressToggle();
      renderSegments();
      renderStops();
    });
    container.appendChild(button);
  }
}

function renderAppShell() {
  const launchMode = isRunnerView && !isPhaseSelected();
  document.getElementById("launch-panel").hidden = !launchMode;
  document.getElementById("runner-summary-panel").hidden = launchMode || !isRunnerView;
  document.getElementById("session-panel").hidden = launchMode;
  document.getElementById("status-panel").hidden = launchMode;
  document.getElementById("segment-section").hidden = launchMode;
  document.querySelector(".stop-section").hidden = launchMode;

  if (launchMode) {
    setStatus("Choose a session to begin.", "info");
    showLaunchScreen();
    return;
  }

  document.getElementById("launch-panel").hidden = true;
  renderSummary();
  renderSessionToggle();
  renderTabs();
  renderRunnerSummary();
  renderShareLinks();
  renderAdminDashboard();
  renderAdminIssues();
  renderAdminAddressToggle();
  renderSegments();
  renderStops();
}

function renderAdminAddressToggle() {
  const button = document.getElementById("admin-address-toggle");
  const workspace = document.getElementById("runner-workspace");
  if (!isAdmin) {
    button.hidden = true;
    workspace.classList.remove("is-collapsed");
    return;
  }

  button.hidden = false;
  button.textContent = state.adminAddressesExpanded ? "Hide Addresses" : "Show Addresses";
  workspace.classList.toggle("is-collapsed", !state.adminAddressesExpanded);
}

function renderTabs() {
  const tabs = document.getElementById("zone-tabs");
  tabs.innerHTML = "";

  for (const zone of state.routes.zones) {
    const visibleCount = visibleStops(zone).length;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "zone-tab";
    if (zone.zone === state.selectedZone) {
      button.classList.add("is-active");
    }
    button.innerHTML = `
      <span class="zone-tab-title">${zone.title}</span>
      <span class="zone-tab-runner">${visibleCount} ${visibleCount === 1 ? "flag" : "flags"}</span>
    `;
    button.addEventListener("click", () => {
      state.selectedZone = zone.zone;
      state.runnerStopIndex = 0;
      renderTabs();
      renderRunnerSummary();
      renderAdminAddressToggle();
      renderSegments();
      renderStops();
    });
    tabs.appendChild(button);
  }
}

function buildRunnerLink(runner, access, phase) {
  const params = new URLSearchParams({ runner, access });
  if (phase) {
    params.set("phase", phase);
  }
  return `/runner?${params.toString()}`;
}

function renderShareLinks() {
  const panel = document.getElementById("share-panel");
  const container = document.getElementById("share-links");
  container.innerHTML = "";

  if (!isAdmin) {
    panel.hidden = true;
    return;
  }

  for (const zone of state.routes.zones) {
    if (!zone.runner) {
      continue;
    }

    const link = buildRunnerLink(zone.runner, zone.runner_access_token || "", "");
    const fullLink = new URL(link, window.location.origin).toString();
    const qrUrl = `/api/qr?data=${encodeURIComponent(fullLink)}`;
    const card = document.createElement("article");
    card.className = "share-card";
    card.innerHTML = `
      <div class="share-card-main">
        <img class="share-qr" src="${qrUrl}" alt="QR code for ${zone.runner}">
        <div>
          <p class="share-kicker">Runner</p>
          <h3>${zone.runner}</h3>
          <p class="share-help">${zone.stops.length} flags assigned in this zone.</p>
          <a class="plain-link" href="${link}">Open Runner Link</a>
        </div>
      </div>
    `;
    container.appendChild(card);
  }

  panel.hidden = container.childElementCount === 0;
}

function renderRunnerSummary() {
  const panel = document.getElementById("runner-summary-panel");
  const grid = document.getElementById("runner-summary-grid");
  grid.innerHTML = "";

  if (!isRunnerView || !state.routes) {
    panel.hidden = true;
    return;
  }

  const zone = activeZone();
  if (!zone) {
    panel.hidden = true;
    return;
  }

  panel.hidden = false;
  const items = [
    ["Flags In Zone", zone.stops.length],
    ["Emplaced", installCount(zone)],
    ["Picked Up", pickedUpCount(zone)],
    ["Still Out", currentlyOutCount(zone)],
  ];

  for (const [label, value] of items) {
    const card = document.createElement("article");
    card.className = "admin-summary-card";
    card.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
    grid.appendChild(card);
  }
}

function renderAdminDashboard() {
  const panel = document.getElementById("admin-panel");
  const summaryGrid = document.getElementById("admin-summary-grid");
  const zoneList = document.getElementById("admin-zone-list");
  summaryGrid.innerHTML = "";
  zoneList.innerHTML = "";

  if (!isAdmin || !state.routes) {
    panel.hidden = true;
    return;
  }

  panel.hidden = false;
  const zones = state.routes.zones || [];
  const totals = {
    currentlyOut: zones.reduce((sum, zone) => sum + currentlyOutCount(zone), 0),
    installedTotal: zones.reduce((sum, zone) => sum + installCount(zone), 0),
    notInstalled: zones.reduce((sum, zone) => sum + notInstalledCount(zone), 0),
    pickedUp: zones.reduce((sum, zone) => sum + pickedUpCount(zone), 0),
    stillToPickUp: zones.reduce((sum, zone) => sum + currentlyOutCount(zone), 0),
  };

  const summaryItems = [
    ["Currently Out", totals.currentlyOut],
    ["Emplaced Total", totals.installedTotal],
    ["Not Emplaced", totals.notInstalled],
    ["Picked Up", totals.pickedUp],
    ["Still To Pick Up", totals.stillToPickUp],
    ["Open Issues", (state.routes.open_issues || []).length],
  ];

  for (const [label, value] of summaryItems) {
    const card = document.createElement("article");
    card.className = "admin-summary-card";
    card.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
    summaryGrid.appendChild(card);
  }

  for (const zone of zones) {
    const installedBy = new Set((zone.stops || []).filter((stop) => stop.install_status === "installed").map((stop) => stop.install_by).filter(Boolean));
    const pickedUpBy = new Set((zone.stops || []).filter((stop) => stop.pickup_status === "picked_up").map((stop) => stop.pickup_by).filter(Boolean));
    const card = document.createElement("article");
    card.className = "admin-zone-card";
    card.innerHTML = `
      <div class="admin-zone-header">
        <div>
          <h3>${zone.title}</h3>
          <p>${currentlyOutCount(zone)} currently out, ${pickedUpCount(zone)} picked up, ${notInstalledCount(zone)} not emplaced</p>
        </div>
        <div class="admin-zone-metrics">
          <span>Emplaced total: ${installCount(zone)}</span>
          <span>Still to pick up: ${currentlyOutCount(zone)}</span>
        </div>
      </div>
      <div class="admin-zone-audit">
        <span>Emplaced by: ${installedBy.size ? Array.from(installedBy).join(", ") : "No emplacements yet"}</span>
        <span>Picked up by: ${pickedUpBy.size ? Array.from(pickedUpBy).join(", ") : "No pickups yet"}</span>
      </div>
    `;
    zoneList.appendChild(card);
  }
}

function renderAdminIssues() {
  const panel = document.getElementById("admin-issues-panel");
  const banner = document.getElementById("admin-issues-banner");
  const list = document.getElementById("admin-issues-list");
  const closedList = document.getElementById("admin-closed-issues-list");
  const toggleButton = document.getElementById("admin-issues-toggle");
  const closedToggleButton = document.getElementById("admin-closed-issues-toggle");
  const closedHeader = document.getElementById("admin-closed-issues-header");
  list.innerHTML = "";
  closedList.innerHTML = "";

  if (!isAdmin || !state.routes) {
    panel.hidden = true;
    toggleButton.hidden = true;
    closedToggleButton.hidden = true;
    closedHeader.hidden = true;
    return;
  }

  const issues = state.routes.open_issues || [];
  const closedIssues = state.routes.closed_issues || [];
  const totalIssueCount = issues.length + closedIssues.length;

  if (!totalIssueCount) {
    panel.hidden = true;
    toggleButton.hidden = true;
    closedToggleButton.hidden = true;
    closedHeader.hidden = true;
    return;
  }

  panel.hidden = false;
  banner.textContent = `${issues.length} OPEN ISSUE${issues.length === 1 ? "" : "S"}`;
  toggleButton.hidden = false;
  toggleButton.textContent = state.adminIssuesExpanded ? "Hide Open Issues" : "Show Open Issues";
  list.hidden = !state.adminIssuesExpanded;
  list.classList.toggle("is-collapsed", !state.adminIssuesExpanded);
  for (const issue of issues) {
    const card = document.createElement("article");
    card.className = "admin-issue-card";
    card.innerHTML = `
      <div class="admin-issue-header">
        <div>
          <p class="share-kicker">Runner: ${escapeHtml(issue.runner || "Unknown")} | Zone ${escapeHtml(issue.zone || "")}</p>
          <h3>${escapeHtml(issue.address || "Unknown address")}</h3>
        </div>
        <span class="admin-issue-time">${escapeHtml(formatDateTime(issue.timestamp) || "No timestamp")}</span>
      </div>
      <p class="admin-issue-meta">Phase: ${escapeHtml(issue.phase || "")}</p>
      <p class="admin-issue-text">${escapeHtml(issue.issue_text || "")}</p>
      <div class="admin-issue-actions">
        <button class="ghost-button resolve-issue-button" type="button">Archive Issue At This Address</button>
      </div>
    `;
    card.querySelector(".resolve-issue-button").addEventListener("click", async () => {
      try {
        await postIssueResolution({
          run_id: state.routes.run_id,
          stop_id: issue.stop_id,
          phase: issue.phase === "pickup" ? "pickup" : "install",
          resolved: true,
        });
        await loadApp({
          preservePhase: true,
          preserveZone: true,
          preserveStopIndex: true,
        });
        state.adminIssuesExpanded = true;
        state.adminClosedIssuesExpanded = true;
        setStatus("Issue archived.", "success");
      } catch (error) {
        console.error(error);
        setStatus("Could not archive that issue.", "danger");
      }
    });
    list.appendChild(card);
  }

  closedHeader.hidden = !closedIssues.length;
  closedToggleButton.hidden = !closedIssues.length;
  closedToggleButton.textContent = state.adminClosedIssuesExpanded ? "Hide Archived Issues" : "Show Archived Issues";
  closedList.hidden = !state.adminClosedIssuesExpanded || !closedIssues.length;
  closedList.classList.toggle("is-collapsed", !state.adminClosedIssuesExpanded || !closedIssues.length);

  for (const issue of closedIssues) {
    const card = document.createElement("article");
    card.className = "admin-issue-card is-closed";
    card.innerHTML = `
      <div class="admin-issue-header">
        <div>
          <p class="share-kicker">Runner: ${escapeHtml(issue.runner || "Unknown")} | Zone ${escapeHtml(issue.zone || "")}</p>
          <h3>${escapeHtml(issue.address || "Unknown address")}</h3>
        </div>
        <span class="admin-issue-time">${escapeHtml(formatDateTime(issue.resolved_at || issue.timestamp) || "No timestamp")}</span>
      </div>
      <p class="admin-issue-meta">Phase: ${escapeHtml(issue.phase || "")} | Resolved by ${escapeHtml(issue.resolved_by || "Admin")}</p>
      <p class="admin-issue-text">${escapeHtml(issue.issue_text || "")}</p>
    `;
    closedList.appendChild(card);
  }
}

function segmentCard(segment) {
  const article = document.createElement("article");
  article.className = "segment-card";
  article.innerHTML = `
    <div class="segment-header">
      <div>
        <p class="segment-kicker">Segment ${segment.segment}</p>
        <h2>${segment.start_stop} to ${segment.end_stop}</h2>
        ${segment.runner ? `<p class="runner-name">${segment.runner}</p>` : ""}
      </div>
      <a class="open-button" href="${segment.link}" target="_blank" rel="noopener noreferrer">Open in Maps</a>
    </div>
    <p class="stop-list">Stops: ${segment.stops_in_segment}</p>
  `;
  return article;
}

function renderSegments() {
  const section = document.getElementById("segment-section");
  const list = document.getElementById("segment-list");
  const toggleButton = document.getElementById("segment-toggle-button");
  const zone = activeZone();
  list.innerHTML = "";

  if (!zone || !(zone.segments || []).length) {
    section.hidden = true;
    section.classList.remove("is-collapsed");
    return;
  }

  section.hidden = false;
  if (isRunnerView) {
    toggleButton.hidden = false;
    toggleButton.textContent = state.runnerSegmentsExpanded ? "Hide Route Segments" : "Show Route Segments";
    section.classList.toggle("is-collapsed", !state.runnerSegmentsExpanded);
  } else {
    toggleButton.hidden = false;
    toggleButton.textContent = state.adminSegmentsExpanded ? "Hide Route Segments" : "Show Route Segments";
    section.classList.toggle("is-collapsed", !state.adminSegmentsExpanded);
  }

  const runnerBanner = document.getElementById("runner-banner");
  const runnerBannerName = document.getElementById("runner-banner-name");
  if (zone.runner) {
    runnerBanner.hidden = false;
    runnerBannerName.textContent = `${zone.runner} | ${zone.stops.length} flags`;
    document.title = `${zone.runner} - ${phaseLabelWithDate(state.currentPhase)} - Flags of Geary County`;
  } else {
    runnerBanner.hidden = true;
    runnerBannerName.textContent = "";
    document.title = "Flags of Geary County";
  }

  for (const segment of zone.segments) {
    list.appendChild(segmentCard(segment));
  }
}

function renderStopPreview(zone, stop) {
  const panel = document.getElementById("stop-preview-panel");
  const title = document.getElementById("stop-preview-title");
  const meta = document.getElementById("stop-preview-meta");
  const map = document.getElementById("stop-preview-map");

  if (!isRunnerView || !stop) {
    panel.hidden = true;
    map.removeAttribute("src");
    return;
  }

  panel.hidden = false;
  title.textContent = stop.address || "Current Address";
  meta.textContent = `${stop.name || "No resident name listed"}${stop.number_of_flags ? ` | Flags: ${stop.number_of_flags}` : ""}`;

  const embedLink = stopPreviewEmbedLink(stop);
  if (embedLink) {
    map.src = embedLink;
  } else {
    map.removeAttribute("src");
  }
}

function actorName(zone) {
  return runnerFilter || zone.runner || "Admin";
}

async function updateStopStatus(zone, stop, checked) {
  const phase = state.currentPhase;
  const status = checked ? (phase === "pickup" ? "picked_up" : "installed") : "pending";

  try {
    await postStopStatus({
      run_id: state.routes.run_id,
      stop_id: stop.stop_id,
      phase,
      status,
      note: "",
      updated_by: actorName(zone),
      runner: zone.runner,
      access: runnerAccess,
    });
    await loadApp({ preservePhase: true, preserveZone: true, preserveStopIndex: true });
  } catch (error) {
    console.error(error);
    alert("Could not save that checkbox update.");
  }
}

async function selectAllEmplacedInZone(zone) {
  const stops = visibleStops(zone).filter((stop) => stop.install_status !== "installed");
  if (!stops.length) {
    setStatus(`${zone.title}: all addresses are already marked emplaced.`, "success");
    return;
  }

  try {
    setStatus(`Marking ${stops.length} addresses as emplaced...`, "info");
    for (const stop of stops) {
      await postStopStatus({
        run_id: state.routes.run_id,
        stop_id: stop.stop_id,
        phase: "install",
        status: "installed",
        note: "",
        updated_by: actorName(zone),
        runner: zone.runner,
        access: runnerAccess,
      });
    }
    await loadApp({ preservePhase: true, preserveZone: true, preserveStopIndex: true });
    setStatus(`${zone.title}: all addresses have been marked emplaced.`, "success");
  } catch (error) {
    console.error(error);
    alert("Could not mark all addresses as emplaced.");
  }
}

async function updateStopNote(zone, stop, note, button) {
  try {
    await postStopNote({
      run_id: state.routes.run_id,
      stop_id: stop.stop_id,
      phase: state.currentPhase,
      note,
      runner: zone.runner,
      access: runnerAccess,
    });
    if (button) {
      button.textContent = "Issue Saved";
      setTimeout(() => {
        button.textContent = "Save Issue";
      }, 1200);
    }
    await loadApp({ preservePhase: true, preserveZone: true, preserveStopIndex: true });
  } catch (error) {
    console.error(error);
    alert("Could not save that issue note.");
  }
}

function stopAuditLines(stop) {
  const lines = [];
  lines.push(`Emplace status: ${stop.install_status === "installed" ? "emplaced" : "not emplaced"}`);
  if (stop.install_at || stop.install_by) {
    lines.push(`Emplaced: ${stop.install_by || "Unknown"}${stop.install_at ? ` on ${formatDateTime(stop.install_at)}` : ""}`);
  }
  if (stop.pickup_at || stop.pickup_by) {
    lines.push(`Picked up: ${stop.pickup_by || "Unknown"}${stop.pickup_at ? ` on ${formatDateTime(stop.pickup_at)}` : ""}`);
  }
  return lines;
}

function buildStopCard(zone, stop, isRunnerActive) {
  const article = document.createElement("article");
  article.className = `stop-card${isRunnerActive ? " is-runner-active" : ""}`;
  const checked = state.currentPhase === "pickup"
    ? stop.pickup_status === "picked_up"
    : stop.install_status === "installed";
  const auditLines = stopAuditLines(stop);
  const issueNote = state.currentPhase === "pickup" ? (stop.pickup_note || "") : (stop.install_note || "");
  const checkboxInstruction = state.currentPhase === "pickup"
    ? "Check here to mark this flag picked up."
    : "Check here to mark this flag emplaced.";
  const checkboxStatus = state.currentPhase === "pickup"
    ? (checked ? "Current status: Flag picked up" : "Current status: Flag not picked up")
    : (checked ? "Current status: Flag emplaced" : "Current status: Flag not emplaced");

  article.innerHTML = `
    <div class="stop-check-row">
      <input class="stop-checkbox" type="checkbox" ${checked ? "checked" : ""}>
      <div class="stop-check-body">
        <p class="segment-kicker">${stop.stop_id}</p>
        <h3>${stop.address}</h3>
        <p class="stop-meta">${stop.name || "No resident name listed"}</p>
        <p class="stop-meta">Runner: ${zone.runner || "Unassigned"}${stop.number_of_flags ? ` | Flags: ${stop.number_of_flags}` : ""}</p>
        <p class="checkbox-copy">${checkboxInstruction}</p>
        <p class="checkbox-status">${checkboxStatus}</p>
        <div class="stop-link-row">
          <a class="stop-map-link" href="${stopMapLink(stop)}" target="_blank" rel="noopener noreferrer">Navigate</a>
        </div>
        <label class="issue-label">Issues at this address</label>
        <textarea class="issue-input" rows="3" placeholder="Could not find the flag base, no access, or other issue...">${issueNote}</textarea>
        <div class="issue-actions">
          <button class="ghost-button save-issue-button" type="button">Save Issue</button>
        </div>
        ${auditLines.map((line) => `<p class="status-timestamp">${line}</p>`).join("")}
        ${stop.notes ? `<p class="stop-notes">${stop.notes}</p>` : ""}
      </div>
    </div>
  `;

  article.querySelector(".stop-checkbox").addEventListener("change", (event) => {
    event.stopPropagation();
    updateStopStatus(zone, stop, event.target.checked);
  });

  const issueInput = article.querySelector(".issue-input");
  const saveIssueButton = article.querySelector(".save-issue-button");
  saveIssueButton.addEventListener("click", () => {
    updateStopNote(zone, stop, issueInput.value, saveIssueButton);
  });

  return article;
}

function buildRunnerNavigation(zone) {
  const wrapper = document.createElement("div");
  wrapper.className = "runner-nav-row";
  const stops = visibleStops(zone);
  const lastIndex = stops.length - 1;
  const previousButton = document.createElement("button");
  previousButton.type = "button";
  previousButton.className = "ghost-button";
  previousButton.textContent = "Previous Address";
  previousButton.disabled = state.runnerStopIndex <= 0;
  previousButton.addEventListener("click", () => {
    if (state.runnerStopIndex > 0) {
      state.runnerStopIndex -= 1;
      renderStops();
    }
  });

  const nextButton = document.createElement("button");
  nextButton.type = "button";
  nextButton.className = "open-button";
  nextButton.textContent = state.runnerStopIndex >= lastIndex ? "Last Address" : "Next Address";
  nextButton.disabled = state.runnerStopIndex >= lastIndex;
  nextButton.addEventListener("click", () => {
    if (state.runnerStopIndex < lastIndex) {
      state.runnerStopIndex += 1;
      renderStops();
    }
  });
  wrapper.append(previousButton, nextButton);
  return wrapper;
}

function renderStops() {
  const container = document.getElementById("stop-list-grid");
  const kicker = document.getElementById("stop-section-kicker");
  const heading = document.getElementById("stop-section-heading");
  const zone = activeZone();
  container.innerHTML = "";

  if (state.currentPhase === "pickup") {
    kicker.textContent = "Pickup Checklist";
    heading.textContent = "Mark each previously emplaced flag as picked up";
  } else {
    kicker.textContent = "Emplace Checklist";
    heading.textContent = "Mark each address after the flag is emplaced";
  }

  if (!zone) {
    setStatus("No route stops were found.", "warning");
    return;
  }

  const stops = visibleStops(zone);
  if (!stops.length) {
    setStatus(
      state.currentPhase === "pickup"
        ? `${zone.title} has no stops in this route.`
        : `${zone.title} has no stops in this route.`,
      "warning",
    );
    return;
  }

  if (state.currentPhase === "pickup") {
    setStatus(`${zone.title}: ${pickedUpCount(zone)} picked up, ${currentlyOutCount(zone)} still out, ${notInstalledCount(zone)} not emplaced.`, "success");
  } else {
    setStatus(`${zone.title}: ${installCount(zone)} emplaced, ${notInstalledCount(zone)} not emplaced.`, "success");
  }

  if (isRunnerView) {
    if (state.runnerShowAllStops) {
      for (const stop of stops) {
        container.appendChild(buildStopCard(zone, stop, false));
      }
      renderStopPreview(zone, null);
    } else {
      const stop = activeRunnerStop(zone);
      if (stop) {
        container.appendChild(buildStopCard(zone, stop, true));
        container.appendChild(buildRunnerNavigation(zone));
        renderStopPreview(zone, stop);
      }
    }
    return;
  }

  renderStopPreview(zone, null);

  for (const stop of stops) {
    container.appendChild(buildStopCard(zone, stop, false));
  }
}

async function loadApp(options = {}) {
  const preservePhase = Boolean(options.preservePhase);
  const preserveZone = Boolean(options.preserveZone);
  const preserveStopIndex = Boolean(options.preserveStopIndex);

  try {
    const previousZone = preserveZone ? state.selectedZone : null;
    const previousStopIndex = preserveStopIndex ? state.runnerStopIndex : 0;
    setStatus("Loading latest routes...");
    state.routes = await fetchRoutes();
    state.currentPhase = preservePhase && state.currentPhase ? state.currentPhase : inferPhase(state.routes);
    updatePhaseInUrl();
    if (!state.routes.zones.length) {
      document.getElementById("zone-tabs").innerHTML = "";
      document.getElementById("segment-list").innerHTML = "";
      document.getElementById("stop-list-grid").innerHTML = "";
      document.getElementById("runner-banner").hidden = true;
      document.getElementById("runner-summary-panel").hidden = true;
      document.getElementById("share-panel").hidden = true;
      document.getElementById("admin-panel").hidden = true;
      document.getElementById("admin-issues-panel").hidden = true;
      document.getElementById("admin-issues-toggle").hidden = true;
      document.getElementById("admin-closed-issues-header").hidden = true;
      document.getElementById("admin-closed-issues-toggle").hidden = true;
      document.getElementById("admin-address-toggle").hidden = true;
      document.getElementById("segment-section").hidden = true;
      document.getElementById("stop-preview-panel").hidden = true;
      setStatus("No route output files were found yet. Run the route builder first.", "warning");
      return;
    }

    state.selectedZone = state.routes.zones.some((zone) => zone.zone === previousZone)
      ? previousZone
      : state.routes.zones[0].zone;
    state.runnerStopIndex = previousStopIndex;

    renderAppShell();
  } catch (error) {
    console.error(error);
    setStatus("Could not load route data. Make sure the server is running.", "danger");
  }
}

document.getElementById("refresh-button").addEventListener("click", () => loadApp({
  preservePhase: true,
  preserveZone: true,
  preserveStopIndex: true,
}));

document.getElementById("segment-toggle-button").addEventListener("click", () => {
  if (isRunnerView) {
    state.runnerSegmentsExpanded = !state.runnerSegmentsExpanded;
  } else {
    state.adminSegmentsExpanded = !state.adminSegmentsExpanded;
  }
  renderSegments();
});

document.getElementById("admin-address-toggle").addEventListener("click", () => {
  state.adminAddressesExpanded = !state.adminAddressesExpanded;
  renderAdminAddressToggle();
});

document.getElementById("admin-issues-toggle").addEventListener("click", () => {
  state.adminIssuesExpanded = !state.adminIssuesExpanded;
  renderAdminIssues();
});

document.getElementById("admin-closed-issues-toggle").addEventListener("click", () => {
  state.adminClosedIssuesExpanded = !state.adminClosedIssuesExpanded;
  renderAdminIssues();
});

loadApp();
