"""Coloca cada modelo 3D sobre el mapa comparando línea a línea.

El modelo trae las vías pintadas con el color de su línea, y los túneles reales
vienen del GTFS/OSM. Para cada línea se calcula la dirección de su vía en el
modelo y la del túnel real dentro de la estación; la diferencia es el giro. Si
las líneas coinciden entre sí, el giro está bien determinado.

    python scripts/ajustar_giro.py
"""
import json
import math
import os

import numpy as np

from analizar_glb import GLB, acc_posiciones, aplicar, leer_glb, matriz_nodo, mul

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M_PER_DEG_LAT = 111320.0

MODELOS = {
    "alonso_martinez": "Alonso Martinez",
    "arguelles": "Argüelles",
    "av_america": "Avenida de América",
    "cuatro_caminos": "Cuatro Caminos",
    "nnmm": "Nuevos Ministerios",
    "pl_castilla": "Plaza de Castilla",
    "opera": "Ópera",
    "sol": "Puerta del Sol",
}


def hex_rgb(c):
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def vertices_por_linea(ruta, lineas):
    """{línea: nube (n,2)} con los vértices de las piezas del color de esa línea"""
    gltf, binario = leer_glb(ruta)
    mats = gltf.get("materials", [])
    acumulado = {l["id"]: [] for l in lineas}
    colores = {l["id"]: hex_rgb(l["color"]) for l in lineas}

    def recorrer(ni, padre):
        n = gltf["nodes"][ni]
        m = mul(padre, matriz_nodo(n))
        if "mesh" in n:
            for prim in gltf["meshes"][n["mesh"]]["primitives"]:
                mi = prim.get("material")
                if mi is None:
                    continue
                base = mats[mi].get("pbrMetallicRoughness", {}).get("baseColorFactor")
                if not base:
                    continue
                col = np.array(base[:3], dtype=float)
                lid, dmin = None, 9.9
                for k, c in colores.items():
                    d = float(np.linalg.norm(col - c))
                    if d < dmin:
                        lid, dmin = k, d
                if lid is None or dmin > 0.30:
                    continue
                ai = prim["attributes"].get("POSITION")
                if ai is None:
                    continue
                for v in acc_posiciones(gltf, binario, ai):
                    x, y, z = aplicar(m, v)
                    if y > 8:          # fuera el nivel de las marquesinas
                        continue
                    acumulado[lid].append((x, -z))
        for h in n.get("children", []):
            recorrer(h, m)

    escena = gltf["scenes"][gltf.get("scene", 0)]
    ident = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    for ni in escena["nodes"]:
        recorrer(ni, ident)
    return {k: np.array(v) for k, v in acumulado.items() if len(v) > 50}


def angulo_eje(nube):
    """dirección del eje principal, en grados, y cuánto manda (relación de ejes)"""
    x = nube[:, 0] - nube[:, 0].mean()
    y = nube[:, 1] - nube[:, 1].mean()
    sxx, syy, sxy = (x * x).mean(), (y * y).mean(), (x * y).mean()
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    tr, det = sxx + syy, sxx * syy - sxy * sxy
    disc = max(0.0, tr * tr / 4 - det)
    l1 = tr / 2 + math.sqrt(disc)
    l2 = tr / 2 - math.sqrt(disc)
    return math.degrees(ang), (l1 / l2 if l2 > 1e-9 else 99.0)


def tunel_linea(metro, linea, lat0, lon0, radio=320):
    """puntos del túnel real de esa línea cerca de la estación, en metros locales"""
    idx = {p["s"] for p in metro["patterns"] if str(p["l"]) == str(linea)}
    pts = []
    for i in sorted(idx):
        trozo = metro["shapes"][i]["pts"]
        for (la1, lo1), (la2, lo2) in zip(trozo, trozo[1:]):
            dx = (lo2 - lo1) * M_PER_DEG_LAT * math.cos(math.radians(lat0))
            dy = (la2 - la1) * M_PER_DEG_LAT
            n = max(1, int(math.hypot(dx, dy) // 6))
            for k in range(n):
                t = k / n
                x = (lo1 + (lo2 - lo1) * t - lon0) * M_PER_DEG_LAT * math.cos(math.radians(lat0))
                y = (la1 + (la2 - la1) * t - lat0) * M_PER_DEG_LAT
                if abs(x) < radio and abs(y) < radio:
                    pts.append((x, y))
    return np.array(pts) if pts else np.zeros((0, 2))


def main():
    metro = json.load(open(os.path.join(RAIZ, "data", "metro.json"), encoding="utf-8"))
    lineas = metro["lines"]
    estaciones = {e["n"]: e for e in metro["stations"]}
    salida = json.load(open(os.path.join(RAIZ, "data", "modelos3d.json"), encoding="utf-8"))

    def llano(t):
        return "".join(c for c in t.lower() if c.isalnum())

    for modelo, nombre in MODELOS.items():
        est = estaciones.get(nombre) or next(
            (e for e in estaciones.values() if llano(e["n"]).startswith(llano(nombre)[:7])), None)
        if not est:
            print(f"!! {modelo}: no encuentro «{nombre}»")
            continue

        vias = vertices_por_linea(os.path.join(GLB, f"{modelo}.glb"), lineas)
        propuestas, detalle = [], []
        for lid, nube in vias.items():
            real = tunel_linea(metro, lid, est["lat"], est["lon"])
            if len(real) < 30:
                continue
            a_mod, exc_mod = angulo_eje(nube)
            a_real, exc_real = angulo_eje(real)
            if exc_mod < 1.2 or exc_real < 1.6:
                continue        # sin eje claro: no sirve para orientar
            giro = (a_real - a_mod) % 180
            propuestas.append(giro)
            detalle.append((lid, round(giro, 1), len(nube), len(real)))

        if not propuestas:
            print(f"!! {modelo}: sin líneas utilizables")
            continue

        dos = [p * 2 for p in propuestas]
        med = (math.degrees(math.atan2(
            sum(math.sin(math.radians(d)) for d in dos),
            sum(math.cos(math.radians(d)) for d in dos))) / 2) % 180
        dispersion = max(abs((p - med + 90) % 180 - 90) for p in propuestas)

        salida[modelo].update({
            "estacion": est["id"],
            "ang": round(med, 1),
            "dispersion": round(dispersion, 1),
            "lineas": len(propuestas),
        })
        print(f"{modelo:16s} giro {med:6.1f}°  (dispersión {dispersion:5.1f}°, "
              f"{len(propuestas)} líneas)")
        for lid, g, nm, nr in detalle:
            print(f"    L{lid:3s} propone {g:6.1f}°   modelo {nm:5d} pts   túnel {nr:5d} pts")

    json.dump(salida, open(os.path.join(RAIZ, "data", "modelos3d.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
