import {byId, json} from "./client.js";

function request(url, method, data) {
  return json(url, {method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
}

async function act(form, callback) {
  const status = form.querySelector("[role=status]");
  const submit = form.querySelector("button");
  submit.disabled = true;
  try { status.textContent = await callback(); }
  catch (error) { status.textContent = error.message; }
  finally { submit.disabled = false; }
}

function editor(album, opened) {
  const fragment = byId("album-editor").content.cloneNode(true);
  const details = fragment.querySelector("details");
  const form = details.querySelector("form");
  const fields = form.elements;
  const url = "/admin/api/events/" + encodeURIComponent(album.slug);
  details.dataset.slug = album.slug;
  details.open = opened;
  details.querySelector("[data-title]").textContent = album.title;
  const size = new Intl.NumberFormat("de", {maximumFractionDigits: 1}).format(album.bytes / 1024 ** 2);
  const state = album.needs_password ? "Ordner gefunden · Passwort festlegen" : album.archived ? "Archiviert" : "Aktiv";
  details.querySelector("[data-info]").textContent = [album.files + (album.files === 1 ? " Datei" : " Dateien"),
    size + " MiB", state, album.folder].join(" · ") +
    (album.orphan_thumbs ? " · Verwaiste Vorschauen: " + album.orphan_thumbs : "");
  fields.title.value = album.title;
  fields.subtitle.value = album.subtitle;
  fields.public_access.checked = album.public_access;
  if (album.share) {
    details.querySelector(".share-links").hidden = false;
    details.querySelector("[data-share]").href = album.share;
    details.querySelector("[data-qr]").href = album.qr;
  }
  form.onsubmit = event => {
    event.preventDefault();
    act(form, async () => {
      const data = {title: fields.title.value, subtitle: fields.subtitle.value, public_access: fields.public_access.checked};
      if (fields.password.value) data.password = fields.password.value;
      await request(url, "PUT", data);
      await load(album.slug, "Album gespeichert.");
      return "";
    });
  };
  const archive = details.querySelector("[data-archive]");
  archive.textContent = album.archived ? "Wiederherstellen" : "Archivieren";
  archive.onclick = () => {
    if (!album.archived && !window.confirm("Album archivieren? Die Fotos bleiben im Datenordner.")) return;
    act(form, async () => {
      await request(album.archived ? url + "/restore" : url, album.archived ? "POST" : "DELETE");
      await load(album.slug, album.archived ? "Album wiederhergestellt." : "Album archiviert.");
      return "";
    });
  };
  return details;
}

async function load(openSlug, message) {
  const albums = await json("/admin/api/events");
  byId("manage").replaceChildren(...albums.map(album => editor(album, album.slug === openSlug)));
  byId("admin-status").textContent = message || (albums.length ? "" : "Es sind noch keine Alben angelegt.");
  if (!albums.length) byId("create").open = true;
}

const create = byId("new-album");
let autoSlug = true;
create.elements.slug.oninput = () => { autoSlug = !create.elements.slug.value; };
create.elements.title.oninput = () => {
  if (autoSlug) create.elements.slug.value = create.elements.title.value.normalize("NFKD").toLowerCase()
    .replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0,64);
};
create.onsubmit = event => {
  event.preventDefault();
  act(create, async () => {
    const data = Object.fromEntries(new FormData(create));
    await request("/admin/api/events", "POST", data);
    create.reset();
    autoSlug = true;
    await load(data.slug, "Album angelegt.");
    return "Gespeichert.";
  });
};
const password = byId("admin-password");
if (password) password.onsubmit = event => {
  event.preventDefault();
  act(password, async () => {
    await request("/admin/api/admin-password", "PUT", {password: password.elements.password.value});
    password.reset();
    return "Adminpasswort geändert.";
  });
};
byId("cleanup").onclick = async () => {
  try {
    const result = await request("/admin/api/cleanup", "POST");
    await load(byId("manage").querySelector("details[open]")?.dataset.slug);
    byId("cleanup-result").textContent = result.removed + " verwaiste Vorschauen entfernt.";
  } catch (error) { byId("cleanup-result").textContent = error.message; }
};
load().catch(error => { byId("admin-status").textContent = error.message; });
