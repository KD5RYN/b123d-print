/* b123d-print 3D viewer. MIT, b123d-print contributors. three.js (MIT, its own notice) is in
   three.bundle.min.js, loaded before this file as the global B123D_THREE.

   The model is data, never code: piece names are shown with textContent only, the loader may
   fetch nothing on the model's behalf (blob: images inside the GLB aside), and the page's CSP
   allows scripts from the server (or these exact inline scripts) only. */
(() => {
  "use strict";
  const T = window.B123D_THREE;
  const $ = (id) => document.getElementById(id);
  const fmt = (v) => (Math.abs(v) < 0.005 ? 0 : v).toFixed(2);

  function status(msg, bad) {
    const s = $("status");
    s.textContent = msg || "";
    s.hidden = !msg;
    s.classList.toggle("bad", !!bad);
  }

  if (!T) {
    status("The viewer library did not load.", true);
    return;
  }

  // ---------------------------------------------------------------------------------------
  // where the model comes from: embedded (the offline file) or the GLB next to this link

  function modelSource() {
    const embedded = $("b123d-model");
    if (embedded) {
      const bin = atob(embedded.textContent.trim());
      const buf = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
      return Promise.resolve(buf.buffer);
    }
    // /view/<workspace>/<token>/<part>/<stem>: the model is <stem>.glb under the same token
    const stem = location.pathname.split("/").pop();
    if (!stem) return Promise.reject(new Error("This link names no model."));
    const title = decodeURIComponent(stem).replace(/_view$/, "");
    $("title").textContent = title;
    document.title = title + " · 3D view";
    return fetch(stem + ".glb", { credentials: "omit", redirect: "error", cache: "no-store" }).then((r) => {
      if (r.status === 410) throw new Error("This link has expired: export the part again for a fresh one.");
      if (!r.ok) throw new Error(`The model could not be loaded (HTTP ${r.status}).`);
      return r.arrayBuffer();
    });
  }

  // ---------------------------------------------------------------------------------------
  // scene

  const canvas = $("view");
  const renderer = new T.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.localClippingEnabled = true;
  const scene = new T.Scene();
  const css = getComputedStyle(document.body);
  scene.background = new T.Color(css.getPropertyValue("--scene").trim() || "#eef1f4");
  const camera = new T.PerspectiveCamera(35, 1, 0.1, 100000);
  scene.add(camera);
  scene.add(new T.HemisphereLight(0xffffff, 0x8a8f99, 2.0));
  const sun = new T.DirectionalLight(0xffffff, 2.2);
  sun.position.set(0.6, 1.0, 0.8);
  camera.add(sun); // the light follows the camera: every side is lit as it turns toward you
  const controls = new T.OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.screenSpacePanning = true;

  // three.js is Y-up like glTF; the part is Z-up with the bed at Z = 0. CAD (x, y, z) = three (x, -z, y).
  const cad = (v) => [v.x, -v.z, v.y];

  const cut = new T.Plane(new T.Vector3(-1, 0, 0), 0);
  const planes = [];
  const pieces = []; // { name, object, color, box }
  let bed = null, boxHelper = null, edges = [];

  function resize() {
    const r = canvas.parentElement.getBoundingClientRect();
    renderer.setSize(Math.max(1, r.width), Math.max(1, r.height), false);
    camera.aspect = Math.max(1, r.width) / Math.max(1, r.height);
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(canvas.parentElement);
  resize();

  (function loop() {
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  })();

  // ---------------------------------------------------------------------------------------
  // the model

  function visibleBox() {
    const b = new T.Box3();
    for (const p of pieces) if (p.object.visible) b.union(p.box);
    return b;
  }

  function showDims() {
    const b = visibleBox();
    const out = $("dims");
    if (b.isEmpty()) {
      out.textContent = "Nothing shown.";
      return;
    }
    const s = cad(b.getSize(new T.Vector3()));
    const lo = cad(b.min), hi = cad(b.max);
    out.textContent = `${fmt(s[0])} × ${fmt(Math.abs(s[1]))} × ${fmt(s[2])} mm (X × Y × Z)`;
    $("extent").textContent =
      `X ${fmt(lo[0])} … ${fmt(hi[0])}, Y ${fmt(Math.min(lo[1], hi[1]))} … ${fmt(Math.max(lo[1], hi[1]))}, ` +
      `Z ${fmt(lo[2])} … ${fmt(hi[2])} mm`;
    if (boxHelper) {
      boxHelper.box.copy(b);
      boxHelper.visible = $("show-box").checked;
    }
    setCutRange();
  }

  function pieceSize(box) {
    const s = cad(box.getSize(new T.Vector3()));
    return `${fmt(s[0])} × ${fmt(Math.abs(s[1]))} × ${fmt(s[2])} mm`;
  }

  function listPieces() {
    const ul = $("pieces");
    ul.replaceChildren();
    pieces.forEach((p) => {
      const li = document.createElement("li");
      const label = document.createElement("label");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = true;
      box.addEventListener("change", () => {
        p.object.visible = box.checked;
        showDims();
      });
      const sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.backgroundColor = "#" + p.color.getHexString();
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = p.name; // a name from the part script: text, never markup
      const size = document.createElement("span");
      size.className = "size";
      size.textContent = pieceSize(p.box);
      label.append(box, sw, name);
      li.append(label, size);
      ul.append(li);
    });
    $("pieces-count").textContent = String(pieces.length);
  }

  function addBed(box) {
    // a grid on Z = 0 (10 mm squares) under the footprint, and a faint plate
    const c = box.getCenter(new T.Vector3());
    const s = box.getSize(new T.Vector3());
    const size = Math.max(50, Math.ceil((Math.max(s.x, s.z) * 1.5) / 10) * 10);
    bed = new T.Group();
    const grid = new T.GridHelper(size, size / 10, 0x7d8590, 0xb4bac3);
    grid.material.transparent = true;
    grid.material.opacity = 0.7;
    const plate = new T.Mesh(
      new T.PlaneGeometry(size, size),
      new T.MeshBasicMaterial({ color: 0x9aa3ad, transparent: true, opacity: 0.18, depthWrite: false, side: T.DoubleSide })
    );
    plate.rotation.x = -Math.PI / 2;
    plate.position.y = -0.02;
    bed.add(grid, plate);
    bed.position.set(Math.round(c.x / 10) * 10, 0, Math.round(c.z / 10) * 10);
    scene.add(bed);
  }

  function nameOf(obj, i, gltf) {
    // GLTFLoader rewrites node names for animation paths (spaces -> "_"); show the file's own
    const a = gltf.parser.associations.get(obj);
    const node = a && a.nodes !== undefined ? (gltf.parser.json.nodes || [])[a.nodes] : null;
    const raw = node && typeof node.name === "string" ? node.name : obj.name;
    return raw ? String(raw).slice(0, 200) : `piece ${i + 1}`;
  }

  function prepare(root, gltf) {
    // descend through unnamed wrapper nodes (the Z-up -> Y-up rotation) to the named pieces
    let top = root;
    while (top.children.length === 1 && !top.children[0].isMesh && !top.children[0].name) top = top.children[0];
    const list = top.children.length ? top.children : [top];
    list.forEach((obj, i) => {
      let color = null;
      obj.traverse((o) => {
        if (!o.isMesh) return;
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        for (const m of mats) {
          m.side = T.DoubleSide;
          m.clippingPlanes = planes;
          m.polygonOffset = true;
          m.polygonOffsetFactor = 1;
          m.polygonOffsetUnits = 1;
          if (!color && m.color) color = m.color.clone();
        }
        const e = new T.LineSegments(
          new T.EdgesGeometry(o.geometry, 25),
          new T.LineBasicMaterial({ color: 0x1f2328, transparent: true, opacity: 0.55, clippingPlanes: planes })
        );
        o.add(e);
        edges.push(e);
      });
      obj.updateMatrixWorld(true);
      pieces.push({ name: nameOf(obj, i, gltf), object: obj, color: color || new T.Color(0x4c8cd9),
                    box: new T.Box3().setFromObject(obj) });
    });
  }

  // ---------------------------------------------------------------------------------------
  // section (clipping plane)

  function setCutRange() {
    const axis = $("cut-axis").value;
    const slider = $("cut-at");
    slider.disabled = axis === "off";
    $("cut-flip").disabled = axis === "off";
    if (axis === "off") {
      planes.length = 0;
      $("cut-value").textContent = "";
      return;
    }
    const b = visibleBox();
    if (b.isEmpty()) return;
    const i = { x: 0, y: 1, z: 2 }[axis];
    const lo = cad(b.min)[i], hi = cad(b.max)[i];
    const min = Math.min(lo, hi), max = Math.max(lo, hi);
    slider.min = String(min);
    slider.max = String(max);
    slider.step = String(Math.max(0.01, (max - min) / 400));
    if (slider.dataset.axis !== axis) {
      slider.value = String((min + max) / 2);
      slider.dataset.axis = axis;
    }
    applyCut();
  }

  function applyCut() {
    const axis = $("cut-axis").value;
    if (axis === "off") return;
    const at = parseFloat($("cut-at").value);
    const sign = $("cut-flip").checked ? -1 : 1;
    // keep the side away from the iso camera (X <= at, Y >= at, Z <= at; flip: the other side),
    // so the cut face looks at you; three: x = X, y = Z, z = -Y. Kept: normal . p + constant >= 0
    const [nx, ny, nz, c] = { x: [-1, 0, 0, 1], y: [0, 0, -1, -1], z: [0, -1, 0, 1] }[axis];
    cut.normal.set(nx * sign, ny * sign, nz * sign);
    cut.constant = c * at * sign;
    if (!planes.length) planes.push(cut);
    $("cut-value").textContent = `${axis.toUpperCase()} = ${fmt(at)} mm`;
  }

  // ---------------------------------------------------------------------------------------
  // camera

  function look(dir) {
    const b = visibleBox();
    if (b.isEmpty()) return;
    const c = b.getCenter(new T.Vector3());
    const r = b.getBoundingSphere(new T.Sphere()).radius || 10;
    const half = T.MathUtils.degToRad(camera.fov / 2); // vertical; on a narrow screen the horizontal one is smaller
    const dist = (r / Math.sin(Math.min(half, Math.atan(Math.tan(half) * camera.aspect)))) * 1.1;
    const d = new T.Vector3(...dir).normalize();
    camera.position.copy(c).addScaledVector(d, dist);
    camera.near = Math.max(0.05, dist / 1000);
    camera.far = dist * 100;
    camera.updateProjectionMatrix();
    controls.target.copy(c);
    controls.update();
  }

  // three-space directions: iso = CAD (1, -1, 1), top = +Z, front = -Y, right = +X
  const VIEWS = { iso: [1, 1, 1], top: [0, 1, 0.0001], front: [0, 0, 1], right: [1, 0, 0] };

  // ---------------------------------------------------------------------------------------
  // wire up

  function onLoaded(gltf) {
    const root = new T.Group();
    root.scale.setScalar(1000); // glTF is in meters; everything here is in mm
    root.add(gltf.scene);
    scene.add(root);
    root.updateMatrixWorld(true);
    prepare(gltf.scene, gltf);
    if (!pieces.length) throw new Error("The model has no pieces.");
    const all = visibleBox();
    addBed(all);
    boxHelper = new T.Box3Helper(all.clone(), 0xd1242f);
    boxHelper.visible = false;
    scene.add(boxHelper);
    let tris = 0;
    root.traverse((o) => {
      if (o.isMesh && o.geometry) tris += (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count) / 3;
    });
    $("tris").textContent = `${Math.round(tris).toLocaleString()} triangles`;
    listPieces();
    showDims();
    look(VIEWS.iso);
    status("");
  }

  $("show-bed").addEventListener("change", (e) => bed && (bed.visible = e.target.checked));
  $("show-box").addEventListener("change", (e) => boxHelper && (boxHelper.visible = e.target.checked));
  $("show-edges").addEventListener("change", (e) => edges.forEach((l) => (l.visible = e.target.checked)));
  $("cut-axis").addEventListener("change", setCutRange);
  $("cut-at").addEventListener("input", applyCut);
  $("cut-flip").addEventListener("change", applyCut);
  for (const [name, dir] of Object.entries(VIEWS)) $("view-" + name).addEventListener("click", () => look(dir));

  const manager = new T.LoadingManager();
  // the GLB is loaded from memory: any other URL it names is refused (no requests for the model)
  manager.setURLModifier((url) => (url.startsWith("blob:") ? url : "data:,refused"));
  const loader = new T.GLTFLoader(manager);
  modelSource()
    .then((buffer) => new Promise((ok, fail) => loader.parse(buffer, "", ok, fail)))
    .then(onLoaded)
    .catch((e) => status(e && e.message ? e.message : String(e), true));
})();
