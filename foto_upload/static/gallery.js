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

function buttons() {
  byId("download-selection").disabled = !chosen.size;
  byId("download-selection").textContent = chosen.size ? "Auswahl als ZIP (" + chosen.size + ")" : "Auswahl als ZIP";
  byId("download-all").disabled = !items.length;
  byId("select-all").disabled = !visible.length;
  byId("select-all").textContent = visible.length && visible.every(item => chosen.has(item.f)) ? "Auswahl aufheben" : "Alle wählen";
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
  open.onclick = () => show(index);
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
  foot.append(element("strong", item.n ? "Von " + item.n : "Ohne Namen"), tools);
  card.append(open, foot);
  return card;
}

function render() {
  visible = items.filter(item => filter.value === "*" || item.n === filter.value.slice(1));
  if (byId("gallery-sort").value === "old") visible.reverse();
  if (byId("gallery-sort").value === "taken") visible.sort((a, b) => b.taken - a.taken || a.f.localeCompare(b.f));
  byId("gcount").textContent = String(visible.length);
  byId("gallery-status").textContent = visible.length ? "" : "Hier sind noch keine Fotos oder Videos.";
  grid.replaceChildren(...visible.slice(0, displayed).map(tile));
  byId("more-files").hidden = visible.length <= displayed;
  buttons();
}

export async function loadGallery() {
  const version = ++generation;
  try {
    const data = await json(scoped("/gallery/list"));
    if (version !== generation) return;
    items = data.items;
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
  stage.replaceChildren(node);
  byId("caption").textContent = (index + 1) + " / " + visible.length + (item.n ? " · Von " + item.n : "");
  byId("original").href = item.dl;
  byId("prev").disabled = byId("next").disabled = visible.length < 2;
  if (!dialog.open) dialog.showModal();
}

function step(offset) { if (visible.length) show((current + offset + visible.length) % visible.length); }
byId("refresh").onclick = loadGallery;
filter.onchange = () => { displayed = 60; render(); };
byId("gallery-sort").onchange = () => { displayed = 60; render(); };
byId("more-files").onclick = () => { displayed += 60; render(); };
byId("select-all").onclick = () => {
  const clear = visible.every(item => chosen.has(item.f));
  visible.forEach(item => clear ? chosen.delete(item.f) : chosen.add(item.f));
  render();
};
byId("close-viewer").onclick = () => dialog.close();
dialog.onclose = () => byId("stage").replaceChildren();
byId("prev").onclick = () => step(-1);
byId("next").onclick = () => step(1);
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
