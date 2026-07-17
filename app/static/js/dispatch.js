/**
 * DispatchController — handles the Dispatch panel form.
 * - Generates Incident ID and Idempotency-Key per submission.
 * - Disables Dispatch button while in flight (single-click guard).
 * - Shows timeout message without auto-retry.
 */
class DispatchController {
  constructor() {
    this._inFlight = false;
  }

  /** Called by NavigationController after panel HTML is cloned into DOM */
  attach() {
    const form = document.getElementById("dispatch-form");
    if (!form) return;

    const incidentTypeEl = document.getElementById("incident-type");
    const customGroup = document.getElementById("custom-incident-type-group");
    const geocodeBtn = document.getElementById("geocode-btn");
    const dispatchBtn = document.getElementById("dispatch-btn");
    const statusEl = document.getElementById("dispatch-status");

    // Wire Other/custom reveal
    incidentTypeEl.addEventListener("change", () => {
      const isOther = incidentTypeEl.value === "Other";
      customGroup.hidden = !isOther;
      const customInput = document.getElementById("custom-incident-type");
      if (customInput) customInput.required = isOther;
    });

    // Geocode button
    if (geocodeBtn) {
      geocodeBtn.addEventListener("click", async () => {
        const locEl = document.getElementById("location");
        const query = locEl ? locEl.value.trim() : "";
        if (!query) return;
        geocodeBtn.disabled = true;
        try {
          const result = await apiClient.post("/api/geocode", { query });
          if (result.latitude !== undefined) {
            if (window.mapController) {
              window.mapController.setCoordinates(result.latitude, result.longitude);
            } else {
              const latEl = document.getElementById("latitude");
              const lonEl = document.getElementById("longitude");
              if (latEl) latEl.value = result.latitude;
              if (lonEl) lonEl.value = result.longitude;
            }
          }
        } catch (err) {
          this._showStatus(statusEl, `Geocode failed: ${err.detail || err.message}`, "error");
        } finally {
          geocodeBtn.disabled = false;
        }
      });
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (this._inFlight) return;
      this._dispatch(form, dispatchBtn, statusEl);
    });

    // If already in-flight (panel re-rendered), restore locked state
    if (this._inFlight && dispatchBtn) {
      dispatchBtn.textContent = "Dispatching";
      dispatchBtn.disabled = true;
    }

    // Listen for map coordinate events
    document.addEventListener("dfr:coordinates", (evt) => {
      const latEl = document.getElementById("latitude");
      const lonEl = document.getElementById("longitude");
      if (latEl) latEl.value = evt.detail.lat;
      if (lonEl) lonEl.value = evt.detail.lon;
    });
  }

  async _dispatch(form, btn, statusEl) {
    this._inFlight = true;
    btn.textContent = "Dispatching";
    btn.disabled = true;
    this._showStatus(statusEl, "", "");

    // Build payload
    const lat = parseFloat(document.getElementById("latitude").value);
    const lon = parseFloat(document.getElementById("longitude").value);
    const incidentType = document.getElementById("incident-type").value || null;
    const customIncidentType =
      incidentType === "Other"
        ? (document.getElementById("custom-incident-type").value || null)
        : null;
    const priority = parseInt(document.getElementById("priority").value, 10);
    const description = document.getElementById("description").value.trim() || null;
    const location = document.getElementById("location").value.trim() || null;
    const operatorName = document.getElementById("operator-name").value.trim() || null;
    const callerPhone = document.getElementById("caller-phone").value.trim() || null;

    // Generate identifiers
    const now = new Date();
    const compact = now.toISOString().replace(/[-:.TZ]/g, "").slice(0, 15);
    const hex = Array.from(crypto.getRandomValues(new Uint8Array(2)))
      .map((b) => b.toString(16).toUpperCase().padStart(2, "0"))
      .join("");
    const incidentId = `INC-${compact}-${hex}`;
    const idempotencyKey = crypto.randomUUID().replace(/-/g, "");

    const payload = {
      incident_id: incidentId,
      latitude: lat,
      longitude: lon,
      priority,
      ...(incidentType ? { incident_type: incidentType } : {}),
      ...(customIncidentType ? { custom_incident_type: customIncidentType } : {}),
      ...(description ? { description } : {}),
      ...(location ? { location } : {}),
      ...(operatorName ? { operator_name: operatorName } : {}),
      ...(callerPhone ? { caller_phone: callerPhone } : {}),
    };

    try {
      const result = await Promise.race([
        apiClient.post("/api/dispatch", payload, { "Idempotency-Key": idempotencyKey }),
        new Promise((_, reject) =>
          setTimeout(
            () => reject(new Error("timeout")),
            15000
          )
        ),
      ]);
      const msg = result.body?.mock
        ? `Mock dispatch recorded: ${result.incident_id} — no FH2 request was sent`
        : `Dispatched: ${result.incident_id} — ${result.outcome}`;
      this._showStatus(
        statusEl,
        msg,
        result.outcome === "success" ? "success" : "error"
      );
    } catch (err) {
      if (err.message === "timeout") {
        this._showStatus(
          statusEl,
          "Outcome unknown; check Log before trying again",
          "error"
        );
      } else {
        this._showStatus(statusEl, `Dispatch failed: ${err.detail || err.message}`, "error");
      }
    } finally {
      this._inFlight = false;
      btn.textContent = "Dispatch";
      btn.disabled = false;
    }
  }

  _showStatus(el, msg, cls) {
    if (!el) return;
    el.textContent = msg;
    el.className = "status-msg" + (cls ? ` ${cls}` : "");
    el.hidden = !msg;
  }
}
