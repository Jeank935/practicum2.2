let servicesDashboard = document.querySelector("[data-services-revision]");
let servicesRefreshStatus = document.querySelector("#services-refresh-status");
const servicesRefreshIntervalMilliseconds = 5000;
let currentServicesRevision = servicesDashboard?.dataset.servicesRevision;
let servicesRefreshInProgress = false;

async function refreshWhenServicesChange() {
  if (!servicesDashboard || servicesRefreshInProgress || document.visibilityState !== "visible") return;
  servicesRefreshInProgress = true;
  const windowDays = servicesDashboard.dataset.windowDays;
  try {
    const response = await fetch(`/api/services-version?window_days=${windowDays}`, {
      cache: "no-store",
    });
    if (redirectWhenSessionExpired(response)) return;
    if (!response.ok) throw new Error("Estado no disponible");
    const result = await response.json();
    if (result.revision !== currentServicesRevision) {
      const editing = document.querySelector("[data-browse-form]")?.contains(document.activeElement);
      if (new URLSearchParams(window.location.search).has("cursor") || editing) {
        servicesRefreshStatus.textContent = "Hay cambios · aplica los filtros o vuelve a la primera página";
        return;
      }
      servicesRefreshStatus.textContent = "Nueva actividad detectada";
      const updated = await fetch(window.location.href, { cache: "no-store" });
      if (redirectWhenSessionExpired(updated)) return;
      if (!updated.ok) throw new Error("Servicios no disponibles");
      const page = new DOMParser().parseFromString(await updated.text(), "text/html");
      const replacement = page.querySelector("[data-services-revision]");
      if (!replacement) throw new Error("Vista incompleta");
      servicesDashboard.replaceWith(replacement);
      servicesDashboard = replacement;
      servicesRefreshStatus = document.querySelector("#services-refresh-status");
      currentServicesRevision = replacement.dataset.servicesRevision;
      servicesRefreshStatus.textContent = "Servicios actualizados";
      return;
    }
    servicesRefreshStatus.textContent = "Actualizado · sin cambios";
  } catch (_error) {
    servicesRefreshStatus.textContent = "Actualización temporalmente no disponible";
  } finally {
    servicesRefreshInProgress = false;
  }
}

window.setInterval(refreshWhenServicesChange, servicesRefreshIntervalMilliseconds);
document.addEventListener("visibilitychange", refreshWhenServicesChange);
