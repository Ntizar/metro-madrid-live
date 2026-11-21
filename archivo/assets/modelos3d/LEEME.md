# Modelos 3D de las estaciones

Los 8 modelos de los intercambiadores de Madrid vienen de **estacions.albertguillaumes.cat**
(Autor: Albert Guillaumes Marcer, 2020). David Antizar cuenta con su permiso para este uso.

Son representaciones **esquemáticas de la topología** de cada estación (andenes, vías y
pasillos de transbordo), **no modelos arquitectónicos del edificio**. No llevan texturas:
usan colores planos, uno por línea.

| Fichero | Estación | Huella (m) | Alto (m) |
|---|---|---|---|
| alonso_martinez.glb | Alonso Martínez | 219 × 163 | 31 |
| arguelles.glb | Argüelles | 232 × 208 | 40 |
| av_america.glb | Avenida de América | 377 × 198 | 48 |
| cuatro_caminos.glb | Cuatro Caminos | 178 × 233 | 66 |
| nnmm.glb | Nuevos Ministerios | 383 × 390 | 40 |
| pl_castilla.glb | Plaza de Castilla | 445 × 258 | 34 |
| opera.glb | Ópera | 88 × 109 | 21 |
| sol.glb | Sol | 330 × 468 | 50 |

## Qué son de verdad

Abiertos los `.blend` originales (`referencias/blend/`, fuera del repo) se ve lo que son:
**el dibujo axonométrico del autor extruido a 3D**, no un modelo arquitectónico. Los objetos
se llaman `path`, `rect` y `Text`, los materiales son `SVGMat.*`, y 19 de las 49 mallas de
Ópera tienen la planta de arriba idéntica a la de abajo (firma de una extrusión), con
espesores de 1 m de mediana.

Consecuencias, que conviene tener claras:

- La escena está en **metros** (`unit_settings.scale_length = 1.0`): la escala es real.
- Las **cotas relativas** entre niveles son coherentes (el dibujo baja 12 m en Ópera y 58 en
  Cuatro Caminos desde la superficie), pero **no son un levantamiento**: son el resultado de
  extruir un dibujo en perspectiva.
- Por eso no sirve para medir anchos de andén ni alturas libres. Datos por estación en
  `data/blend_origen.json`.

## Colocación

Cada modelo se coloca en el punto de su estación (lat/lon del CRTM) y se gira y desplaza
según el resultado de `scripts/encajar_modelos.py`, que encaja su huella de vías con los
túneles reales del GTFS/OSM por correlación (giro + desplazamiento, medido en `encaje`).

Cuando el encaje no es concluyente (< 65 % o desplazamiento > 80 m) se deja el modelo con
giro 0 y sin desplazamiento: la web del autor no documenta ejes ni escala, y los modelos
parecen estar orientados al norte. Esas estaciones van marcadas con `giro_confiable: false`
en `data/modelos3d.json`.

**La escala no está validada contra un plano oficial.** Las magnitudes son plausibles
(huellas de 88 a 468 m) pero el autor no documenta escala.

## Cómo se regeneran los ajustes

```
python scripts/analizar_glb.py      # mide cada modelo (huella, centro, alto)
python scripts/encajar_modelos.py   # giro y desplazamiento contra los túneles reales
```
