const state = {
  routes: null,
  selectedZone: null,
};

async function fetchRoutes() {
  const response = await fetch("/api/routes", { cache: "no-store" });
  if (!response.ok) {
    throw new Error("Could not load route data.");
  }
  return response.json();
}

function setStatus(message, tone = "info") {
  const panel = document.getElementById("status-panel");
  panel.textContent = message;
  panel.dataset.tone = tone;
}

function renderTabs() {
  const tabs = document.getElementById("zone-tabs");
  tabs.innerHTML = "";

  for (const zone of state.routes.zones) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "zone-tab";
    if (zone.zone === state.selectedZone) {
      button.classList.add("is-active");
    }
    button.innerHTML = zone.runner
      ? `<span class="zone-tab-title">${zone.title}</span><span class="zone-tab-runner">${zone.runner}</span>`
      : `<span class="zone-tab-title">${zone.title}</span><span class="zone-tab-runner">${zone.segment_count} segments</span>`;
    button.addEventListener("click", () => {
      state.selectedZone = zone.zone;
      renderTabs();
      renderSegments();
    });
    tabs.appendChild(button);
  }
}

function segmentCard(segment) {
  const article = document.createElement("article");
  article.className = "segment-card";

  const heading = document.createElement("div");
  heading.className = "segment-header";
  heading.innerHTML = `
    <div>
      <p class="segment-kicker">Segment ${segment.segment}</p>
      <h2>${segment.start_stop} to ${segment.end_stop}</h2>
      ${segment.runner ? `<p class="runner-name">Assigned to ${segment.runner}</p>` : ""}
    </div>
    <a class="open-button" href="${segment.link}" target="_blank" rel="noopener noreferrer">Open in Maps</a>
  `;

  const stops = document.createElement("p");
  stops.className = "stop-list";
  stops.textContent = `Stops: ${segment.stops_in_segment}`;

  const linkRow = document.createElement("div");
  linkRow.className = "link-row";

  const copyButton = document.createElement("button");
  copyButton.type = "button";
  copyButton.className = "copy-button";
  copyButton.textContent = "Copy Link";
  copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(segment.link);
      copyButton.textContent = "Copied";
      setTimeout(() => {
        copyButton.textContent = "Copy Link";
      }, 1200);
    } catch {
      alert("Could not copy the link on this device.");
    }
  });

  const plainLink = document.createElement("a");
  plainLink.className = "plain-link";
  plainLink.href = segment.link;
  plainLink.target = "_blank";
  plainLink.rel = "noopener noreferrer";
  plainLink.textContent = "Preview Link";

  linkRow.append(copyButton, plainLink);
  article.append(heading, stops, linkRow);
  return article;
}

function renderSegments() {
  const list = document.getElementById("segment-list");
  list.innerHTML = "";

  const zone = state.routes.zones.find((entry) => entry.zone === state.selectedZone);
  if (!zone) {
    setStatus("No route segments found.", "warning");
    return;
  }

  const runnerBanner = document.getElementById("runner-banner");
  const runnerBannerName = document.getElementById("runner-banner-name");
  if (zone.runner) {
    runnerBanner.hidden = false;
    runnerBannerName.textContent = zone.runner;
  } else {
    runnerBanner.hidden = true;
    runnerBannerName.textContent = "";
  }

  const runnerText = zone.runner ? ` for ${zone.runner}` : "";
  setStatus(`${zone.title}${runnerText} has ${zone.segment_count} route segments ready.`, "success");
  for (const segment of zone.segments) {
    list.appendChild(segmentCard(segment));
  }
}

function renderSummary() {
  document.getElementById("generated-at").textContent = state.routes.generated_at || "No route run found";
  document.getElementById("segment-count").textContent = String(state.routes.segment_count || 0);
}

async function loadApp() {
  try {
    setStatus("Loading latest routes...");
    state.routes = await fetchRoutes();
    renderSummary();

    if (!state.routes.zones.length) {
      document.getElementById("zone-tabs").innerHTML = "";
      document.getElementById("segment-list").innerHTML = "";
      document.getElementById("runner-banner").hidden = true;
      setStatus("No route output files were found yet. Run the route builder first.", "warning");
      return;
    }

    state.selectedZone = state.routes.zones[0].zone;
    renderTabs();
    renderSegments();
  } catch (error) {
    console.error(error);
    setStatus("Could not load route data. Make sure the server is running.", "danger");
  }
}

document.getElementById("refresh-button").addEventListener("click", loadApp);
loadApp();
