(() => {
  const dashboard = document.querySelector("[data-dashboard-revision]");
  if (!dashboard) return;
  const status = document.querySelector("#refresh-status");
  const fallbackMs = Number(dashboard.dataset.fallbackSeconds) * 1000;
  const reconnectMs = Number(dashboard.dataset.reconnectSeconds) * 1000;
  let revision = dashboard.dataset.dashboardRevision;
  let stream = null;
  let reconnectTimer = null;
  let fetching = false;

  const show = message => { status.textContent = message; };
  const setText = (selector, value) => {
    const element = dashboard.querySelector(selector);
    if (element) element.textContent = String(value);
  };

  async function refreshSnapshot() {
    if (fetching || document.visibilityState !== "visible") return;
    fetching = true;
    try {
      const response = await fetch("/api/v1/dashboard/snapshot", { cache: "no-store" });
      if (redirectWhenSessionExpired(response)) return;
      if (!response.ok) throw new Error("Resumen no disponible");
      const { operational, source_label: sourceLabel, recent_html: recentHtml } = await response.json();
      if (operational.revision !== revision) {
        setText("[data-source-label]", sourceLabel);
        for (const key of ["pending_review", "investigating"]) {
          setText(`[data-summary="${key}"]`, operational[key]);
        }
        setText('[data-summary="critical"]', operational.open_by_severity.critical || 0);
        setText('[data-summary="closed"]', operational.resolved + operational.false_positive);
        setText('[data-summary="closed-detail"]', `${operational.resolved} resueltos · ${operational.false_positive} falsos positivos`);
        for (const level of ["critical", "high", "medium", "low"]) {
          setText(`[data-severity="${level}"]`, operational.open_by_severity[level] || 0);
        }
        for (const key of ["pending_review", "investigating", "resolved", "false_positive"]) {
          setText(`[data-state="${key}"]`, operational[key]);
        }
        dashboard.querySelector("[data-recent-alerts]").innerHTML = recentHtml;
        revision = operational.revision;
        dashboard.dataset.dashboardRevision = revision;
        show("Casos actualizados");
      } else {
        show("Al día · sin cambios");
      }
    } catch (_error) {
      show("Sin conexión · se reintentará automáticamente");
    } finally {
      fetching = false;
    }
  }

  async function fallbackCheck() {
    if (document.visibilityState !== "visible" || stream?.readyState === EventSource.OPEN) return;
    try {
      const response = await fetch("/api/dashboard-version", { cache: "no-store" });
      if (redirectWhenSessionExpired(response)) return;
      if (!response.ok) throw new Error("Versión no disponible");
      if ((await response.json()).revision !== revision) await refreshSnapshot();
    } catch (_error) {
      show("Sin conexión · se reintentará automáticamente");
    }
  }

  function closeStream() {
    if (stream) stream.close();
    stream = null;
  }

  function connect() {
    if (stream || document.visibilityState !== "visible" || !window.EventSource) return;
    stream = new EventSource("/api/v1/dashboard/stream");
    stream.onopen = () => show("Actualización en vivo");
    stream.addEventListener("revision", event => {
      if (JSON.parse(event.data).revision !== revision) void refreshSnapshot();
    });
    stream.addEventListener("session-expired", () => {
      closeStream();
      window.location.assign("/auth/login");
    });
    stream.addEventListener("unavailable", () => {
      show("Conexión en vivo interrumpida · consulta periódica activa");
      closeStream();
      scheduleReconnect();
    });
    stream.onerror = () => {
      show("Conexión en vivo interrumpida · consulta periódica activa");
      closeStream();
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, reconnectMs);
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      closeStream();
      return;
    }
    void fallbackCheck();
    connect();
  });
  window.addEventListener("pagehide", closeStream);
  window.setInterval(fallbackCheck, fallbackMs);
  connect();
})();
