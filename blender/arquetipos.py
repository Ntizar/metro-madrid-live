"""Genera los modelos de estación en Blender (headless) y los exporta a glTF.

    blender -b -P blender/arquetipos.py

Cada estación del metro de Madrid es una de seis tipologías. Se modelan una vez,
paramétricas (largo del andén, número de andenes, niveles) y el visor las coloca
en su sitio con la posición y el ángulo reales de OpenStreetMap.

Salida: blender/salida/estacion_<tipo>_<largo>.glb
Unidades: metros. En Blender Z es arriba; el exportador glTF lo pasa a Y arriba.
"""
import math
import os

import bpy

AQUI = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(AQUI, "salida")
LARGOS = (60, 90, 110)      # los tres largos de andén de la red
ANCHO_ANDEN = 8.0
ALTO_ANDEN = 1.15


# ───────────────────────────────── materiales ─────────────────────────────────
def material(nombre, color, emision=0.0, alfa=1.0):
    m = bpy.data.materials.get(nombre)
    if m:
        return m
    m = bpy.data.materials.new(nombre)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.85
    bsdf.inputs["Metallic"].default_value = 0.0
    if emision:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emision
    if alfa < 1.0:
        bsdf.inputs["Alpha"].default_value = alfa
        m.blend_method = 'BLEND'
    return m


def aplicar(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def caja(nombre, largo, ancho, alto, x=0, y=0, z=0, mat=None, rot=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, z))
    o = bpy.context.object
    o.name = nombre
    o.scale = (largo / 2, ancho / 2, alto / 2)
    if rot:
        o.rotation_euler[2] = rot
    if mat:
        aplicar(o, mat)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return o


def cilindro(nombre, radio, largo, x=0, y=0, z=0, mat=None, caras=20, alfa=1.0):
    bpy.ops.mesh.primitive_cylinder_add(vertices=caras, radius=radio, depth=largo,
                                        location=(x, y, z), rotation=(0, math.pi / 2, 0))
    o = bpy.context.object
    o.name = nombre
    if mat:
        aplicar(o, mat)
    return o


# ───────────────────────────────── piezas ─────────────────────────────────
def anden(L, ancho, mat_and, mat_borde, x=0, y=0, z=0):
    """plataforma con el borde de seguridad marcado"""
    caja(f"anden_{x:.0f}", L, ancho, ALTO_ANDEN, x, y, z + ALTO_ANDEN / 2, mat_and)
    # franja del borde: la línea blanca que se ve desde arriba
    caja(f"borde_{x:.0f}", L, 0.45, 0.06, x, y + ancho / 2 - 0.3,
         z + ALTO_ANDEN + 0.01, mat_borde)
    caja(f"borde2_{x:.0f}", L, 0.45, 0.06, x, y - ancho / 2 + 0.3,
         z + ALTO_ANDEN + 0.01, mat_borde)


def via(L, y, mat):
    caja(f"via_{y:.0f}", L, 2.6, 0.22, 0, y, -0.11, mat)
    for dy in (-0.72, 0.72):
        caja(f"carril_{y:.0f}_{dy:.1f}", L, 0.14, 0.14, 0, y + dy, 0.02, mat)


def boveda(L, ancho_total, mat):
    """el túnel: media caña por encima de las vías"""
    o = cilindro("boveda", ancho_total / 2, L + 16, 0, 0, ALTO_ANDEN - 0.1, mat)
    # media caña: se corta por debajo del andén
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -6))
    corte = bpy.context.object
    corte.scale = (L + 20, ancho_total + 4, 12)
    bpy.ops.object.transform_apply(scale=True)
    mod = o.modifiers.new("corte", 'BOOLEAN')
    mod.object = corte
    mod.operation = 'DIFFERENCE'
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier="corte")
    bpy.data.objects.remove(corte, do_unlink=True)
    return o


def escalera(x, y, ancho, mat):
    """tramo de escalones que sube desde el andén"""
    alto, huella = 0.28, 0.34
    for i in range(14):
        caja(f"escalon_{x:.0f}_{i}", huella * 2, ancho, alto,
             x + i * huella, y, alto / 2 + i * alto, mat)


def vestibulo(L, ancho, mat):
    caja("vestibulo", L, ancho, 3.2, 0, 0, 7.5, mat)
    for dx in (-L / 3, L / 3):
        caja("pilar", 0.9, 0.9, 6.0, dx, 0, 3.0, mat)


# ───────────────────────────────── tipologías ─────────────────────────────────
def tipo_lateral(L, mats):
    """dos andenes laterales, una vía por lado: la estación de toda la vida"""
    anden(L, ANCHO_ANDEN, mats["and"], mats["borde"], 0, 7.0)
    anden(L, ANCHO_ANDEN, mats["and"], mats["borde"], 0, -7.0)
    via(L, 2.7, mats["via"])
    via(L, -2.7, mats["via"])
    boveda(L, 26, mats["tunel"])
    escalera(0, 7.0, 3.0, mats["and"])


def tipo_central(L, mats):
    """andén central entre las dos vías"""
    anden(L, 10.0, mats["and"], mats["borde"], 0, 0)
    via(L, 6.6, mats["via"])
    via(L, -6.6, mats["via"])
    boveda(L, 24, mats["tunel"])
    escalera(0, 0, 3.2, mats["and"])


def tipo_paralelo(L, mats):
    """dos andenes laterales con un espacio central (andenes paralelos)"""
    anden(L, ANCHO_ANDEN, mats["and"], mats["borde"], 0, 9.5)
    anden(L, ANCHO_ANDEN, mats["and"], mats["borde"], 0, -9.5)
    via(L, 4.2, mats["via"])
    via(L, -4.2, mats["via"])
    boveda(L, 30, mats["tunel"])
    escalera(-L / 4, 0, 3.0, mats["and"])
    caja("pasillo", 3.2, 11.0, 3.0, -L / 4, 0, 1.6, mats["and"])


def tipo_tresbolillo(L, mats):
    """tres andenes: el central compartido (andén tresbolillo)"""
    anden(L, ANCHO_ANDEN, mats["and"], mats["borde"], 0, 11.0)
    anden(L, 12.0, mats["and"], mats["borde"], 0, 0)
    anden(L, ANCHO_ANDEN, mats["and"], mats["borde"], 0, -11.0)
    via(L, 5.0, mats["via"])
    via(L, -5.0, mats["via"])
    boveda(L, 34, mats["tunel"])


def tipo_dos_niveles(L, mats):
    """transbordo: dos andenes paralelos en dos cotas, unidos por un vestíbulo"""
    anden(L, ANCHO_ANDEN, mats["and"], mats["borde"], 0, 8.0, 0)
    via(L, 3.0, mats["via"])
    # nivel inferior
    anden(L, ANCHO_ANDEN, mats["and"], mats["borde"], 0, 8.0, -7.0)
    via(L, 18.0, mats["via"])
    vestibulo(L * 0.6, 14, mats["and"])
    escalera(-L / 5, 8.0, 3.0, mats["and"])
    escalera(L / 5, 8.0, 3.0, mats["and"])


def tipo_elevada(L, mats):
    """sin túnel: el andén va en trinchera o sobre viaducto"""
    anden(L, ANCHO_ANDEN, mats["and"], mats["borde"], 0, 7.0)
    anden(L, ANCHO_ANDEN, mats["and"], mats["borde"], 0, -7.0)
    via(L, 2.7, mats["via"])
    via(L, -2.7, mats["via"])
    for dx in (-L / 2.5, 0, L / 2.5):
        caja("marquesina", 12, 26, 0.4, dx, 0, 5.4, mats["techo"])
        for dy in (-11, 11):
            caja("poste", 0.5, 0.5, 5.2, dx, dy, 2.6, mats["via"])


TIPOS = {
    "lateral": tipo_lateral,
    "central": tipo_central,
    "paralelo": tipo_paralelo,
    "tresbolillo": tipo_tresbolillo,
    "dos_niveles": tipo_dos_niveles,
    "elevada": tipo_elevada,
}


def main():
    os.makedirs(SALIDA, exist_ok=True)
    mats = {
        "and": material("anden", (0.78, 0.79, 0.81), 0.05),
        "borde": material("borde", (1.0, 1.0, 1.0), 1.2),
        "via": material("via", (0.16, 0.17, 0.19)),
        "tunel": material("tunel", (0.30, 0.32, 0.36), alfa=0.10),
        "techo": material("techo", (0.55, 0.57, 0.62), alfa=0.7),
    }
    hechos = 0
    for tipo, fn in TIPOS.items():
        for L in LARGOS:
            bpy.ops.wm.read_factory_settings(use_empty=True)
            # los materiales se recrean tras vaciar la escena
            mats = {
                "and": material("anden", (0.78, 0.79, 0.81), 0.05),
                "borde": material("borde", (1.0, 1.0, 1.0), 1.2),
                "via": material("via", (0.16, 0.17, 0.19)),
                "tunel": material("tunel", (0.30, 0.32, 0.36), alfa=0.10),
                "techo": material("techo", (0.55, 0.57, 0.62), alfa=0.7),
            }
            fn(float(L), mats)
            ruta = os.path.join(SALIDA, f"estacion_{tipo}_{L}.glb")
            bpy.ops.export_scene.gltf(
                filepath=ruta, export_format='GLB',
                export_apply=True, export_yup=True,
                export_cameras=False, export_lights=False,
            )
            kb = os.path.getsize(ruta) / 1024
            print(f"{os.path.basename(ruta):34s} {kb:6.1f} KB")
            hechos += 1
    print(f"\n{hechos} modelos en {SALIDA}")


if __name__ == "__main__":
    main()
