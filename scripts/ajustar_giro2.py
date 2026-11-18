"""Busca el giro de cada modelo 3D que mejor lo encaja sobre los túneles reales.

Método: se proyectan a planta los vértices de vía del modelo (los que llevan el
color de una línea) y los trazados reales del GTFS/OSM. Se rasterizan en una
rejilla de 4 m y se puntúa cada giro por la fracción de vía del modelo que cae
sobre túnel real (dilatado a 12 m, que es el ancho de un túnel con andenes).
El máximo de esa curva es el giro que hay que aplicar.

    python scripts/ajustar_giro.py
"""
import json
import math
import os

import numpy as np

from analizar_glb import GLB, acc_posiciones, aplicar, leer_glb, matriz_nodo, mul

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M_PER_DEG_LAT = 111320.0
CELDA = 4.0
LADO = 260          # celdas -> 1040 m de lado
CENTRO = LADO // 2

MODELOS = {
    "alonso_martinez": "Alonso Martinez",
    "arguelles": "Argüelles",
    "av_america": "Avenida de América",
    "cuatro_caminos": "Cuatro Caminos",
    "nnmm": "Nuevos Ministerios",
    "pl_castilla": "Plaza de Castilla",
    "opera": "Ope",
    "sol": "Puerta del Sol",
}


def hex_rgb(c):
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def vertices_via(ruta, lineas):
    """vértices de las piezas pintadas con color de línea, en planta (este, norte)"""
    gltf, binario = leer_glb(ruta)
    mats = gltf.get("materials", [])
    colores = [hex_rgb(l["color"]) for l in lineas if l.get("color")]
    pts = []

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
                if min(float(np.linalg.norm(col - c)) for c in colores) > 0.30:
                    continue
                ai = prim["attributes"].get("POSITION")
                if ai is None:
                    continue
                for v in acc_posiciones(gltf, binario, ai):
                    x, y, z = aplicar(m, v)
                    if y > 8:
                        continue
                    pts.append((x, -z))
        for h in n.get("children", []):
            recorrer(h, m)

    escena = gltf["scenes"][gltf.get("scene", 0)]
    ident = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    for ni in escena["nodes"]:
        recorrer(ni, ident)
    return np.array(pts) if pts else np.zeros((0, 2))


def raster(nubes, dilatar=1):
    """máscara booleana LADO×LADO con los puntos dados a la rejilla"""
    m = np.zeros((LADO, LADO), dtype=bool)
    for nube in nubes:
        if len(nube) == 0:
            continue
        cx = np.round(nube[:, 0] / CELDA).astype(np.int32) + CENTRO
        cy = np.round(nube[:, 1] / CELDA).astype(np.int32) + CENTRO
        ok = (cx >= 0) & (cx < LADO) & (cy >= 0) & (cy < LADO)
        m[cy[ok], cx[ok]] = True
    for _ in range(dilatar):
        m = m | np.roll(m, 1, 0) | np.roll(m, -1, 0) | np.roll(m, 1, 1) | np.roll(m, -1, 1)
    return m


def tuneles(metro, est, radio=520):
    lat0, lon0 = est["lat"], est["lon"]
    lineas = set(est["l"])
    idx = {p["s"] for p in metro["patterns"] if str(p["l"]) in lineas}
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
    estaciones = {e["n"]: e for e in metro["stations"]}
    salida = json.load(open(os.path.join(RAIZ, "data", "modelos3d.json"), encoding="utf-8"))

    def llano(t):
        return "".join(c for c in t.lower() if c.isalnum())

    for modelo, nombre in MODELOS.items():
        est = estaciones.get(nombre) or next(
            (e for e in estaciones.values() if llano(e["n"]).startswith(llano(nombre))), None)
        if not est:
            print(f"!! {modelo}: no encuentro «{nombre}»")
            continue

        nube = vertices_via(os.path.join(GLB, f"{modelo}.glb"), metro["lines"])
        real = tuneles(metro, est)
        if len(nube) == 0 or len(real) == 0:
            print(f"!! {modelo}: sin datos ({len(nube)} vía / {len(real)} túnel)")
            continue

        m_real = raster([real], dilatar=3)      # 12 m de ancho de túnel
        mejor = (-1.0, 0.0)
        curva = []
        for ang in range(0, 180, 2):
            a = math.radians(ang)
            c, s = math.cos(a), math.sin(a)
            rx = nube[:, 0] * c - nube[:, 1] * s
            ry = nube[:, 0] * s + nube[:, 1] * c
            m_mod = raster([np.column_stack([rx, ry])], dilatar=1)
            total = m_mod.sum()
            acierto = (m_mod & m_real).sum() / max(1, total)
            curva.append((ang, acierto))
            if acierto > mejor[1]:
                mejor = (ang, acierto)
        # refinar grado a grado alrededor del máximo
        for ang in [mejor[0] + d for d in (-1, 1)]:
            a = math.radians(ang)
            c, s = math.cos(a), math.sin(a)
            m_mod = raster([np.column_stack([nube[:, 0] * c - nube[:, 1] * s,
                                             nube[:, 0] * s + nube[:, 1] * c])], dilatar=1)
            acierto = (m_mod & m_real).sum() / max(1, m_mod.sum())
            if acierto > mejor[1]:
                mejor = (ang, acierto)

        ordenada = sorted(curva, key=lambda x: -x[1])
        salida[modelo].update({
            "estacion": est["id"],
            "ang": float(mejor[0] % 360),
            "encaje": round(mejor[1], 3),
        })
        print(f"{modelo:16s} giro {mejor[0]:5.0f}°  encaje {mejor[1]*100:5.1f}%  "
              f"(2º {ordenada[0][0]:3d}° {ordenada[0][1]*100:4.1f}% · "
              f"3º {ordenada[1][0]:3d}° {ordenada[1][1]*100:4.1f}%)")

    json.dump(salida, open(os.path.join(RAIZ, "data", "modelos3d.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
