"""Dibuja, para cada modelo, su vía (rojo) y los túneles reales (azul) en planta.
Una imagen por estación: si el modelo está bien orientado, rojo y azul coinciden.

    python scripts/dibujar_encaje.py
"""
import json
import math
import os

import numpy as np

from ajustar_glb_util import vertices_via, tuneles, CELDA, LADO, CENTRO
from analizar_glb import GLB

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(RAIZ, "preview-encaje")


def png(ruta, capas, lado=LADO):
    """capas: [(mask_bool, (r,g,b))] -> PNG sin dependencias"""
    import struct
    import zlib
    img = np.zeros((lado, lado, 3), dtype=np.uint8)
    img[:, :] = (12, 14, 18)
    for mask, color in capas:
        img[mask] = color
    # PNG en escala de grises->RGB, fila a fila
    filas = b"".join(b"\x00" + img[y].tobytes() for y in range(lado))

    def chunk(tipo, datos):
        return (struct.pack(">I", len(datos)) + tipo + datos +
                struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF))

    cabecera = struct.pack(">IIBBBBB", lado, lado, 8, 2, 0, 0, 0)
    datos = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", cabecera) +
             chunk(b"IDAT", zlib.compress(filas, 6)) + chunk(b"IEND", b""))
    open(ruta, "wb").write(datos)


def main():
    os.makedirs(SALIDA, exist_ok=True)
    metro = json.load(open(os.path.join(RAIZ, "data", "metro.json"), encoding="utf-8"))
    info = json.load(open(os.path.join(RAIZ, "data", "modelos3d.json"), encoding="utf-8"))
    estaciones = {e["id"]: e for e in metro["stations"]}

    for modelo, m in info.items():
        if not m.get("estacion"):
            continue
        est = estaciones.get(m["estacion"])
        if not est:
            continue
        nube = vertices_via(os.path.join(GLB, f"{modelo}.glb"), metro["lines"])
        real = tuneles(metro, est)
        if len(nube) == 0 or len(real) == 0:
            continue
        from ajustar_glb_util import raster
        m_real = raster([real], dilatar=2)
        # sin girar y con el giro calculado, una al lado de la otra
        for etiqueta, ang in (("0", 0.0), ("giro", float(m.get("ang") or 0))):
            a = math.radians(ang)
            c, s = math.cos(a), math.sin(a)
            girada = np.column_stack([nube[:, 0] * c - nube[:, 1] * s,
                                      nube[:, 0] * s + nube[:, 1] * c])
            m_mod = raster([girada], dilatar=1)
            png(os.path.join(SALIDA, f"{modelo}_{etiqueta}.png"),
                [(m_real, (40, 90, 210)), (m_mod, (235, 60, 70))])
        print("ok", modelo)


if __name__ == "__main__":
    main()
