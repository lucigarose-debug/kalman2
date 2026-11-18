/* Lógica de la interfaz: carga de archivos, parámetros, Aplicar/Borrar y leyenda. */
(function () {
  "use strict";

  const CFG = JSON.parse(document.getElementById("app-config").textContent);
  const D = CFG.defaults;
  const { LeafletAdapter, GoogleAdapter, RAW_COLOR } = window.MapAdapters;

  // Paleta para rutas filtradas (sin rojos, para no confundir con la original)
  const PALETTE = ["#1e88e5", "#43a047", "#8e24aa", "#fb8c00", "#00acc1",
                   "#3949ab", "#c0ca33", "#6d4c41", "#d81b60", "#00897b"];

  // Rangos (escala logarítmica en los sliders)
  const RANGES = {
    q_cv: [0.01, 20], q_rw: [0.05, 50], r: [0.5, 100],
  };
  const MODEL_DEFAULT_Q = { cv: D.q, rw: 2.0 };
  const MODEL_HINT = {
    cv: "Estado [posición, velocidad]. Q modela aceleraciones aleatorias (σ en m/s²). Ideal para vehículos, bici o a pie.",
    rw: "Estado [posición]. Q modela velocidad aleatoria (σ en m/s). Útil para receptores casi estáticos.",
  };

  const $ = (id) => document.getElementById(id);
  const state = {
    raw: null,          // [[lat, lon, ele, t], ...]
    rawName: "",
    rawVisible: true,
    summary: null,
    routes: [],         // {id, color, points, params, stats, visible}
    nextId: 1,
    colorIdx: 0,
    filterEnabled: true,
    provider: CFG.googleKey ? "google" : "leaflet",
    busy: false,
  };
  let map = null;

  /* ---------------------------------------------------------------- */
  /* Utilidades                                                        */
  /* ---------------------------------------------------------------- */
  const fmtDist = (m) => (m >= 1000 ? (m / 1000).toFixed(2) + " km" : m.toFixed(0) + " m");
  const fmtDur = (s) => {
    if (s == null) return "—";
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.round(s % 60);
    return (h ? h + " h " : "") + (h || m ? m + " min " : "") + sec + " s";
  };
  const fmtNum = (v) => {
    if (v >= 100) return v.toFixed(0);
    if (v >= 10) return v.toFixed(1);
    if (v >= 1) return v.toFixed(2);
    return v.toPrecision(2);
  };
  const toLog = (v, [lo, hi]) => Math.round(1000 * Math.log(v / lo) / Math.log(hi / lo));
  const fromLog = (s, [lo, hi]) => lo * Math.pow(hi / lo, s / 1000);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };

  let toastTimer = null;
  function toast(msg, kind = "info") {
    const t = $("toast");
    t.textContent = msg;
    t.className = "toast show " + kind;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.className = "toast"), kind === "error" ? 6000 : 3000);
  }

  function setBusy(b) {
    state.busy = b;
    $("busy").classList.toggle("hidden", !b);
    updateButtons();
  }

  async function api(url, opts) {
    const res = await fetch(url, opts);
    let body = null;
    try { body = await res.json(); } catch (_) { /* respuesta no JSON */ }
    if (!res.ok) throw new Error((body && body.error) || `Error HTTP ${res.status}`);
    return body;
  }

  /* ---------------------------------------------------------------- */
  /* Mapa                                                              */
  /* ---------------------------------------------------------------- */
  async function initMap(provider) {
    if (map) { try { map.destroy(); } catch (_) {} }
    // Contenedor nuevo: Leaflet y Google no comparten bien el mismo nodo
    const old = $("map");
    const fresh = el("div");
    fresh.id = "map";
    old.replaceWith(fresh);

    try {
      map = provider === "google" ? new GoogleAdapter(CFG.googleKey, CFG.googleMapId) : new LeafletAdapter();
      await map.init(fresh);
      state.provider = provider;
    } catch (err) {
      console.error(err);
      toast("Google Maps no disponible; se usa OpenStreetMap. " + err.message, "error");
      map = new LeafletAdapter();
      await map.init(fresh);
      state.provider = "leaflet";
    }
    $("provider").value = state.provider;
    redrawAll();
  }

  // Google llama a esta función global si la API key es inválida/no autorizada
  window.gm_authFailure = () => {
    toast("La API key de Google Maps no es válida para este dominio. Usando OpenStreetMap.", "error");
    initMap("leaflet");
  };

  const latlngs = (pts) => pts.map((p) => [p[0], p[1]]);

  function routeLabel(r) {
    const p = r.params;
    const bits = [`#${r.id} ${p.model.toUpperCase()}`, `Q=${fmtNum(p.q)}`, `R=${fmtNum(p.r)}`];
    if (p.smoother) bits.push("RTS");
    if (p.gate > 0) bits.push(`gate ${p.gate}σ`);
    return bits.join(" · ");
  }

  function redrawAll() {
    if (!map || !state.raw) return;
    map.setRaw(latlngs(state.raw), "Ruta original — " + state.rawName);
    map.setRawVisible(state.rawVisible);
    state.routes.forEach((r) => {
      map.addRoute(r.id, latlngs(r.points), r.color, routeLabel(r));
      map.setVisible(r.id, r.visible && state.filterEnabled);
    });
  }

  /* ---------------------------------------------------------------- */
  /* Carga de archivos                                                 */
  /* ---------------------------------------------------------------- */
  async function handleFile(file) {
    if (!file) return;
    if (file.size > CFG.maxMb * 1024 * 1024) {
      toast(`El archivo supera ${CFG.maxMb} MB.`, "error");
      return;
    }
    const fd = new FormData();
    fd.append("file", file);
    setBusy(true);
    try {
      const data = await api("/api/upload", { method: "POST", body: fd });
      state.raw = data.points;
      state.rawName = data.name;
      state.summary = data.summary;
      state.rawVisible = true;
      clearRoutes(true);
      renderFileInfo(data);
      map.setRaw(latlngs(state.raw), "Ruta original — " + data.name);
      renderRoutes();
      toast(`${data.summary.n} puntos cargados (${data.format.toUpperCase()}).`, "ok");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
      $("file-input").value = "";
    }
  }

  function renderFileInfo(data) {
    const s = data.summary;
    const box = $("file-info");
    box.replaceChildren();
    box.classList.remove("hidden");
    const name = el("div", "fname", data.name);
    const tag = el("span", "tag", data.format.toUpperCase());
    name.prepend(tag);
    box.appendChild(name);
    const dl = el("dl", "stats");
    const add = (k, v) => { dl.appendChild(el("dt", null, k)); dl.appendChild(el("dd", null, v)); };
    add("Puntos", s.n.toLocaleString("es-ES"));
    add("Longitud", fmtDist(s.length_m));
    add("Duración", s.has_time ? fmtDur(s.duration_s) : "sin tiempos");
    add("Muestreo", s.has_time && s.median_dt_s != null ? `${s.median_dt_s} s (mediana)` : `fijo (${$("dt-default").value} s)`);
    add("Elevación", s.has_ele ? `${s.ele_min} – ${s.ele_max} m` : "no disponible");
    box.appendChild(dl);

    const ul = $("warnings");
    ul.replaceChildren();
    (data.warnings || []).forEach((w) => ul.appendChild(el("li", null, w)));
    $("filter-ele").disabled = !s.has_ele;
  }

  /* ---------------------------------------------------------------- */
  /* Parámetros                                                        */
  /* ---------------------------------------------------------------- */
  function qRange() { return $("model").value === "cv" ? RANGES.q_cv : RANGES.q_rw; }

  function bindLog(rangeId, numId, rangeFn, varId, onChange) {
    const range = $(rangeId), num = $(numId);
    const sync = (v) => {
      $(varId).textContent = fmtNum(v * v);
      if (onChange) onChange(v);
    };
    range.addEventListener("input", () => {
      const v = fromLog(+range.value, rangeFn());
      num.value = fmtNum(v);
      sync(v);
    });
    num.addEventListener("change", () => {
      const [lo, hi] = rangeFn();
      let v = parseFloat(num.value);
      if (!isFinite(v) || v <= 0) v = lo;
      v = Math.min(Math.max(v, lo), hi);
      num.value = fmtNum(v);
      range.value = toLog(v, rangeFn());
      sync(v);
    });
    return (v) => { num.value = fmtNum(v); range.value = toLog(v, rangeFn()); sync(v); };
  }

  const setQ = bindLog("q-range", "q-num", qRange, "q-var");
  const setR = bindLog("r-range", "r-num", () => RANGES.r, "r-var");

  function applyModelUI(resetQ) {
    const m = $("model").value;
    $("q-unit").textContent = m === "cv" ? "m/s²" : "m/s";
    $("qe-unit").textContent = m === "cv" ? "m/s²" : "m/s";
    $("model-hint").textContent = MODEL_HINT[m];
    if (resetQ) setQ(MODEL_DEFAULT_Q[m]);
    else setQ(parseFloat($("q-num").value) || MODEL_DEFAULT_Q[m]);
  }

  function resetParams() {
    $("model").value = D.model;
    applyModelUI(true);
    setR(D.r);
    $("smoother").checked = D.smoother;
    $("gate-on").checked = D.gate > 0;
    $("gate").value = D.gate > 0 ? D.gate : 4;
    $("filter-ele").checked = D.filter_ele;
    $("q-ele").value = D.q_ele;
    $("r-ele").value = D.r_ele;
    $("dt-default").value = D.dt_default;
    $("vel0").value = D.vel0;
    syncGate();
  }

  function syncGate() { $("gate").disabled = !$("gate-on").checked; }

  function readParams() {
    return {
      model: $("model").value,
      q: parseFloat($("q-num").value),
      r: parseFloat($("r-num").value),
      smoother: $("smoother").checked,
      gate: $("gate-on").checked ? parseFloat($("gate").value) || 4 : 0,
      filter_ele: $("filter-ele").checked && !$("filter-ele").disabled,
      q_ele: parseFloat($("q-ele").value),
      r_ele: parseFloat($("r-ele").value),
      dt_default: parseFloat($("dt-default").value),
      vel0: parseFloat($("vel0").value),
    };
  }

  /* ---------------------------------------------------------------- */
  /* Aplicar / Borrar                                                  */
  /* ---------------------------------------------------------------- */
  async function applyFilter() {
    if (!state.raw || state.busy || !state.filterEnabled) return;
    setBusy(true);
    try {
      const data = await api("/api/filter", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ points: state.raw, params: readParams() }),
      });
      const route = {
        id: state.nextId++,
        color: PALETTE[state.colorIdx++ % PALETTE.length],
        points: data.points, params: data.params, stats: data.stats, visible: true,
      };
      state.routes.push(route);
      map.addRoute(route.id, latlngs(route.points), route.color, routeLabel(route));
      renderRoutes();
      const rej = data.stats.rejected ? ` · ${data.stats.rejected} outliers` : "";
      toast(`Ruta #${route.id}: desviación RMS ${data.stats.rms_dev_m} m${rej}`, "ok");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function clearRoutes(silent) {
    if (map) map.clearRoutes();
    state.routes = [];
    state.colorIdx = 0;
    state.nextId = 1;
    renderRoutes();
    if (!silent) toast("Rutas filtradas eliminadas.", "info");
  }

  function removeRoute(id) {
    map.removeRoute(id);
    state.routes = state.routes.filter((r) => r.id !== id);
    renderRoutes();
  }

  /* ---------------------------------------------------------------- */
  /* Exportación                                                       */
  /* ---------------------------------------------------------------- */
  function download(name, mime, text) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: mime }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }

  function baseName() { return (state.rawName || "ruta").replace(/\.[^.]+$/, ""); }

  function exportGeoJSON(r) {
    const hasT = r.points.every((p) => p[3] != null);
    const gj = {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        properties: Object.assign({ name: routeLabel(r), filter: r.params, stats: r.stats },
          hasT ? { coordTimes: r.points.map((p) => new Date(p[3] * 1000).toISOString()) } : {}),
        geometry: {
          type: "LineString",
          coordinates: r.points.map((p) => (p[2] != null ? [p[1], p[0], p[2]] : [p[1], p[0]])),
        },
      }],
    };
    download(`${baseName()}_kalman_${r.id}.geojson`, "application/geo+json", JSON.stringify(gj));
  }

  function exportCSV(r) {
    const lines = ["time,latitude,longitude,elevation"];
    r.points.forEach((p) => {
      const t = p[3] != null ? new Date(p[3] * 1000).toISOString() : "";
      lines.push(`${t},${p[0]},${p[1]},${p[2] != null ? p[2] : ""}`);
    });
    download(`${baseName()}_kalman_${r.id}.csv`, "text/csv", lines.join("\n"));
  }

  /* ---------------------------------------------------------------- */
  /* Leyenda / lista de rutas                                          */
  /* ---------------------------------------------------------------- */
  function iconBtn(title, svgPath, onClick, extraCls) {
    const b = el("button", "icon " + (extraCls || ""));
    b.type = "button";
    b.title = title;
    b.setAttribute("aria-label", title);
    b.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${svgPath}"/></svg>`;
    b.addEventListener("click", onClick);
    return b;
  }
  const ICON_EYE = "M12 5C6 5 2 12 2 12s4 7 10 7 10-7 10-7-4-7-10-7zm0 11a4 4 0 110-8 4 4 0 010 8z";
  const ICON_EYE_OFF = "M3 4l17 17-1.4 1.4-3.1-3.1A11 11 0 0112 19C6 19 2 12 2 12a19 19 0 014.3-5.2L1.6 5.4 3 4zm9 3c6 0 10 5 10 5a18 18 0 01-3 3.6L16.7 13A4 4 0 0011 7.3L9.4 5.7A10 10 0 0112 7z";
  const ICON_DL = "M12 3v10l4-4 1.4 1.4L12 16.8l-5.4-5.4L8 10l4 3V3zM4 19h16v2H4z";
  const ICON_X = "M6.4 5L12 10.6 17.6 5 19 6.4 13.4 12 19 17.6 17.6 19 12 13.4 6.4 19 5 17.6 10.6 12 5 6.4z";
  const ICON_FIT = "M4 4h6v2H6v4H4V4zm10 0h6v6h-2V6h-4V4zM4 14h2v4h4v2H4v-6zm14 0h2v6h-6v-2h4v-4z";

  function renderRoutes() {
    const ul = $("route-list");
    ul.replaceChildren();
    if (!state.raw) {
      ul.appendChild(el("li", "empty", "Carga un archivo para empezar."));
      updateButtons();
      return;
    }
    // Ruta original
    const li = el("li", "route raw");
    const sw = el("span", "swatch");
    sw.style.background = RAW_COLOR;
    const txt = el("div", "rtext");
    txt.appendChild(el("strong", null, "Original (datos crudos)"));
    txt.appendChild(el("small", null, `${state.summary.n.toLocaleString("es-ES")} pts · ${fmtDist(state.summary.length_m)}`));
    const tools = el("div", "rtools");
    tools.appendChild(iconBtn("Encuadrar ruta", ICON_FIT, () => map.fit()));
    tools.appendChild(iconBtn(state.rawVisible ? "Ocultar" : "Mostrar",
      state.rawVisible ? ICON_EYE : ICON_EYE_OFF, () => {
        state.rawVisible = !state.rawVisible;
        map.setRawVisible(state.rawVisible);
        renderRoutes();
      }));
    li.append(sw, txt, tools);
    ul.appendChild(li);

    state.routes.forEach((r) => {
      const li = el("li", "route" + (r.visible && state.filterEnabled ? "" : " off"));
      const sw = el("span", "swatch");
      sw.style.background = r.color;
      const txt = el("div", "rtext");
      txt.appendChild(el("strong", null, routeLabel(r)));
      const s = r.stats;
      txt.appendChild(el("small", null,
        `RMS ${s.rms_dev_m} m · máx ${s.max_dev_m} m · ${fmtDist(s.length_filtered_m)}` +
        (s.rejected ? ` · ${s.rejected} outliers` : "")));
      const tools = el("div", "rtools");
      tools.appendChild(iconBtn(r.visible ? "Ocultar" : "Mostrar", r.visible ? ICON_EYE : ICON_EYE_OFF, () => {
        r.visible = !r.visible;
        map.setVisible(r.id, r.visible && state.filterEnabled);
        renderRoutes();
      }));
      const dl = iconBtn("Descargar (clic: GeoJSON · Mayús+clic: CSV)", ICON_DL, (e) => {
        if (e.shiftKey) exportCSV(r); else exportGeoJSON(r);
      });
      tools.appendChild(dl);
      tools.appendChild(iconBtn("Quitar esta ruta", ICON_X, () => removeRoute(r.id), "danger"));
      li.append(sw, txt, tools);
      ul.appendChild(li);
    });
    if (!state.routes.length) {
      ul.appendChild(el("li", "empty", "Ajusta los parámetros y pulsa «Aplicar»."));
    }
    updateButtons();
  }

  function updateButtons() {
    $("apply-btn").disabled = !state.raw || state.busy || !state.filterEnabled;
    $("clear-btn").disabled = !state.routes.length || state.busy;
  }

  /* ---------------------------------------------------------------- */
  /* Eventos                                                           */
  /* ---------------------------------------------------------------- */
  function bindEvents() {
    $("file-input").addEventListener("change", (e) => handleFile(e.target.files[0]));
    const dz = $("dropzone");
    ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => {
      e.preventDefault(); dz.classList.add("over");
    }));
    ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => {
      e.preventDefault(); dz.classList.remove("over");
    }));
    dz.addEventListener("drop", (e) => handleFile(e.dataTransfer.files[0]));
    // Permitir soltar el archivo en cualquier parte del mapa
    document.querySelector(".map-wrap").addEventListener("dragover", (e) => e.preventDefault());
    document.querySelector(".map-wrap").addEventListener("drop", (e) => {
      e.preventDefault(); handleFile(e.dataTransfer.files[0]);
    });

    $("model").addEventListener("change", () => applyModelUI(true));
    $("gate-on").addEventListener("change", syncGate);
    $("reset-params").addEventListener("click", resetParams);
    $("apply-btn").addEventListener("click", applyFilter);
    $("clear-btn").addEventListener("click", () => clearRoutes(false));

    $("filter-enabled").addEventListener("change", (e) => {
      state.filterEnabled = e.target.checked;
      $("filter-controls").disabled = !state.filterEnabled;
      state.routes.forEach((r) => map.setVisible(r.id, r.visible && state.filterEnabled));
      renderRoutes();
    });

    // Atajo: Ctrl/Cmd + Enter = Aplicar
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") applyFilter();
    });

    if (CFG.googleKey) {
      $("provider-wrap").classList.remove("hidden");
      $("provider").addEventListener("change", (e) => initMap(e.target.value));
    }
    window.addEventListener("resize", () => map && map.invalidate());
  }

  /* ---------------------------------------------------------------- */
  bindEvents();
  resetParams();
  initMap(state.provider);
})();
