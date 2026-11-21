# Cotas del visor: cada vía pasa por su andén

**2026-11-18** · `metro-madrid-live`

## El fallo

Cada línea se dibujaba plana a una profundidad fija y el andén de un
intercambiador se plantaba a la profundidad de su línea *más profunda*. Resultado:
en Plaza de Castilla la vía de L1 (18 m) pasaba 13 m por encima del andén (31 m),
y los trenes, dibujados a la cota de su línea, tampoco caían sobre la plataforma.
En total 49 pares estación-línea con desajuste, hasta 15 m.

## El contrato que queda

1. **Una cota por estación**: media de las profundidades base de sus líneas,
   redondeada a 0,5 m (`stations[].cota`). Todas las vías de un intercambiador
   y su andén comparten cota.
2. **Un perfil de cota por trazado** (`perfiles[shape]` = `[[s_m, cota], ...]`):
   meseta plana centrada en la proyección del centro de la estación sobre la vía
   y rampa suavizada (smoothstep) entre estaciones. La meseta es imprescindible:
   la vía no puede ir en rampa justo debajo del andén.
3. **Una sola fuente**: `build_datos.py` calcula el perfil; el visor y
   `verificar_cotas.py` solo lo leen. Nada de recalcular cotas en el navegador.
4. **Tolerancia**: 0,5 m. `python3 scripts/verificar_cotas.py` debe dar 0
   desajustes en los 291 pares estación-línea.

## Trampas encontradas

- **RDP sobre un anillo**: con inicio == fin la cuerda es degenerada y
  `rdp()` devuelve solo 2 puntos. La L12 (MetroSur, circular) se quedaba sin
  trazado y se reconstruía a mano con un camino de 74 km que se doblaba sobre
  sí mismo. `rdp_anillo()` parte el anillo por el punto más lejano al inicio.
- **Perfiles mezclados por dirección**: si un mismo `shape` lo usan las dos
  direcciones (caso de la L3 reconstruida), las paradas llegan invertidas y las
  cotas se cruzan en las mismas distancias. Se construye el perfil solo desde la ida.
- **Cota del andén ≠ cota del eje de la estación**: proyectar el centroide
  fusionado de una estación da diferencias de 150-300 m con la parada del GTFS.
  Por eso la meseta se centra en la proyección del centroide (el punto donde el
  visor planta el andén), no en la parada.
- **Exageración vertical**: con cotas reales, ×200 convierte una pendiente real
  del 2,8 % en un muro de 83°. Por defecto ahora ×80 (`?exag=N` para ajustar).

## Verificación

Navegador real (chrome-headless + swiftshader) sobre la URL publicada: 328
andenes a su cota, los 291 pares estación-línea con el vértice de vía más
cercano a 0,00 m del andén, sin errores de consola.
