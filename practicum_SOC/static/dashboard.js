const button = document.querySelector("#run-demo");
const statusBox = document.querySelector("#demo-status");

button?.addEventListener("click", async () => {
  button.disabled = true;
  button.textContent = "Ejecutando...";
  statusBox.classList.add("visible");
  statusBox.textContent = "Procesando el periodo de evaluación y actualizando la bandeja.";
  try {
    const response = await fetch("/demo/run", { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "No fue posible ejecutar el demo");
    statusBox.textContent = `Demo completado: ${result.created_alerts} alertas nuevas, ${result.persisted_alerts} persistidas.`;
    window.setTimeout(() => window.location.reload(), 900);
  } catch (error) {
    statusBox.textContent = error.message;
    button.disabled = false;
    button.textContent = "Ejecutar demo";
  }
});
