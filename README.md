# Metro de Madrid · gemelo digital

Visor 3D de la red de Metro de Madrid construido sobre el **catálogo funcional r2** (21-11-2026):
560 tramos dirigidos, 587 andenes y 242 estaciones con sus cotas de railhead, **dibujados tal cual
los produce el catálogo** (sin recálculo). Encima, los **240 modelos reales de estación**
(reconstrucción desde croquis de Albert Guillaumes) anclados por grupos de línea a su andén.

**En vivo:** https://ntizar.github.io/metro-madrid-live/  
Versiones: `/archivo/` (planos por tipologías + 268 fichas) · `/gemelo/` (variante con LiDAR y GTFS del CRTM)

## El encaje, medido

| Cifra | Valor |
|---|---|
| Estaciones emparejadas | 240/240 (por `catalogue_ids` ↔ `station_ids`) |
| Grupos por línea colocados sobre su andén | 503 (los GLB traen las piezas marcadas por línea) |
| Giro mediano al rumbo del andén | **1,2°** |
| Modelo | RÍGIDO: sin deformación; el pozo hasta la calle lo dibuja el visor |

## Estructura

```
index.html  app.js           el visor (three.js r170, 1 malla por estaciones, 13 por líneas)
datos/red.json              red del catálogo r2: 560 tramos + 242 estaciones + andenes (6 MB)
datos/estaciones.bin        los 240 modelos encajados al marco del catálogo (10 MB)
datos/trenes/*.glb          flota del catálogo: 3000 (estrecho), 9000 (ancho), 9700 (L9)
scripts/anclar_funcional.py el encaje: por grupos de línea, ancla al punto medio del andén
```

## Fuentes y límites

En el propio visor (botón «El proyecto»): catálogo funcional sobre datos del **CRTM**, croquis de
**Albert Guillaumes**, flota del catálogo, movimiento simulado (no es horario). Los límites que el
catálogo declara (cotas estimadas, desvíos locales hasta 35,75 m) están en la ficha modal.

