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
  document.querySelectorAll("[data-browse-form]").forEach(form => {
    form.addEventListener("submit", () => {
      form.setAttribute("aria-busy", "true");
      form.querySelectorAll("button").forEach(button => { button.disabled = true; });
      loading();
    });
  });
  document.querySelectorAll("[data-page-link]").forEach(link => link.addEventListener("click", loading));
  window.addEventListener("pageshow", reset);
})();
