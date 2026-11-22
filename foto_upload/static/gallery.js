import {byId, element, json, scoped} from "./client.js";

const grid = byId("grid");
const filter = byId("filter");
const dialog = byId("viewer");
const chosen = new Set();
let items = [];
let visible = [];
let current = -1;
let generation = 0;
let displayed = 60;
let slideshowTimer;
let allowReactions = false;
let allowComments = false;

function updateSocial(item, data) {
  item.favorite = data.favorite;
  item.favorite_count = data.favorite_count;
  item.comments = data.comments;
}

function buttons() {
  byId("download-selection").disabled = !chosen.size;
  byId("download-selection").textContent = chosen.size ? "Auswahl als ZIP (" + chosen.size + ")" : "Auswahl als ZIP";
  byId("download-all").disabled = !items.length;
  byId("select-all").disabled = !visible.length;
  byId("select-all").textContent = visible.length && visible.every(item => chosen.has(item.f)) ? "Auswahl aufheben" : "Alle wählen";
  byId("slideshow").disabled = !visible.length;
}

function tile(item, index) {
  const card = element("article", undefined, "tile");
  const open = element("button", undefined, "preview");
  const label = item.k === "video" ? "Video" : "Foto";
  open.setAttribute("aria-label", label + " öffnen: " + item.f);
  open.append(element("span", label));
  const img = element("img");
  img.alt = "";
  img.loading = "lazy";
  img.onerror = () => img.remove();
  if (item.has_preview) {
    img.src = item.thumb;
    open.append(img);
  }
  let held = false;
  let hold;
  open.onpointerdown = event => {
    if (event.pointerType !== "mouse") hold = setTimeout(() => {
      held = true;
      chosen.has(item.f) ? chosen.delete(item.f) : chosen.add(item.f);
      render();
    }, 550);
  };
  open.onpointerup = open.onpointercancel = () => clearTimeout(hold);
  open.onclick = () => { if (held) held = false; else show(index); };
  const foot = element("footer");
  const tools = element("div", undefined, "row");
  const check = element("input");
  check.type = "checkbox";
  check.checked = chosen.has(item.f);
  check.setAttribute("aria-label", item.f + " auswählen");
  check.onchange = () => {
    if (check.checked) chosen.add(item.f);
    else chosen.delete(item.f);
    buttons();
  };
  const selectLabel = element("label", undefined, "check");
  selectLabel.append(check, "Wählen");
  const download = element("a", "Laden");
  download.href = item.dl;
  download.download = "";
  tools.append(selectLabel, download);
  foot.append(element("small", new Date(item.taken * 1000).toLocaleDateString("de") +
      (item.favorite_count ? " · ♥ " + item.favorite_count : "") +
      (item.comments.length ? " · 💬 " + item.comments.length : ""), "media-meta"),
    element("strong", item.n ? "Von " + item.n : "Ohne Namen"), tools);
  card.append(open, foot);
  return card;
}

function render() {
  const query = byId("gallery-search").value.trim().toLocaleLowerCase("de");
  const type = byId("gallery-type").value;
  visible = items.filter(item => (filter.value === "*" || item.n === filter.value.slice(1)) &&
    (type === "*" || item.k === type) && (item.f + " " + item.n).toLocaleLowerCase("de").includes(query));
  if (byId("gallery-sort").value === "old") visible.reverse();
  if (byId("gallery-sort").value === "taken") visible.sort((a, b) => b.taken - a.taken || a.f.localeCompare(b.f));
  if (byId("gallery-sort").value === "favorites") visible.sort((a, b) => b.favorite_count - a.favorite_count || b.taken - a.taken);
  byId("gcount").textContent = String(visible.length);
  byId("gallery-status").textContent = visible.length ? "" : "Hier sind noch keine Fotos oder Videos.";
  const view = byId("gallery-view").value;
  grid.className = view === "timeline" ? "grid timeline" : view === "map" ? "grid map-list" : "grid";
  if (view === "map") {
    const located = visible.filter(item => item.gps);
    const groups = new Map();
    for (const item of located) {
      const key = item.gps.map(value => value.toFixed(3)).join(",");
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    grid.replaceChildren(...[...groups.values()].map(group => {
      const item = group[0];
      const card = element("article", undefined, "map-card");
      const link = element("a", "📍 " + group.length + (group.length === 1 ? " Aufnahme" : " Aufnahmen"));
      link.href = "https://www.openstreetmap.org/?mlat=" + item.gps[0] + "&mlon=" + item.gps[1] + "#map=16/" + item.gps[0] + "/" + item.gps[1];
      link.target = "_blank"; link.rel = "noopener";
      const open = element("button", "Fotos ansehen");
      open.onclick = () => show(visible.indexOf(item));
      card.append(link, element("small", item.gps.join(", "), "media-meta"), open);
      return card;
    }));
    byId("gallery-status").textContent = located.length ? located.length + " Aufnahme(n) mit Standort." : "Keine Fotos mit GPS-Standort vorhanden.";
  } else if (view === "timeline") {
    const nodes = [];
    let day = "";
    visible.slice(0, displayed).forEach((item, index) => {
      const next = new Date(item.taken * 1000).toLocaleDateString("de", {weekday: "long", year: "numeric", month: "long", day: "numeric"});
      if (next !== day) { day = next; nodes.push(element("h3", day, "timeline-day")); }
      nodes.push(tile(item, index));
    });
    grid.replaceChildren(...nodes);
  } else grid.replaceChildren(...visible.slice(0, displayed).map(tile));
  byId("more-files").hidden = visible.length <= displayed;
  buttons();
}

export async function loadGallery() {
  const version = ++generation;
  try {
    const data = await json(scoped("/gallery/list"));
    if (version !== generation) return;
    items = data.items;
    allowReactions = data.allow_reactions;
    allowComments = data.allow_comments;
    const names = new Set(items.map(item => item.n));
    const files = new Set(items.map(item => item.f));
    for (const file of chosen) if (!files.has(file)) chosen.delete(file);
    const previous = filter.value;
    filter.replaceChildren(new Option("Alle Personen", "*"));
    for (const name of [...names].sort((a,b) => a.localeCompare(b, "de"))) {
      filter.add(new Option(name || "Ohne Namen", ":" + name));
    }
    if (previous.startsWith(":") && names.has(previous.slice(1))) filter.value = previous;
    render();
  } catch (error) {
    if (version !== generation) return;
    if ([401, 409].includes(error.status)) {
      items = []; chosen.clear(); render();
      if (dialog.open) dialog.close();
    }
    byId("gallery-status").textContent = error.message;
  }
}

function show(index) {
  current = index;
  const item = visible[index];
  if (!item) return;
  const stage = byId("stage");
  const node = element(item.k === "video" ? "video" : "img");
  if (item.k === "video") {
    node.controls = true;
    node.playsInline = true;
    if (item.has_preview) node.poster = item.thumb;
    node.onloadedmetadata = () => {
      const duration = Number.isFinite(node.duration) ? Math.round(node.duration) : 0;
      byId("media-info").textContent = "Video" + (duration ? " · " + Math.floor(duration / 60) + ":" + String(duration % 60).padStart(2, "0") : "") + " · " + formatBytes(item.s);
    };
  } else node.alt = item.n ? "Foto von " + item.n : "Foto";
  node.onerror = () => {
    if (item.k === "image" && node.dataset.tried !== "yes") {
      node.dataset.tried = "yes";
      node.src = item.thumb;
    } else {
      stage.replaceChildren(element("p", "Keine Vorschau verfügbar. Du kannst das Original laden."));
    }
  };
  node.src = item.url;
  node.onclick = () => node.classList.toggle("zoomed");
  stage.replaceChildren(node);
  byId("caption").textContent = (index + 1) + " / " + visible.length + (item.n ? " · Von " + item.n : "");
  if (item.k !== "video") byId("media-info").textContent = new Date(item.taken * 1000).toLocaleString("de") + " · " + formatBytes(item.s);
  byId("original").href = item.dl;
  byId("prev").disabled = byId("next").disabled = visible.length < 2;
  renderSocial(item);
  if (!dialog.open) dialog.showModal();
}

function renderSocial(item) {
  const favorite = byId("favorite");
  favorite.hidden = !allowReactions;
  favorite.classList.toggle("favorite", item.favorite);
  favorite.textContent = (item.favorite ? "♥" : "♡") + " Favorit" + (item.favorite_count ? " (" + item.favorite_count + ")" : "");
  const comments = byId("comments");
  comments.hidden = !allowComments;
  byId("comment-list").replaceChildren(...item.comments.map(row => {
    const card = element("div", row.text, "comment");
    card.prepend(element("small", (row.name || "Gast") + " · " + new Date(row.time * 1000).toLocaleString("de")));
    return card;
  }));
}

byId("favorite").onclick = async () => {
  const item = visible[current];
  if (!item) return;
  try {
    const data = await json(scoped("/gallery/favorite"), {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({file: item.f, active: !item.favorite})});
    updateSocial(item, data); renderSocial(item);
  } catch (error) { byId("gallery-status").textContent = error.message; }
};

byId("comment-form").onsubmit = async event => {
  event.preventDefault();
  const item = visible[current];
  const input = byId("comment-text");
  if (!item || !input.value.trim()) return;
  try {
    const data = await json(scoped("/gallery/comment"), {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({file: item.f, text: input.value.trim(), name: byId("who").value.trim()})});
    updateSocial(item, data); input.value = ""; byId("comment-status").textContent = "Kommentar gespeichert."; renderSocial(item);
  } catch (error) { byId("comment-status").textContent = error.message; }
};

function formatBytes(value) {
  return new Intl.NumberFormat("de", {maximumFractionDigits: 1}).format(value / 1024 / 1024) + " MiB";
}

function toggleSlideshow() {
  if (slideshowTimer) {
    clearInterval(slideshowTimer); slideshowTimer = undefined; byId("play").textContent = "▶ Diashow";
  } else {
    if (!dialog.open) show(0);
    slideshowTimer = setInterval(() => step(1), 5000); byId("play").textContent = "⏸ Pause";
  }
}

function step(offset) { if (visible.length) show((current + offset + visible.length) % visible.length); }
byId("refresh").onclick = loadGallery;
filter.onchange = () => { displayed = 60; render(); };
byId("gallery-search").oninput = () => { displayed = 60; render(); };
byId("gallery-type").onchange = () => { displayed = 60; render(); };
byId("gallery-view").onchange = () => { displayed = 60; render(); };
byId("gallery-sort").onchange = () => { displayed = 60; render(); };
byId("more-files").onclick = () => { displayed += 60; render(); };
byId("select-all").onclick = () => {
  const clear = visible.every(item => chosen.has(item.f));
  visible.forEach(item => clear ? chosen.delete(item.f) : chosen.add(item.f));
  render();
};
byId("close-viewer").onclick = () => dialog.close();
dialog.onclose = () => { byId("stage").replaceChildren(); if (slideshowTimer) toggleSlideshow(); };
byId("prev").onclick = () => step(-1);
byId("next").onclick = () => step(1);
byId("slideshow").onclick = toggleSlideshow;
byId("play").onclick = toggleSlideshow;
dialog.addEventListener("keydown", event => {
  if (event.key === "ArrowLeft") step(-1);
  if (event.key === "ArrowRight") step(1);
});
let touch;
dialog.addEventListener("touchstart", event => { touch = event.touches[0].clientX; }, {passive: true});
dialog.addEventListener("touchend", event => {
  const dx = event.changedTouches[0].clientX - touch;
  if (Math.abs(dx) > 70) step(dx > 0 ? -1 : 1);
}, {passive: true});

function downloadZip(all) {
  const form = element("form");
  form.method = "post";
  form.action = scoped("/gallery/zip");
  for (const value of all ? ["1"] : chosen) {
    const field = element("input");
    field.type = "hidden";
    field.name = all ? "all" : "f";
    field.value = value;
    form.append(field);
  }
  document.body.append(form);
  form.submit();
  form.remove();
}
byId("download-selection").onclick = () => downloadZip(false);
byId("download-all").onclick = () => downloadZip(true);
setInterval(() => { if (!document.hidden && !dialog.open && navigator.onLine) loadGallery(); }, 30000);
