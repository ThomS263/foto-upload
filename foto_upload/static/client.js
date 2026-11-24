export const byId = id => document.getElementById(id);
export const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

export function scoped(path) {
  const url = new URL(path, location.origin);
  url.searchParams.set("event", byId("album").dataset.event);
  return url.pathname + url.search;
}

export function element(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}

export async function json(url, options) {
  options = options ? {...options} : {};
  options.headers = new Headers(options.headers || {});
  options.headers.set("X-CSRF-Token", csrfToken());
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(data.error || "Anfrage fehlgeschlagen."), {status: response.status});
  return data;
}
