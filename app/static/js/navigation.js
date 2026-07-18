/**
 * NavigationController — toggles nav-rail expansion and swaps panel templates.
 * All three layout elements (rail, panel, map) shift together.
 * Calls map.invalidateSize after 220ms on each toggle.
 */
class NavigationController {
  constructor() {
    this._rail = document.getElementById("nav-rail");
    this._toggle = document.getElementById("nav-toggle");
    this._panel = document.getElementById("functional-panel");
    this._mapEl = document.getElementById("map");
    this._activeModule = "dispatch";
    this._motionMs = 220;

    this._toggle.addEventListener("click", () => this._toggleExpanded());

    document.querySelectorAll(".nav-item[data-module]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mod = btn.dataset.module;
        this._activateModule(mod);
        // On mobile, expand to show the panel when a module is selected
        if (!this._isExpanded()) this._setExpanded(true);
      });
    });

    // Initial panel render
    this._renderPanel("dispatch");
  }

  _isExpanded() {
    return document.body.dataset.navExpanded === "true";
  }

  _setExpanded(expanded) {
    document.body.dataset.navExpanded = expanded ? "true" : "false";
    this._toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    this._toggle.setAttribute(
      "aria-label",
      expanded ? "Collapse navigation" : "Expand navigation"
    );
    // Invalidate map size after animation completes
    setTimeout(() => {
      if (window.mapController) window.mapController.invalidateSize();
    }, this._motionMs);
  }

  _toggleExpanded() {
    this._setExpanded(!this._isExpanded());
  }

  _activateModule(mod) {
    if (mod === this._activeModule) return;
    this._activeModule = mod;
    document.querySelectorAll(".nav-item[data-module]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.module === mod);
    });
    this._renderPanel(mod);
  }

  /** Swap panel content with a 150ms opacity fade */
  _renderPanel(mod) {
    const panel = this._panel;
    // Fade out
    panel.style.opacity = "0";
    panel.style.transition = `opacity ${150}ms ease`;
    setTimeout(() => {
      const tplId = `tpl-${mod}`;
      const tpl = document.getElementById(tplId);
      if (tpl) {
        panel.innerHTML = "";
        panel.appendChild(tpl.content.cloneNode(true));
      } else {
        panel.innerHTML = `<div class="panel-inner"><p style="color:var(--fh2-muted)">No panel for: ${mod}</p></div>`;
      }
      // Wire up panel-specific controllers
      if (mod === "dispatch" && window.dispatchController) {
        window.dispatchController.attach();
      } else if (mod === "configuration" && window.configurationController) {
        window.configurationController.attach();
      } else if (mod === "logs" && window.logsController) {
        window.logsController.attach();
      } else if (mod === "live" && window.liveController) {
        window.liveController.attach();
      }
      // Fade in
      panel.style.opacity = "1";
    }, 150);
  }
}
