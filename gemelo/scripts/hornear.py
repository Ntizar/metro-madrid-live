"""Hornea el gemelo digital del Metro de Madrid para three.js.

Entradas:
  datos/estaciones/*.glb   (240 modelos, glTF 2.0 del respaldo 2026-11-20)
  datos/gtfs/*.zip         (CRTM: metro, metroligero, cercanias)
  datos/estaciones.json    (metadatos + anclaje EPSG:25830)
  IGN WMTS (ortofoto PNOA) + terrarium (elevación)

Salidas (datos/):
  estaciones.bin + estaciones_head.json   geometría fusionada y georreferenciada
  tren.bin + tren_head.json
  mundo.json                              líneas GTFS, paradas, terreno, marco
  terreno.png                             cotas RGB 16 bits
  ortofoto.jpg

Uso:  python scripts/hornear.py [estaciones|lineas|terreno|todo]
"""
import io
import json
import math
import os
import struct
import sys
import urllib.request
import zipfile

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import latlon_a_utm, latlon_a_tesela, resolucion_m, tesela_a_latlon, utm_a_latlon

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36"

# Marco local: Puerta del Sol. x = E - EREF, z = -(N - NREF), y = cota.
EREF, NREF = 440291.28, 4474254.60


def a_local(E, N):
    return E - EREF, -(N - NREF)


# --------------------------------------------------------------------------
# glTF 2.0 / GLB
# --------------------------------------------------------------------------
CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16,
      5125: np.uint32, 5126: np.float32}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def leer_glb(ruta):
    buf = open(ruta, "rb").read()
    magic, ver, largo = struct.unpack_from("<III", buf, 0)
    if magic != 0x46546C67:
        raise ValueError(f"{ruta}: no es GLB")
    off, js, binario = 12, None, b""
    while off < largo:
        clen, ctype = struct.unpack_from("<II", buf, off)
        trozo = buf[off + 8: off + 8 + clen]
        off += 8 + clen
        if ctype == 0x4E4F534A:
            js = json.loads(trozo.decode("utf-8"))
        elif ctype == 0x004E4942:
            binario = trozo
    return js, binario


def leer_accessor(js, binario, idx):
    acc = js["accessors"][idx]
    n = acc["count"]
    tipo = np.dtype(CT[acc["componentType"]])
    comps = NC[acc["type"]]
    if "bufferView" not in acc:
        return np.zeros((n, comps), dtype=tipo)
    bv = js["bufferViews"][acc["bufferView"]]
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    paso = bv.get("byteStride") or tipo.itemsize * comps
    if paso == tipo.itemsize * comps:
        arr = np.frombuffer(binario, dtype=tipo, count=n * comps, offset=base)
        arr = arr.reshape(n, comps)
    else:
        out = np.empty((n, comps), dtype=tipo)
        for i in range(n):
            out[i] = np.frombuffer(binario, dtype=tipo, count=comps, offset=base + i * paso)
        arr = out
    return arr


def matriz_nodo(n):
    if "matrix" in n:
        return np.array(n["matrix"], dtype=np.float64).reshape(4, 4).T
    m = np.eye(4)
    t = n.get("translation", [0, 0, 0])
    r = n.get("rotation", [0, 0, 0, 1])
    s = n.get("scale", [1, 1, 1])
    x, y, z, w = r
    rot = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
        [0, 0, 0, 1]])
    esc = np.diag([s[0], s[1], s[2], 1.0])
    tra = np.eye(4)
    tra[:3, 3] = t
    return tra @ rot @ esc


def glb_a_triangulos(ruta):
    """Devuelve posiciones (N,3) float32 en coords del modelo, colores (N,3) float32 0-1,
    índices (M,3) y lista de piezas."""
    js, binario = leer_glb(ruta)
    piezas = []  # (posiciones mundo, indices, color)

    def color_de(mat_idx):
        c = [0.62, 0.62, 0.60]
        if mat_idx is not None and "materials" in js:
            mat = js["materials"][mat_idx]
            pbr = mat.get("pbrMetallicRoughness", {})
            if "baseColorFactor" in pbr:
                c = pbr["baseColorFactor"][:3]
            elif "baseColorTexture" in pbr:
                c = [0.70, 0.68, 0.62]
        return c

    def recorrer(ni, padre):
        nodo = js["nodes"][ni]
        mundo = padre @ matriz_nodo(nodo)
        if "mesh" in nodo:
            for prim in js["meshes"][nodo["mesh"]]["primitives"]:
                if "POSITION" not in prim.get("attributes", {}):
                    continue
                pos = leer_accessor(js, binario, prim["attributes"]["POSITION"]).astype(np.float64)
                if pos.shape[1] == 3:
                    ph = np.hstack([pos, np.ones((len(pos), 1))])
                    pos = (mundo @ ph.T).T[:, :3]
                if "indices" in prim:
                    idx = leer_accessor(js, binario, prim["indices"]).reshape(-1).astype(np.int64)
                else:
                    idx = np.arange(len(pos), dtype=np.int64)
                col = color_de(prim.get("material"))
                piezas.append((pos, idx.reshape(-1, 3), col))
        for hijo in nodo.get("children", []):
            recorrer(hijo, mundo)

    escena = js.get("scenes", [{"nodes": []}])[js.get("scene", 0)]
    for ni in escena.get("nodes", []):
        recorrer(ni, np.eye(4))
    return piezas


# --------------------------------------------------------------------------
# Estaciones
# --------------------------------------------------------------------------
def normaliza(s):
    tabla = str.maketrans("áàäâéèëêíìïîóòöôúùüûñç", "aaaaeeeeiiiioooouuuunc")
    s = (s or "").lower().translate(tabla)
    for c in ".,;:()[]'\"-_/":
        s = s.replace(c, " ")
    return " ".join(s.split())


def csv_filas(z, nombre):
    """CSV del GTFS como lista de dicts, por nombre de columna (orden real del fichero)."""
    if nombre not in z.namelist():
        return []
    lineas = z.read(nombre).decode("utf-8-sig").splitlines()
    if not lineas:
        return []
    cab = [c.strip().lower() for c in lineas[0].split(",")]
    salida = []
    for fila in lineas[1:]:
        p = fila.split(",")
        if len(p) < len(cab):
            continue
        salida.append(dict(zip(cab, p)))
    return salida


def lineas_metro_por_parada():
    """stop_name normalizado -> {ref: {ref, color, nombre}} desde el GTFS de Metro."""
    z = zipfile.ZipFile(os.path.join(DATOS, "gtfs", "metro.zip"))
    rutas = {}
    for r in csv_filas(z, "routes.txt"):
        rutas[r["route_id"]] = {"ref": r.get("route_short_name", ""),
                                "nombre": r.get("route_long_name", ""),
                                "color": "#" + (r.get("route_color") or "888888")}
    viaje_ruta = {t["trip_id"]: t["route_id"] for t in csv_filas(z, "trips.txt")}
    parada_nombre = {s["stop_id"]: s["stop_name"] for s in csv_filas(z, "stops.txt")}
    salida = {}
    for st in csv_filas(z, "stop_times.txt"):
        r = rutas.get(viaje_ruta.get(st["trip_id"]))
        nom = parada_nombre.get(st["stop_id"])
        if not r or not nom:
            continue
        d = salida.setdefault(normaliza(nom), {})
        d[r["ref"]] = r
    return salida


def hornear_estaciones():
    meta = json.load(open(os.path.join(DATOS, "estaciones.json"), encoding="utf-8"))
    mundo = json.load(open(os.path.join(DATOS, "mundo.json"), encoding="utf-8"))
    lineas_metro = [l for l in mundo["lineas"] if l["red"] in ("metro", "ligero")]
    pos_trozos, col_trozos, idx_trozos = [], [], []
    cabecera, base_v, base_i = [], 0, 0
    sin_linea, errores = [], []
    for m in sorted(meta, key=lambda x: x["id"]):
        ruta = os.path.join(DATOS, "estaciones", m["id"] + ".glb")
        if not os.path.exists(ruta):
            continue
        piezas = glb_a_triangulos(ruta)
        if not piezas:
            continue
        E0, N0 = m["E0"], m["N0"]
        # nativo (x, y, z) -> local: x'=x+(E0-EREF), z'=z-(N0-NREF), y'=y-40
        off = np.array([E0 - EREF, -40.0, -(N0 - NREF)])
        # línea por proximidad geométrica al trazado GTFS
        x_l, z_l = a_local(E0, N0)
        cand = []
        for L in lineas_metro:
            d = min((dist_a_polilinea(x_l, z_l, t)[0] for t in L["tramos"]), default=9e9)
            if d < 250.0:
                cand.append((d, L))
        cand.sort(key=lambda t: t[0])
        cand = cand[:3]
        refs = [c[1]["ref"] for c in cand]
        color = cand[0][1]["color"] if cand else "#8a8f98"
        errores.append(cand[0][0] if cand else -1.0)
        if not cand:
            sin_linea.append(m["estaciones"])
        color_rgb = np.array([int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)],
                             dtype=np.float32) / 255.0

        v_ini = base_v
        i_ini = base_i
        for pos, idx, col in piezas:
            p = (pos + off).astype(np.float32)
            c = np.array(col, dtype=np.float32)
            # tinte de línea sobre el gris del croquis: 60 % color de línea
            mezcla = c * 0.4 + color_rgb * 0.6
            colores = np.clip(np.repeat(mezcla[None, :], len(p), axis=0), 0, 1)
            pos_trozos.append(p)
            col_trozos.append((colores * 255).astype(np.uint8))
            idx_trozos.append((idx + base_v).astype(np.uint32))
            base_v += len(p)
            base_i += idx.size
        cabecera.append({
            "id": m["id"], "nombre": m["estaciones"], "lineas": refs, "color": color,
            "E": round(E0, 2), "N": round(N0, 2),
            "v0": v_ini, "vn": base_v - v_ini,
            "i0": i_ini, "in": base_i - i_ini, "dist": round(errores[-1], 1),
            "tri": (base_i - i_ini) // 3,
        })
    pos = np.vstack(pos_trozos)
    col = np.vstack(col_trozos)
    idx = np.concatenate(idx_trozos)
    # centrar y radio por estación (para selección y encuadre)
    for est in cabecera:
        p = pos[est["v0"]:est["v0"] + est["vn"]]
        c = p.mean(axis=0)
        est["c"] = [round(float(v), 1) for v in c]
        est["r"] = round(float(np.linalg.norm(p - c, axis=1).max()), 1)
    cab = {
        "origen": {"E": EREF, "N": NREF, "lat": 40.416775, "lon": -3.703790},
        "estaciones": cabecera,
        "vertices": int(len(pos)), "triangulos": int(len(idx)),
        "sin_linea": sin_linea,
        "registro": {
            "criterio": "distancia del anclaje de la estación al trazado GTFS de su línea",
            "mediana_m": round(float(np.median([e for e in errores if e >= 0])), 1),
            "p90_m": round(float(np.percentile([e for e in errores if e >= 0], 90)), 1),
            "max_m": round(float(max([e for e in errores if e >= 0], default=0)), 1),
            "sin_linea_a_250m": len(sin_linea),
        },
    }
    escribir_binario(os.path.join(DATOS, "estaciones.bin"),
                     json.dumps(cab, ensure_ascii=False).encode("utf-8"),
                     [pos.astype(np.float32).tobytes(), col.tobytes(), idx.astype(np.uint32).tobytes()])
    r = cab["registro"]
    print(f"  estaciones: {len(cabecera)} | {len(pos)} vert | {len(idx)} tri | "
          f"{os.path.getsize(os.path.join(DATOS,'estaciones.bin'))/1e6:.2f} MB")
    print(f"  registro estación↔línea: mediana {r['mediana_m']} m · p90 {r['p90_m']} m · máx {r['max_m']} m · "
          f"sin línea {r['sin_linea_a_250m']}")


def escribir_binario(ruta, cabecera_json, trozos):
    with open(ruta, "wb") as f:
        f.write(b"MMG1")
        f.write(struct.pack("<I", len(cabecera_json)))
        f.write(cabecera_json)
        for t in trozos:
            f.write(t)


def hornear_tren():
    fuente = os.path.join(DATOS, "SERIE_9000_ORIGINAL.glb")
    piezas = glb_a_triangulos(fuente)
    # El manifiesto pide girar Y +90º y las ruedas apoyadas en y=0
    ry = math.pi / 2
    R = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
    pos_t, col_t, idx_t, base = [], [], [], 0
    for pos, idx, col in piezas:
        p = (pos @ R.T).astype(np.float32)
        pos_t.append(p)
        col_t.append(np.repeat(np.array(col, dtype=np.float32)[None, :] * 255, len(p), axis=0).astype(np.uint8))
        idx_t.append((idx + base).astype(np.uint32))
        base += len(p)
    pos = np.vstack(pos_t)
    col = np.vstack(col_t)
    idx = np.concatenate(idx_t)
    mn, mx = pos.min(axis=0), pos.max(axis=0)
    pos = pos - np.array([(mn[0] + mx[0]) / 2, mn[1], (mn[2] + mx[2]) / 2], dtype=np.float32)
    # tras girar Y +90º el eje longitudinal queda en Z (convención de la escena original)
    cab = {"largo": float(mx[2] - mn[2]), "alto": float(mx[1] - mn[1]),
           "ancho": float(mx[0] - mn[0]), "vertices": int(len(pos)), "triangulos": int(len(idx)),
           "origen": "SERIE_9000_ORIGINAL.glb · revisión 20-nov-2026 (6 coches)"}
    escribir_binario(os.path.join(DATOS, "tren.bin"), json.dumps(cab, ensure_ascii=False).encode(),
                     [pos.tobytes(), col.tobytes(), idx.tobytes()])
    print(f"  tren: largo {cab['largo']:.1f} m alto {cab['alto']:.1f} m ancho {cab['ancho']:.1f} m "
          f"| {cab['triangulos']} tri | {os.path.getsize(os.path.join(DATOS,'tren.bin'))/1e6:.2f} MB")


# --------------------------------------------------------------------------
# GTFS -> líneas y paradas
# --------------------------------------------------------------------------
def simplificar(pts, tol=6.0):
    """Douglas-Peucker en 2D."""
    if len(pts) < 3:
        return pts
    a, b = np.array(pts[0], dtype=np.float64), np.array(pts[-1], dtype=np.float64)
    ab = b - a
    P = np.array(pts, dtype=np.float64)
    L = math.hypot(ab[0], ab[1])
    if L < 1e-9:
        d = np.hypot(P[:, 0] - a[0], P[:, 1] - a[1])
    else:
        d = np.abs(ab[0] * (P[:, 1] - a[1]) - ab[1] * (P[:, 0] - a[0])) / L
    i = int(np.argmax(d))
    if d[i] <= tol:
        return [pts[0], pts[-1]]
    return simplificar(pts[:i + 1], tol)[:-1] + simplificar(pts[i:], tol)


def dist_a_polilinea(px, pz, pts):
    """Distancia (m) del punto a la polilínea y punto más cercano."""
    P = np.asarray(pts, dtype=np.float64)
    if len(P) < 2:
        return 1e9, None
    A, B = P[:-1], P[1:]
    AB = B - A
    den = np.maximum((AB ** 2).sum(axis=1), 1e-9)
    t = np.clip(((px - A[:, 0]) * AB[:, 0] + (pz - A[:, 1]) * AB[:, 1]) / den, 0.0, 1.0)
    Q = A + AB * t[:, None]
    d = np.hypot(Q[:, 0] - px, Q[:, 1] - pz)
    i = int(np.argmin(d))
    return float(d[i]), Q[i]


def extension_terreno():
    est = json.load(open(os.path.join(DATOS, "estaciones.json"), encoding="utf-8"))
    xs = [a_local(e["E0"], e["N0"])[0] for e in est]
    zs = [a_local(e["E0"], e["N0"])[1] for e in est]
    m = 3000.0
    return min(xs) - m, max(xs) + m, min(zs) - m, max(zs) + m


def recortar(puntos, x0, x1, z0, z1):
    """Parte una polilínea en los tramos que caen dentro del recuadro."""
    tramos, cur = [], []
    for p in puntos:
        if x0 <= p[0] <= x1 and z0 <= p[1] <= z1:
            cur.append(p)
        else:
            if len(cur) > 1:
                tramos.append(cur)
            cur = []
    if len(cur) > 1:
        tramos.append(cur)
    return tramos


# Rutas sin traza en el GTFS del CRTM (comprobado: 0 viajes y 0 shapes para la línea 3).
# Se reconstruye el eje uniendo sus paradas EN ORDEN, tal como están en stops.txt.
TRAZAS_MANUALES = {
    "4__3___": ["Moncloa", "Argüelles", "Ventura Rodríguez", "Plaza de España", "Callao", "Sol",
                "Lavapiés", "Embajadores", "Palos de la Frontera", "Delicias", "Legazpi",
                "Almendrales", "Hospital 12 de Octubre", "San Fermín-Orcasur", "Ciudad de los Ángeles",
                "Villaverde Bajo-Cruce", "San Cristóbal", "Villaverde Alto"],
}


def _largo(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _misma_traza(a, b, tol=70.0):
    """Dos trazas son la misma si empiezan y acaban en el mismo sitio (en cualquier sentido)."""
    if not a or not b:
        return False
    d = math.dist(a[0], b[0]) + math.dist(a[-1], b[-1])
    r = math.dist(a[0], b[-1]) + math.dist(a[-1], b[0])
    return min(d, r) < tol * 2


def hornear_lineas():
    x0, x1, z0, z1 = extension_terreno()
    salida = {"lineas": [], "paradas": [], "recuadro": {"x0": x0, "x1": x1, "z0": z0, "z1": z1}}
    for red, fichero in [("metro", "metro.zip"), ("ligero", "metroligero.zip"), ("cercanias", "cercanias.zip")]:
        ruta = os.path.join(DATOS, "gtfs", fichero)
        if not os.path.exists(ruta):
            continue
        z = zipfile.ZipFile(ruta)
        rutas = {}
        for r in csv_filas(z, "routes.txt"):
            rutas[r["route_id"]] = {"ref": r.get("route_short_name") or r["route_id"],
                                    "nombre": r.get("route_long_name", ""),
                                    "color": "#" + (r.get("route_color") or "888888")}
        sh = {}
        for s in csv_filas(z, "shapes.txt"):
            try:
                sh.setdefault(s["shape_id"], []).append(
                    (int(s["shape_pt_sequence"]), float(s["shape_pt_lat"]), float(s["shape_pt_lon"])))
            except (ValueError, KeyError):
                continue
        # todas las trazas declaradas por los viajes (no solo los que tienen stop_times:
        # el GTFS del CRTM trocea los horarios y dejaba fuera líneas enteras, p. ej. la 3)
        por_ruta = {}
        for t in csv_filas(z, "trips.txt"):
            rid, sid = t.get("route_id"), t.get("shape_id")
            if rid and sid and sid in sh:
                por_ruta.setdefault(rid, set()).add(sid)

        def simplifica_shape(sid):
            loc = []
            for _, la, lo in sorted(sh[sid]):
                E, N = latlon_a_utm(la, lo)
                loc.append(a_local(E, N))
            return simplificar(loc, 6.0)

        # rutas sin shapes: eje reconstruido por paradas oficiales
        for rid, nombres in TRAZAS_MANUALES.items():
                if rid not in rutas or rid in por_ruta:
                    continue
                coords = {}
                for st in csv_filas(z, "stops.txt"):
                    n = normaliza(st.get("stop_name", ""))
                    if n in [normaliza(x) for x in nombres] and n not in coords:
                        coords[n] = (float(st["stop_lat"]), float(st["stop_lon"]))
                pts = [coords[normaliza(n)] for n in nombres if normaliza(n) in coords]
                if len(pts) < 3:
                    continue
                loc = []
                for la, lo in pts:
                    E, N = latlon_a_utm(la, lo)
                    loc.append(a_local(E, N))
                simp = simplificar(loc, 6.0)
                tramos = recortar(simp, x0, x1, z0, z1)
                if not tramos:
                    continue
                r = rutas[rid]
                salida["lineas"].append({
                    "red": red, "ref": r["ref"], "nombre": r["nombre"], "color": r["color"],
                    "puntos": [(round(x, 1), round(zz, 1)) for x, zz in tramos[0]],
                    "tramos": [[(round(x, 1), round(zz, 1)) for x, zz in t] for t in tramos],
                    "largo_km": round(_largo(simp) / 1000.0, 1),
                    "trazas": 1, "origen": "paradas",
                })

        for rid, sids in por_ruta.items():
            r = rutas.get(rid)
            if not r:
                continue
            # se conservan las ramas (MetroEste, Rivas, norte…) y se descartan duplicados
            candidatas = []
            for sid in sids:
                simp = simplifica_shape(sid)
                if len(simp) > 1:
                    candidatas.append((_largo(simp), simp))
            candidatas.sort(key=lambda x: -x[0])
            aceptadas = []
            for largo, simp in candidatas:
                if any(_misma_traza(simp, a) for a in aceptadas):
                    continue
                aceptadas.append(simp)
            tramos = []
            for simp in aceptadas:
                tramos.extend(recortar(simp, x0, x1, z0, z1))
            tramos = [t for t in tramos if len(t) > 1]
            if not tramos:
                continue
            tramos.sort(key=len, reverse=True)
            salida["lineas"].append({
                "red": red, "ref": r["ref"], "nombre": r["nombre"], "color": r["color"],
                "puntos": [(round(x, 1), round(zz, 1)) for x, zz in tramos[0]],
                "tramos": [[(round(x, 1), round(zz, 1)) for x, zz in t] for t in tramos],
                "largo_km": round(_largo(aceptadas[0]) / 1000.0, 1),
                "trazas": len(aceptadas),
            })
        for s in csv_filas(z, "stops.txt"):
            try:
                E, N = latlon_a_utm(float(s["stop_lat"]), float(s["stop_lon"]))
            except (ValueError, KeyError):
                continue
            x, zz = a_local(E, N)
            salida["paradas"].append({"red": red, "nombre": s.get("stop_name", ""),
                                      "x": round(x, 1), "z": round(zz, 1),
                                      "tipo": s.get("location_type", "0")})
    # una entrada por línea real: la traza más larga de cada (red, ref)
    unicas = {}
    for l in salida["lineas"]:
        k = (l["red"], l["ref"])
        if k not in unicas or sum(len(t) for t in l["tramos"]) > sum(len(t) for t in unicas[k]["tramos"]):
            unicas[k] = l
    salida["lineas"] = sorted(unicas.values(), key=lambda l: (l["red"] != "metro", l["red"] != "ligero", str(l["ref"])))
    json.dump(salida, open(os.path.join(DATOS, "mundo.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  líneas: {len(salida['lineas'])} | paradas: {len(salida['paradas'])} | "
          f"{os.path.getsize(os.path.join(DATOS,'mundo.json'))/1e6:.2f} MB")


# --------------------------------------------------------------------------
# Terreno y ortofoto
# --------------------------------------------------------------------------
def bajar(url, cabecera=True):
    req = urllib.request.Request(url, headers={"User-Agent": UA} if cabecera else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def hornear_terreno():
    est = json.load(open(os.path.join(DATOS, "estaciones.json"), encoding="utf-8"))
    xs, zs = [], []
    for e in est:
        x, z = a_local(e["E0"], e["N0"])
        xs.append(x)
        zs.append(z)
    margen = 3000.0
    x0, x1 = min(xs) - margen, max(xs) + margen
    z0, z1 = min(zs) - margen, max(zs) + margen
    ancho, alto = x1 - x0, z1 - z0
    paso = max(16.0, max(ancho, alto) / 2000.0)
    nx, nz = int(ancho / paso) + 1, int(alto / paso) + 1
    print(f"  extensión {ancho/1000:.1f} x {alto/1000:.1f} km | rejilla {nx} x {nz} = {nx*nz/1e6:.2f} M px "
          f"({paso:.1f} m/px)")

    E0, N1 = EREF + x0, NREF - z1     # esquina NO
    E1, N0 = EREF + x1, NREF - z0     # esquina SE
    lat_n, lon_o = utm_a_latlon(E0, N1)
    lat_s, lon_e = utm_a_latlon(E1, N0)

    z = 13
    txa, tya = latlon_a_tesela(lat_n, lon_o, z)
    txb, tyb = latlon_a_tesela(lat_s, lon_e, z)
    tx0, tx1 = int(min(txa, txb)) - 1, int(max(txa, txb)) + 1
    ty0, ty1 = int(min(tya, tyb)) - 1, int(max(tya, tyb)) + 1
    W = (tx1 - tx0 + 1) * 256
    H = (ty1 - ty0 + 1) * 256
    print(f"  teselas z{z}: {tx1-tx0+1} x {ty1-ty0+1} = {(tx1-tx0+1)*(ty1-ty0+1)} teselas, lienzo {W}x{H}")

    dem = np.zeros((H, W), dtype=np.float32)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{tx}/{ty}.png"
            try:
                im = Image.open(io.BytesIO(bajar(url))).convert("RGB")
            except Exception as e:
                print("   fallo", tx, ty, e)
                continue
            a = np.asarray(im).astype(np.float32)
            h = a[:, :, 0] * 256.0 + a[:, :, 1] + a[:, :, 2] / 256.0 - 32768.0
            oy, ox = (ty - ty0) * 256, (tx - tx0) * 256
            dem[oy:oy + 256, ox:ox + 256] = h
    print(f"  cota DEM: {dem.min():.0f} .. {dem.max():.0f} m")

    # muestreo bilineal de la rejilla local
    def px_de_local(x, zl):
        lat, lon = utm_a_latlon(EREF + x, NREF - zl)
        gx, gy = latlon_a_tesela(lat, lon, z)
        return (gx - tx0) * 256.0, (gy - ty0) * 256.0

    gx0, gy0 = px_de_local(x0, z0)
    gx1, gy1 = px_de_local(x1, z1)
    xi = np.linspace(gx0, gx1, nx)
    yi = np.linspace(gy0, gy1, nz)
    XI, YI = np.meshgrid(xi, yi)
    X0 = np.floor(XI).astype(int).clip(0, W - 2)
    Y0 = np.floor(YI).astype(int).clip(0, H - 2)
    fx, fy = XI - X0, YI - Y0
    cotas = (dem[Y0, X0] * (1 - fx) * (1 - fy) + dem[Y0, X0 + 1] * fx * (1 - fy)
             + dem[Y0 + 1, X0] * (1 - fx) * fy + dem[Y0 + 1, X0 + 1] * fx * fy)
    # datum vertical: la cota del origen (Sol) pasa a ser 0, para que el subsuelo
    # (andenes a -22 m) quede a profundidad física real bajo su propia calle.
    ix0, iz0 = nx // 2, nz // 2
    x_ref, z_ref = x0 + (ix0 / (nx - 1)) * ancho, z0 + (iz0 / (nz - 1)) * alto
    h_ref = float(cotas[iz0, ix0])
    cotas_rel = cotas - h_ref
    v = np.clip(np.round((cotas_rel + 1200.0) * 10.0), 0, 65535).astype(np.uint16)
    rgb = np.zeros((nz, nx, 3), dtype=np.uint8)
    rgb[:, :, 0] = (v >> 8).astype(np.uint8)
    rgb[:, :, 1] = (v & 0xFF).astype(np.uint8)
    rgb[:, :, 2] = 0
    Image.fromarray(rgb, "RGB").save(os.path.join(DATOS, "terreno.png"), optimize=True)
    print(f"  terreno.png: {os.path.getsize(os.path.join(DATOS,'terreno.png'))/1e6:.2f} MB")

    # ortofoto PNOA (WMTS) al mismo encuadre
    orto = Image.new("RGB", (W, H), (20, 20, 24))
    fallos = 0
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            url = ("https://www.ign.es/wmts/pnoa-ma?layer=OI.OrthoimageCoverage&style=default"
                   f"&tilematrixset=GoogleMapsCompatible&Service=WMTS&Request=GetTile&Version=1.0.0"
                   f"&Format=image/jpeg&TileMatrix={z}&TileCol={tx}&TileRow={ty}")
            try:
                im = Image.open(io.BytesIO(bajar(url))).convert("RGB")
                orto.paste(im, ((tx - tx0) * 256, (ty - ty0) * 256))
            except Exception:
                fallos += 1
    orto = orto.resize((nx, nz), Image.LANCZOS)
    orto.save(os.path.join(DATOS, "ortofoto.jpg"), quality=82, optimize=True)
    print(f"  ortofoto.jpg: {os.path.getsize(os.path.join(DATOS,'ortofoto.jpg'))/1e6:.2f} MB (fallos {fallos})")

    cab = {
        "x0": round(x0, 1), "z0": round(z0, 1), "nx": nx, "nz": nz, "paso": round(paso, 3),
        "ancho": round(ancho, 1), "alto": round(alto, 1),
        "h_ref": round(h_ref, 1),
        "cota_min": round(float(cotas_rel.min()), 1), "cota_max": round(float(cotas_rel.max()), 1),
        "cota_abs_min": round(float(cotas.min()), 1), "cota_abs_max": round(float(cotas.max()), 1),
        "desnivel": round(float(cotas.max() - cotas.min()), 1),
        "origen": {"E": EREF, "N": NREF},
        "dem": {"z": z, "tx0": tx0, "ty0": ty0},
        "fuente_dem": "AWS terrain-tiles (terrarium) z13 ~14,6 m/px",
        "fuente_orto": "IGN PNOA WMTS OI.OrthoimageCoverage z13",
    }
    json.dump(cab, open(os.path.join(DATOS, "terreno.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  datum: cota 0 en {h_ref:.1f} m (absoluta) · relativo {cab['cota_min']} .. {cab['cota_max']} m")
    print(f"  desnivel medido: {cab['desnivel']} m · absoluto {cab['cota_abs_min']} .. {cab['cota_abs_max']} m")


if __name__ == "__main__":
    que = sys.argv[1] if len(sys.argv) > 1 else "todo"
    if que in ("lineas", "todo"):
        print("[1/4] líneas GTFS")
        hornear_lineas()
    if que in ("estaciones", "todo"):
        print("[2/4] estaciones")
        hornear_estaciones()
        print("[3/4] tren")
        hornear_tren()
    if que in ("terreno", "todo"):
        print("[4/4] terreno + ortofoto")
        hornear_terreno()
    print("hecho")
