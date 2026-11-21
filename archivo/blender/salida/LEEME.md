# Arquetipos de estación

18 GLB: 6 tipologías × 3 largos de andén (60, 90 y 110 m). Generados con
`blender -b -P blender/arquetipos.py`.

## Calibración contra 36 intercambiadores reales

Se midieron 36 modelos de estaciones de otras ciudades (París, Londres, Berlín,
Barcelona, Toronto, Estocolmo, Budapest, Montreal, Roma, Viena, Bucarest), cuyas
fichas están en `data/referencias_ciudades.json`:

- **Niveles por estación:** mediana 3, media 3.1, máximo 7 (T-Centralen).
- **Separación vertical entre niveles:** mediana 6.5 m, rango 3,5-30 m.
- **Huella mayor:** mediana 274 m (entre 87 y 760 m).

Los arquetipos usan **7,0 m** entre niveles en `dos_niveles`, dentro del rango real y
a un paso de la mediana medida (6.5 m). El ancho de andén de 8 m y el
alto de 1,15 m no se han podido contrastar con estas fichas (los modelos no separan
el andén del resto de la losa), así que siguen siendo valores de partida.

Estos 36 modelos **no se colocan en el mapa**: son maquetas de otras redes y sólo
sirven como referencia de proporciones. Viven en `referencias/`, fuera del repo.
