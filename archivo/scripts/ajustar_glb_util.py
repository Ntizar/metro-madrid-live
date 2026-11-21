"""Utilidades compartidas: vértices de vía del modelo, túneles reales y rejilla."""
import math
import os

import numpy as np

from analizar_glb import GLB, acc_posiciones, aplicar, leer_glb, matriz_nodo, mul

M_PER_DEG_LAT = 111320.0
CELDA = 4.0
LADO = 260
CENTRO = LADO // 2


def hex_rgb(c):
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def vertices_via(ruta, lineas):
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


def raster(nubes, dilatar=1):
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
