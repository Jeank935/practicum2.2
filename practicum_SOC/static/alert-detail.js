const container = document.querySelector(".status-actions");
const message = document.querySelector("#status-message");
const statusLabels = {
  new: "Nuevo",
  notified: "Notificado",
  investigating: "En investigación",
  resolved: "Resuelto",
  false_positive: "Falso positivo",
};
let toastTimer;

function showMessage(text, type) {
  window.clearTimeout(toastTimer);
  message.textContent = text;
  message.className = `toast visible ${type}`;
  toastTimer = window.setTimeout(() => message.classList.remove("visible"), 4500);
}

function updateStatusControls(status) {
  document.querySelector("#current-status").textContent = statusLabels[status] || status;
  document.querySelector("#current-status").className = `status-pill status-${status}`;
  container.querySelectorAll("button[data-status]").forEach((item) => {
    const isCurrent = item.dataset.status === status;
    item.classList.toggle("is-current", isCurrent);
    item.setAttribute("aria-pressed", String(isCurrent));
  });
}

container?.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-status]");
  if (!button) return;
  const note = document.querySelector("#status-note").value;
  const buttons = container.querySelectorAll("button[data-status]");
  const originalLabel = button.querySelector("span").textContent;
  container.setAttribute("aria-busy", "true");
  buttons.forEach((item) => { item.disabled = true; });
  button.querySelector("span").textContent = "Actualizando…";
  try {
    const response = await fetch(`/alerts/${container.dataset.alertId}/status`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]')?.content || "",
      },
      body: JSON.stringify({ status: button.dataset.status, note }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "No fue posible actualizar la alerta.");
    updateStatusControls(result.investigation_status);
    showMessage(`Estado actualizado: ${statusLabels[result.investigation_status]}.`, "success");
  } catch (error) {
    showMessage(`${error.message} Inténtalo nuevamente.`, "error");
  } finally {
    button.querySelector("span").textContent = originalLabel;
    buttons.forEach((item) => { item.disabled = false; });
    container.removeAttribute("aria-busy");
  }
});
