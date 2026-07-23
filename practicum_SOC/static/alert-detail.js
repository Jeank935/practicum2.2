const container = document.querySelector(".status-actions");
const message = document.querySelector("#status-message");

container?.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-status]");
  if (!button) return;
  const note = document.querySelector("#status-note").value;
  const response = await fetch(`/alerts/${container.dataset.alertId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: button.dataset.status, note }),
  });
  const result = await response.json();
  message.classList.add("visible");
  if (!response.ok) {
    message.textContent = result.detail || "No fue posible actualizar la alerta.";
    return;
  }
  document.querySelector("#current-status").textContent = result.investigation_status;
  message.textContent = `Estado actualizado a ${result.investigation_status}.`;
});
