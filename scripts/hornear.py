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


def leer_cotas_png(ruta):
    from PIL import Image as _Img
    im = _Img.open(ruta).convert("RGB")
    a = np.asarray(im).astype(np.uint16)
    v = (a[:, :, 0].astype(np.uint16) << 8) + a[:, :, 1]
    return (v.astype(np.float64) / 10.0) - 1200.0


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
            nombre_malla = js["meshes"][nodo["mesh"]].get("name", "")
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
                piezas.append((pos, idx.reshape(-1, 3), col, nombre_malla))
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


def hornear_estaciones(factor=1.0):
    """Vestíbulo de cada estación a nivel de la calle y andén a la profundidad que
    define su propio modelo; el túnel se cuelga de esa cota. Incluye corrección
    global del desfase horizontal contra el eje GTFS (la red real manda)."""
    meta = json.load(open(os.path.join(DATOS, "estaciones.json"), encoding="utf-8"))
    mundo = json.load(open(os.path.join(DATOS, "mundo.json"), encoding="utf-8"))
    lineas = [l for l in mundo["lineas"] if l["red"] in ("metro", "ligero")]
    cotas = leer_cotas_png(os.path.join(DATOS, "terreno.png"))
    tc = json.load(open(os.path.join(DATOS, "terreno.json"), encoding="utf-8"))
    nx, nz = tc["nx"], tc["nz"]

    def cota(x, z):
        fx = min(max((x - tc["x0"]) / tc["ancho"], 0), 1) * (nx - 1)
        fz = min(max((z - tc["z0"]) / tc["alto"], 0), 1) * (nz - 1)
        i0, j0 = min(int(fx), nx - 2), min(int(fz), nz - 2)
        dx, dz = fx - i0, fz - j0
        a = cotas[j0, i0]; b = cotas[j0, i0 + 1]
        c = cotas[j0 + 1, i0]; d = cotas[j0 + 1, i0 + 1]
        return float((a * (1 - dx) + b * dx) * (1 - dz) + (c * (1 - dx) + d * dx) * dz)

    def mejor_carril(L, x_l, z_l):
        mejor = None
        vias = L["vias"]
        for k, via in enumerate(vias):
            pts = via["p"]
            d, qx, qz, rumbo = proyectar(x_l, z_l, pts)
            if d > 250.0:
                continue
            S = None
            mx, mz = qx, qz
            # el carril de sentido contrario (d opuesto) más cercano
            q1 = None
            bh = None
            for j, v2 in enumerate(vias):
                if v2["d"] == via["d"]:
                    continue
                r2 = proyectar(x_l, z_l, v2["p"])
                if r2[0] < 80.0 and (bh is None or r2[0] < bh[0]):
                    bh = r2
            if bh:
                S = math.hypot(bh[1] - qx, bh[2] - qz)
                if 1.0 < S < 40.0:
                    mx, mz = (qx + bh[1]) / 2.0, (qz + bh[2]) / 2.0
                else:
                    S = None
            if mejor is None or d < mejor[0]:
                mejor = (d, mx, mz, rumbo, S, L, k)
        return mejor

    def longitud_total(pts):
        return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))

    # --- pasada 1: corrección global del desfase ---
    deltas = []
    for m in sorted(meta, key=lambda x: x["id"]):
        x_l, z_l = a_local(m["E0"], m["N0"])
        for L in lineas:
            r = mejor_carril(L, x_l, z_l)
            if r:
                deltas.append((r[1] - x_l, r[2] - z_l))
                break
    mdx = float(np.median([d[0] for d in deltas]))
    mdz = float(np.median([d[1] for d in deltas]))

    # --- pasada 2: colocación final ---
    pos_t, col_t, idx_t = [], [], []
    cabecera, base_v, base_i = [], 0, 0
    sin_linea, snaps, giros, seps = [], [], [], []
    for m in sorted(meta, key=lambda x: x["id"]):
        ruta = os.path.join(DATOS, "estaciones", m["id"] + ".glb")
        if not os.path.exists(ruta):
            continue
        piezas = glb_a_triangulos(ruta)
        if not piezas:
            continue
        E0, N0 = m["E0"] + mdx, m["N0"] + mdz
        x_l, z_l = a_local(E0, N0)

        mejor = None
        for L in lineas:
            r = mejor_carril(L, x_l, z_l)
            if r and (mejor is None or r[0] < mejor[0]):
                mejor = r

        ang, rumbo, S, dmin, ax, az, s_arc, refs, color_rgb = 0.0, None, None, -1.0, None, None, 0.5, [], None
        if mejor is None:
            sin_linea.append(m["estaciones"])
            color_rgb = np.array([0.55, 0.55, 0.55], dtype=np.float32)
            todos = np.vstack([pz[0] for pz in piezas])
            ax, az = float(todos[:, 0].mean()) + a_local(m["E0"], m["N0"])[0] - a_local(m["E0"], m["N0"])[0], float(todos[:, 2].mean())
            # centroide del modelo sin anclaje: lo dejamos donde estaba (E0/N0 originales)
            cx0, cz0 = a_local(m["E0"], m["N0"])
            p0 = todos.mean(axis=0)
            ax, az = cx0 + (p0[0] - p0[0]), cz0
            todos_l = todos + np.array([a_local(m["E0"], m["N0"])[0], 0, a_local(m["E0"], m["N0"])[1]])
            ax, az = float(todos_l[:, 0].mean()), float(todos_l[:, 2].mean())
        else:
            dmin, ax, az, rumbo, S, L, k_via = mejor
            refs = [L["ref"]]
            color_rgb = np.array([int(L["color"][1:3], 16), int(L["color"][3:5], 16),
                                  int(L["color"][5:7], 16)], dtype=np.float32) / 255.0
            snaps.append(dmin)
            if S:
                seps.append(S)
            pts = L["vias"][k_via]["p"]
            total = longitud_total(pts)
            acum = 0.0
            for i in range(len(pts) - 1):
                seg = math.dist(pts[i], pts[i + 1])
                dd = math.dist(pts[i], (ax, az))
                if dd <= seg + 1e-9:
                    s_arc = (acum + dd) / total if total > 0 else 0.5
                    break
                acum += seg
            else:
                s_arc = 0.5

        # profundidad que define el PROPIO modelo: cota del vestíbulo (piezas nombradas)
        ys_hall = []
        for pz in piezas:
            nm = (pz[3].lower() if len(pz) > 3 and pz[3] else "")
            if nm and any(t in nm for t in ("vestibul", "ticket", "hall", "acces", "lobby", "entresol")):
                ys_hall.append(float(pz[0][:, 1].max()))
        if ys_hall:
            hall = max(ys_hall)
        else:
            ys = np.concatenate([pz[0][:, 1] for pz in piezas])
            hall = float(np.percentile(ys, 98))
        hall = min(max(hall, 6.0), 40.0)

        # geometría en local (con la corrección global), centrada en el ancla
        todos = np.vstack([pz[0] + np.array([E0 - EREF, 0.0, -(N0 - NREF)]) for pz in piezas])
        cx, cz = float(todos[:, 0].mean()), float(todos[:, 2].mean())
        y_calle = cota(cx, cz)

        dxs = todos[:, 0] - cx
        dzs = todos[:, 2] - cz
        try:
            w, v = np.linalg.eigh(np.cov(np.vstack([dxs, dzs])))
            u = v[:, int(np.argmax(w))]
            ang_propio = math.atan2(u[1], u[0])
        except Exception:
            ang_propio = 0.0
        if rumbo is not None:
            ang = rumbo - ang_propio
            while ang > math.pi:
                ang -= 2 * math.pi
            while ang < -math.pi:
                ang += 2 * math.pi
            giros.append(abs(math.degrees(ang)))
        ca, sa = math.cos(ang), math.sin(ang)

        hall_eff = hall * factor
        v_ini, i_ini = base_v, base_i
        for pz in piezas:
            pos, idx, col = pz[0], pz[1], pz[2]
            p = pos.astype(np.float64).copy()
            dx, dz = p[:, 0] - cx, p[:, 2] - cz
            p[:, 0] = ax + dx * ca - dz * sa
            p[:, 2] = az + dx * sa + dz * ca
            p[:, 1] = y_calle + (p[:, 1] - hall) * factor
            p = p.astype(np.float32)
            c = np.array(col, dtype=np.float32)
            mezcla = c * 0.35 + color_rgb * 0.65
            colores = np.clip(np.repeat(mezcla[None, :], len(p), axis=0), 0, 1)
            pos_t.append(p)
            col_t.append((colores * 255).astype(np.uint8))
            idx_t.append((idx + base_v).astype(np.uint32))
            base_v += len(p)
            base_i += idx.size

        cabecera.append({
            "id": m["id"], "nombre": m["estaciones"], "lineas": refs,
            "color": "#" + "".join("%02x" % int(round(cc * 255)) for cc in color_rgb),
            "E": round(E0, 2), "N": round(N0, 2),
            "v0": v_ini, "vn": base_v - v_ini, "i0": i_ini, "in": base_i - i_ini,
            "dist": round(dmin, 1), "giro": round(abs(math.degrees(ang)), 1),
            "sep_vias": round(S, 2) if S else None,
            "D": round(hall_eff, 2), "kv": (mejor[6] if mejor else 0), "s": round(float(s_arc), 4),
            "y_calle": round(y_calle, 1), "L": mejor[5]["ref"] if mejor else None,
        })

    pos = np.vstack(pos_t)
    col = np.vstack(col_t)
    idx = np.concatenate(idx_t)
    for est in cabecera:
        pq = pos[est["v0"]:est["v0"] + est["vn"]]
        c = pq.mean(axis=0)
        est["c"] = [round(float(vv), 1) for vv in c]
        est["r"] = round(float(np.linalg.norm(pq - c, axis=1).max()), 1)

    def med(v):
        return round(float(np.median(v)), 1) if v else None

    cab = {
        "origen": {"E": EREF, "N": NREF, "lat": 40.416775, "lon": -3.703790},
        "correccion_global_m": {"dx": round(mdx, 2), "dz": round(mdz, 2), "n": len(deltas)},
        "estaciones": cabecera,
        "vertices": int(len(pos)), "triangulos": int(len(idx)),
        "sin_linea": sin_linea,
        "registro": {
            "criterio": "punto medio de las dos vías + giro al rumbo + vestíbulo a nivel de calle",
            "mediana_m": med(snaps), "p90_m": round(float(np.percentile(snaps, 90)), 1) if snaps else None,
            "max_m": round(float(max(snaps)), 1) if snaps else None,
            "giro_mediano_deg": med(giros),
            "separacion_mediana_m": med(seps),
            "profundidad_anden_mediana_m": med([e["D"] for e in cabecera]),
            "sin_linea_a_250m": len(sin_linea),
        },
    }
    escribir_binario(os.path.join(DATOS, "estaciones.bin"),
                     json.dumps(cab, ensure_ascii=False).encode("utf-8"),
                     [pos.astype(np.float32).tobytes(), col.tobytes(), idx.astype(np.uint32).tobytes()])
    print(f"  estaciones: {len(cabecera)} | {len(pos)} vert | {len(idx)} tri | "
          f"{os.path.getsize(os.path.join(DATOS, 'estaciones.bin')) / 1e6:.2f} MB")
    print(f"  corrección global del anclaje: ({mdx:+.1f}, {mdz:+.1f}) m sobre {len(deltas)} estaciones")
    print(f"  encaje: {cab['registro']['mediana_m']} m mediano · giro {cab['registro']['giro_mediano_deg']}° · "
          f"andén a {cab['registro']['profundidad_anden_mediana_m']} m · sin línea {len(sin_linea)}")


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
    for pz in piezas:
        pos, idx, col = pz[0], pz[1], pz[2]
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


def remuestrear(pts, paso=4.0):
    """Polilínea densa a paso fijo: la spline pasa por todos los puntos, así la traza,
    el túnel, la vía y el tren comparten la MISMA geometría (no hay desvío posible)."""
    if len(pts) < 2:
        return list(pts)
    out = [pts[0]]
    for i in range(1, len(pts)):
        x0, z0 = pts[i - 1]
        x1, z1 = pts[i]
        d = math.hypot(x1 - x0, z1 - z0)
        if d < 1e-9:
            continue
        n = max(1, int(d // paso))
        for k in range(1, n + 1):
            t = k / n
            out.append((x0 + (x1 - x0) * t, z0 + (z1 - z0) * t))
    return out


def proyectar(px, pz, pts):
    """Punto más cercano de la polilínea, su distancia y el rumbo del segmento (rad)."""
    best = (1e18, px, pz, 0.0)
    for i in range(len(pts) - 1):
        x0, z0 = pts[i]
        x1, z1 = pts[i + 1]
        dx, dz = x1 - x0, z1 - z0
        den = dx * dx + dz * dz
        if den < 1e-12:
            continue
        t = max(0.0, min(1.0, ((px - x0) * dx + (pz - z0) * dz) / den))
        qx, qz = x0 + dx * t, z0 + dz * t
        d = math.hypot(qx - px, qz - pz)
        if d < best[0]:
            best = (d, qx, qz, math.atan2(dz, dx))
    return best


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
    salida = {"lineas": [], "paradas": [],
              "recuadro": {"x0": x0, "x1": x1, "z0": z0, "z1": z1}}
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
        # cada shape pertenece a una DIRECCIÓN: son los dos carriles, no dos versiones
        por_ruta_dir = {}
        for t in csv_filas(z, "trips.txt"):
            rid, sid = t.get("route_id"), t.get("shape_id")
            if rid and sid and sid in sh:
                por_ruta_dir.setdefault(rid, {}).setdefault(t.get("direction_id") or "0", set()).add(sid)

        def simplifica_shape(sid):
            loc = []
            for _, la, lo in sorted(sh[sid]):
                E, N = latlon_a_utm(la, lo)
                loc.append(a_local(E, N))
            return simplificar(loc, 2.0)

        for rid, dirs in por_ruta_dir.items():
            r = rutas.get(rid)
            if not r:
                continue
            vias = []
            for d, sids in sorted(dirs.items()):
                cands = []
                for sid in sids:
                    simp = simplifica_shape(sid)
                    if len(simp) > 1:
                        cands.append((_largo(simp), simp))
                cands.sort(key=lambda xv: -xv[0])
                aceptadas = []
                for largo, simp in cands:
                    if any(_misma_traza(simp, a) for a in aceptadas):
                        continue
                    aceptadas.append(simp)
                for simp in aceptadas[:2]:          # eje principal + un ramal por dirección
                    for t in recortar(simp, x0, x1, z0, z1):
                        if len(t) > 1:
                            vias.append({"d": int(d), "p": remuestrear(t, 6.0)})
            if not vias:
                continue
            largo_total = max(_largo(v["p"]) for v in vias)
            salida["lineas"].append({
                "red": red, "ref": r["ref"], "nombre": r["nombre"], "color": r["color"],
                "vias": [{"d": v["d"], "p": [[round(x, 1), round(zz, 1)] for x, zz in v["p"]]} for v in vias],
                "largo_km": round(largo_total / 1000.0, 1),
                "trazas": len(vias),
                "dobles_vias": len({v["d"] for v in vias}) > 1,
            })

        # rutas sin shapes en el feed: eje reconstruido por paradas oficiales
        for rid, nombres in TRAZAS_MANUALES.items():
            if rid not in rutas or rid in por_ruta_dir:
                continue
            objetivo = {normaliza(x) for x in nombres}
            coords = {}
            for st in csv_filas(z, "stops.txt"):
                n = normaliza(st.get("stop_name", ""))
                if n in objetivo and n not in coords:
                    coords[n] = (float(st["stop_lat"]), float(st["stop_lon"]))
            pts = [coords[normaliza(n)] for n in nombres if normaliza(n) in coords]
            if len(pts) < 3:
                continue
            loc = []
            for la, lo in pts:
                E, N = latlon_a_utm(la, lo)
                loc.append(a_local(E, N))
            simp = simplificar(loc, 2.0)
            tramos = [t for t in recortar(simp, x0, x1, z0, z1) if len(t) > 1]
            if not tramos:
                continue
            r = rutas[rid]
            salida["lineas"].append({
                "red": red, "ref": r["ref"], "nombre": r["nombre"], "color": r["color"],
                "vias": [{"d": 0, "p": [[round(x, 1), round(zz, 1)] for x, zz in remuestrear(t, 6.0)]}
                         for t in tramos],
                "largo_km": round(_largo(simp) / 1000.0, 1),
                "trazas": 1, "origen": "paradas", "dobles_vias": False,
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

    unicas = {}
    for l in salida["lineas"]:
        k = (l["red"], l["ref"])
        if k not in unicas or sum(len(v["p"]) for v in l["vias"]) > sum(len(v["p"]) for v in unicas[k]["vias"]):
            unicas[k] = l
    salida["lineas"] = sorted(unicas.values(),
                              key=lambda l: (l["red"] != "metro", l["red"] != "ligero", str(l["ref"])))
    json.dump(salida, open(os.path.join(DATOS, "mundo.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  líneas: {len(salida['lineas'])} | vías: {sum(len(l['vias']) for l in salida['lineas'])} | "
          f"paradas: {len(salida['paradas'])} | "
          f"{os.path.getsize(os.path.join(DATOS,'mundo.json'))/1e6:.2f} MB")


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
        fac = 1.0
        for a in sys.argv[2:]:
            if a.startswith("--factor="):
                fac = float(a.split("=", 1)[1])
        hornear_estaciones(fac)
        print("[3/4] tren")
        hornear_tren()
    if que in ("terreno", "todo"):
        print("[4/4] terreno + ortofoto")
        hornear_terreno()
    print("hecho")
