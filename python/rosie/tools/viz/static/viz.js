(() => {
  const canvas = document.getElementById("canvas");
  const ctx = canvas.getContext("2d");
  const robotList = document.getElementById("robot-list");
  const detailBody = document.getElementById("detail-body");
  const meta = document.getElementById("meta");
  const cameraImg = document.getElementById("camera");
  const bagSection = document.getElementById("bag-section");
  const bagSlider = document.getElementById("bag-slider");
  const bagTime = document.getElementById("bag-time");
  const bagPlay = document.getElementById("bag-play");
  const bagPause = document.getElementById("bag-pause");
  const bagRate = document.getElementById("bag-rate");

  let state = { robots: {}, selected: null, mode: "live", bag: null };
  let selected = null;
  let follow = true;
  let view = { cx: 0, cy: 0, scale: 80 }; // scale: px per meter
  let dragging = false;
  let lastPan = null;
  let scrubbing = false;

  const COLORS = [
    "#3d9cf0", "#5ecf8e", "#f0b429", "#e86a6a", "#c084fc", "#2dd4bf", "#fb7185",
  ];

  function colorFor(id) {
    let h = 0;
    for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
    return COLORS[h % COLORS.length];
  }

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = Math.floor(rect.width * dpr);
    canvas.height = Math.floor(rect.height * dpr);
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function worldToScreen(x, y) {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    return {
      sx: w / 2 + (x - view.cx) * view.scale,
      sy: h / 2 - (y - view.cy) * view.scale,
    };
  }

  function pickRobot(sx, sy) {
    const hitR = 18;
    let best = null;
    let bestD = hitR;
    for (const id of Object.keys(state.robots)) {
      const r = state.robots[id];
      const p = worldToScreen(r.x, r.y);
      const d = Math.hypot(p.sx - sx, p.sy - sy);
      if (d < bestD) {
        bestD = d;
        best = id;
      }
    }
    return best;
  }

  function fitToRobots() {
    const ids = Object.keys(state.robots);
    if (!ids.length) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const id of ids) {
      const r = state.robots[id];
      minX = Math.min(minX, r.x);
      maxX = Math.max(maxX, r.x);
      minY = Math.min(minY, r.y);
      maxY = Math.max(maxY, r.y);
      for (const [tx, ty] of r.trail || []) {
        minX = Math.min(minX, tx);
        maxX = Math.max(maxX, tx);
        minY = Math.min(minY, ty);
        maxY = Math.max(maxY, ty);
      }
    }
    if (!Number.isFinite(minX)) return;
    const pad = 0.5;
    const dx = Math.max(maxX - minX, 1) + pad * 2;
    const dy = Math.max(maxY - minY, 1) + pad * 2;
    view.cx = (minX + maxX) / 2;
    view.cy = (minY + maxY) / 2;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    view.scale = Math.min(w / dx, h / dy) * 0.85;
  }

  function drawGrid() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    ctx.save();
    ctx.strokeStyle = "rgba(60, 80, 110, 0.35)";
    ctx.lineWidth = 1;
    const step = view.scale >= 40 ? 1 : view.scale >= 15 ? 2 : 5;
    const x0 = view.cx - w / 2 / view.scale;
    const x1 = view.cx + w / 2 / view.scale;
    const y0 = view.cy - h / 2 / view.scale;
    const y1 = view.cy + h / 2 / view.scale;
    const gx0 = Math.floor(x0 / step) * step;
    const gy0 = Math.floor(y0 / step) * step;
    for (let x = gx0; x <= x1; x += step) {
      const { sx } = worldToScreen(x, 0);
      ctx.beginPath();
      ctx.moveTo(sx, 0);
      ctx.lineTo(sx, h);
      ctx.stroke();
    }
    for (let y = gy0; y <= y1; y += step) {
      const { sy } = worldToScreen(0, y);
      ctx.beginPath();
      ctx.moveTo(0, sy);
      ctx.lineTo(w, sy);
      ctx.stroke();
    }
    // axes
    ctx.strokeStyle = "rgba(90, 120, 160, 0.55)";
    const o = worldToScreen(0, 0);
    ctx.beginPath();
    ctx.moveTo(0, o.sy);
    ctx.lineTo(w, o.sy);
    ctx.moveTo(o.sx, 0);
    ctx.lineTo(o.sx, h);
    ctx.stroke();
    ctx.restore();
  }

  function drawRobot(id, r) {
    const color = colorFor(id);
    const trail = r.trail || [];
    if (trail.length > 1) {
      ctx.beginPath();
      ctx.strokeStyle = color + "99";
      ctx.lineWidth = 2;
      trail.forEach(([x, y], i) => {
        const p = worldToScreen(x, y);
        if (i === 0) ctx.moveTo(p.sx, p.sy);
        else ctx.lineTo(p.sx, p.sy);
      });
      ctx.stroke();
    }
    const { sx, sy } = worldToScreen(r.x, r.y);
    const len = 14;
    const theta = -r.theta; // screen y is flipped
    ctx.save();
    ctx.translate(sx, sy);
    ctx.rotate(theta);
    ctx.beginPath();
    ctx.moveTo(len, 0);
    ctx.lineTo(-len * 0.6, len * 0.55);
    ctx.lineTo(-len * 0.6, -len * 0.55);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.globalAlpha = r.stale ? 0.35 : 1;
    ctx.fill();
    if (id === selected) {
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    ctx.restore();
    ctx.globalAlpha = r.stale ? 0.45 : 1;
    ctx.fillStyle = "#e7ecf3";
    ctx.font = "12px IBM Plex Sans, system-ui, sans-serif";
    ctx.fillText(id, sx + 10, sy - 10);
    ctx.globalAlpha = 1;
  }

  function draw() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    ctx.clearRect(0, 0, w, h);
    if (follow) fitToRobots();
    drawGrid();
    const ids = Object.keys(state.robots).sort();
    for (const id of ids) drawRobot(id, state.robots[id]);
    requestAnimationFrame(draw);
  }

  function updateSidebar() {
    const ids = Object.keys(state.robots).sort();
    robotList.innerHTML = "";
    for (const id of ids) {
      const r = state.robots[id];
      const li = document.createElement("li");
      li.textContent = `${id}  ·  ${r.mode || "?"}`;
      if (id === selected) li.classList.add("selected");
      if (r.stale) li.classList.add("stale");
      li.style.borderLeft = `3px solid ${colorFor(id)}`;
      li.addEventListener("click", () => {
        selected = id;
        send({ type: "select", robot: id });
        updateSidebar();
      });
      robotList.appendChild(li);
    }
    const fleet = state.fleet ? `fleet ${state.fleet}` : "fleet ?";
    meta.textContent = `${state.mode || "live"} · ${fleet} · ${ids.length} robot(s)`;
    if (selected && state.robots[selected]) {
      const r = state.robots[selected];
      detailBody.textContent = [
        `id: ${selected}`,
        `x: ${Number(r.x).toFixed(3)} m`,
        `y: ${Number(r.y).toFixed(3)} m`,
        `θ: ${Number(r.theta).toFixed(3)} rad`,
        `mode: ${r.mode}`,
        r.dist != null ? `dist: ${Number(r.dist).toFixed(3)} m` : null,
        r.goal_id != null ? `goal_id: ${r.goal_id}` : null,
        r.navigating != null ? `navigating: ${r.navigating}` : null,
      ].filter(Boolean).join("\n");
    } else {
      detailBody.textContent = "—";
    }
    if (state.jpeg) {
      cameraImg.src = `data:image/jpeg;base64,${state.jpeg}`;
    }
    if (state.mode === "bag" && state.bag) {
      bagSection.classList.remove("hidden");
      if (!scrubbing) {
        bagSlider.min = state.bag.t_min;
        bagSlider.max = state.bag.t_max;
        bagSlider.value = state.bag.t;
      }
      const span = state.bag.t_max - state.bag.t_min;
      const rel = span > 0 ? (state.bag.t - state.bag.t_min) : 0;
      bagTime.textContent = `${rel.toFixed(2)}s / ${span.toFixed(2)}s` +
        (state.bag.paused ? " (paused)" : "");
    } else {
      bagSection.classList.add("hidden");
    }
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  let ws;
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { meta.textContent = "connected"; };
    ws.onclose = () => {
      meta.textContent = "disconnected — retrying…";
      setTimeout(connect, 1000);
    };
    ws.onmessage = (ev) => {
      try {
        state = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (state.selected && !selected) selected = state.selected;
      updateSidebar();
    };
  }

  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    follow = false;
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    view.scale = Math.min(500, Math.max(8, view.scale * factor));
  }, { passive: false });

  let panMoved = false;
  canvas.addEventListener("pointerdown", (e) => {
    dragging = true;
    panMoved = false;
    lastPan = { x: e.clientX, y: e.clientY };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!dragging || !lastPan) return;
    const dx = e.clientX - lastPan.x;
    const dy = e.clientY - lastPan.y;
    if (!panMoved && Math.hypot(dx, dy) <= 3) return;
    panMoved = true;
    follow = false;
    lastPan = { x: e.clientX, y: e.clientY };
    view.cx -= dx / view.scale;
    view.cy += dy / view.scale;
  });
  canvas.addEventListener("pointerup", (e) => {
    if (dragging && !panMoved) {
      const rect = canvas.getBoundingClientRect();
      const id = pickRobot(e.clientX - rect.left, e.clientY - rect.top);
      if (id) {
        selected = id;
        send({ type: "select", robot: id });
        updateSidebar();
      }
    }
    dragging = false;
    lastPan = null;
  });
  canvas.addEventListener("dblclick", () => { follow = true; });

  bagPlay.addEventListener("click", () => send({ type: "bag_cmd", cmd: "play" }));
  bagPause.addEventListener("click", () => send({ type: "bag_cmd", cmd: "pause" }));
  bagRate.addEventListener("change", () => {
    send({ type: "bag_cmd", cmd: "rate", rate: Number(bagRate.value) || 1 });
  });
  bagSlider.addEventListener("pointerdown", () => { scrubbing = true; });
  bagSlider.addEventListener("pointerup", () => {
    scrubbing = false;
    send({ type: "bag_cmd", cmd: "seek", t: Number(bagSlider.value) });
  });
  bagSlider.addEventListener("change", () => {
    send({ type: "bag_cmd", cmd: "seek", t: Number(bagSlider.value) });
  });

  window.addEventListener("resize", resize);
  resize();
  connect();
  requestAnimationFrame(draw);
})();
