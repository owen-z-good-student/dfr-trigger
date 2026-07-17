class ConfigurationController {
  attach() {
    const form = document.getElementById("config-form");
    if (!form) return;
    const message = document.getElementById("config-status-msg");
    this._load();
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = {
        region: document.getElementById("config-region").value,
        user_token: document.getElementById("user-token").value,
        project_uuid: document.getElementById("project-uuid").value,
        workflow_uuid: document.getElementById("workflow-uuid").value,
      };
      try {
        const status = await apiClient.put("/api/config", payload);
        this._renderStatus(status);
        document.getElementById("user-token").value = "";
        this._message(message, "Configuration saved", "success");
      } catch (error) {
        this._message(message, error.detail || error.message, "error");
      }
    });
    document.getElementById("test-config-btn").addEventListener("click", async () => {
      try {
        const result = await apiClient.post("/api/config/test", {});
        this._message(
          message,
          result.fh2_request_sent
            ? "Configuration validated"
            : "Configuration format validated. No FH2 task was created.",
          "success"
        );
      } catch (error) {
        this._message(message, error.detail || error.message, "error");
      }
    });

    // Set as Default Center button
    this._wireDefaultCenter();

    // Logo upload
    this._wireLogoUpload();
  }

  async _load() {
    try {
      this._renderStatus(await apiClient.get("/api/config"));
    } catch (_) {
      this._renderStatus({ token_configured: false });
    }
  }

  _renderStatus(status) {
    const token = document.getElementById("token-status");
    if (token) token.textContent = status.token_configured ? "Configured" : "Not configured";
    const region = document.getElementById("config-region");
    if (region && status.region) region.value = status.region;
    const suffixes = [
      ["project-uuid", status.project_uuid_suffix],
      ["workflow-uuid", status.workflow_uuid_suffix],
    ];
    suffixes.forEach(([id, suffix]) => {
      const input = document.getElementById(id);
      if (input && suffix) input.placeholder = `Configured ••••••${suffix}`;
    });
  }

  _message(element, text, type) {
    if (!element) return;
    element.textContent = text;
    element.className = `status-msg ${type}`;
    element.hidden = false;
  }

  _wireDefaultCenter() {
    const btn = document.getElementById("set-default-center-btn");
    const display = document.getElementById("default-center-display");
    if (!btn || !display) return;

    // Read current state from map controller if already clicked
    const current = window.mapController?.getLastCoordinates();
    if (current) {
      display.textContent = `${current.lat}, ${current.lon}`;
      btn.disabled = false;
    }

    // Update button state when coordinates change
    const updateFromEvent = (evt) => {
      const { lat, lon } = evt.detail;
      display.textContent = `${lat}, ${lon}`;
      btn.disabled = false;
    };
    document.addEventListener("dfr:coordinates", updateFromEvent);

    btn.addEventListener("click", () => {
      const coords = window.mapController?.getLastCoordinates();
      if (!coords) return;
      window.mapController.setDefaultCenter(coords.lat, coords.lon);
      display.textContent = `${coords.lat}, ${coords.lon}`;
      this._message(
        document.getElementById("config-status-msg"),
        `Default center set to ${coords.lat}, ${coords.lon}`,
        "success"
      );
    });

    // Show stored default center if any
    try {
      const stored = localStorage.getItem("dfr_default_center");
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length === 2) {
          display.textContent = `${parsed[0]}, ${parsed[1]}`;
        }
      }
    } catch (_) { /* ignore */ }
  }

  _wireLogoUpload() {
    const fileInput = document.getElementById("logo-upload");
    const uploadBtn = document.getElementById("logo-upload-btn");
    const removeBtn = document.getElementById("logo-remove-btn");
    const statusEl = document.getElementById("logo-status");
    if (!fileInput || !uploadBtn) return;

    const LOGO_KEY = "dfr_logo";

    const refreshLogoUI = () => {
      const stored = localStorage.getItem(LOGO_KEY);
      if (stored) {
        statusEl.textContent = "Logo set";
        removeBtn.hidden = false;
      } else {
        statusEl.textContent = "No logo";
        removeBtn.hidden = true;
      }
      window._loadNavLogo();
    };

    refreshLogoUI();

    uploadBtn.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
      const file = fileInput.files[0];
      if (!file) return;
      if (file.type !== "image/png") {
        this._message(document.getElementById("config-status-msg"), "Only PNG files are accepted", "error");
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        try {
          localStorage.setItem(LOGO_KEY, reader.result);
          refreshLogoUI();
          this._message(document.getElementById("config-status-msg"), "Logo updated", "success");
        } catch (_) {
          this._message(document.getElementById("config-status-msg"), "Image too large", "error");
        }
      };
      reader.readAsDataURL(file);
      fileInput.value = "";
    });

    removeBtn.addEventListener("click", () => {
      localStorage.removeItem(LOGO_KEY);
      refreshLogoUI();
      this._message(document.getElementById("config-status-msg"), "Logo removed", "success");
    });
  }
}
