// Metro de Madrid bajo tierra — visor 3D
// Datos: GTFS oficial del CRTM (Red de Metro). Ver scripts/build_datos.py

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';

const $ = (s) => document.querySelector(s);
const lienzo = $('#lienzo');
const velo = $('#velo');
const M_PER_DEG = 111320;
// Escala vertical exagerada: a escala real 30 m de túnel son invisibles en 50 km de ciudad
const EXAG = 200;

// ————————————————————————————— estado —————————————————————————————
const estado = {
  datos: null,
  centro: { lat: 40.42, lon: -3.7 },
  lineas: new Map(),      // id -> {meta, visible}
  horaBase: 0,            // segundos desde medianoche
  t0: performance.now(),
  velocidad: 1,
  trenes: [],
  seleccion: null,
  superficie: null,
  opacidadSuperficie: 0.95,
};

// ————————————————————————————— escena —————————————————————————————
const escena = new THREE.Scene();
escena.fog = new THREE.FogExp2(0x05060a, 0.000012);

const camara = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 10, 400000);
camara.position.set(0, 46000, 1000);

const renderer = new THREE.WebGLRenderer({ canvas: lienzo, antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.setClearColor(0x05060a, 1);

const controles = new OrbitControls(camara, renderer.domElement);
controles.enableDamping = true;
controles.dampingFactor = 0.06;
controles.maxPolarAngle = Math.PI / 2 - 0.02;
controles.minDistance = 900;
controles.maxDistance = 120000;
controles.zoomSpeed = 0.9;
controles.panSpeed = 1.1;

escena.add(new THREE.HemisphereLight(0xffffff, 0x080810, 1.1));
const luz = new THREE.DirectionalLight(0xffffff, 0.9);
luz.position.set(0.4, 1, 0.6);
escena.add(luz);

// ————————————————————————————— proyección —————————————————————————————
let escala = 1;
function aMundo(lat, lon) {
  const x = (lon - estado.centro.lon) * M_PER_DEG * Math.cos(estado.centro.lat * Math.PI / 180);
  const z = -(lat - estado.centro.lat) * M_PER_DEG;
  return [x * escala, z * escala];
}

// ————————————————————————————— superficie (teselas) —————————————————————————————
function lon2tile(lon, z) { return Math.floor((lon + 180) / 360 * 2 ** z); }
function lat2tile(lat, z) {
  const r = lat * Math.PI / 180;
  return Math.floor((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * 2 ** z);
}
function tile2lon(x, z) { return x / 2 ** z * 360 - 180; }
function tile2lat(y, z) {
  const n = Math.PI - 2 * Math.PI * y / 2 ** z;
  return 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}

async function construirSuperficie(bbox) {
  const { minLat, maxLat, minLon, maxLon } = bbox;
  let z = 13;
  for (; z > 9; z--) {
    const nx = lon2tile(maxLon, z) - lon2tile(minLon, z) + 1;
    const ny = lat2tile(minLat, z) - lat2tile(maxLat, z) + 1;
    if (nx * ny <= 36) break;
  }
  const x0 = lon2tile(minLon, z), x1 = lon2tile(maxLon, z);
  const y0 = lat2tile(maxLat, z), y1 = lat2tile(minLat, z);
  const nx = x1 - x0 + 1, ny = y1 - y0 + 1;
  const tile = 256;
  const cv = document.createElement('canvas');
  cv.width = nx * tile;
  cv.height = ny * tile;
  const ctx = cv.getContext('2d');
  ctx.fillStyle = '#0a0b0f';
  ctx.fillRect(0, 0, cv.width, cv.height);

  const trabajos = [];
  for (let ty = y0; ty <= y1; ty++) {
    for (let tx = x0; tx <= x1; tx++) {
      const url = `https://tile.openstreetmap.org/${z}/${tx}/${ty}.png`;
      trabajos.push(cargarTile(url).then((img) => {
        if (!img) return;
        ctx.save();
        ctx.filter = 'grayscale(1) invert(1) contrast(1.15) brightness(1)';
        ctx.drawImage(img, (tx - x0) * tile, (ty - y0) * tile, tile, tile);
        ctx.restore();
      }).catch(() => {}));
    }
  }
  await Promise.all(trabajos);

  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  tex.minFilter = THREE.LinearMipmapLinearFilter;

  // georreferencia del lienzo: esquinas del bloque de teselas
  const lonA = tile2lon(x0, z), lonB = tile2lon(x1 + 1, z);
  const latA = tile2lat(y0, z), latB = tile2lat(y1 + 1, z);
  const [x1m, z1m] = aMundo(latA, lonA);
  const [x2m, z2m] = aMundo(latB, lonB);
  const ancho = Math.abs(x2m - x1m), alto = Math.abs(z2m - z1m);

  const geo = new THREE.PlaneGeometry(ancho, alto, 1, 1);
  const mat = new THREE.MeshBasicMaterial({
    map: tex, transparent: true, opacity: estado.opacidadSuperficie,
    depthWrite: false, side: THREE.DoubleSide, color: 0xffffff,
  });
  const plano = new THREE.Mesh(geo, mat);
  plano.rotation.x = -Math.PI / 2;
  plano.position.set((x1m + x2m) / 2, 0, (z1m + z2m) / 2);
  plano.renderOrder = 2;
  escena.add(plano);
  estado.superficie = plano;

  // bloque de terreno bajo la superficie: da volumen al diorama
  const profMax = Math.max(...[...estado.lineas.values()].map((l) => l.meta.depth)) * EXAG;
  const caja = new THREE.Mesh(
    new THREE.BoxGeometry(ancho, profMax * 1.15, alto),
    new THREE.MeshBasicMaterial({
      color: 0x0e1622, transparent: true, opacity: 0.32,
      depthWrite: false, side: THREE.DoubleSide,
    })
  );
  caja.position.set(plano.position.x, -profMax * 1.15 / 2, plano.position.z);
  caja.renderOrder = -2;
  escena.add(caja);
  const aristas = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(ancho, profMax * 1.15, alto)),
    new THREE.LineBasicMaterial({ color: 0x39485c, transparent: true, opacity: 0.55 })
  );
  aristas.position.copy(caja.position);
  escena.add(aristas);

  // marco del plano: da la lectura de «corte» sin gradientes
  // eje de profundidad: escala vertical en el borde oeste del diorama
  const xEje = plano.position.x + ancho / 2 - 900;
  const zEje = plano.position.z - alto / 2 + 1200;
  const matEje = new THREE.LineBasicMaterial({ color: 0x8ea0bd, transparent: true, opacity: 0.5, depthTest: false });
  const ejePts = [new THREE.Vector3(xEje, 0, zEje), new THREE.Vector3(xEje, -profMax * 1.05, zEje)];
  const eje = new THREE.Line(new THREE.BufferGeometry().setFromPoints(ejePts), matEje);
  eje.renderOrder = 7;
  escena.add(eje);
  for (let m = 10; m <= 40; m += 10) {
    const y = -m * EXAG;
    const tick = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(xEje, y, zEje), new THREE.Vector3(xEje + 900, y, zEje)]),
      matEje);
    tick.renderOrder = 7;
    escena.add(tick);
    const cv = document.createElement('canvas');
    cv.width = 256; cv.height = 64;
    const cx = cv.getContext('2d');
    cx.fillStyle = 'rgba(255,255,255,0.72)';
    cx.font = '500 34px system-ui, sans-serif';
    cx.textBaseline = 'middle';
    cx.fillText(m + ' m', 8, 34);
    const tex2 = new THREE.CanvasTexture(cv);
    tex2.colorSpace = THREE.SRGBColorSpace;
    const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex2, transparent: true, depthTest: false }));
    spr.scale.set(1600, 400, 1);
    spr.position.set(xEje + 2200, y, zEje);
    spr.renderOrder = 7;
    escena.add(spr);
  }

  const borde = new THREE.LineSegments(
    new THREE.EdgesGeometry(geo),
    new THREE.LineBasicMaterial({ color: 0x2b2f3a, transparent: true, opacity: 0.9 })
  );
  borde.rotation.x = -Math.PI / 2;
  borde.position.copy(plano.position);
  escena.add(borde);
}

function cargarTile(url) {
  return new Promise((res) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => res(img);
    img.onerror = () => res(null);
    img.src = url;
    setTimeout(() => res(img.complete && img.naturalWidth ? img : null), 6000);
  });
}

// ————————————————————————————— red —————————————————————————————
const resolucion = new THREE.Vector2(innerWidth, innerHeight);

// servicio del día (calendar.txt del GTFS): laborable, viernes, sábado o domingo
function serviciosActivos(calendar) {
  const dia = new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Madrid', weekday: 'long' })
    .format(new Date()).toLowerCase();
  const activos = new Set();
  for (const [svc, dias] of Object.entries(calendar || {})) if (dias[dia] === 1) activos.add(svc);
  if (!activos.size) Object.keys(calendar || {}).forEach((k) => activos.add(k));
  return activos;
}

function construirRed() {
  const { lines, shapes, stations } = estado.datos;
  const activos = serviciosActivos(estado.datos.calendar);
  const patterns = estado.datos.patterns.filter((p) => activos.has(p.svc));
  const ETIQUETA = { '4_I12': 'Sábado', '4_I13': 'Domingo y festivo', '4_I14': 'Laborable', '4_I15': 'Viernes' };
  estado.servicio = [...activos].map((s) => ETIQUETA[s] || s).join(', ');
  const colorPorLinea = new Map();

  for (const l of lines) {
    colorPorLinea.set(l.id, new THREE.Color(l.color));
    estado.lineas.set(l.id, { meta: l, visible: true });
  }

  for (const sh of shapes) {
    const pts = sh.pts;
    const grupos = new Map();
    for (const p of patterns) {
      if (p.s !== shapes.indexOf(sh)) continue;
      const depth = estado.lineas.get(p.l).meta.depth;
      const clave = p.l + '|' + depth;
      if (!grupos.has(clave)) grupos.set(clave, { l: p.l, depth, dirs: [] });
      grupos.get(clave).dirs.push(p.d);
    }
    for (const [clave, g] of grupos) {
      const posiciones = [];
      for (const [lat, lon] of pts) {
        const [x, z] = aMundo(lat, lon);
        posiciones.push(x, -g.depth * EXAG, z);
      }
      const geo = new LineGeometry();
      geo.setPositions(posiciones);
      const color = colorPorLinea.get(g.l);
      const mat = new LineMaterial({
        color: color.clone().multiplyScalar(0.95).getHex(),
        linewidth: 2.6,
        resolution: resolucion,
        transparent: true,
        opacity: 0.95,
        depthTest: false,
        blending: THREE.AdditiveBlending,
      });
      const linea = new Line2(geo, mat);
      linea.computeLineDistances();
      linea.renderOrder = 10;
      linea.userData = { tipo: 'linea', id: g.l };
      escena.add(linea);
      (estado.objetosLinea ||= []).push(linea);

      const halo = new LineMaterial({
        color: color.getHex(), linewidth: 12, resolution: resolucion,
        transparent: true, opacity: 0.13, depthWrite: false, depthTest: false,
        blending: THREE.AdditiveBlending,
      });
      const haloLinea = new Line2(geo, halo);
      haloLinea.renderOrder = 9;
      haloLinea.userData = { tipo: 'halo', id: g.l };
      escena.add(haloLinea);
      (estado.objetosLinea ||= []).push(haloLinea);
    }
  }

  // estaciones: disco en superficie + pozo hasta el túnel
  const n = stations.length;
  const discoGeo = new THREE.CylinderGeometry(1, 1, 1, 14);
  const discoMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.32 });
  const discos = new THREE.InstancedMesh(discoGeo, discoMat, n);
  discos.userData.tipo = 'estaciones';

  const pozoGeo = new THREE.CylinderGeometry(1, 1, 1, 10, 1, true);
  const pozoMat = new THREE.MeshBasicMaterial({
    color: 0x8ea0bd, transparent: true, opacity: 0.13, side: THREE.DoubleSide, depthWrite: false, depthTest: false,
  });
  const pozos = new THREE.InstancedMesh(pozoGeo, pozoMat, n);

  const m4 = new THREE.Matrix4();
  stations.forEach((st, i) => {
    const [x, z] = aMundo(st.lat, st.lon);
    st._x = x; st._z = z;
    const prof = Math.max(...st.l.map((id) => estado.lineas.get(id)?.meta.depth ?? 20));
    st._prof = prof;
    m4.compose(
      new THREE.Vector3(x, 0.5, z),
      new THREE.Quaternion(),
      new THREE.Vector3(52, 2, 52)
    );
    discos.setMatrixAt(i, m4);
    m4.compose(
      new THREE.Vector3(x, -prof * EXAG / 2, z),
      new THREE.Quaternion(),
      new THREE.Vector3(26, prof * EXAG, 26)
    );
    pozos.setMatrixAt(i, m4);
  });
  discos.instanceMatrix.needsUpdate = true;
  pozos.instanceMatrix.needsUpdate = true;
  pozos.renderOrder = 8;
  discos.renderOrder = 11;
  escena.add(pozos, discos);
  estado.discos = discos;

  // trenes: puntos de tamaño constante en pantalla (visibles a cualquier zoom)
  const nMax = 1400;
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(nMax * 3);
  const col = new Float32Array(nMax * 3);
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setDrawRange(0, 0);
  const puntos = new THREE.Points(geo, new THREE.PointsMaterial({
    size: 8, sizeAttenuation: false, color: 0xffffff,
    transparent: true, opacity: 0.98, depthWrite: false, depthTest: false,
  }));
  puntos.frustumCulled = false;
  puntos.renderOrder = 12;
  escena.add(puntos);

  const geoHalo = new THREE.BufferGeometry();
  geoHalo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
  geoHalo.setAttribute('color', new THREE.BufferAttribute(col, 3).setUsage(THREE.DynamicDrawUsage));
  geoHalo.setDrawRange(0, 0);
  const halo = new THREE.Points(geoHalo, new THREE.PointsMaterial({
    size: 34, sizeAttenuation: false, vertexColors: true, transparent: true,
    opacity: 0.34, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
  }));
  halo.frustumCulled = false;
  halo.renderOrder = 11;
  escena.add(halo);

  estado.puntosTrenes = puntos;
  estado.haloTrenes = halo;

  // precalcular color de cada patrón
  estado.patrones = patterns.map((p) => ({
    ...p,
    color: colorPorLinea.get(p.l).clone(),
    depth: estado.lineas.get(p.l).meta.depth,
    shape: shapes[p.s],
  }));
}

// ————————————————————————————— simulación —————————————————————————————
function horaMadridSegundos(fecha) {
  const f = new Intl.DateTimeFormat('es-ES', {
    timeZone: 'Europe/Madrid', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  });
  const partes = f.formatToParts(fecha);
  const v = (t) => parseInt(partes.find((p) => p.type === t).value, 10);
  return v('hour') * 3600 + v('minute') * 60 + v('second');
}

function puntoEnShape(shape, s) {
  const cum = shape.cum, pts = shape.pts;
  if (s <= 0) return pts[0];
  if (s >= cum[cum.length - 1]) return pts[pts.length - 1];
  let lo = 0, hi = cum.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (cum[mid] <= s) lo = mid; else hi = mid;
  }
  const span = cum[hi] - cum[lo] || 1;
  const f = (s - cum[lo]) / span;
  return [pts[lo][0] + (pts[hi][0] - pts[lo][0]) * f,
          pts[lo][1] + (pts[hi][1] - pts[lo][1]) * f];
}

const m4 = new THREE.Matrix4();
const q = new THREE.Quaternion();
const v3 = new THREE.Vector3();
const esc = new THREE.Vector3();

function actualizarTrenes(tSeg) {
  const visibles = [];
  const dia = 86400;
  for (const p of estado.patrones) {
    if (!estado.lineas.get(p.l).visible) continue;
    const dur = p.dur;
    for (const [ini, fin, head] of p.w) {
      // ventanas de hoy y de la víspera (trenes que siguen circulando tras medianoche)
      for (const off of [0, -dia]) {
        const iniD = ini + off, finD = fin + off;
        let k = Math.ceil((tSeg - dur - iniD) / head);
        if (k < 0) k = 0;
        for (let s = iniD + k * head; s <= finD && s <= tSeg; s += head) {
          const tt = tSeg - s;
          if (tt < 0 || tt > dur) continue;
          let i = 0;
          while (i + 1 < p.o.length && p.o[i + 1] <= tt) i++;
          const j = Math.min(i + 1, p.o.length - 1);
          const tramo = (p.o[j] - p.o[i]) || 1;
          const f = Math.min(1, Math.max(0, (tt - p.o[i]) / tramo));
          const sDist = p.sp[i] + (p.sp[j] - p.sp[i]) * f;
          const [lat, lon] = puntoEnShape(p.shape, sDist);
          const [x, z] = aMundo(lat, lon);
          visibles.push({ x, z, y: -p.depth * EXAG - 60, color: p.color, linea: p.l });
        }
        if (visibles.length > 1380) break;
      }
    }
  }
  estado.trenes = visibles;

  const n = Math.min(visibles.length, 1400);
  const pos = estado.puntosTrenes.geometry.attributes.position.array;
  const col = estado.puntosTrenes.geometry.attributes.color.array;
  const posH = estado.haloTrenes.geometry.attributes.position.array;
  const colH = estado.haloTrenes.geometry.attributes.color.array;
  for (let i = 0; i < n; i++) {
    const t = visibles[i];
    pos[i * 3] = t.x; pos[i * 3 + 1] = t.y; pos[i * 3 + 2] = t.z;
    posH[i * 3] = t.x; posH[i * 3 + 1] = t.y; posH[i * 3 + 2] = t.z;
    col[i * 3] = t.color.r; col[i * 3 + 1] = t.color.g; col[i * 3 + 2] = t.color.b;
    colH[i * 3] = t.color.r; colH[i * 3 + 1] = t.color.g; colH[i * 3 + 2] = t.color.b;
  }
  const g = estado.puntosTrenes.geometry, gh = estado.haloTrenes.geometry;
  g.setDrawRange(0, n); gh.setDrawRange(0, n);
  g.attributes.position.needsUpdate = true; g.attributes.color.needsUpdate = true;
  gh.attributes.position.needsUpdate = true; gh.attributes.color.needsUpdate = true;
}

// ————————————————————————————— etiquetas —————————————————————————————
const capaEtiquetas = document.createElement('div');
capaEtiquetas.style.cssText = 'position:fixed;inset:0;pointer-events:none;overflow:hidden';
document.body.appendChild(capaEtiquetas);
const etiquetas = new Map();

function crearEtiqueta(st) {
  const d = document.createElement('div');
  d.className = 'etiqueta';
  d.textContent = st.n;
  capaEtiquetas.appendChild(d);
  etiquetas.set(st.id, d);
  return d;
}

function actualizarEtiquetas() {
  const seleccion = estado.seleccion;
  const dist = camara.position.length();
  const cerca = dist < 32000;
  const lista = estado.datos.stations.filter((st) => {
    if (seleccion) return st.l.includes(seleccion);
    return cerca ? st.l.length > 1 : st.l.length > 1;
  }).slice(0, 70);

  const vistas = new Set();
  const ocupadas = [];
  // prioridad: más líneas primero (intercambiadores)
  const orden = [...lista].sort((a, b) => b.l.length - a.l.length);
  for (const st of orden) {
    const d = etiquetas.get(st.id) || crearEtiqueta(st);
    vistas.add(st.id);
    v3.set(st._x, 0, st._z).project(camara);
    const x = (v3.x * 0.5 + 0.5) * innerWidth;
    const y = (-v3.y * 0.5 + 0.5) * innerHeight;
    const dentro = v3.z < 1 && v3.z > -1 && x > 320 && x < innerWidth - 20 && y > 60 && y < innerHeight - 40;
    const choque = ocupadas.some(([ox, oy]) => Math.abs(ox - x) < 92 && Math.abs(oy - y) < 15);
    const visible = dentro && !choque;
    if (visible) ocupadas.push([x, y]);
    d.classList.toggle('is-visible', visible);
    d.style.left = x.toFixed(1) + 'px';
    d.style.top = y.toFixed(1) + 'px';
  }
  for (const [id, d] of etiquetas) if (!vistas.has(id)) d.classList.remove('is-visible');
}

// ————————————————————————————— cámara —————————————————————————————
let transicion = null;
function irA(pos, target, ms = 1300) {
  transicion = {
    desde: camara.position.clone(), hasta: new THREE.Vector3(...pos),
    tDesde: controles.target.clone(), tHasta: new THREE.Vector3(...target),
    inicio: performance.now(), ms,
  };
}

function vista(nombre) {
  const c = estado.centro;
  if (nombre === 'plano') irA([0, 46000, 200], [0, 0, 0], 1400);
  else if (nombre === 'vuelo') irA([-11000, 12000, 15000], [0, -1600, 0], 1400);
  else {
    escena.fog.density = 0.00028;
    irA([900, -2400, 2400], [0, -3000, 0], 1400);
  }
  if (nombre !== 'tunel') escena.fog.density = 0.000012;
}

// ————————————————————————————— interacción —————————————————————————————
const raycaster = new THREE.Raycaster();
const puntero = new THREE.Vector2();

renderer.domElement.addEventListener('pointerdown', (e) => {
  estado._down = { x: e.clientX, y: e.clientY, t: performance.now() };
});
renderer.domElement.addEventListener('pointerup', (e) => {
  const d = estado._down;
  if (!d) return;
  if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 6 || performance.now() - d.t > 600) return;
  puntero.x = (e.clientX / innerWidth) * 2 - 1;
  puntero.y = -(e.clientY / innerHeight) * 2 + 1;
  raycaster.setFromCamera(puntero, camara);
  const hit = raycaster.intersectObject(estado.discos, false)[0];
  if (hit) seleccionar(estado.datos.stations[hit.instanceId]);
  else { estado.seleccion = null; pintarFicha(null); actualizarLineasUI(); }
});

function seleccionar(st) {
  estado.seleccion = st.l[0] ?? null;
  pintarFicha(st);
  actualizarLineasUI();
}

function pintarFicha(st) {
  const f = $('#ficha');
  if (!st) {
    f.innerHTML = '<p class="nota">Pincha una estación en el mapa.</p>';
    return;
  }
  const cercanos = estado.trenes.filter((t) =>
    st.l.includes(t.linea) && Math.hypot(t.x - st._x, t.z - st._z) < 2500).length;
  f.innerHTML = `
    <strong class="ficha__nombre">${st.n}</strong>
    <span class="ficha__meta">${st.l.length > 1 ? 'Correspondencia' : 'Estación'} · pozo de ${Math.round(st._prof)} m (estimado)</span>
    <div class="ficha__lineas">${st.l.map((id) => {
      const m = estado.lineas.get(id)?.meta;
      return `<span class="pastilla" style="--c:${m ? m.color : '#fff'}">${m ? m.name.replace('Línea ', 'L') : id}</span>`;
    }).join('')}</div>
    <span class="ficha__meta">${cercanos} tren${cercanos === 1 ? '' : 'es'} de estas líneas a menos de 2,5 km</span>`;
}

// ————————————————————————————— UI —————————————————————————————
function construirListaLineas() {
  const ul = $('#lineas');
  ul.innerHTML = '';
  for (const [id, { meta }] of estado.lineas) {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.className = 'linea-chip';
    b.dataset.linea = id;
    b.innerHTML = `<span class="linea-chip__color" style="background:${meta.color}"></span>
      <span class="linea-chip__nombre">${id === 'R' ? 'Ramal' : 'L' + id}</span>
      <span>${meta.long}</span>${meta.reconstruida ? '<span class="linea-chip__rec">reconstruida</span>' : ''}`;
    b.addEventListener('click', () => {
      const l = estado.lineas.get(id);
      l.visible = !l.visible;
      aplicarVisibilidad();
      actualizarLineasUI();
    });
    li.appendChild(b);
    ul.appendChild(li);
  }
}

function actualizarLineasUI() {
  document.querySelectorAll('.linea-chip').forEach((b) => {
    const { meta } = estado.lineas.get(b.dataset.linea);
    b.classList.toggle('is-apagada', !estado.lineas.get(b.dataset.linea).visible);
    b.classList.toggle('is-sel', estado.seleccion === meta.id);
  });
}

function aplicarVisibilidad() {
  for (const o of estado.objetosLinea || []) {
    o.visible = estado.lineas.get(o.userData.id).visible;
  }
}

$('#corte').addEventListener('input', (e) => {
  const v = +e.target.value / 100;
  estado.opacidadSuperficie = v;
  $('#corte-val').textContent = Math.round(v * 100) + ' %';
  if (estado.superficie) estado.superficie.material.opacity = v;
  velo.classList.toggle('is-claro', v < 0.4);
});

$('#velocidad').addEventListener('click', (e) => {
  const escala = [1, 60, 300];
  const i = (escala.indexOf(estado.velocidad) + 1) % escala.length;
  estado.velocidad = escala[i];
  e.target.textContent = '×' + estado.velocidad;
});

$('#todas').addEventListener('click', () => {
  for (const l of estado.lineas.values()) l.visible = true;
  aplicarVisibilidad();
  actualizarLineasUI();
});

document.querySelectorAll('[data-vista]').forEach((b) => {
  b.addEventListener('click', () => {
    document.querySelectorAll('[data-vista]').forEach((x) => x.classList.remove('is-active'));
    b.classList.add('is-active');
    vista(b.dataset.vista);
  });
});

$('#plegar').addEventListener('click', (e) => {
  const p = $('#panel');
  const oculto = p.classList.toggle('is-oculto');
  e.currentTarget.setAttribute('aria-expanded', String(!oculto));
  e.currentTarget.querySelector('span').textContent = oculto ? '›' : '‹';
});

// ————————————————————————————— bucle —————————————————————————————
let ultimoTick = 0;
function animar(ahora) {
  requestAnimationFrame(animar);
  const dt = ahora - ultimoTick;
  ultimoTick = ahora;

  if (transicion) {
    const t = Math.min(1, (ahora - transicion.inicio) / transicion.ms);
    const e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
    camara.position.lerpVectors(transicion.desde, transicion.hasta, e);
    controles.target.lerpVectors(transicion.tDesde, transicion.tHasta, e);
    if (t >= 1) transicion = null;
  }

  const tSeg = estado.horaBase + (ahora - estado.t0) / 1000 * estado.velocidad;
  const h = Math.floor(tSeg / 3600) % 24;
  const m = Math.floor(tSeg / 60) % 60;
  $('#reloj').textContent = String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');

  if (ahora - (estado._ultimoTren || 0) > 220) {
    estado._ultimoTren = ahora;
    actualizarTrenes(tSeg % 86400);
    $('#contador').textContent = `${estado.trenes.length} trenes en circulación · ${estado.datos.stations.length} estaciones · ${estado.lineas.size} líneas`;
  }

  actualizarEtiquetas();
  controles.update();
  renderer.render(escena, camara);
}

// ————————————————————————————— arranque —————————————————————————————
async function iniciar() {
  const aviso = document.createElement('div');
  aviso.id = 'aviso-carga';
  aviso.textContent = 'Cargando la red…';
  document.body.appendChild(aviso);

  const datos = await fetch('data/metro.json').then((r) => r.json());
  estado.datos = datos;

  // centro y bbox
  let minLat = 90, maxLat = -90, minLon = 180, maxLon = -180;
  for (const sh of datos.shapes) {
    for (const [la, lo] of sh.pts) {
      if (la < minLat) minLat = la;
      if (la > maxLat) maxLat = la;
      if (lo < minLon) minLon = lo;
      if (lo > maxLon) maxLon = lo;
    }
  }
  estado.centro = { lat: (minLat + maxLat) / 2, lon: (minLon + maxLon) / 2 };
  const anchoKm = (maxLon - minLon) * M_PER_DEG * Math.cos(estado.centro.lat * Math.PI / 180) / 1000;
  escala = anchoKm > 1 ? 1 : 1;

  construirRed();
  construirListaLineas();
  await construirSuperficie({ minLat, maxLat, minLon, maxLon });

  estado.horaBase = horaMadridSegundos(new Date());
  estado.t0 = performance.now();
  actualizarTrenes(estado.horaBase);
  $('#badge-estado').textContent = 'Servicio simulado · ' + estado.servicio;
  aviso.remove();

  window.__mm = estado; // depuración
  controles.target.set(0, -1400, 0);
  irA([0, 15500, 17500], [0, -1400, 0], 2200);
  // el terreno se abre solo: de plano a corte geológico en 2,6 s
  const t0 = performance.now();
  const desde = estado.opacidadSuperficie, hasta = 0.34;
  const fundido = (t) => {
    const k = Math.min(1, (t - t0) / 2600);
    const e = 1 - (1 - k) ** 3;
    const v = desde + (hasta - desde) * e;
    estado.opacidadSuperficie = v;
    if (estado.superficie) estado.superficie.material.opacity = v;
    const sl = $('#corte');
    sl.value = Math.round(v * 100);
    $('#corte-val').textContent = Math.round(v * 100) + ' %';
    velo.classList.toggle('is-claro', v < 0.4);
    if (k < 1) requestAnimationFrame(fundido);
  };
  requestAnimationFrame(fundido);
  requestAnimationFrame(animar);
}

addEventListener('resize', () => {
  camara.aspect = innerWidth / innerHeight;
  camara.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  resolucion.set(innerWidth, innerHeight);
  for (const o of estado.objetosLinea || []) o.material.resolution.copy(resolucion);
});

iniciar().catch((err) => {
  console.error(err);
  const b = $('#badge-estado');
  b.textContent = 'Error al cargar los datos';
  b.classList.add('nz-badge--danger');
});
