import {byId, element, json} from "./client.js";

let albums = [];
let openAlbum = null;
const formatSize = bytes => new Intl.NumberFormat("de", {maximumFractionDigits: 1}).format(bytes / 1024 ** 3) + " GiB";

async function loadStorage() {
  try {
    const disk = await json("/admin/api/storage");
    byId("stat-storage").textContent = formatSize(disk.free);
    byId("disk-space").textContent = formatSize(disk.free) + " von " + formatSize(disk.total) + " frei" +
      (disk.free <= disk.reserve ? " · Zu wenig Speicher für weitere Uploads." : "");
  } catch (error) { byId("disk-space").textContent = error.message; }
}

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
    size + " MiB", album.latest ? "Neu: " + new Date(album.latest * 1000).toLocaleString("de") : "Noch keine Uploads", state, album.folder].join(" · ") +
    (album.orphan_thumbs ? " · Verwaiste Vorschauen: " + album.orphan_thumbs : "");
  fields.title.value = album.title;
  fields.subtitle.value = album.subtitle;
  fields.event_date.value = album.event_date || "";
  fields.tone.value = album.tone || "green";
  fields.public_access.checked = album.public_access;
  fields.allow_upload.checked = album.allow_upload;
  fields.allow_gallery.checked = album.allow_gallery;
  fields.allow_download.checked = album.allow_download;
  fields.expose_gps.checked = album.expose_gps;
  fields.allow_reactions.checked = album.allow_reactions;
  fields.allow_comments.checked = album.allow_comments;
  if (album.share_expires) {
    const date = new Date(album.share_expires * 1000);
    fields.share_expires.value = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }
  if (album.share) {
    details.querySelector(".share-links").hidden = false;
    details.querySelector("[data-share]").href = album.share;
    details.querySelector("[data-qr]").href = album.qr;
  }
  form.onsubmit = event => {
    event.preventDefault();
    act(form, async () => {
      const data = {title: fields.title.value, subtitle: fields.subtitle.value,
        event_date: fields.event_date.value, tone: fields.tone.value,
        public_access: fields.public_access.checked, allow_upload: fields.allow_upload.checked,
        allow_gallery: fields.allow_gallery.checked, allow_download: fields.allow_download.checked,
        expose_gps: fields.expose_gps.checked, allow_reactions: fields.allow_reactions.checked,
        allow_comments: fields.allow_comments.checked};
      data.share_expires = fields.share_expires.value ? Math.floor(new Date(fields.share_expires.value).getTime() / 1000) : 0;
      if (fields.password.value) data.password = fields.password.value;
      await request(url, "PUT", data);
      if (fields.cover.files[0]) {
        const cover = new FormData();
        cover.set("cover", fields.cover.files[0]);
        const response = await fetch(url + "/cover", {method: "POST", body: cover});
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || "Titelbild konnte nicht gespeichert werden.");
        fields.cover.value = "";
      }
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
  details.querySelector("[data-load-files]").onclick = async () => {
    const status = details.querySelector("[data-files-status]");
    const list = details.querySelector("[data-files]");
    try {
      const data = await json(url + "/files");
      list.replaceChildren();
      status.textContent = data.files.length ? data.files.length + " Dateien" : "Keine Dateien vorhanden.";
      for (const file of data.files) {
        const row = element("li");
        const label = element("span", file.name + (file.guest ? " · " + file.guest : ""));
        const remove = element("button", "Löschen");
        remove.type = "button";
        remove.setAttribute("aria-label", file.name + " löschen");
        remove.onclick = async () => {
          if (!window.confirm("Datei „" + file.name + "“ in den Papierkorb verschieben?")) return;
          remove.disabled = true;
          try {
            await request(url + "/files/" + encodeURIComponent(file.name), "DELETE");
            row.remove();
            status.textContent = "Datei im Papierkorb.";
            loadStorage();
          } catch (error) { status.textContent = error.message; remove.disabled = false; }
        };
        row.append(label, remove);
        list.append(row);
      }
    } catch (error) { status.textContent = error.message; }
  };
  details.querySelector("[data-load-trash]").onclick = async () => {
    const status = details.querySelector("[data-trash-status]");
    const list = details.querySelector("[data-trash]");
    try {
      const data = await json(url + "/trash");
      list.replaceChildren();
      status.textContent = data.files.length ? data.files.length + " Dateien im Papierkorb" : "Papierkorb ist leer.";
      for (const file of data.files) {
        const row = element("li");
        const restore = element("button", "Wiederherstellen");
        restore.type = "button";
        restore.onclick = async () => {
          restore.disabled = true;
          try {
            await request(url + "/trash", "POST", {name: file.name});
            row.remove();
            status.textContent = "Datei wiederhergestellt.";
          } catch (error) { status.textContent = error.message; restore.disabled = false; }
        };
        row.append(element("span", file.name), restore);
        list.append(row);
      }
    } catch (error) { status.textContent = error.message; }
  };
  return details;
}

async function load(openSlug, message) {
  albums = await json("/admin/api/events");
  byId("stat-albums").textContent = String(albums.filter(album => !album.archived).length);
  byId("stat-files").textContent = new Intl.NumberFormat("de").format(albums.reduce((sum, album) => sum + album.files, 0));
  openAlbum = openSlug;
  renderAlbums();
  byId("admin-status").textContent = message || (albums.length ? "" : "Es sind noch keine Alben angelegt.");
  if (!albums.length) byId("create").open = true;
}

function renderAlbums() {
  const query = byId("album-search").value.trim().toLocaleLowerCase("de");
  const sort = byId("album-sort").value;
  const visible = albums.filter(album => (album.title + " " + album.folder).toLocaleLowerCase("de").includes(query));
  visible.sort((a, b) => (sort === "files" ? b.files - a.files : sort === "size" ? b.bytes - a.bytes : 0) || a.title.localeCompare(b.title, "de"));
  byId("manage").replaceChildren(...visible.map(album => editor(album, album.slug === openAlbum)));
}
byId("album-search").addEventListener("input", renderAlbums);
byId("album-sort").addEventListener("change", renderAlbums);
loadStorage();
async function diagnostics() {
  const data = await json("/admin/api/diagnostics");
  byId("security-status").textContent = data.issues.length
    ? data.issues.length + " Hinweis(e) gefunden."
    : "✓ HTTPS, Speicher und Sicherungsstatus sehen gut aus.";
  byId("stat-security").textContent = data.issues.length ? data.issues.length + " Hinweis(e)" : "✓ Gut";
  byId("stat-security").classList.toggle("warning", data.issues.length > 0);
  byId("security-issues").replaceChildren(...data.issues.map(issue => element("li", issue)));
  byId("update-command").value = data.update_command;
}
byId("reload-diagnostics").onclick = () => diagnostics().catch(error => { byId("security-status").textContent = error.message; });
byId("copy-update").onclick = async () => {
  try { await navigator.clipboard.writeText(byId("update-command").value); byId("security-status").textContent = "Update-Befehl kopiert."; }
  catch { byId("update-command").select(); byId("security-status").textContent = "Befehl markiert – bitte kopieren."; }
};
diagnostics().catch(error => { byId("security-status").textContent = error.message; });
const publicUrl = byId("public-url");
json("/admin/api/public-url").then(data => {
  publicUrl.elements.url.value = data.url || "";
  byId("public-url-state").textContent = data.url
    ? "✓ Öffentliche Adresse ist eingerichtet. Neue QR-Codes verwenden sie."
    : "Noch keine öffentliche Adresse eingerichtet. QR-Codes verwenden die aktuell geöffnete Adresse.";
})
  .catch(error => { publicUrl.querySelector("[role=status]").textContent = error.message; });
publicUrl.onsubmit = event => {
  event.preventDefault();
  act(publicUrl, async () => {
    const data = await request("/admin/api/public-url", "PUT", {url: publicUrl.elements.url.value});
    publicUrl.elements.url.value = data.url;
    byId("public-url-state").textContent = data.url
      ? "✓ Öffentliche Adresse ist eingerichtet."
      : "Keine feste öffentliche Adresse eingerichtet.";
    return data.url ? "Gespeichert. Neue QR-Codes verwenden diese Adresse." : "Eigene Adresse entfernt.";
  });
};
byId("test-public-url").onclick = () => {
  const value = publicUrl.elements.url.value.trim().replace(/\/$/, "");
  const status = publicUrl.querySelector("[role=status]");
  if (!value.startsWith("https://")) { status.textContent = "Bitte zuerst eine HTTPS-Adresse eingeben."; return; }
  window.open(value + "/health?ready=1", "_blank", "noopener");
  status.textContent = "Der Erreichbarkeitstest wurde in einem neuen Fenster geöffnet.";
};
json("/admin/api/version").then(data => {
  const current = data.current.split(".").map(Number);
  const latest = (data.latest || "").split(".").map(Number);
  const newer = latest.length === 3 && latest.every(Number.isFinite) &&
    (latest[0] > current[0] || (latest[0] === current[0] && (latest[1] > current[1] ||
    (latest[1] === current[1] && latest[2] > current[2]))));
  byId("version-status").textContent = "Version " + data.current + (newer ? " · Update " + data.latest + " verfügbar." : data.latest ? " · Aktuell." : " · Updateprüfung nicht erreichbar.");
}).catch(() => { byId("version-status").textContent = "Updateprüfung nicht erreichbar."; });

async function backupStatus() {
  try {
    const data = await json("/admin/api/automatic-backup");
    byId("auto-backup").checked = data.enabled;
    const state = data.status;
    const last = state.success ? "Letzte Sicherung: " + new Date(state.success * 1000).toLocaleString("de") : "Noch keine automatische Sicherung.";
    byId("backup-status").textContent = last + (state.error ? " Fehler: " + state.error : "");
  } catch (error) { byId("backup-status").textContent = error.message; }
}
byId("auto-backup").onchange = async event => {
  try { await request("/admin/api/automatic-backup", "PUT", {enabled: event.target.checked}); }
  catch (error) { event.target.checked = !event.target.checked; byId("backup-status").textContent = error.message; return; }
  backupStatus();
};
backupStatus();

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
const totp = byId("totp");
byId("totp-setup").onclick = async () => {
  try {
    const data = await request("/admin/api/totp", "PUT", {});
    totp.elements.secret.value = data.secret;
    totp.querySelector("[role=status]").textContent = "Schlüssel in der Authenticator-App eintragen und den erzeugten Code bestätigen.";
  } catch (error) { totp.querySelector("[role=status]").textContent = error.message; }
};
totp.onsubmit = event => {
  event.preventDefault();
  act(totp, async () => {
    await request("/admin/api/totp", "PUT", {secret: totp.elements.secret.value, code: totp.elements.code.value});
    totp.elements.code.value = "";
    return "Zwei-Faktor-Anmeldung ist aktiviert.";
  });
};
byId("totp-disable").onclick = async () => {
  try {
    await request("/admin/api/totp", "DELETE", {code: totp.elements.code.value});
    totp.reset(); totp.querySelector("[role=status]").textContent = "Zwei-Faktor-Anmeldung ist deaktiviert.";
  } catch (error) { totp.querySelector("[role=status]").textContent = error.message; }
};
byId("cleanup").onclick = async () => {
  try {
    const result = await request("/admin/api/cleanup", "POST");
    await load(byId("manage").querySelector("details[open]")?.dataset.slug);
    byId("cleanup-result").textContent = result.removed + " verwaiste Vorschauen entfernt.";
  } catch (error) { byId("cleanup-result").textContent = error.message; }
};
byId("load-audit").onclick = async () => {
  const status = byId("audit-status");
  try {
    const data = await json("/admin/api/audit");
    const formatter = new Intl.DateTimeFormat("de", {dateStyle: "short", timeStyle: "short"});
    byId("audit-list").replaceChildren(...data.records.map(record => {
      const details = Object.entries(record).filter(([key]) => !["time", "action"].includes(key))
        .map(([key, value]) => key + ": " + value).join(" · ");
      return element("li", formatter.format(new Date(record.time * 1000)) + " · " + record.action + (details ? " · " + details : ""));
    }));
    status.textContent = data.records.length ? data.records.length + " Einträge" : "Noch keine Aktivitäten vorhanden.";
  } catch (error) { status.textContent = error.message; }
};
load().catch(error => { byId("admin-status").textContent = error.message; });
