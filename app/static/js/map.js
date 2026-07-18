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
    this._homeMarker = null;
    this._lastCoords = null;
    this._init();
  }

  _init() {
    let center = [48.8566, 2.3522];
    let zoom = 5;
    let homeCoords = null;
    try {
      const stored = localStorage.getItem(DEFAULT_CENTER_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length === 2) {
          center = parsed;
          zoom = 12;
          homeCoords = parsed;
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

    if (homeCoords) {
      this._addHomeMarker(homeCoords[0], homeCoords[1]);
    }

    this._map.on("click", (e) => {
      let lat = Math.round(e.latlng.lat * 1e6) / 1e6;
      let lon = Math.round(e.latlng.lng * 1e6) / 1e6;
      lat = Math.max(-90, Math.min(90, lat));
      lon = ((lon + 540) % 360) - 180;
      lon = Math.round(lon * 1e6) / 1e6;
      this._lastCoords = { lat, lon };
      this.setCoordinates(lat, lon);
    });
  }

  _addHomeMarker(lat, lon) {
    if (this._homeMarker) {
      this._map.removeLayer(this._homeMarker);
    }
    const icon = L.divIcon({
      className: "home-marker-icon",
      html: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" fill="#2f73d9" stroke="#fff" stroke-width="2"/><circle cx="12" cy="12" r="4" fill="#fff"/></svg>',
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
    this._homeMarker = L.marker([lat, lon], { icon, zIndexOffset: 1000 }).addTo(this._map);
    this._homeMarker.bindTooltip("Default Center", {
      permanent: true,
      direction: "top",
      offset: [0, -16],
      className: "home-marker-tooltip",
    });
  }

  setCoordinates(lat, lon) {
    const latEl = document.getElementById("latitude");
    const lonEl = document.getElementById("longitude");
    if (latEl) latEl.value = lat;
    if (lonEl) lonEl.value = lon;

    this.placeMarker(lat, lon);

    this._lastCoords = { lat, lon };

    document.dispatchEvent(
      new CustomEvent("dfr:coordinates", { detail: { lat, lon } })
    );
  }

  placeMarker(lat, lon) {
    if (this._marker) {
      this._marker.setLatLng([lat, lon]);
    } else {
      this._marker = L.marker([lat, lon]).addTo(this._map);
    }
    this._map.setView([lat, lon], this._map.getZoom() < 12 ? 12 : this._map.getZoom());
    this._ensureHomeMarker();
  }

  _ensureHomeMarker() {
    try {
      const stored = localStorage.getItem(DEFAULT_CENTER_KEY);
      if (!stored) return;
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed) && parsed.length === 2) {
        this._addHomeMarker(parsed[0], parsed[1]);
      }
    } catch (_) { /* ignore */ }
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
    this._addHomeMarker(lat, lon);
  }

  invalidateSize() {
    if (this._map) this._map.invalidateSize({ animate: false });
  }

  drawMissionLine(targetLat, targetLon) {
    this.clearMissionLine();
    const home = this._lastCoords;
    if (!home) return;
    this._missionLine = L.polyline([[home.lat, home.lon], [targetLat, targetLon]], {
      color: "#2f73d9", weight: 2, dashArray: "8 6", className: "mission-line",
    }).addTo(this._map);
  }

  clearMissionLine() {
    if (this._missionLine) { this._map.removeLayer(this._missionLine); this._missionLine = null; }
    if (this._droneMarker) { this._map.removeLayer(this._droneMarker); this._droneMarker = null; }
  }

  updateDroneMarker(lat, lon) {
    if (this._droneMarker) {
      this._droneMarker.setLatLng([lat, lon]);
    } else {
      const icon = L.divIcon({
        className: "drone-marker-icon",
        html: '<svg width=\"28\" height=\"28\" viewBox=\"0 0 24 24\" fill=\"none\"><circle cx=\"12\" cy=\"12\" r=\"11\" fill=\"#2f73d9\" fill-opacity=\"0.3\" stroke=\"#2f73d9\" stroke-width=\"2\"/><circle cx=\"12\" cy=\"12\" r=\"4\" fill=\"#2f73d9\"/></svg>',
        iconSize: [28, 28], iconAnchor: [14, 14],
      });
      this._droneMarker = L.marker([lat, lon], { icon, zIndexOffset: 2000 }).addTo(this._map);
    }
  }
}
