const dashboard = document.querySelector("[data-dashboard-revision]");
const refreshStatus = document.querySelector("#refresh-status");
const refreshIntervalMilliseconds = 5000;
let currentRevision = dashboard?.dataset.dashboardRevision;
let refreshInProgress = false;

async function refreshWhenCasesChange() {
  if (!dashboard || refreshInProgress || document.visibilityState !== "visible") return;
  refreshInProgress = true;
  try {
    const response = await fetch("/api/dashboard-version", { cache: "no-store" });
    if (!response.ok) throw new Error("Estado no disponible");
    const result = await response.json();
    if (result.revision !== currentRevision) {
      refreshStatus.textContent = "Nuevos cambios detectados";
      window.location.reload();
      return;
    }
    refreshStatus.textContent = "Actualizado · sin cambios";
  } catch (_error) {
    refreshStatus.textContent = "Actualización temporalmente no disponible";
  } finally {
    refreshInProgress = false;
  }
}

window.setInterval(refreshWhenCasesChange, refreshIntervalMilliseconds);
document.addEventListener("visibilitychange", refreshWhenCasesChange);
