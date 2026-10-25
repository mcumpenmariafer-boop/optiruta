/* ==========================================================================
   Escena del login: mini-optimizador interactivo.
   - Los puntos de entrega y el almacén se pueden arrastrar.
   - Doble clic agrega un punto (máximo 12); clic derecho sobre un punto lo quita.
   - Cada cambio recalcula la ruta con Vecino Más Cercano + 2-opt (el mismo
     algoritmo del backend, simplificado) y los camiones la recorren.
   ========================================================================== */
(() => {
  const svg = document.getElementById("lienzo");
  if (!svg) return;
  const NS = "http://www.w3.org/2000/svg";
  const KM_POR_PX = 0.011;
  const reducirMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const el = (tag, attrs = {}, padre = null) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (padre) padre.appendChild(n);
    return n;
  };

  let W = 0, H = 0;
  let deposito = null;
  let puntos = [];
  let ordenOptimo = [];
  const capas = {};

  /* ---------------- Algoritmo (versión navegador) ---------------- */
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const longitud = (orden) => {
    if (!orden.length) return 0;
    let d = dist(deposito, orden[0]);
    for (let i = 1; i < orden.length; i++) d += dist(orden[i - 1], orden[i]);
    return d + dist(orden[orden.length - 1], deposito);
  };
  function optimizar(lista) {
    const pendientes = [...lista];
    const ruta = [];
    let actual = deposito;
    while (pendientes.length) {               // Fase 1: vecino más cercano
      let mejor = 0;
      pendientes.forEach((p, i) => { if (dist(actual, p) < dist(actual, pendientes[mejor])) mejor = i; });
      actual = pendientes.splice(mejor, 1)[0];
      ruta.push(actual);
    }
    let mejoro = true;                        // Fase 2: 2-opt
    while (mejoro) {
      mejoro = false;
      for (let i = 0; i < ruta.length - 1; i++) {
        for (let k = i + 1; k < ruta.length; k++) {
          const candidata = [...ruta.slice(0, i), ...ruta.slice(i, k + 1).reverse(), ...ruta.slice(k + 1)];
          if (longitud(candidata) < longitud(ruta) - 0.01) { ruta.splice(0, ruta.length, ...candidata); mejoro = true; }
        }
      }
    }
    return ruta;
  }

  /* ---------------- Dibujo ---------------- */
  function calles() {
    capas.calles.innerHTML = "";
    const paso = 96;
    for (let x = -paso; x < W + paso; x += paso) {
      el("line", { x1: x, y1: 0, x2: x + 60, y2: H, stroke: "rgba(255,255,255,.045)", "stroke-width": 14 }, capas.calles);
    }
    for (let y = 40; y < H + paso; y += paso) {
      el("line", { x1: 0, y1: y, x2: W, y2: y - 40, stroke: "rgba(255,255,255,.045)", "stroke-width": 14 }, capas.calles);
    }
    // dos avenidas principales con línea central discontinua
    const av = [`M ${-20} ${H * 0.82} C ${W * 0.3} ${H * 0.6}, ${W * 0.55} ${H * 0.95}, ${W + 20} ${H * 0.55}`,
                `M ${W * 0.62} ${-20} C ${W * 0.55} ${H * 0.35}, ${W * 0.85} ${H * 0.55}, ${W * 0.78} ${H + 20}`];
    av.forEach((d) => {
      el("path", { d, fill: "none", stroke: "rgba(255,255,255,.07)", "stroke-width": 26 }, capas.calles);
      el("path", { d, fill: "none", stroke: "rgba(245,180,0,.22)", "stroke-width": 2, "stroke-dasharray": "14 12" }, capas.calles);
    });
  }

  function rutaD(orden) {
    if (!orden.length) return "";
    return `M ${deposito.x} ${deposito.y} ` + orden.map((p) => `L ${p.x} ${p.y}`).join(" ") + ` L ${deposito.x} ${deposito.y}`;
  }

  function recalcular() {
    ordenOptimo = optimizar(puntos);
    capas.manual.setAttribute("d", rutaD(puntos));
    capas.optima.setAttribute("d", rutaD(ordenOptimo));
    capas.optimaBorde.setAttribute("d", rutaD(ordenOptimo));
    ordenOptimo.forEach((p, i) => { p.etiqueta.textContent = i + 1; });
    const kmM = longitud(puntos) * KM_POR_PX, kmO = longitud(ordenOptimo) * KM_POR_PX;
    const fmt = (n) => n.toLocaleString("es-PE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    document.getElementById("km-manual").textContent = fmt(kmM);
    document.getElementById("km-opt").textContent = fmt(kmO);
    document.getElementById("km-ahorro").textContent = kmM ? `${Math.max(0, Math.round(100 * (kmM - kmO) / kmM))}%` : "0%";
  }

  function crearPin(p) {
    const g = el("g", { class: "pin", tabindex: 0, role: "button", "aria-label": "Punto de entrega arrastrable", style: "cursor:grab" }, capas.pines);
    el("ellipse", { cx: 0, cy: 2, rx: 9, ry: 3.5, fill: "rgba(0,0,0,.3)" }, g);
    el("path", { d: "M0 0 C -4 -8, -14 -14, -14 -24 A 14 14 0 1 1 14 -24 C 14 -14, 4 -8, 0 0 Z", fill: "#fff", stroke: "#14324F", "stroke-width": 2 }, g);
    p.etiqueta = el("text", { x: 0, y: -19, "text-anchor": "middle", "font-family": "Barlow Condensed", "font-weight": 700, "font-size": 15, fill: "#14324F" }, g);
    p.g = g;
    mover(p);
    arrastrable(g, p);
    g.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      if (puntos.length <= 3) return;
      puntos = puntos.filter((q) => q !== p);
      g.remove();
      recalcular();
    });
  }

  function crearDeposito() {
    const g = el("g", { style: "cursor:grab", role: "button", "aria-label": "Almacén arrastrable" }, capas.pines);
    el("rect", { x: -17, y: -17, width: 34, height: 34, rx: 5, fill: "#F5B400", stroke: "#0E2438", "stroke-width": 3, transform: "rotate(45)" }, g);
    el("path", { d: "M -8 3 L 0 -6 L 8 3 L 8 9 L -8 9 Z", fill: "#0E2438" }, g);
    deposito.g = g;
    mover(deposito);
    arrastrable(g, deposito);
  }

  const mover = (p) => p.g.setAttribute("transform", `translate(${p.x} ${p.y})`);

  function arrastrable(g, p) {
    g.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      g.setPointerCapture(e.pointerId);
      g.style.cursor = "grabbing";
      const mov = (ev) => {
        const r = svg.getBoundingClientRect();
        p.x = Math.min(W - 16, Math.max(16, ev.clientX - r.left));
        p.y = Math.min(H - (W < 700 ? 80 : 10), Math.max(40, ev.clientY - r.top));
        mover(p);
        recalcular();
      };
      const fin = () => { g.style.cursor = "grab"; g.removeEventListener("pointermove", mov); g.removeEventListener("pointerup", fin); };
      g.addEventListener("pointermove", mov);
      g.addEventListener("pointerup", fin);
    });
    // Accesible con teclado: flechas mueven el punto
    g.addEventListener("keydown", (e) => {
      const d = { ArrowLeft: [-12, 0], ArrowRight: [12, 0], ArrowUp: [0, -12], ArrowDown: [0, 12] }[e.key];
      if (!d) return;
      e.preventDefault();
      p.x += d[0]; p.y += d[1]; mover(p); recalcular();
    });
  }

  function crearCamion() {
    const g = el("g", {}, capas.camiones);
    el("rect", { x: -13, y: -8, width: 18, height: 16, rx: 2.5, fill: "#F5B400" }, g);
    el("rect", { x: 5, y: -6, width: 9, height: 12, rx: 2.5, fill: "#fff" }, g);
    el("rect", { x: 9, y: -4.5, width: 4, height: 9, rx: 1, fill: "#2F80ED" }, g);
    return { g, avance: Math.random() };
  }

  /* ---------------- Inicio ---------------- */
  function construir() {
    const r = svg.getBoundingClientRect();
    const anteriorW = W || r.width, anteriorH = H || r.height;
    W = r.width; H = r.height;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    if (!capas.calles) {
      capas.calles = el("g", {}, svg);
      capas.manual = el("path", { fill: "none", stroke: "rgba(159,180,200,.45)", "stroke-width": 2, "stroke-dasharray": "3 7", "stroke-linecap": "round" }, svg);
      capas.optimaBorde = el("path", { fill: "none", stroke: "rgba(245,180,0,.18)", "stroke-width": 14, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      capas.optima = el("path", { fill: "none", stroke: "#F5B400", "stroke-width": 4, "stroke-linejoin": "round", "stroke-linecap": "round", "stroke-dasharray": "16 10" }, svg);
      capas.camiones = el("g", {}, svg);
      capas.pines = el("g", {}, svg);
      const movil = W < 700;
      deposito = { x: W * (movil ? 0.62 : 0.6), y: H * (movil ? 0.5 : 0.6) };
      crearDeposito();
      const semillas = movil
        ? [[.62, .18], [.9, .3], [.42, .62], [.88, .62], [.15, .58], [.75, .42]]
        : [[.48, .78], [.82, .3], [.7, .82], [.92, .62], [.38, .6], [.58, .38], [.86, .9], [.3, .88]];
      semillas.forEach(([fx, fy]) => { const p = { x: W * fx, y: H * fy }; puntos.push(p); crearPin(p); });
      svg.addEventListener("dblclick", (e) => {
        if (puntos.length >= 12) return;
        const rr = svg.getBoundingClientRect();
        const p = { x: e.clientX - rr.left, y: e.clientY - rr.top };
        puntos.push(p); crearPin(p); recalcular();
      });
      capas.lista = [crearCamion(), crearCamion()];
    } else {
      // reescalar posiciones al cambiar el tamaño
      [deposito, ...puntos].forEach((p) => { p.x *= W / anteriorW; p.y *= H / anteriorH; mover(p); });
    }
    calles();
    recalcular();
  }

  let ultimo = performance.now();
  let desplazamiento = 0;
  function animar(t) {
    const dt = Math.min(64, t - ultimo); ultimo = t;
    const largo = capas.optima.getTotalLength();
    desplazamiento -= dt * 0.03;
    capas.optima.setAttribute("stroke-dashoffset", desplazamiento);
    if (largo > 0) {
      capas.lista.forEach((c, i) => {
        c.avance = (c.avance + dt * 0.00006 * (900 / largo) * (i ? 1.15 : 1)) % 1;
        const s = c.avance * largo;
        const a = capas.optima.getPointAtLength(s);
        const b = capas.optima.getPointAtLength(Math.min(largo, s + 2));
        const ang = Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI;
        c.g.setAttribute("transform", `translate(${a.x} ${a.y}) rotate(${ang})`);
      });
    }
    if (!reducirMovimiento) requestAnimationFrame(animar);
  }

  construir();
  window.addEventListener("resize", () => { clearTimeout(window.__rz); window.__rz = setTimeout(construir, 150); });
  requestAnimationFrame(animar);
})();
