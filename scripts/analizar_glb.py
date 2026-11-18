"""Lee los GLB de las 8 estaciones de Madrid y saca su huella, su centro y el
ángulo dominante en planta, para poder colocarlos en el mapa con la orientación
correcta.

GlTF guarda las posiciones en Y-arriba; aquí se pasan a (este, norte) = (x, z)
con la Z del glTF negada, que es el mismo convenio que usa el visor.

    python scripts/analizar_glb.py
"""
import json
import math
import os
import struct

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLB = os.path.join(RAIZ, "assets", "modelos3d")


def leer_glb(ruta):
    with open(ruta, "rb") as f:
        datos = f.read()
    assert datos[:4] == b"glTF", ruta
    _, _version, _total = struct.unpack("<III", datos[:12])
    pos, i = 12, {}
    chunks = []
    while pos < len(datos):
        largo, tipo = struct.unpack("<II", datos[pos:pos + 8])
        chunks.append((tipo, datos[pos + 8:pos + 8 + largo]))
        pos += 8 + largo
    gltf = json.loads([c for t, c in chunks if t == 0x4E4F534A][0])
    binario = b""
    for t, c in chunks:
        if t == 0x004E4942:
            binario = c
            break
    return gltf, binario


def matriz_nodo(n):
    """matriz local de un nodo glTF, a partir de matrix o de TRS"""
    if "matrix" in n:
        m = n["matrix"]
        return [[m[0], m[4], m[8], m[12]], [m[1], m[5], m[9], m[13]],
                [m[2], m[6], m[10], m[14]], [m[3], m[7], m[11], m[15]]]
    t = n.get("translation", [0, 0, 0])
    r = n.get("rotation", [0, 0, 0, 1])
    s = n.get("scale", [1, 1, 1])
    x, y, z, w = r
    rot = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    return [
        [rot[0][0] * s[0], rot[0][1] * s[1], rot[0][2] * s[2], t[0]],
        [rot[1][0] * s[0], rot[1][1] * s[1], rot[1][2] * s[2], t[1]],
        [rot[2][0] * s[0], rot[2][1] * s[1], rot[2][2] * s[2], t[2]],
        [0, 0, 0, 1],
    ]


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def aplicar(m, p):
    return [sum(m[i][k] * (p[k] if k < 3 else 1.0) for k in range(4)) for i in range(3)]


def acc_posiciones(gltf, binario, idx):
    acc = gltf["accessors"][idx]
    bv = gltf["bufferViews"][acc["bufferView"]]
    off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    n = acc["count"]
    comp = {5126: ("f", 4), 5123: ("H", 2), 5125: ("I", 4), 5121: ("B", 1)}[acc["componentType"]]
    nc = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    fmt = "<" + comp[0] * nc
    paso = bv.get("byteStride") or comp[1] * nc
    salida = []
    for i in range(n):
        p = off + i * paso
        salida.append(struct.unpack_from(fmt, binario, p))
    return salida


def recolectar(gltf, binario):
    """todos los vértices en coordenadas de escena (x, y, z glTF)"""
    puntos = []

    def recorrer(ni, padre):
        n = gltf["nodes"][ni]
        m = mul(padre, matriz_nodo(n))
        if "mesh" in n:
            for prim in gltf["meshes"][n["mesh"]]["primitives"]:
                ai = prim["attributes"].get("POSITION")
                if ai is None:
                    continue
                for v in acc_posiciones(gltf, binario, ai):
                    puntos.append(aplicar(m, v))
        for h in n.get("children", []):
            recorrer(h, m)

    escena = gltf["scenes"][gltf.get("scene", 0)]
    ident = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    for ni in escena["nodes"]:
        recorrer(ni, ident)
    return puntos


def pca_planta(puntos):
    """ángulo del eje principal en el plano (este=x, norte=-z) y su excentricidad"""
    xs = [p[0] for p in puntos]
    zs = [-p[2] for p in puntos]      # norte
    mx, mz = sum(xs) / len(xs), sum(zs) / len(zs)
    sxx = sum((x - mx) ** 2 for x in xs) / len(xs)
    szz = sum((z - mz) ** 2 for z in zs) / len(zs)
    sxz = sum((x - mx) * (z - mz) for x, z in zip(xs, zs)) / len(xs)
    ang = 0.5 * math.atan2(2 * sxz, sxx - szz)
    # autovalores para saber cuánto manda el eje
    tr, det = sxx + szz, sxx * szz - sxz ** 2
    disc = max(0.0, tr * tr / 4 - det)
    l1 = tr / 2 + math.sqrt(disc)
    l2 = tr / 2 - math.sqrt(disc)
    return math.degrees(ang), (l1 / l2 if l2 > 1e-9 else float("inf"))


def main():
    salida = {}
    for f in sorted(os.listdir(GLB)):
        if not f.endswith(".glb"):
            continue
        ruta = os.path.join(GLB, f)
        gltf, binario = leer_glb(ruta)
        pts = recolectar(gltf, binario)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        zs = [-p[2] for p in pts]
        ang, exc = pca_planta(pts)
        salida[f[:-4]] = {
            "vertices": len(pts),
            "ancho": round(max(xs) - min(xs), 2),
            "alto": round(max(ys) - min(ys), 2),
            "fondo": round(max(zs) - min(zs), 2),
            "cx": round((max(xs) + min(xs)) / 2, 2),
            "cz": round((max(zs) + min(zs)) / 2, 2),
            "y0": round(min(ys), 2),
            "ang": round(ang, 1),
            "excentricidad": round(exc, 2),
        }
        s = salida[f[:-4]]
        print(f"{f[:-4]:16s} {s['vertices']:7d} v  {s['ancho']:7.1f} x {s['fondo']:7.1f} m  "
              f"alto {s['alto']:5.1f}  centro ({s['cx']:7.1f}, {s['cz']:7.1f})  "
              f"eje {s['ang']:6.1f}°  exc {s['excentricidad']:5.2f}")
    json.dump(salida, open(os.path.join(RAIZ, "data", "modelos3d.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
