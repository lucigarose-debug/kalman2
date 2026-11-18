/* Adaptadores de mapa con una interfaz común:
 *   init(el) · setRaw(latlngs) · addRoute(id, latlngs, color, label)
 *   setVisible(id, bool) · setRawVisible(bool) · removeRoute(id) · clearRoutes()
 *   fit() · destroy()
 * latlngs = [[lat, lon], ...]
 */
(function () {
  "use strict";

  const RAW_COLOR = "#e53935";

  /* ------------------------------------------------------------------ */
  /* Leaflet + OpenStreetMap (por defecto, sin API key)                  */
  /* ------------------------------------------------------------------ */
  class LeafletAdapter {
    constructor() {
      this.routes = new Map();
      this.raw = null;
      this.markers = [];
      this.bounds = null;
    }

    async init(el) {
      this.map = L.map(el, { preferCanvas: true, zoomControl: true }).setView([40.4168, -3.7038], 5);
      const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, attribution: "&copy; OpenStreetMap contributors",
      });
      const light = L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
        maxZoom: 20, attribution: "&copy; OpenStreetMap &copy; CARTO",
      });
      const sat = L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
          maxZoom: 19, attribution: "Tiles &copy; Esri",
        });
      light.addTo(this.map);
      L.control.layers({ "Claro": light, "OpenStreetMap": osm, "Satélite": sat }, null,
        { position: "topright" }).addTo(this.map);
      L.control.scale({ imperial: false }).addTo(this.map);
    }

    setRaw(latlngs, label) {
      this._clearRaw();
      this.raw = L.polyline(latlngs, { color: RAW_COLOR, weight: 3, opacity: 0.85 })
        .bindTooltip(label || "Ruta original", { sticky: true })
        .addTo(this.map);
      const mk = (ll, color, title) => L.circleMarker(ll, {
        radius: 7, color: "#fff", weight: 2, fillColor: color, fillOpacity: 1,
      }).bindTooltip(title).addTo(this.map);
      this.markers = [mk(latlngs[0], "#2e7d32", "Inicio"), mk(latlngs[latlngs.length - 1], "#111", "Fin")];
      this.bounds = this.raw.getBounds();
      this.fit();
    }

    setRawVisible(v) {
      [this.raw, ...this.markers].forEach((l) => {
        if (!l) return;
        if (v) l.addTo(this.map); else l.remove();
      });
    }

    addRoute(id, latlngs, color, label) {
      const line = L.polyline(latlngs, { color, weight: 4, opacity: 0.9 })
        .bindTooltip(label, { sticky: true })
        .addTo(this.map);
      this.routes.set(id, line);
      this.markers.forEach((m) => m.bringToFront());
    }

    setVisible(id, v) {
      const l = this.routes.get(id);
      if (!l) return;
      if (v) l.addTo(this.map); else l.remove();
    }

    removeRoute(id) {
      const l = this.routes.get(id);
      if (l) { l.remove(); this.routes.delete(id); }
    }

    clearRoutes() {
      this.routes.forEach((l) => l.remove());
      this.routes.clear();
    }

    fit() {
      if (this.bounds) this.map.fitBounds(this.bounds, { padding: [30, 30] });
    }

    invalidate() { this.map.invalidateSize(); }

    _clearRaw() {
      if (this.raw) this.raw.remove();
      this.markers.forEach((m) => m.remove());
      this.raw = null; this.markers = [];
    }

    destroy() { this.map.remove(); }
  }

  /* ------------------------------------------------------------------ */
  /* Google Maps JavaScript API (si se define GOOGLE_MAPS_API_KEY)      */
  /* ------------------------------------------------------------------ */
  let googleLoading = null;

  function loadGoogle(key) {
    if (window.google && window.google.maps) return Promise.resolve();
    if (googleLoading) return googleLoading;
    googleLoading = new Promise((resolve, reject) => {
      window.__gmapsReady = () => resolve();
      const s = document.createElement("script");
      s.src = "https://maps.googleapis.com/maps/api/js?key=" + encodeURIComponent(key) +
        "&loading=async&libraries=marker&callback=__gmapsReady&language=es";
      s.async = true;
      s.onerror = () => reject(new Error("No se pudo cargar Google Maps"));
      document.head.appendChild(s);
      setTimeout(() => reject(new Error("Google Maps tardó demasiado en cargar")), 15000);
    });
    // Si falla, permitir reintentar más tarde desde el selector de mapa
    googleLoading.catch(() => { googleLoading = null; });
    return googleLoading;
  }

  class GoogleAdapter {
    constructor(key, mapId) {
      this.key = key;
      this.mapId = mapId || "DEMO_MAP_ID";
      this.routes = new Map();
      this.raw = null;
      this.markers = [];
      this.bounds = null;
      this.info = null;
    }

    async init(el) {
      await loadGoogle(this.key);
      const g = google.maps;
      this.map = new g.Map(el, {
        center: { lat: 40.4168, lng: -3.7038 }, zoom: 5,
        mapId: this.mapId,
        mapTypeControl: true, streetViewControl: false, fullscreenControl: true,
        mapTypeControlOptions: { position: g.ControlPosition.TOP_RIGHT },
      });
      this.info = new g.InfoWindow();
    }

    _path(latlngs) { return latlngs.map(([lat, lng]) => ({ lat, lng })); }

    _hover(poly, label) {
      poly.addListener("click", (e) => {
        this.info.setContent(label);
        this.info.setPosition(e.latLng);
        this.info.open(this.map);
      });
    }

    setRaw(latlngs, label) {
      this._clearRaw();
      const g = google.maps;
      const path = this._path(latlngs);
      this.raw = new g.Polyline({
        path, map: this.map, strokeColor: RAW_COLOR, strokeOpacity: 0.85, strokeWeight: 3, zIndex: 1,
      });
      this._hover(this.raw, label || "Ruta original");
      this.markers = [];
      try {
        const { AdvancedMarkerElement, PinElement } = g.marker;
        const mk = (pos, color, title) => new AdvancedMarkerElement({
          map: this.map, position: pos, title,
          content: new PinElement({ background: color, borderColor: "#fff", glyphColor: "#fff", scale: 0.8 }).element,
        });
        this.markers = [mk(path[0], "#2e7d32", "Inicio"), mk(path[path.length - 1], "#111111", "Fin")];
      } catch (err) {
        console.warn("Marcadores avanzados no disponibles:", err);
      }
      this.bounds = new g.LatLngBounds();
      path.forEach((p) => this.bounds.extend(p));
      this.fit();
    }

    setRawVisible(v) {
      if (this.raw) this.raw.setMap(v ? this.map : null);
      this.markers.forEach((m) => { m.map = v ? this.map : null; });
    }

    addRoute(id, latlngs, color, label) {
      const poly = new google.maps.Polyline({
        path: this._path(latlngs), map: this.map,
        strokeColor: color, strokeOpacity: 0.9, strokeWeight: 4, zIndex: 2 + this.routes.size,
      });
      this._hover(poly, label);
      this.routes.set(id, poly);
    }

    setVisible(id, v) {
      const p = this.routes.get(id);
      if (p) p.setMap(v ? this.map : null);
    }

    removeRoute(id) {
      const p = this.routes.get(id);
      if (p) { p.setMap(null); this.routes.delete(id); }
    }

    clearRoutes() {
      this.routes.forEach((p) => p.setMap(null));
      this.routes.clear();
    }

    fit() { if (this.bounds) this.map.fitBounds(this.bounds, 30); }

    invalidate() { /* Google Maps se redimensiona solo */ }

    _clearRaw() {
      if (this.raw) this.raw.setMap(null);
      this.markers.forEach((m) => { m.map = null; });
      this.raw = null; this.markers = [];
    }

    destroy() {
      this.clearRoutes();
      this._clearRaw();
    }
  }

  window.MapAdapters = { LeafletAdapter, GoogleAdapter, RAW_COLOR };
})();
