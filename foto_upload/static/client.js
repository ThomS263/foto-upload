export const byId = id => document.getElementById(id);

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
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(data.error || "Anfrage fehlgeschlagen."), {status: response.status});
  return data;
}
