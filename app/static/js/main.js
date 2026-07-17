document.addEventListener("DOMContentLoaded", async () => {
  window._loadNavLogo = () => {
    const logo = document.getElementById("nav-logo");
    if (!logo) return;
    const stored = localStorage.getItem("dfr_logo");
    if (stored) {
      logo.innerHTML = '<img src="' + stored + '" alt="Logo" />';
      logo.hidden = false;
    } else {
      logo.hidden = true;
    }
  };
  window._loadNavLogo();

  window.dispatchController = new DispatchController();
  window.configurationController = new ConfigurationController();
  window.logsController = new LogsController();
  window.mapController = new MapController();
  window.navigationController = new NavigationController();
  if (window.lucide) window.lucide.createIcons({ attrs: { "stroke-width": 2 } });
  try {
    await apiClient.bootstrap();
  } catch (error) {
    console.error("DFR bootstrap failed", error.status || "network");
  }
});
