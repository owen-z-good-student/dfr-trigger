/**
 * MapController — Leaflet map with OSM tiles.
 * Single marker, rounds to 6 decimal places, writes #latitude/#longitude,
 * dispatches dfr:coordinates custom event.
 */
const DEFAULT_CENTER_KEY = "dfr_default_center";

class MapController {
  constructor() {
    this._map = null;
    this._marker = null;
    this._lastCoords = null;
    this._init();
  }

  _init() {
    // Read default center from localStorage
    let center = [48.8566, 2.3522];
    let zoom = 5;
    try {
      const stored = localStorage.getItem(DEFAULT_CENTER_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length === 2) {
          center = parsed;
          zoom = 12;
        }
      }
    } catch (_) { /* ignore */ }

    this._map = L.map("map", {
      center,
      zoom,
      zoomControl: true,
    });

    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      crossOrigin: "anonymous",
    }).addTo(this._map);

    this._map.on("click", (e) => {
      const lat = Math.round(e.latlng.lat * 1e6) / 1e6;
      const lon = Math.round(e.latlng.lng * 1e6) / 1e6;
      this._lastCoords = { lat, lon };
      this.setCoordinates(lat, lon);
    });
  }

  setCoordinates(lat, lon) {
    const latEl = document.getElementById("latitude");
    const lonEl = document.getElementById("longitude");
    if (latEl) latEl.value = lat;
    if (lonEl) lonEl.value = lon;

    // Place or move single marker
    if (this._marker) {
      this._marker.setLatLng([lat, lon]);
    } else {
      this._marker = L.marker([lat, lon]).addTo(this._map);
    }

    this._lastCoords = { lat, lon };

    document.dispatchEvent(
      new CustomEvent("dfr:coordinates", { detail: { lat, lon } })
    );
  }

  /** Returns the last clicked coordinates, or null */
  getLastCoordinates() {
    return this._lastCoords;
  }

  /** Store current map center as default in localStorage */
  setDefaultCenter(lat, lon) {
    try {
      localStorage.setItem(DEFAULT_CENTER_KEY, JSON.stringify([lat, lon]));
    } catch (_) { /* ignore quota errors */ }
  }

  invalidateSize() {
    if (this._map) this._map.invalidateSize({ animate: false });
  }
}
