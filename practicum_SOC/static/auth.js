function csrfHeaders() {
  return {
    "Content-Type": "application/json",
    "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]')?.content || "",
  };
}

function redirectWhenSessionExpired(response) {
  if (response.status !== 401) return false;
  window.location.assign("/auth/login");
  return true;
}

document.querySelector("#logout-button")?.addEventListener("click", async () => {
  const response = await fetch("/auth/logout", { method: "POST", headers: csrfHeaders() });
  if (response.ok) window.location.assign((await response.json()).redirect);
  else if (response.status === 401) window.location.assign("/auth/login");
});

document.querySelectorAll("[data-save-user]").forEach((button) => {
  button.addEventListener("click", async () => {
    const row = button.closest("[data-user-id]");
    const message = document.querySelector("#user-message");
    button.disabled = true;
    try {
      const response = await fetch(`/admin/users/${row.dataset.userId}`, {
        method: "PATCH",
        headers: csrfHeaders(),
        body: JSON.stringify({
          role: row.querySelector("select").value,
          enabled: row.querySelector('input[type="checkbox"]').checked,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "No se pudo guardar el acceso.");
      message.textContent = "Acceso actualizado. Sus sesiones anteriores se han cerrado.";
    } catch (error) {
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
});
