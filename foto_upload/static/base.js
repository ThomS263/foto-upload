document.querySelectorAll("[data-show]").forEach(button => {
  button.addEventListener("click", () => {
    const field = document.getElementById(button.dataset.show);
    const reveal = field.type === "password";
    field.type = reveal ? "text" : "password";
    button.textContent = reveal ? "Verbergen" : "Anzeigen";
    button.setAttribute("aria-pressed", String(reveal));
  });
});
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}
