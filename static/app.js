/* DeepakPhotoSearch frontend — vanilla JS SPA with hash routing. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const api = {
  get: (url) => fetch(url).then((r) => r.json()),
  send: (method, url, body) =>
    fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      return r.json();
    }),
};

/* ---------------- state ---------------- */
const state = {
  route: "photos",
  filters: {},        // {person, album, favorites, query}
  items: [],          // loaded photo items (in grid order)
  cursor: null,
  loading: false,
  done: false,
  selection: new Set(),
  lbIndex: -1,        // index into state.items for the lightbox
  lbFaces: true,
  persons: [],
  map: null,
};

/* ---------------- routing ---------------- */
window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", () => {
  bindChrome();
  route();
  pollLoop();
});

let lastScanState = "idle";
async function pollLoop() {
  await pollStatus();
  // poll fast while a scan runs so progress feels live, slow when idle
  const busy = lastScanState === "scanning" || lastScanState === "stopping";
  setTimeout(pollLoop, busy ? 1200 : 4000);
}

function route() {
  const h = (location.hash || "#photos").slice(1);
  const [name, arg] = h.split("/");
  state.route = name;
  document.querySelectorAll(".tabs a").forEach((a) => {
    a.classList.toggle("active", a.dataset.tab === name ||
      (a.dataset.tab === "photos" && ["person", "album", "favorites"].includes(name)) ||
      (a.dataset.tab === "albums" && name === "album"));
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  clearSelection();

  if (name === "people") { $("#view-people").classList.remove("hidden"); loadPeople(); }
  else if (name === "unknown") { $("#view-unknown").classList.remove("hidden"); loadClusters(); }
  else if (name === "albums") { $("#view-albums").classList.remove("hidden"); loadAlbums(); }
  else if (name === "map") { $("#view-map").classList.remove("hidden"); loadMap(); }
  else if (name === "settings") { $("#view-settings").classList.remove("hidden"); loadSettings(); }
  else {
    // photo grid variants: photos | person/<id> | album/<id> | favorites | search
    $("#view-grid").classList.remove("hidden");
    const f = {};
    if (name === "person") f.person = +arg;
    if (name === "album") f.album = +arg;
    if (name === "favorites") f.favorites = 1;
    if (name === "search") f.query = decodeURIComponent(arg || "");
    startGrid(f);
  }
}

function bindChrome() {
  const si = $("#search-input");
  si.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const q = si.value.trim();
      location.hash = q ? "#search/" + encodeURIComponent(q) : "#photos";
    }
  });
  $("#sel-clear").onclick = clearSelection;
  $("#sel-fav").onclick = favoriteSelection;
  $("#sel-album").onclick = () => pickAlbum([...state.selection]);
  $("#new-album-btn").onclick = async () => {
    const name = await promptModal("New album", "Album name");
    if (name) { await api.send("POST", "/api/albums", { name }); loadAlbums(); }
  };
  $("#add-folder-btn").onclick = addFolder;
  $("#browse-folder-btn").onclick = browseFolder;
  $("#folder-input").addEventListener("keydown", (e) => e.key === "Enter" && addFolder());
  $("#scan-btn").onclick = async () => {
    try { await api.send("POST", "/api/scan"); } catch (e) { /* already running */ }
    pollStatus();
  };
  $("#stop-scan-btn").onclick = async () => {
    try { await api.send("POST", "/api/scan/stop"); } catch (e) { /* not running */ }
    pollStatus();
  };
  $("#restart-app-btn").onclick = async () => {
    if (!confirm("Restart the app? A running scan will stop (it resumes on the next scan).")) return;
    try { await api.send("POST", "/api/app/restart"); } catch (e) {}
    document.body.innerHTML = '<div class="empty" style="padding-top:30vh">Restarting… this page will reload automatically.</div>';
    const wait = setInterval(async () => {
      try { await fetch("/api/scan/status"); clearInterval(wait); location.reload(); } catch (e) {}
    }, 1500);
  };
  $("#stop-app-btn").onclick = async () => {
    if (!confirm("Quit the app? Reopen it later with run.bat.")) return;
    try { await api.send("POST", "/api/app/stop"); } catch (e) {}
    document.body.innerHTML = '<div class="empty" style="padding-top:30vh">App stopped. Reopen it with run.bat, then refresh this page.</div>';
  };
  bindLightbox();
}

/* ---------------- photo grid ---------------- */
async function startGrid(filters) {
  state.filters = filters;
  state.items = [];
  state.cursor = null;
  state.done = false;
  $("#grid").innerHTML = "";
  $("#grid-empty").classList.add("hidden");
  await renderGridHeader();
  await loadMore();
  observeSentinel();
}

async function renderGridHeader() {
  const h = $("#grid-header");
  const f = state.filters;
  h.classList.add("hidden");
  if (f.person) {
    const persons = await getPersons();
    const p = persons.find((x) => x.id === f.person);
    h.innerHTML = "";
    const back = el("button", "btn ghost", "←"); back.onclick = () => history.back();
    h.append(back, el("span", "", p ? p.name : "Person"),
             el("span", "sub", p ? `${p.photo_count} photos` : ""));
    if (p) {
      const ren = el("button", "btn", "Rename");
      ren.onclick = async () => {
        const name = await promptModal("Rename person", "Name", p.name);
        if (name) { await api.send("PATCH", `/api/persons/${p.id}`, { name }); state.persons = []; renderGridHeader(); }
      };
      const del = el("button", "btn danger", "Remove person");
      del.onclick = async () => {
        if (confirm(`Remove "${p.name}"? Photos are kept; their faces go back to Unknown.`)) {
          await api.send("DELETE", `/api/persons/${p.id}`); state.persons = []; location.hash = "#people";
        }
      };
      h.append(ren, del);
    }
    h.classList.remove("hidden");
  } else if (f.album) {
    const albums = await api.get("/api/albums");
    const a = albums.find((x) => x.id === f.album);
    h.innerHTML = "";
    const back = el("button", "btn ghost", "←"); back.onclick = () => (location.hash = "#albums");
    h.append(back, el("span", "", a ? a.name : "Album"),
             el("span", "sub", a ? `${a.photo_count} photos` : ""));
    h.classList.remove("hidden");
  } else if (f.favorites) {
    h.textContent = "♥ Favorites"; h.classList.remove("hidden");
  } else if (f.query) {
    h.innerHTML = "";
    h.append(el("span", "", `Results for “${f.query}”`));
    h.classList.remove("hidden");
    $("#search-input").value = f.query;
  } else {
    $("#search-input").value = "";
  }
}

async function loadMore() {
  if (state.loading || state.done) return;
  state.loading = true;
  const f = state.filters;
  const qs = new URLSearchParams();
  if (state.cursor) qs.set("cursor", state.cursor);
  if (f.person) qs.set("person", f.person);
  if (f.album) qs.set("album", f.album);
  if (f.favorites) qs.set("favorites", 1);
  if (f.query) qs.set("query", f.query);
  const data = await api.get("/api/timeline?" + qs);
  state.cursor = data.next_cursor;
  state.done = !data.next_cursor;
  appendItems(data.items, data.mode);
  state.loading = false;
  if (!state.items.length) {
    const e = $("#grid-empty");
    e.classList.remove("hidden");
    e.textContent = f.query ? "No matches." :
      "No photos yet — add a folder in Settings and run a scan.";
  }
}

function appendItems(items, mode) {
  const grid = $("#grid");
  let lastMonth = grid.dataset.lastMonth || "";
  let row = grid.lastElementChild?.classList?.contains("photo-row") ? grid.lastElementChild : null;
  for (const it of items) {
    if (mode !== "search") {
      const month = (it.taken_at || "").slice(0, 7);
      if (month !== lastMonth) {
        lastMonth = month;
        grid.appendChild(el("div", "month-h", monthLabel(month)));
        row = null;
      }
    }
    if (!row) { row = el("div", "photo-row"); grid.appendChild(row); }
    const idx = state.items.length;
    state.items.push(it);
    row.appendChild(photoTile(it, idx));
  }
  grid.dataset.lastMonth = lastMonth;
}

function photoTile(it, idx) {
  const d = el("div", "ph");
  d.dataset.idx = idx;
  const img = el("img");
  img.loading = "lazy";
  img.src = "/media/thumb/" + it.id;
  if (it.width && it.height) d.style.flexBasis = (180 * it.width / it.height) + "px";
  d.appendChild(img);
  if (it.favorite) d.appendChild(el("span", "fav-ind", "♥"));
  const check = el("div", "check", "✓");
  check.onclick = (e) => { e.stopPropagation(); toggleSelect(it.id, d); };
  d.appendChild(check);
  d.onclick = (e) => {
    if (state.selection.size) toggleSelect(it.id, d);
    else openLightbox(idx);
  };
  return d;
}

function monthLabel(ym) {
  if (!ym) return "Unknown date";
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

let sentinelObs = null;
function observeSentinel() {
  if (sentinelObs) sentinelObs.disconnect();
  sentinelObs = new IntersectionObserver((es) => es[0].isIntersecting && loadMore(),
    { rootMargin: "800px" });
  sentinelObs.observe($("#grid-sentinel"));
}

/* ---------------- selection ---------------- */
function toggleSelect(id, tile) {
  if (state.selection.has(id)) state.selection.delete(id);
  else state.selection.add(id);
  tile.classList.toggle("selected", state.selection.has(id));
  const bar = $("#selbar");
  bar.classList.toggle("hidden", !state.selection.size);
  $("#selbar-count").textContent = state.selection.size + " selected";
}

function clearSelection() {
  state.selection.clear();
  $("#selbar").classList.add("hidden");
  document.querySelectorAll(".ph.selected").forEach((t) => t.classList.remove("selected"));
}

async function favoriteSelection() {
  for (const id of state.selection) await api.send("POST", `/api/photos/${id}/favorite`);
  clearSelection();
  if (state.filters.favorites) route(); // refresh favorites view
}

async function pickAlbum(photoIds) {
  const albums = await api.get("/api/albums");
  const box = $("#modal-box");
  box.innerHTML = "<h3>Add to album</h3>";
  for (const a of albums) {
    const b = el("button", "btn list-item", `${a.name} (${a.photo_count})`);
    b.onclick = async () => {
      await api.send("POST", `/api/albums/${a.id}/photos`, { photo_ids: photoIds });
      closeModal(); clearSelection();
    };
    box.appendChild(b);
  }
  const nb = el("button", "btn primary list-item", "＋ New album…");
  nb.onclick = async () => {
    const name = await promptModal("New album", "Album name");
    if (name) {
      const { id } = await api.send("POST", "/api/albums", { name });
      await api.send("POST", `/api/albums/${id}/photos`, { photo_ids: photoIds });
    }
    closeModal(); clearSelection();
  };
  box.appendChild(nb);
  const cancel = el("button", "btn ghost list-item", "Cancel");
  cancel.onclick = closeModal;
  box.appendChild(cancel);
  $("#modal").classList.remove("hidden");
}

/* ---------------- people ---------------- */
async function getPersons(force) {
  if (force || !state.persons.length) state.persons = await api.get("/api/persons");
  return state.persons;
}

async function loadPeople() {
  const persons = await getPersons(true);
  const g = $("#people-grid");
  g.innerHTML = "";
  if (!persons.length) {
    g.innerHTML = '<div class="empty">No named people yet — check the <a href="#unknown">Unknown</a> tab after a scan.</div>';
    return;
  }
  for (const p of persons) {
    const c = el("div", "card person");
    const pic = el("div", "pic");
    if (p.sample_face) pic.appendChild(Object.assign(el("img"), { src: "/media/face/" + p.sample_face, loading: "lazy" }));
    c.append(pic, el("div", "name", p.name), el("div", "sub", `${p.photo_count} photos`));
    c.onclick = () => (location.hash = "#person/" + p.id);
    g.appendChild(c);
  }
}

/* ---------------- unknown clusters ---------------- */
async function loadClusters() {
  const [clusters, persons] = await Promise.all([api.get("/api/clusters"), getPersons(true)]);
  const list = $("#cluster-list");
  list.innerHTML = "";
  updateUnknownBadge(clusters.length);
  if (!clusters.length) {
    list.innerHTML = '<div class="empty">No unknown faces 🎉 — everyone is tagged (or no scan has run yet).</div>';
    return;
  }
  const dl = el("datalist");
  dl.id = "persons-dl";
  persons.forEach((p) => dl.appendChild(Object.assign(el("option"), { value: p.name })));
  list.appendChild(dl);
  for (const c of clusters) {
    const div = el("div", "cluster");
    const pile = el("div", "facepile");
    c.sample_faces.forEach((fid) =>
      pile.appendChild(Object.assign(el("img"), { src: "/media/face/" + fid, loading: "lazy" })));
    const meta = el("div", "meta");
    meta.append(el("div", "title", `Unknown person #${c.id}`),
                el("div", "sub hint", `${c.face_count} faces in ${c.photo_count} photos`));
    const tag = el("div", "tagbox");
    const inp = Object.assign(el("input", "tag-input"), { placeholder: "Who is this?" });
    inp.setAttribute("list", "persons-dl");
    const btn = el("button", "btn primary", "Tag");
    const doTag = async () => {
      const name = inp.value.trim();
      if (!name) return;
      btn.disabled = true;
      await api.send("POST", `/api/clusters/${c.id}/assign`, { name });
      state.persons = [];
      loadClusters();
    };
    btn.onclick = doTag;
    inp.addEventListener("keydown", (e) => e.key === "Enter" && doTag());
    tag.append(inp, btn);
    div.append(pile, meta, tag);
    list.appendChild(div);
  }
}

function updateUnknownBadge(n) {
  const b = $("#unknown-badge");
  b.classList.toggle("hidden", !n);
  b.textContent = n;
}

/* ---------------- albums ---------------- */
async function loadAlbums() {
  const albums = await api.get("/api/albums");
  const g = $("#albums-grid");
  g.innerHTML = "";
  // Favorites pseudo-album first
  const fav = el("div", "card");
  fav.innerHTML = '<div class="pic" style="display:flex;align-items:center;justify-content:center;font-size:52px">♥</div>';
  fav.append(el("div", "name", "Favorites"));
  fav.onclick = () => (location.hash = "#favorites");
  g.appendChild(fav);
  let sawAuto = false;
  for (const a of albums) {
    if (a.auto && !sawAuto) {
      sawAuto = true;
      const h = el("div", "month-h", "✨ Smart albums (auto-created from places, trips and themes)");
      h.style.gridColumn = "1 / -1";
      g.appendChild(h);
    }
    const c = el("div", "card");
    const pic = el("div", "pic");
    if (a.cover) pic.appendChild(Object.assign(el("img"), { src: "/media/thumb/" + a.cover, loading: "lazy" }));
    c.append(pic, el("div", "name", a.name),
             el("div", "sub", `${a.photo_count} photos${a.auto ? " · auto" : ""}`));
    c.onclick = () => (location.hash = "#album/" + a.id);
    if (!a.auto) c.oncontextmenu = async (e) => {
      e.preventDefault();
      if (confirm(`Delete album "${a.name}"? (Photos are not deleted.)`)) {
        await api.send("DELETE", `/api/albums/${a.id}`); loadAlbums();
      }
    };
    g.appendChild(c);
  }
}

/* ---------------- map ---------------- */
async function loadMap() {
  const markers = await api.get("/api/map/markers");
  if (!state.map) {
    state.map = L.map("map").setView([20.59, 78.96], 4); // start over India
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "© OpenStreetMap",
    }).addTo(state.map);
    state.mapLayer = L.layerGroup().addTo(state.map);
  }
  setTimeout(() => state.map.invalidateSize(), 60);
  state.mapLayer.clearLayers();
  if (!markers.length) return;
  const pts = [];
  // group nearby photos (~100 m grid) into one marker
  const groups = new Map();
  for (const m of markers) {
    const key = m.lat.toFixed(3) + "," + m.lon.toFixed(3);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(m);
  }
  for (const [key, g] of groups) {
    const [lat, lon] = key.split(",").map(Number);
    pts.push([lat, lon]);
    const mk = L.marker([lat, lon]).addTo(state.mapLayer);
    const html = g.slice(0, 8).map((m) =>
      `<img data-open="${m.id}" src="/media/thumb/${m.id}" style="width:64px;height:64px;object-fit:cover;border-radius:6px;margin:2px;cursor:pointer">`).join("") +
      (g.length > 8 ? `<div>+${g.length - 8} more</div>` : "");
    mk.bindPopup(html, { maxWidth: 320 });
  }
  state.map.off("popupopen");
  state.map.on("popupopen", (e) => {
    e.popup.getElement().querySelectorAll("img[data-open]").forEach((img) => {
      img.onclick = () => openLightboxSingle(+img.dataset.open);
    });
  });
  state.map.fitBounds(pts, { padding: [40, 40], maxZoom: 14 });
}

/* ---------------- settings ---------------- */
async function loadSettings() {
  const folders = await api.get("/api/folders");
  const ul = $("#folder-list");
  ul.innerHTML = "";
  if (!folders.length) ul.innerHTML = '<li><span class="hint">No folders yet — add your photo folder below.</span></li>';
  for (const f of folders) {
    const li = el("li");
    const rm = el("button", "btn danger", "Remove");
    rm.onclick = async () => { await api.send("DELETE", `/api/folders/${f.id}`); loadSettings(); };
    li.append(el("span", "", f.path), rm);
    ul.appendChild(li);
  }
}

async function browseFolder() {
  const btn = $("#browse-folder-btn");
  btn.disabled = true;
  btn.textContent = "Choose the folder in the Windows dialog…";
  try {
    const r = await api.get("/api/pick-folder");
    if (r.path) {
      await api.send("POST", "/api/folders", { path: r.path });
      loadSettings();
    }
  } catch (e) { alert(e.message || "Could not open the folder dialog."); }
  btn.disabled = false;
  btn.textContent = "Add folder…";
}

async function addFolder() {
  const inp = $("#folder-input");
  const path = inp.value.trim();
  if (!path) return;
  try {
    await api.send("POST", "/api/folders", { path });
    inp.value = "";
    loadSettings();
  } catch (e) { alert(e.message); }
}

async function pollStatus() {
  let s;
  try { s = await api.get("/api/scan/status"); } catch { return; }
  lastScanState = s.state;
  updateUnknownBadge(s.stats.clusters);
  const running = s.state === "scanning" || s.state === "stopping";

  // progress chip in the top bar — visible on every tab
  const chip = $("#scan-chip");
  chip.classList.toggle("hidden", !running);
  if (running) {
    $("#scan-chip-text").textContent = s.state === "stopping" ? "Stopping…" :
      s.total ? `Scanning ${s.done}/${s.total}` : (s.phase || "Scanning…");
  }

  if (state.route !== "settings") return;
  const prog = $("#scan-progress"), bar = $("#scan-bar"), st = $("#scan-status");
  $("#stop-scan-btn").classList.toggle("hidden", s.state !== "scanning");
  if (running) {
    prog.classList.remove("hidden");
    bar.style.width = s.total ? (100 * s.done / s.total) + "%" : "0%";
    const detail = [s.phase, s.total ? `${s.done}/${s.total}` : "", s.current]
      .filter(Boolean).join(" · ");
    st.textContent = s.state === "stopping" ? "Stopping…" : detail || "Scanning…";
    $("#scan-btn").disabled = true;
  } else {
    prog.classList.add("hidden");
    $("#scan-btn").disabled = false;
    st.textContent = s.state === "error" ? "Scan error: " + s.error :
      (s.new_photos ? `Last scan added ${s.new_photos} photos.` : "");
  }
  $("#index-stats").innerHTML =
    `<div><b>${s.stats.photos}</b>photos</div><div><b>${s.stats.faces}</b>faces</div>` +
    `<div><b>${s.stats.persons}</b>people</div><div><b>${s.stats.clusters}</b>unknown groups</div>`;
}

/* ---------------- lightbox ---------------- */
let lbFadeTimer = null;
function lbWakeOverlay() {
  // tags show while the mouse moves, fade away after it goes idle
  const ov = $("#lb-overlay");
  ov.classList.remove("faded");
  clearTimeout(lbFadeTimer);
  lbFadeTimer = setTimeout(() => ov.classList.add("faded"), 2200);
}

function bindLightbox() {
  $("#lightbox").addEventListener("mousemove", lbWakeOverlay);
  $("#lb-close").onclick = closeLightbox;
  $("#lb-prev").onclick = () => stepLightbox(-1);
  $("#lb-next").onclick = () => stepLightbox(1);
  $("#lb-fav").onclick = lbToggleFav;
  $("#lb-album").onclick = () => { const p = lbPhoto(); p && pickAlbum([p.id]); };
  $("#lb-faces").onclick = () => { state.lbFaces = !state.lbFaces; renderLightbox(); };
  $("#lb-info").onclick = () => $("#lb-panel").classList.toggle("hidden");
  window.addEventListener("resize", () => !lbHidden() && positionFaceBoxes());
  document.addEventListener("keydown", (e) => {
    if (!$("#modal").classList.contains("hidden")) { if (e.key === "Escape") closeModal(); return; }
    if (lbHidden()) return;
    if (e.target.tagName === "INPUT") return;
    if (e.key === "Escape") closeLightbox();
    else if (e.key === "ArrowLeft") stepLightbox(-1);
    else if (e.key === "ArrowRight") stepLightbox(1);
    else if (e.key.toLowerCase() === "f") lbToggleFav();
    else if (e.key.toLowerCase() === "b") { state.lbFaces = !state.lbFaces; renderLightbox(); }
    else if (e.key.toLowerCase() === "i") $("#lb-panel").classList.toggle("hidden");
  });
}

const lbHidden = () => $("#lightbox").classList.contains("hidden");
const lbPhoto = () => state.lbDetail;

function openLightbox(idx) {
  state.lbIndex = idx;
  $("#lightbox").classList.remove("hidden");
  renderLightbox();
}

async function openLightboxSingle(photoId) {
  // open a photo not in the current grid (e.g. from the map)
  state.items = [{ id: photoId }];
  state.lbIndex = 0;
  $("#lightbox").classList.remove("hidden");
  renderLightbox();
}

function closeLightbox() {
  $("#lightbox").classList.add("hidden");
  $("#lb-panel").classList.add("hidden");
}

async function stepLightbox(d) {
  let i = state.lbIndex + d;
  if (i < 0) return;
  if (i >= state.items.length) {
    if (!state.done) { await loadMore(); }
    if (i >= state.items.length) return;
  }
  state.lbIndex = i;
  renderLightbox();
  if (i > state.items.length - 20) loadMore(); // prefetch ahead
}

async function renderLightbox() {
  const it = state.items[state.lbIndex];
  if (!it) return;
  const img = $("#lb-img");
  img.src = "/media/photo/" + it.id;
  $("#lb-overlay").innerHTML = "";
  const detail = await api.get("/api/photos/" + it.id);
  state.lbDetail = detail;
  it.favorite = detail.favorite;
  $("#lb-fav").textContent = detail.favorite ? "♥" : "♡";
  $("#lb-fav").classList.toggle("on", !!detail.favorite);
  $("#lb-faces").classList.toggle("on", state.lbFaces);
  if (img.complete) positionFaceBoxes(); else img.onload = positionFaceBoxes;
  lbWakeOverlay(); // show tags briefly on open/navigation, then fade
  renderInfoPanel(detail);
}

function positionFaceBoxes() {
  const d = state.lbDetail;
  const overlay = $("#lb-overlay");
  overlay.innerHTML = "";
  if (!d || !state.lbFaces) return;
  const img = $("#lb-img");
  const sx = img.clientWidth / d.width, sy = img.clientHeight / d.height;
  for (const f of d.faces) {
    const box = el("div", "facebox" + (f.person_id ? "" : " unknown"));
    box.style.left = f.bbox_x * sx + "px";
    box.style.top = f.bbox_y * sy + "px";
    box.style.width = f.bbox_w * sx + "px";
    box.style.height = f.bbox_h * sy + "px";
    box.appendChild(el("span", "fb-label", f.person_name || "Unknown — click to tag"));
    box.onclick = (e) => { e.stopPropagation(); faceMenu(f); };
    overlay.appendChild(box);
  }
}

async function faceMenu(face) {
  const persons = await getPersons(true);
  const box = $("#modal-box");
  box.innerHTML = `<h3>${face.person_name ? "Face: " + face.person_name : "Tag this face"}</h3>`;
  const dl = el("datalist"); dl.id = "face-dl";
  persons.forEach((p) => dl.appendChild(Object.assign(el("option"), { value: p.name })));
  const row = el("div", "row");
  const inp = Object.assign(el("input", "tag-input"), { placeholder: "Type a name…" });
  inp.setAttribute("list", "face-dl");
  const ok = el("button", "btn primary", "Tag");
  const doTag = async () => {
    const name = inp.value.trim();
    if (!name) return;
    await api.send("PATCH", `/api/faces/${face.id}`, { name });
    state.persons = [];
    closeModal(); renderLightbox();
  };
  ok.onclick = doTag;
  inp.addEventListener("keydown", (e) => e.key === "Enter" && doTag());
  row.append(inp, ok);
  box.append(dl, row);
  if (face.person_id) {
    const clr = el("button", "btn list-item", "Remove tag (back to unknown)");
    clr.onclick = async () => {
      await api.send("PATCH", `/api/faces/${face.id}`, { clear: true });
      closeModal(); renderLightbox();
    };
    box.appendChild(clr);
  }
  const ign = el("button", "btn danger list-item", "Not a face / ignore");
  ign.onclick = async () => {
    await api.send("POST", `/api/faces/${face.id}/ignore`);
    closeModal(); renderLightbox();
  };
  const cancel = el("button", "btn ghost list-item", "Cancel");
  cancel.onclick = closeModal;
  box.append(ign, cancel);
  $("#modal").classList.remove("hidden");
  inp.focus();
}

function renderInfoPanel(d) {
  const p = $("#lb-panel");
  const dt = d.taken_at ? new Date(d.taken_at.replace(" ", "T")) : null;
  let html = `<h3>Details</h3>
    <div>${d.filename}</div>
    <div class="hint">${dt ? dt.toLocaleString() : ""}</div>
    <div class="hint">${d.width}×${d.height}${d.camera ? " · " + d.camera : ""}</div>
    <div class="hint" style="word-break:break-all">${d.path}</div>`;
  if (d.gps_lat != null) html += `<div class="hint">📍 ${d.gps_lat.toFixed(5)}, ${d.gps_lon.toFixed(5)}</div>`;
  html += "<h3>People</h3>";
  p.innerHTML = html;
  const named = d.faces.filter((f) => f.person_id);
  if (!named.length) p.append(el("div", "hint", "No one tagged yet."));
  for (const f of named) {
    const chip = el("span", "chip");
    chip.appendChild(Object.assign(el("img"), { src: "/media/face/" + f.id }));
    chip.appendChild(document.createTextNode(f.person_name));
    chip.onclick = () => { closeLightbox(); location.hash = "#person/" + f.person_id; };
    p.appendChild(chip);
  }
  if (d.albums.length) {
    p.appendChild(el("h3", "", "Albums"));
    d.albums.forEach((a) => {
      const chip = el("span", "chip", a.name);
      chip.onclick = () => { closeLightbox(); location.hash = "#album/" + a.id; };
      p.appendChild(chip);
    });
  }
}

async function lbToggleFav() {
  const d = state.lbDetail;
  if (!d) return;
  const r = await api.send("POST", `/api/photos/${d.id}/favorite`);
  d.favorite = r.favorite;
  $("#lb-fav").textContent = r.favorite ? "♥" : "♡";
  $("#lb-fav").classList.toggle("on", !!r.favorite);
}

/* ---------------- helpers ---------------- */
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function closeModal() { $("#modal").classList.add("hidden"); }

function promptModal(title, placeholder, initial = "") {
  return new Promise((resolve) => {
    const box = $("#modal-box");
    box.innerHTML = `<h3>${title}</h3>`;
    const row = el("div", "row");
    const inp = Object.assign(el("input", "tag-input"), { placeholder, value: initial });
    const ok = el("button", "btn primary", "OK");
    const cancel = el("button", "btn ghost", "Cancel");
    const finish = (v) => { closeModal(); resolve(v); };
    ok.onclick = () => finish(inp.value.trim() || null);
    cancel.onclick = () => finish(null);
    inp.addEventListener("keydown", (e) => e.key === "Enter" && finish(inp.value.trim() || null));
    row.append(inp, ok, cancel);
    box.appendChild(row);
    $("#modal").classList.remove("hidden");
    inp.focus();
  });
}
