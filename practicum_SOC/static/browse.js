(() => {
  const reset = () => {
    document.querySelectorAll("[data-browse-form]").forEach(form => {
      form.removeAttribute("aria-busy");
      form.querySelectorAll("button").forEach(button => { button.disabled = false; });
    });
    document.querySelectorAll("[data-browse-status]").forEach(node => { node.textContent = ""; });
  };
  const loading = () => {
    document.querySelectorAll("[data-browse-status]").forEach(node => { node.textContent = "Cargando resultados…"; });
  };
  document.addEventListener("submit", event => {
    const form = event.target.closest("[data-browse-form]");
    if (!form) return;
    form.setAttribute("aria-busy", "true");
    form.querySelectorAll("button").forEach(button => { button.disabled = true; });
    loading();
  });
  document.addEventListener("click", event => {
    if (event.target.closest("[data-page-link]")) loading();
  });
  window.addEventListener("pageshow", reset);
})();
