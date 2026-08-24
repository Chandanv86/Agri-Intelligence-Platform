const API = "/api/v1";
const BOUNDARIES = "/static/boundaries";

const COUNTRY_BY_ISO3 = { IND: "IND", KEN: "KEN", UGA: "UGA", TZA: "TZA", ETH: "ETH", ZAF: "ZAF" };
const ADMIN1_FILE = {
  IND: "admin1_india.geojson", KEN: "admin1_kenya.geojson", UGA: "admin1_uganda.geojson",
  TZA: "admin1_tanzania.geojson", ETH: "admin1_ethiopia.geojson", ZAF: "admin1_south_africa.geojson",
};
const COUNTRY_NAMES = { IND: "India", KEN: "Kenya", UGA: "Uganda", TZA: "Tanzania", ETH: "Ethiopia", ZAF: "South Africa" };

// India district file slugs mostly match slugify(canonical_name); a small
// number of divergences from the underlying (older-vintage) district source
// need explicit overrides -- see docs/BOUNDARY_DATA_SOURCES.md.
const INDIA_DISTRICT_FILE_OVERRIDES = { "NCT of Delhi": "delhi" };

function slugify(name) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try { const body = await r.json(); if (body.detail) detail = body.detail; } catch (e) {}
    const err = new Error(detail);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

// ---------------------------------------------------------------- state ---
const state = { breadcrumb: ["World"], indiaDistrictManifest: null };

const el = (id) => document.getElementById(id);
const cardsRoot = el("cards-root");
const listPicker = el("list-picker");
const emptyState = el("empty-state");
const brandBreadcrumb = el("brand-breadcrumb");

function setBreadcrumb(parts) {
  state.breadcrumb = parts;
  brandBreadcrumb.textContent = parts.join(" → ");
}
function showEmptyPanel() {
  cardsRoot.innerHTML = "";
  listPicker.style.display = "none";
  emptyState.style.display = "block";
}
function fmt(n, digits = 1) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}

// ------------------------------------------------------------- map init ---
const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {
      // NOTE: tile.openstreetmap.org does not reliably send CORS headers,
      // and MapLibre GL (WebGL) refuses to texture-map an image that fails
      // the CORS check -- this breaks the base map for every visitor, not
      // just in restricted environments. CARTO's free basemap tiles do send
      // proper CORS headers and are commonly used with MapLibre/Mapbox GL
      // for exactly this reason. Attribution to OSM is still required and
      // included below since CARTO's basemap is itself OSM-derived.
      basemap: {
        type: "raster",
        tiles: ["https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"],
        tileSize: 256,
        attribution: "© OpenStreetMap contributors © CARTO",
      },
    },
    layers: [{ id: "basemap", type: "raster", source: "basemap" }],
  },
  center: [45, 10],
  zoom: 1.6,
  projection: "globe",
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
window.__map = map; // exposed for automated testing (Playwright); harmless in production

let idleRotation = null;
function startIdleRotation() {
  stopIdleRotation();
  idleRotation = setInterval(() => {
    const c = map.getCenter();
    map.easeTo({ center: [c.lng + 0.25, c.lat], duration: 260, easing: (t) => t });
  }, 260);
}
function stopIdleRotation() {
  if (idleRotation) { clearInterval(idleRotation); idleRotation = null; }
}
map.on("dragstart", stopIdleRotation);
map.on("wheel", stopIdleRotation);

function bboxOfGeometry(geometry) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const walk = (coords) => {
    if (typeof coords[0] === "number") {
      const [x, y] = coords;
      if (x < minX) minX = x; if (x > maxX) maxX = x;
      if (y < minY) minY = y; if (y > maxY) maxY = y;
    } else { coords.forEach(walk); }
  };
  walk(geometry.coordinates);
  return [[minX, minY], [maxX, maxY]];
}

// --------------------------------------------------- ONE active handler ---
// Only ever one map layer is "interactive" at a time -- this is the fix for
// the earlier version's bug where drilling into districts left the parent
// state layer's click handler still live underneath, firing both handlers
// on a single click. `activeHandler` is always {layerId, fn} or null, and
// every drill-in/reset path goes through setActiveHandler().
let activeHandler = null;
function setActiveHandler(layerId, fn) {
  if (activeHandler) {
    map.off("click", activeHandler.layerId, activeHandler.fn);
  }
  activeHandler = layerId ? { layerId, fn } : null;
  if (activeHandler) {
    map.on("click", layerId, fn);
  }
}

const LAYER_IDS = {
  world: ["world-context-fill", "world-context-line", "world-supported-fill", "world-supported-line"],
  admin1: ["admin1-fill", "admin1-line"],
  admin2: ["admin2-fill", "admin2-line"],
};
function removeLayerGroup(key) {
  for (const id of LAYER_IDS[key]) { if (map.getLayer(id)) map.removeLayer(id); }
  if (map.getSource(key)) map.removeSource(key);
}

// Plain DOM popups instead of WebGL text-field symbol layers: MapLibre's
// symbol layers require a `glyphs` (font PBF) URL configured on the style,
// which this self-contained build deliberately doesn't add (one less
// external CDN dependency). A hover popup gives the same "what is this"
// feedback without that requirement.
const hoverPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
function bindHoverPopup(layerId, getLabel) {
  map.on("mousemove", layerId, (e) => {
    map.getCanvas().style.cursor = "pointer";
    const label = getLabel(e.features[0]);
    hoverPopup.setLngLat(e.lngLat).setText(label).addTo(map);
  });
  map.on("mouseleave", layerId, () => {
    map.getCanvas().style.cursor = "";
    hoverPopup.remove();
  });
}

async function initWorldLayers() {
  const [context, supported] = await Promise.all([
    getJSON(`${BOUNDARIES}/world_all_countries.geojson`),
    getJSON(`${BOUNDARIES}/world_supported_countries.geojson`),
  ]);
  map.addSource("world", { type: "geojson", data: context });
  map.addLayer({ id: "world-context-fill", type: "fill", source: "world", paint: { "fill-color": "#1c2a25", "fill-opacity": 0.5 } });
  map.addLayer({ id: "world-context-line", type: "line", source: "world", paint: { "line-color": "#24332d", "line-width": 0.6 } });

  map.addSource("world-supported", { type: "geojson", data: supported });
  map.addLayer({ id: "world-supported-fill", type: "fill", source: "world-supported", paint: { "fill-color": "#4fd1a5", "fill-opacity": 0.45 } });
  map.addLayer({ id: "world-supported-line", type: "line", source: "world-supported", paint: { "line-color": "#4fd1a5", "line-width": 1.6 } });
  bindHoverPopup("world-supported-fill", (f) => f.properties.name);
  setActiveHandler("world-supported-fill", onWorldCountryClick);
}

function onWorldCountryClick(e) {
  const feature = e.features[0];
  const countryId = COUNTRY_BY_ISO3[feature.properties["iso-a3"]];
  if (!countryId) return;
  stopIdleRotation();
  enterCountry(countryId, feature);
}

async function enterCountry(countryId, worldFeature) {
  removeLayerGroup("world");
  showEmptyPanel();
  setBreadcrumb(["World", COUNTRY_NAMES[countryId]]);
  map.fitBounds(bboxOfGeometry(worldFeature.geometry), { padding: 60, duration: 1400 });

  const admin1Geojson = await getJSON(`${BOUNDARIES}/${ADMIN1_FILE[countryId]}`);
  const names = admin1Geojson.features.map((f) => f.properties.name);
  const { matches, geometry_level_note } = await getJSON(`${API}/geography/match`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ country_id: countryId, names }),
  });
  for (const f of admin1Geojson.features) f.properties.__admin_id = matches[f.properties.name] || null;

  map.addSource("admin1", { type: "geojson", data: admin1Geojson });
  map.addLayer({ id: "admin1-fill", type: "fill", source: "admin1", paint: { "fill-color": "#4fd1a5", "fill-opacity": 0.25 } });
  map.addLayer({ id: "admin1-line", type: "line", source: "admin1", paint: { "line-color": "#4fd1a5", "line-width": 1.4 } });
  bindHoverPopup("admin1-fill", (f) => f.properties.name);
  setActiveHandler("admin1-fill", (e) => onAdmin1Click(countryId, e.features[0]));

  if (geometry_level_note) showNotLiveMessage(COUNTRY_NAMES[countryId], geometry_level_note);
}

async function ensureIndiaManifest() {
  if (!state.indiaDistrictManifest) {
    state.indiaDistrictManifest = await getJSON(`${BOUNDARIES}/india_districts/_manifest.json`);
  }
  return state.indiaDistrictManifest;
}

async function onAdmin1Click(countryId, feature) {
  const name = feature.properties.name;
  const adminId = feature.properties.__admin_id;
  setBreadcrumb(["World", COUNTRY_NAMES[countryId], name]);
  map.fitBounds(bboxOfGeometry(feature.geometry), { padding: 80, duration: 1200 });

  if (countryId === "KEN") return handleKenyaProvinceClick(name);

  if (countryId === "IND") {
    const manifest = await ensureIndiaManifest();
    const slug = INDIA_DISTRICT_FILE_OVERRIDES[name] || slugify(name);
    if (manifest[slug]) return loadIndiaDistricts(slug, name, adminId);
  }

  // Leaf level: attempt a snapshot directly (handler stays bound to admin1
  // so the user can click a different admin1 unit next).
  if (!adminId) showNotInRegistry(name);
  else await loadAndRenderSnapshot(adminId, name);
}

async function loadIndiaDistricts(slug, stateName, stateAdminId) {
  const geojson = await getJSON(`${BOUNDARIES}/india_districts/${slug}.geojson`);

  let childByName = {};
  if (stateAdminId) {
    try {
      const kids = await getJSON(`${API}/geography/${stateAdminId}/children`);
      for (const k of kids) childByName[k.canonical_name.toLowerCase()] = k.admin_id;
    } catch (e) { /* no MVP children registered for this state -- fine */ }
  }
  for (const f of geojson.features) {
    f.properties.__admin_id = childByName[f.properties.NAME_2.toLowerCase()] || null;
  }

  if (map.getLayer("admin1-fill")) map.setPaintProperty("admin1-fill", "fill-opacity", 0.05);

  map.addSource("admin2", { type: "geojson", data: geojson });
  map.addLayer({ id: "admin2-fill", type: "fill", source: "admin2", paint: { "fill-color": "#f2c14e", "fill-opacity": 0.35 } });
  map.addLayer({ id: "admin2-line", type: "line", source: "admin2", paint: { "line-color": "#f2c14e", "line-width": 1.2 } });
  bindHoverPopup("admin2-fill", (f) => f.properties.NAME_2);
  setActiveHandler("admin2-fill", async (e) => {
    const f = e.features[0];
    const districtName = f.properties.NAME_2;
    setBreadcrumb(["World", "India", stateName, districtName]);
    map.fitBounds(bboxOfGeometry(f.geometry), { padding: 100, duration: 900 });
    const adminId = f.properties.__admin_id;
    if (!adminId) showNotInRegistry(districtName);
    else await loadAndRenderSnapshot(adminId, districtName);
  });
}

async function handleKenyaProvinceClick(provinceName) {
  // NOTE: admin1's click handler (bound in enterCountry) intentionally stays
  // active here, so clicking a different province still works without a
  // manual reset -- Kenya's map layer never gets a deeper interactive layer.
  const groups = await getJSON(`${API}/geography/KEN/legacy-groups`);
  const normalized = provinceName === "North-Eastern" ? "North Eastern" : provinceName;
  const group = groups.find((g) => g.legacy_name.toLowerCase() === normalized.toLowerCase());

  emptyState.style.display = "none";
  cardsRoot.innerHTML = "";
  listPicker.style.display = "flex";
  if (!group || !group.maps_to_admin_ids.length) {
    listPicker.innerHTML = `<div class="not-live-state">No county list available for <strong>${provinceName}</strong> yet.</div>`;
    return;
  }
  const counties = [];
  for (const id of group.maps_to_admin_ids) {
    try {
      const r = await getJSON(`${API}/geography/resolve/${id}`);
      counties.push({ admin_id: r.admin_id, canonical_name: r.canonical_name });
    } catch (e) { /* skip unresolved */ }
  }
  listPicker.innerHTML =
    `<div class="list-picker-title">Counties in ${provinceName} (real county boundaries not available yet — pick one to check for a live snapshot)</div>` +
    counties.map((c) => `<button class="list-item" data-admin-id="${c.admin_id}" data-name="${c.canonical_name}">${c.canonical_name}</button>`).join("");
  listPicker.querySelectorAll(".list-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      setBreadcrumb(["World", "Kenya", provinceName, btn.dataset.name]);
      loadAndRenderSnapshot(btn.dataset.adminId, btn.dataset.name);
    });
  });
}

function showNotInRegistry(name) {
  emptyState.style.display = "none";
  listPicker.style.display = "none";
  cardsRoot.innerHTML = `
    <div class="area-heading">${name}</div>
    <div class="area-sub">${state.breadcrumb.join(" → ")}</div>
    <div class="not-live-state">
      This boundary isn't linked to an administrative registry entry yet, so
      no snapshot can be requested for it. Expected for most areas outside
      the current MVP pilot — see <strong>docs/KNOWN_LIMITATIONS.md</strong>.
    </div>`;
}
function showNotLiveMessage(name, detail) {
  emptyState.style.display = "none";
  listPicker.style.display = "none";
  cardsRoot.innerHTML = `<div class="area-heading">${name}</div><div class="not-live-state">${detail}</div>`;
}

async function loadAndRenderSnapshot(adminId, displayName) {
  cardsRoot.innerHTML = `<div class="loading-pill">Loading snapshot…</div>`;
  listPicker.style.display = "none";
  emptyState.style.display = "none";
  try {
    const payload = await getJSON(`${API}/agri/areas/${adminId}/snapshot?crop_id=rice&season_id=IND-2026-kharif-rice`);
    renderCards(payload);
  } catch (e) {
    cardsRoot.innerHTML = `
      <div class="area-heading">${displayName}</div>
      <div class="area-sub">${state.breadcrumb.join(" → ")}</div>
      <div class="not-live-state">
        <strong>No live analytical snapshot here yet</strong> (${e.status || "error"}).
        The MVP pilot only has real fixture data wired for Ludhiana (Punjab)
        and Patna (Bihar), Rice / Kharif 2026. This area's boundary and
        identity are correctly registered — it just doesn't have satellite
        evidence wired up yet. See docs/KNOWN_LIMITATIONS.md.
      </div>`;
  }
}

function cardHTML(card, snapshot) {
  const path = card.snapshot_path.split(".");
  let val = snapshot;
  for (const p of path) { val = val ? val[p] : undefined; }
  let valueLine = "—", subLine = "", statusPill = "";

  if (card.card_id === "agri_situation" && val) {
    valueLine = `<span class="risk-${val.risk_label}">${val.risk_label} risk</span>`;
    subLine = `Sowing ${fmt(val.sowing_deviation_pp)} pp · Yield ${fmt(val.yield_vs_historical_pct)}% vs historical`;
    statusPill = val.data_status;
  } else if (card.card_id === "sowing_progress" && val) {
    valueLine = `${fmt(val.progress_pct)}%`;
    subLine = `Target ${fmt(val.target_area_ha, 0)} ha · Expected ${fmt(val.expected_progress_pct)}% · ${fmt(val.deviation.value)} pp`;
    statusPill = val.data_status;
  } else if (card.card_id === "sowing_trend" && snapshot.sowing) {
    valueLine = `${fmt(snapshot.sowing.weekly_rate_pp)} pp/wk`;
    subLine = `Status: ${snapshot.sowing.status.replace(/_/g, " ")}`;
  } else if (card.card_id === "yield_current" && snapshot.yield_performance) {
    const y = snapshot.yield_performance;
    valueLine = `${fmt(y.estimated_yield_kg_ha, 0)} kg/ha`;
    subLine = `Historical expected ${fmt(y.historical_expected_yield_kg_ha, 0)} kg/ha`;
    statusPill = y.data_status;
  } else if (card.card_id === "yield_gap" && snapshot.yield_performance) {
    const y = snapshot.yield_performance;
    valueLine = `${fmt(y.yield_gap_kg_ha, 0)} kg/ha`;
    subLine = `${fmt(y.relative_yield_gap_pct)}% below attainable (${y.counterfactual_tier})`;
  } else if (card.card_id === "production_economic" && snapshot.yield_performance) {
    const y = snapshot.yield_performance;
    const currency = y.price_basis ? y.price_basis.currency : "";
    valueLine = `${fmt(y.production_gap_mt, 0)} Mt`;
    subLine = y.economic_exposure ? `${currency} ${fmt(y.economic_exposure, 0)} indicative exposure` : "";
  } else if (card.card_id === "confidence" && snapshot.sowing) {
    const c = snapshot.sowing.confidence;
    valueLine = `${c.label.toUpperCase()} (${fmt(c.score * 100, 0)}%)`;
    subLine = Object.entries(c.components).map(([k, v]) => `${k}: ${fmt(v * 100, 0)}%`).join(" · ");
  } else if (card.card_id === "freshness" && snapshot.sowing) {
    const f = snapshot.sowing.freshness;
    valueLine = new Date(f.observed_at).toLocaleDateString();
    subLine = `Processed ${new Date(f.processed_at).toLocaleDateString()} · gap ${fmt(f.observation_gap_days, 0)}d`;
  } else if (card.card_id === "crops_grown_here" && Array.isArray(val)) {
    valueLine = val.map((c) => `${c.canonical_name} ${fmt(c.area_share_pct)}%`).join(" · ");
  } else if (val && typeof val === "object") {
    subLine = JSON.stringify(val).slice(0, 140);
  } else if (val !== undefined) {
    valueLine = String(val);
  }

  return `
    <div class="card">
      <div class="card-title">${card.title}</div>
      <div class="card-value">${valueLine}</div>
      <div class="card-sub">${subLine}</div>
      ${statusPill ? `<span class="status-pill">${statusPill}</span>` : ""}
    </div>`;
}

function renderCards(payload) {
  const { snapshot, renderable_cards } = payload;
  const badge = el("data-status-badge");
  badge.textContent = `${snapshot.data_status} MODE`;
  badge.className = "badge " + (snapshot.data_status === "DEMO" ? "badge-demo" : "badge-live");
  setBreadcrumb(snapshot.identity.breadcrumb);

  const tiers = { 1: [], 2: [], 3: [] };
  for (const c of renderable_cards) tiers[c.tier].push(c);
  const tierLabel = { 1: "Always visible", 2: "Expandable", 3: "Advanced" };

  let html = `<div class="area-heading">${snapshot.identity.canonical_name}</div>
    <div class="area-sub">${snapshot.identity.breadcrumb.join(" → ")} · ${snapshot.identity.crop_id}</div>`;

  for (const tier of [1, 2, 3]) {
    if (!tiers[tier].length) continue;
    const bodyId = `tier-body-${tier}`;
    html += `<div class="tier-heading">Tier ${tier} — ${tierLabel[tier]} (${tiers[tier].length})</div>`;
    if (tier !== 1) html += `<button class="tier-toggle" data-target="${bodyId}">Show/Hide</button>`;
    html += `<div id="${bodyId}" class="card-grid tier-body ${tier !== 1 ? "collapsed" : ""}">`;
    html += tiers[tier].map((c) => cardHTML(c, snapshot)).join("");
    html += `</div>`;
  }
  cardsRoot.innerHTML = html;
  cardsRoot.querySelectorAll(".tier-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.getElementById(btn.dataset.target).classList.toggle("collapsed");
      btn.classList.toggle("active");
    });
  });
}

// ------------------------------------------------------------- controls ---
el("intro-enter").addEventListener("click", () => {
  el("intro").classList.add("hidden");
  startIdleRotation();
});

el("reset-btn").addEventListener("click", () => {
  removeLayerGroup("admin2");
  removeLayerGroup("admin1");
  activeHandler = null; // layers behind it are already gone; avoid a stale .off() reference
  if (!map.getSource("world")) initWorldLayers();
  map.flyTo({ center: [45, 10], zoom: 1.6, duration: 1600 });
  setBreadcrumb(["World"]);
  showEmptyPanel();
  startIdleRotation();
});

map.on("load", () => { initWorldLayers(); });
