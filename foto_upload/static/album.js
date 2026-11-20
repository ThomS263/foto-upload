import {byId, element, json, scoped} from "./client.js";
import {loadGallery} from "./gallery.js";

const queue = [];
const blockSize = 8 * 1024 * 1024;
const limit = Number(byId("album").dataset.limit);
const summary = byId("summary");
const nameField = byId("who");
let running = 0;
let wake;
let acquiring = false;

function saved(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* Private browsing can disable storage. */ }
}
nameField.value = saved("uploaderName") || "";
nameField.addEventListener("change", () => saved("uploaderName", nameField.value.trim()));
byId("speak").checked = saved("foto-speak") === "yes";
byId("speak").onchange = event => saved("foto-speak", event.target.checked ? "yes" : "no");

function uploadId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, "0")).join("");
}

function row(file) {
  const node = element("li", undefined, "job");
  const status = element("small", "Wartet …");
  const progress = element("progress");
  progress.max = 100;
  progress.value = 0;
  progress.setAttribute("aria-label", "Fortschritt für " + file.name);
  const retry = element("button", "Erneut versuchen");
  retry.hidden = true;
  node.append(element("strong", file.name), status, progress, retry);
  byId("jobs").append(node);
  return {status, progress, retry};
}

function addFiles(files) {
  for (const file of files) {
    const key = JSON.stringify(["foto-upload-v3", byId("album").dataset.event, file.name, file.size, file.lastModified]);
    if (queue.some(job => job.key === key && job.state !== "ok")) continue;
    const job = {...row(file), file, key, id: saved(key) || uploadId(), name: nameField.value.trim(), state: "wait"};
    saved(key, job.id);
    job.retry.onclick = () => reset(job);
    queue.push(job);
  }
  pump();
}

function reset(job) {
  if (job.state !== "failed") return;
  job.retry.hidden = true;
  job.state = "wait";
  pump();
}

for (const id of ["files", "camera"]) {
  byId(id).addEventListener("change", event => {
    addFiles(event.target.files);
    event.target.value = "";
  });
  byId(id).disabled = false;
}
const drop = byId("upload");
drop.ondragover = event => { event.preventDefault(); drop.classList.add("drag"); };
drop.ondragleave = () => drop.classList.remove("drag");
drop.ondrop = event => {
  event.preventDefault();
  drop.classList.remove("drag");
  addFiles(event.dataTransfer.files);
};
byId("retry-all").onclick = () => queue.filter(job => job.state === "failed").forEach(reset);

function report() {
  const done = queue.filter(job => job.state === "ok").length;
  const failed = queue.filter(job => job.state === "failed").length;
  summary.textContent = queue.length ? done + " von " + queue.length + " gespeichert" +
    (failed ? " · " + failed + " fehlgeschlagen" : "") : "";
  byId("retry-all").hidden = failed === 0;
}

function send(path, data, update) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", scoped(path));
    xhr.timeout = 180000;
    xhr.responseType = "json";
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) update(event.loaded / event.total);
    };
    xhr.onload = () => {
      if (xhr.status === 200 && xhr.response?.ok) resolve(xhr.response);
      else reject(Object.assign(new Error(xhr.response?.error || "Übertragung fehlgeschlagen."), {status: xhr.status}));
    };
    xhr.onerror = xhr.ontimeout = () => reject(new Error("Verbindung unterbrochen."));
    xhr.send(data);
  });
}

async function poster(file) {
  if (!file.type.startsWith("video/")) return null;
  const video = document.createElement("video");
  const url = URL.createObjectURL(file);
  video.muted = true;
  video.playsInline = true;
  try {
    return await new Promise(resolve => {
      const timer = setTimeout(() => resolve(null), 3000);
      const finish = value => { clearTimeout(timer); resolve(value); };
      video.onerror = () => finish(null);
      video.onloadeddata = () => {
        try {
          const scale = Math.min(1, 480 / Math.max(video.videoWidth, video.videoHeight));
          const canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
          canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
          canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
          canvas.toBlob(finish, "image/jpeg", .75);
        } catch { finish(null); }
      };
      video.preload = "auto";
      video.src = url;
    });
  } finally {
    video.onerror = video.onloadeddata = null;
    video.removeAttribute("src");
    video.load();
    URL.revokeObjectURL(url);
  }
}

async function retryable(job, operation) {
  let attempts = 0;
  for (;;) {
    if (!navigator.onLine) {
      job.status.textContent = "Wartet auf Verbindung …";
      await new Promise(resolve => window.addEventListener("online", resolve, {once: true}));
    }
    try { return await operation(); }
    catch (error) {
      if ((error.status && error.status < 500) || error.status === 507 || ++attempts > 2) throw error;
      job.status.textContent = "Verbindung wird erneut versucht …";
      await new Promise(resolve => setTimeout(resolve, attempts * 1200));
    }
  }
}

async function upload(job) {
  if (!job.file.size || job.file.size > limit) throw new Error("Bitte eine Datei von höchstens 2 GiB auswählen, die nicht leer ist.");
  const large = job.file.size > 2 * blockSize;
  const total = large ? Math.ceil(job.file.size / blockSize) : 1;
  const previous = await retryable(job, () => json(scoped("/upload/status/" + job.id)));
  if (previous.complete) return;
  let index = Math.min(previous.received, total - 1);
  const thumb = index === 0 ? await poster(job.file) : null;
  while (index < total) {
    const data = new FormData();
    data.set("name", job.name);
    data.set("upload_id", job.id);
    const start = index * blockSize;
    const part = large ? job.file.slice(start, start + blockSize) : job.file;
    if (large) {
      data.set("chunk", part, "block");
      data.set("filename", job.file.name);
      data.set("type", job.file.type);
      data.set("total", total);
      data.set("index", index);
    } else data.set("file", part, job.file.name);
    if (index === 0 && thumb) data.set("thumb", thumb, "vorschau.jpg");
    const update = fraction => {
      const percent = Math.min(99, Math.round(100 * (start + part.size * fraction) / job.file.size));
      job.progress.value = percent;
      job.status.textContent = percent + " % hochgeladen";
    };
    update(0);
    const result = await retryable(job, () => send(large ? "/upload/chunk" : "/upload", data, update));
    if (result.complete) return;
    if (result.received <= index) throw new Error("Bitte die Übertragung erneut versuchen.");
    index = result.received;
  }
}

async function keepAwake() {
  if (acquiring || wake || !running || document.hidden || !navigator.wakeLock) return;
  acquiring = true;
  try {
    const lock = await navigator.wakeLock.request("screen");
    wake = lock;
    lock.addEventListener("release", () => { if (wake === lock) wake = null; });
    if (!running) await lock.release();
  } catch { /* Available only on supported devices. */ }
  finally { acquiring = false; }
}

async function run(job) {
  running++;
  job.state = "run";
  keepAwake();
  try {
    await upload(job);
    saved(job.key, null);
    job.progress.value = 100;
    job.status.textContent = "✓ Gespeichert";
    job.state = "ok";
  } catch (error) {
    job.status.textContent = error.message;
    job.retry.hidden = false;
    job.state = "failed";
  } finally {
    running--;
    pump();
    if (!running) {
      wake?.release().catch(() => {});
      loadGallery();
      if (byId("speak").checked && queue.every(item => item.state === "ok") && "speechSynthesis" in window) {
        speechSynthesis.speak(new SpeechSynthesisUtterance("Alle Dateien wurden gespeichert."));
      }
    }
  }
}

function pump() {
  for (const job of queue) {
    if (running >= 2) break;
    if (job.state === "wait") run(job);
  }
  report();
}
window.addEventListener("beforeunload", event => {
  if (running) { event.preventDefault(); event.returnValue = ""; }
});
document.addEventListener("visibilitychange", keepAwake);
function network() { byId("network").hidden = navigator.onLine; }
window.addEventListener("online", network);
window.addEventListener("offline", network);
network();
loadGallery();
