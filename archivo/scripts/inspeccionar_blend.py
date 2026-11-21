"""Inspecciona los .blend originales de las 8 estaciones de Madrid.

Saca lo que el GLB no dice: unidades de la escena, colecciones, y el ancho real
de los andenes (para dejar de inventarse el del arquetipo).

    LD_LIBRARY_PATH=~/.local/blender/libs/usr/lib/x86_64-linux-gnu \\
    ~/.local/blender/blender-4.2.15-linux-x64/blender -b archivo.blend -P inspeccionar_blend.py
"""
import json
import os
import sys

import bpy
from mathutils import Vector

DATOS = []


def dims(obj):
    return tuple(round(v, 2) for v in obj.dimensions)


def main():
    esc = bpy.context.scene
    escena = {
        "fichero": os.path.basename(bpy.data.filepath),
        "unidad_escala": round(esc.unit_settings.scale_length, 4),
        "unidad_sistema": esc.unit_settings.system,
        "colecciones": [c.name for c in bpy.data.collections],
        "objetos": len(bpy.data.objects),
        "mallas": len([o for o in bpy.data.objects if o.type == "MESH"]),
    }

    # caja total de la escena
    xs, ys, zs = [], [], []
    andenes = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        for c in o.bound_box:
            v = o.matrix_world @ Vector(c)
            xs.append(v.x)
            ys.append(v.y)
            zs.append(v.z)
        nombre = o.name.lower()
        if any(k in nombre for k in ("anden", "andén", "plataforma", "platform")):
            andenes.append({
                "objeto": o.name,
                "dimensiones": dims(o),
                # el ancho es la dimensión menor de la planta
                "ancho": round(min(o.dimensions.x, o.dimensions.y), 2),
                "largo": round(max(o.dimensions.x, o.dimensions.y), 2),
            })
    if xs:
        escena["caja"] = {
            "x": round(max(xs) - min(xs), 1),
            "y": round(max(ys) - min(ys), 1),
            "z": round(max(zs) - min(zs), 1),
            "min_z": round(min(zs), 1),
            "max_z": round(max(zs), 1),
        }
    escena["andenes"] = andenes
    escena["nombres"] = sorted(o.name for o in bpy.data.objects)[:60]

    DATOS.append(escena)
    with open(os.environ.get("SALIDA_JSON", "/tmp/blend_datos.json"), "w", encoding="utf-8") as f:
        json.dump(DATOS, f, ensure_ascii=False, indent=1)
    print(f"== {escena['fichero']} unidad={escena['unidad_escala']} "
          f"caja={escena.get('caja')} andenes={len(andenes)}")


main()
