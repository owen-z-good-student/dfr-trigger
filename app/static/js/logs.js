class LogsController {
  attach() {
    const refresh = document.getElementById("log-refresh-btn");
    if (!refresh) return;
    refresh.addEventListener("click", () => this.load());
    ["log-search", "log-priority-filter", "log-outcome-filter"].forEach((id) => {
      document.getElementById(id).addEventListener("change", () => this.load());
    });
    this.load();
  }

  async load() {
    const list = document.getElementById("log-list");
    if (!list) return;
    const params = new URLSearchParams({ limit: "50" });
    const query = document.getElementById("log-search").value.trim();
    const priority = document.getElementById("log-priority-filter").value;
    const outcome = document.getElementById("log-outcome-filter").value;
    if (query) params.set("query", query);
    if (priority) params.set("priority", priority);
    if (outcome) params.set("outcome", outcome);
    list.replaceChildren();
    try {
      const result = await apiClient.get("/api/logs?" + params);
      if (!result.items.length) {
        const empty = document.createElement("p");
        empty.className = "log-record-meta";
        empty.textContent = "No dispatch records";
        list.appendChild(empty);
        return;
      }
      result.items.forEach((item) => list.appendChild(this._record(item)));
    } catch (error) {
      const failure = document.createElement("p");
      failure.className = "status-msg error";
      failure.textContent = error.detail || error.message;
      list.appendChild(failure);
    }
  }

  _record(item) {
    const record = document.createElement("article");
    record.className = "log-record";

    // Header row
    const header = document.createElement("div");
    header.className = "log-record-header";

    const idEl = document.createElement("span");
    idEl.className = "log-record-id";
    idEl.textContent = item.incident_id;

    const outcomeEl = document.createElement("span");
    outcomeEl.className = "log-record-outcome " + item.outcome;
    outcomeEl.textContent = item.outcome;

    const metaEl = document.createElement("span");
    metaEl.className = "log-record-meta";
    metaEl.textContent = item.submitted_at + " · P" + item.priority;

    header.append(idEl, outcomeEl, metaEl);
    record.appendChild(header);

    // Status line
    const statusLine = document.createElement("div");
    statusLine.className = "log-status-line";

    const httpCode = item.http_status;
    const resp = item.response || {};
    const hmsCode = resp.code || resp.error_code || null;
    const friendly = this._friendlyMsg(httpCode, hmsCode, resp);

    const httpSpan = document.createElement("span");
    httpSpan.className = "log-http-code" + (httpCode === 200 ? " log-http-ok" : httpCode >= 400 ? " log-http-err" : " log-http-warn");
    httpSpan.textContent = httpCode || "—";

    if (hmsCode !== null) {
      const codeSpan = document.createElement("span");
      codeSpan.className = "log-hms-badge";
      codeSpan.textContent = "HMS " + hmsCode;
      statusLine.appendChild(codeSpan);
    }

    const msgSpan = document.createElement("span");
    msgSpan.className = "log-friendly-msg";
    msgSpan.textContent = friendly;
    statusLine.appendChild(httpSpan); statusLine.appendChild(msgSpan);
    record.appendChild(statusLine);

    // Collapsible request/response
    const details = document.createElement("details");
    details.className = "log-details";
    const summary = document.createElement("summary");
    summary.textContent = "Request  Response";
    details.appendChild(summary);

    if (item.request) {
      const reqH = document.createElement("div");
      reqH.className = "log-section-label";
      reqH.textContent = "Request";
      const reqPre = document.createElement("pre");
      reqPre.className = "log-json";
      reqPre.textContent = JSON.stringify(item.request, null, 2);
      details.appendChild(reqH); details.appendChild(reqPre);
    }
    if (resp && Object.keys(resp).length) {
      const resH = document.createElement("div");
      resH.className = "log-section-label";
      resH.textContent = "Response";
      const resPre = document.createElement("pre");
      resPre.className = "log-json";
      resPre.textContent = JSON.stringify(resp, null, 2);
      details.appendChild(resH); details.appendChild(resPre);
    }
    record.appendChild(details);
    return record;
  }

  _friendlyMsg(httpCode, hmsCode, body) {
    if (!httpCode) return "No response";
    if (body.mock === true) return "Mock dispatch recorded — no FH2 request was sent";
    if (httpCode === 200) return "Task accepted by FH2 — processing";
    const msg = body.message || body.detail || "";
    if (hmsCode === 245008) return "Workflow UUID not found in this project";
    if (hmsCode === 40101 || httpCode === 401) return "Token invalid — check FH2 configuration";
    if (hmsCode === 40300 || httpCode === 403) return "No permission for this project";
    if (hmsCode === 40401 || httpCode === 404) return "Resource not found — check UUIDs";
    if (httpCode === 400) return (msg || "Invalid payload — check required fields").substring(0, 80);
    if (httpCode >= 500) return "FH2 server error — retry later";
    return msg ? msg.substring(0, 80) : "HTTP " + httpCode;
  }
}
