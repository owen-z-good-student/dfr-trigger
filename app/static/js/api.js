/**
 * ApiClient — same-origin JSON client with CSRF token support.
 * Never retries, never logs request bodies, reads dfr_csrf cookie for non-GET.
 */
class ApiClient {
  constructor() {
    this._csrfToken = null;
  }

  /** Read dfr_csrf cookie value (httponly=false so readable by JS) */
  _readCsrfCookie() {
    const name = "dfr_csrf=";
    for (const part of document.cookie.split(";")) {
      const c = part.trim();
      if (c.startsWith(name)) return c.slice(name.length);
    }
    return null;
  }

  /**
   * Bootstrap: call /api/bootstrap to get mode and set CSRF cookie.
   * @returns {Promise<{mode: string}>}
   */
  async bootstrap() {
    const res = await fetch("/api/bootstrap", {
      method: "GET",
      credentials: "same-origin",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body.detail || "bootstrap failed");
    }
    const data = await res.json();
    this._csrfToken = this._readCsrfCookie();
    return data;
  }

  /**
   * General request helper.
   * @param {string} method
   * @param {string} path
   * @param {object|null} body
   * @param {Record<string,string>} extraHeaders
   * @returns {Promise<any>}
   */
  async request(method, path, body = null, extraHeaders = {}) {
    const headers = { "Content-Type": "application/json", ...extraHeaders };
    if (method !== "GET" && method !== "HEAD") {
      const csrf = this._csrfToken || this._readCsrfCookie();
      if (csrf) headers["X-CSRF-Token"] = csrf;
    }
    const init = { method, credentials: "same-origin", headers };
    if (body !== null) init.body = JSON.stringify(body);
    const res = await fetch(path, init);
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const errBody = await res.json();
        if (errBody && errBody.detail !== undefined) {
          if (typeof errBody.detail === "string") {
            detail = errBody.detail;
          } else if (Array.isArray(errBody.detail)) {
            detail = errBody.detail
              .map((e) => {
                const loc = Array.isArray(e.loc) ? e.loc.join(".") : e.loc;
                return loc ? `${loc}: ${e.msg}` : e.msg;
              })
              .join("; ");
          } else if (typeof errBody.detail === "object") {
            detail = JSON.stringify(errBody.detail);
          } else {
            detail = String(errBody.detail);
          }
        }
      } catch (_) { /* ignore parse error */ }
      throw new ApiError(res.status, detail);
    }
    return res.json();
  }

  get(path) { return this.request("GET", path); }
  put(path, body) { return this.request("PUT", path, body); }
  post(path, body, extra) { return this.request("POST", path, body, extra); }
}

class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
    this.detail = detail;
    this.name = "ApiError";
  }
}

// Singleton
const apiClient = new ApiClient();
