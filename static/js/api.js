/* ==========================================================================
   OptiRuta — cliente de la API (JWT) y utilidades de interfaz.
   El token se guarda en localStorage y se envía en el encabezado Authorization.
   Si el access token expira, se renueva con el refresh; si falla, redirige al login.
   ========================================================================== */
const OR = (() => {
  const CLAVE = "optiruta.sesion";

  const sesion = {
    leer() { try { return JSON.parse(localStorage.getItem(CLAVE)) || null; } catch { return null; } },
    guardar(datos) { localStorage.setItem(CLAVE, JSON.stringify(datos)); },
    cerrar(motivo) {
      localStorage.removeItem(CLAVE);
      const q = motivo ? `?motivo=${encodeURIComponent(motivo)}` : "";
      window.location.href = "/login/" + q;
    },
    usuario() { return (this.leer() || {}).usuario || null; },
  };

  async function renovar() {
    const s = sesion.leer();
    if (!s || !s.refresh) return false;
    const r = await fetch("/api/auth/refresh/", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh: s.refresh }),
    });
    if (!r.ok) return false;
    const d = await r.json();
    s.access = d.access;
    if (d.refresh) s.refresh = d.refresh;
    sesion.guardar(s);
    return true;
  }

  class ErrorApi extends Error {
    constructor(mensaje, estado, datos) { super(mensaje); this.estado = estado; this.datos = datos; }
  }

  /** Llama a la API. Devuelve JSON o lanza ErrorApi con el mensaje del backend. */
  async function api(ruta, { metodo = "GET", datos = null, reintento = true, crudo = false } = {}) {
    const s = sesion.leer();
    const opciones = { method: metodo, headers: { Accept: "application/json" } };
    if (s && s.access) opciones.headers.Authorization = `Bearer ${s.access}`;
    if (datos !== null) {
      opciones.headers["Content-Type"] = "application/json";
      opciones.body = JSON.stringify(datos);
    }
    let r;
    try {
      r = await fetch(ruta.startsWith("/") ? ruta : `/api/${ruta}`, opciones);
    } catch (e) {
      throw new ErrorApi("No hay conexión con el servidor. Revisa tu red e inténtalo de nuevo.", 0);
    }
    if (r.status === 401 && reintento && s) {
      if (await renovar()) return api(ruta, { metodo, datos, reintento: false, crudo });
      sesion.cerrar("expirada");
      throw new ErrorApi("Tu sesión expiró.", 401);
    }
    if (crudo) return r;
    if (r.status === 204) return null;
    const cuerpo = await r.json().catch(() => ({}));
    if (!r.ok) throw new ErrorApi(mensajeDe(cuerpo, r.status), r.status, cuerpo);
    return cuerpo;
  }

  function mensajeDe(cuerpo, estado) {
    if (cuerpo && cuerpo.error) {
      const det = cuerpo.detalle;
      if (cuerpo.codigo === "validacion" && det && typeof det === "object") {
        const primero = Object.entries(det).find(([k]) => k !== "detail");
        if (primero) {
          const [campo, msgs] = primero;
          const texto = Array.isArray(msgs) ? msgs[0] : (typeof msgs === "object" ? Object.values(msgs)[0] : msgs);
          return campo === "non_field_errors" ? String(texto) : `${campo.replace(/_/g, " ")}: ${texto}`;
        }
      }
      return cuerpo.error;
    }
    if (estado === 403) return "No tienes permiso para esta acción.";
    if (estado === 404) return "No se encontró el recurso.";
    if (estado >= 500) return "El servidor tuvo un problema. Inténtalo en unos segundos.";
    return "La operación no se pudo completar.";
  }

  /* ---------------- Interfaz ---------------- */
  function aviso(texto, tipo = "info", ms = 4500) {
    let zona = document.querySelector(".toast-zona");
    if (!zona) { zona = document.createElement("div"); zona.className = "toast-zona"; zona.setAttribute("aria-live", "polite"); document.body.appendChild(zona); }
    const el = document.createElement("div");
    el.className = `aviso ${tipo}`;
    const icono = tipo === "error" ? "exclamation-octagon" : tipo === "ok" ? "check-circle" : "info-circle";
    el.innerHTML = `<i class="bi bi-${icono}"></i><div></div>`;
    el.querySelector("div").textContent = texto;
    zona.appendChild(el);
    setTimeout(() => el.remove(), ms);
  }

  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const estado = (codigo, texto) => `<span class="estado e-${esc(codigo)}">${esc(texto || codigo.replace(/_/g, " ").toLowerCase().replace(/^\w/, (m) => m.toUpperCase()))}</span>`;
  const prioridad = (p) => `<span class="prio prio-${esc(p)}">${esc(p.charAt(0) + p.slice(1).toLowerCase())}</span>`;
  const num = (n, dec = 1) => Number(n || 0).toLocaleString("es-PE", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const hora = (iso) => iso ? new Date(iso).toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit" }) : "—";
  const fecha = (iso) => iso ? new Date(iso + (iso.length === 10 ? "T12:00:00" : "")).toLocaleDateString("es-PE", { day: "2-digit", month: "short", year: "numeric" }) : "—";
  const hoyISO = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
  const cargando = (texto = "Cargando…") => `<div class="cargando"><div class="spinner-border spinner-border-sm"></div>${esc(texto)}</div>`;
  const vacio = (texto, icono = "inbox") => `<div class="vacio"><i class="bi bi-${icono}"></i>${esc(texto)}</div>`;

  /** Botón con estado de carga mientras dura la promesa. */
  async function conCarga(boton, promesa) {
    const original = boton.innerHTML;
    boton.disabled = true;
    boton.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>${boton.dataset.cargando || "Procesando…"}`;
    try { return await promesa(); } finally { boton.disabled = false; boton.innerHTML = original; }
  }

  /* ---------------- Mapas (Leaflet) ---------------- */
  const iconos = {
    deposito: () => L.divIcon({ className: "", html: '<div class="marcador-deposito"><i class="bi bi-house-gear-fill"></i></div>', iconSize: [40, 40], iconAnchor: [20, 20] }),
    camion: (enCurso, tipo, color) => L.divIcon({ className: "", html: `<div class="marcador-camion ${enCurso ? "en-curso" : ""}" ${color ? `style="background:${color};color:#fff"` : ""}><i class="bi bi-${tipo === "MOTO" ? "bicycle" : "truck"}"></i></div>`, iconSize: [36, 36], iconAnchor: [18, 18] }),
    parada: (n, color) => L.divIcon({ className: "", html: `<div class="marcador-parada" style="background:${color}">${n}</div>`, iconSize: [28, 28], iconAnchor: [14, 14] }),
  };
  // Estado del VEHÍCULO en el mapa del día (criterio 17 de la guía)
  const ESTADO_VEHICULO = {
    EN_CAMINO: { color: "#C98F00", texto: "En camino" },
    INCIDENCIA: { color: "#D64545", texto: "Con incidencia" },
    COMPLETADA: { color: "#1E8E5A", texto: "Ruta completada" },
    PLANIFICADA: { color: "#7C8B98", texto: "En almacén (planificada)" },
  };
  function estadoVehiculo(ruta) {
    if (ruta.estado === "COMPLETADA") return "COMPLETADA";
    if (ruta.estado === "PLANIFICADA") return "PLANIFICADA";
    return ruta.paradas.some((p) => p.estado === "FALLIDO") ? "INCIDENCIA" : "EN_CAMINO";
  }
  const COLOR_ESTADO = { PENDIENTE: "#7C8B98", EN_CAMINO: "#F5B400", ENTREGADO: "#1E8E5A", FALLIDO: "#D64545", REPROGRAMADO: "#7B3FB0" };

  // Mapas base gratuitos y sin clave. Si el primero falla, se usa el siguiente.
  const PROVEEDORES = [
    ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
      "Mapa &copy; Esri, HERE, Garmin, &copy; OpenStreetMap"],
    ["https://tile.openstreetmap.org/{z}/{x}/{y}.png", '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'],
    ["https://tile.openstreetmap.de/{z}/{x}/{y}.png", "&copy; OpenStreetMap"],
  ];
  function mapa(id, centro, zoom = 13) {
    const m = L.map(id, { zoomControl: true }).setView(centro, zoom);
    let i = 0, errores = 0, capa = null;
    const poner = () => {
      if (capa) m.removeLayer(capa);
      const [url, attribution] = PROVEEDORES[i];
      capa = L.tileLayer(url, { maxZoom: 19, attribution }).addTo(m);
      capa.on("tileerror", () => {
        if (++errores >= 4 && i < PROVEEDORES.length - 1) { i++; errores = 0; poner(); }
      });
    };
    poner();
    return m;
  }

  /* ---------------- Tiempo real (WebSocket) ---------------- */
  /**
   * Abre /ws/mapa/ con el token JWT. Llama a alEvento(tipo, datos) con cada novedad y a
   * alCambiarEstado(true|false) cuando la conexión se abre o se cae. Se reconecta solo.
   */
  function enVivo(alEvento, alCambiarEstado = () => {}) {
    let ws = null, intentos = 0, latido = null, cerrado = false;
    const conectar = () => {
      const s = sesion.leer();
      if (!s || !s.access || cerrado) return;
      const protocolo = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${protocolo}://${location.host}/ws/mapa/?token=${encodeURIComponent(s.access)}`);
      ws.onopen = () => {
        intentos = 0;
        alCambiarEstado(true);
        latido = setInterval(() => ws.readyState === 1 && ws.send(JSON.stringify({ tipo: "ping" })), 25000);
      };
      ws.onmessage = (e) => {
        try { const m = JSON.parse(e.data); if (m.tipo !== "pong" && m.tipo !== "conectado") alEvento(m.tipo, m.datos); } catch {}
      };
      ws.onclose = async (e) => {
        clearInterval(latido);
        alCambiarEstado(false);
        if (cerrado) return;
        if (e.code === 4403 && intentos === 0) await renovar();   // token vencido: se renueva y reintenta
        const espera = Math.min(30000, 1000 * 2 ** intentos++);
        setTimeout(conectar, espera);
      };
    };
    conectar();
    return { cerrar() { cerrado = true; ws && ws.close(); } };
  }

  /* ---------------- Validación en vivo de formularios ---------------- */
  const REGLAS = {
    celular: { re: /^9\d{8}$/, msg: "El celular peruano tiene 9 dígitos y empieza con 9 (ej. 987654321)." },
    email: { re: /^[^\s@]+@[^\s@]+\.[a-zA-Z]{2,}$/, msg: "Escribe un correo válido, con @ y dominio (ej. nombre@gmail.com)." },
  };

  /** Valida cada campo mientras se escribe y muestra el mensaje bajo el campo. */
  function validarEnVivo(form) {
    const revisar = (campo) => {
      const tipo = campo.dataset.tipo;
      campo.setCustomValidity("");
      if (tipo && REGLAS[tipo] && campo.value.trim() && !REGLAS[tipo].re.test(campo.value.trim())) {
        campo.setCustomValidity(REGLAS[tipo].msg);
      }
      if (tipo === "celular" && campo.dataset.inicioMal && !campo.value) {
        campo.setCustomValidity("Los celulares en Perú empiezan con 9.");
      }
      const fb = campo.closest(".campo, [class*=col]")?.querySelector(".invalid-feedback");
      if (fb && campo.validationMessage) fb.textContent = campo.dataset.mensaje || campo.validationMessage;
      if (campo.dataset.tocado) campo.classList.toggle("is-invalid", !campo.checkValidity());
      campo.classList.toggle("is-valid", !!campo.dataset.tocado && campo.checkValidity() && campo.value !== "");
    };
    form.querySelectorAll("input, select, textarea").forEach((c) => {
      // Celular: solo números, máximo 9 dígitos
      if (c.dataset.tipo === "celular") {
        c.addEventListener("input", () => {
          let v = c.value.replace(/\D/g, "");
          if (v.startsWith("51") && v.length > 9) v = v.slice(2);        // pegaron +51987...
          if (v && v[0] !== "9") {                                       // en Perú empieza con 9
            v = v.replace(/^[^9]+/, "");
            c.dataset.tocado = "1";
            c.dataset.inicioMal = "1";
          } else if (v) {
            delete c.dataset.inicioMal;
          }
          c.value = v.slice(0, 9);
        });
      }
      c.addEventListener("input", () => revisar(c));
      c.addEventListener("blur", () => { c.dataset.tocado = "1"; revisar(c); });
    });
    form.addEventListener("submit", () => form.querySelectorAll("input, select, textarea").forEach((c) => { c.dataset.tocado = "1"; revisar(c); }), true);
    form.addEventListener("reset", () => setTimeout(() => form.querySelectorAll(".is-valid, .is-invalid").forEach((c) => {
      c.classList.remove("is-valid", "is-invalid"); delete c.dataset.tocado; c.setCustomValidity("");
    })));
  }

  return { sesion, api, ErrorApi, aviso, esc, estado, prioridad, num, hora, fecha, hoyISO, cargando, vacio, conCarga, iconos, mapa, COLOR_ESTADO, ESTADO_VEHICULO, estadoVehiculo, validarEnVivo, enVivo };
})();

/* ---------------- Protección de páginas por rol ---------------- */
(function proteger() {
  const permitidos = document.body.dataset.roles;
  if (!permitidos) return;
  const u = OR.sesion.usuario();
  if (!u) { window.location.replace("/login/?siguiente=" + encodeURIComponent(location.pathname)); return; }
  if (!permitidos.split(",").includes(u.rol)) {
    window.location.replace(u.rol === "CONDUCTOR" ? "/app/conductor/" : "/app/dashboard/");
  }
})();
