const I18N = (() => {
  let _lang = localStorage.getItem("dfr_lang") || "en";
  let _data = {};

  async function init() {
    try {
      const res = await fetch("/static/i18n/" + _lang + ".json");
      _data = await res.json();
    } catch (_) {
      _data = {};
    }
    apply();
    renderLangSelector();
  }

  function t(path) {
    return path.split(".").reduce((o, k) => (o && o[k] !== undefined ? o[k] : null), _data) || path;
  }

  function apply() {
    document.querySelectorAll("[data-i18n]").forEach(el => {
      const key = el.getAttribute("data-i18n");
      const text = t(key);
      if (text) el.textContent = text;
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
      const key = el.getAttribute("data-i18n-placeholder");
      const text = t(key);
      if (text) el.placeholder = text;
    });
    document.querySelectorAll("[data-i18n-aria]").forEach(el => {
      const key = el.getAttribute("data-i18n-aria");
      const text = t(key);
      if (text) el.setAttribute("aria-label", text);
    });
    // Dispatch incident type options
    const sel = document.getElementById("incident-type");
    if (sel) {
      const opts = [
        ["", "dispatch.select_type"],
        ["Security Alarm", "dispatch.options.security_alarm"],
        ["Fire", "dispatch.options.fire"],
        ["Traffic Accident", "dispatch.options.traffic_accident"],
        ["Crime in Progress", "dispatch.options.crime_in_progress"],
        ["Search & Rescue", "dispatch.options.search_rescue"],
        ["Missing Person", "dispatch.options.missing_person"],
        ["Other", "dispatch.options.other"]
      ];
      opts.forEach(([val, key]) => {
        const opt = sel.querySelector('option[value="' + val + '"]');
        if (opt) { const txt = t(key); if (txt) opt.textContent = txt; }
      });
    }
    document.dispatchEvent(new CustomEvent("i18n:applied"));
  }

  function renderLangSelector() {
    const container = document.getElementById("lang-selector");
    if (!container) return;
    container.innerHTML = "";
    const sel = document.createElement("select");
    sel.id = "lang-select";
    [{ code: "en", label: "EN" }, { code: "pt", label: "PT" }].forEach(l => {
      const opt = document.createElement("option");
      opt.value = l.code; opt.textContent = l.label;
      if (l.code === _lang) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener("change", () => {
      _lang = sel.value;
      localStorage.setItem("dfr_lang", _lang);
      init();
    });
    container.appendChild(sel);
  }

  async function setLang(code) {
    _lang = code;
    localStorage.setItem("dfr_lang", code);
    await init();
  }

  return { init, t, apply, setLang, get lang() { return _lang; } };
})();

document.addEventListener("DOMContentLoaded", () => I18N.init());