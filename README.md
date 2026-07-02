# Personas reportadas tras el terremoto de Venezuela (2026)

Tras los terremotos del 24 de junio de 2026 (magnitudes 7.2 y 7.5, epicentro cerca de la costa
del estado La Guaira), miles de personas fueron reportadas como desaparecidas en registros
ciudadanos. Este proyecto **consolida esos reportes en cifras por persona** —quiénes se buscan,
quiénes aparecieron, su sexo y su edad— y las publica en una **infografía trilingüe**
(español · English · français) pensada para prensa, organizaciones humanitarias y público general.

## 📊 La infografía

**[Ver la infografía →](https://htmlpreview.github.io/?https://github.com/juanacasique/venezuela-missing-persons-dedup/blob/main/docs/infografia_2026-07-01.html)**

Contiene: panorama general, cifras clave, qué implican los datos, tendencia entre cortes,
composición por sexo y edad, **tres pirámides poblacionales** (aún buscadas · encontradas o a
salvo · ingresos a hospitales y refugios) y localidades. Funciona en teléfono y computadora,
sin conexión a servicios externos.

> El archivo se llama `docs/infografia_<fecha>.html` — cada actualización genera un corte nuevo
> con su fecha y hora (hora de Venezuela, UTC−4) selladas en la cabecera.

## Qué dicen los datos (corte del 1 de julio de 2026)

- **46.471 personas** en el registro: **40.557 aún se buscan** (87%) y **5.914** fueron
  encontradas o están a salvo.
- De quienes aún se buscan, el **48% son mujeres**, frente a un **41% de hombres**; del **11%**
  restante no se conoce el sexo. Ninguna cifra debe leerse como "el resto".
- Entre las personas buscadas hay **4.036 niñas, niños y adolescentes** y **6.407 personas
  mayores de 60 años** — los grupos que suelen requerir atención prioritaria.
- Las mujeres adultas (35–54 años) son las más sobrerrepresentadas: **5.231 mujeres frente a
  4.150 hombres** aún buscadas en esas edades.
- Por separado, **17.946 personas** figuran en listas comunitarias de ingreso a hospitales y
  refugios. Aparecer en una lista **no confirma** que la persona esté a salvo.
- Los reportes se concentran en la franja costera de La Guaira (La Guaira, Catia La Mar,
  Caraballeda, Caribe…).

*Las cifras cambian con cada corte; la infografía vigente siempre manda.*

## Cómo leer estas cifras (importante para publicar)

1. **No es un censo de víctimas ni una cifra oficial.** Son reportes ciudadanos **sin verificar**,
   de una sola fuente (en expansión). Úsense como información **indicativa** y contrástense con
   fuentes oficiales antes de publicar conclusiones.
2. **Una fila = una persona, no un reporte.** Los datos llegan ya de-duplicados en origen: una
   ficha canónica por persona, aunque la hayan reportado varios familiares.
3. **El sexo y la edad se infieren cuando no fueron reportados** (por el nombre y la descripción,
   nunca inventados). La inferencia se validó: coincide **98,7%** con los casos donde el dato sí
   fue reportado. Aun así, úsese en el agregado, no para casos individuales.
4. **La incertidumbre se muestra, no se rellena:** las categorías "sin dato" aparecen en todas
   las gráficas. Cada porcentaje es un piso, no un techo.
5. **Datos sensibles.** El registro contiene información personal de población vulnerable. Este
   repositorio publica **solo código y agregados**; úsese únicamente para apoyar la localización
   de personas.

## Fuente de los datos

**Venezuela Reporta** — [venezuelareporta.org](https://venezuelareporta.org), vía su
[API abierta](https://venezuelareporta.org/api-abierta) (`/api/v1/personas` y `/api/v1/ingresos`),
con datos de-duplicados en origen. La atribución "Venezuela Reporta — venezuelareporta.org" es
obligatoria al reutilizar estos datos. Se integrarán otras bases; las cifras crecerán al sumar
nuevas fuentes.

## Autoría y créditos

Proyecto apoyado por el **[Observatorio Latinoamericano de Desarrollo Sostenible
(OLDS2030)](https://www.olds2030.org/)** y la red **Todos con Venezuela**.

- **[Juana Casique](https://github.com/juanacasique)** — análisis, pipeline de la API e infografía
  · [jcasique@kognis.org](mailto:jcasique@kognis.org)
- **[Alberto Castillo Aroca](https://github.com/alcastaro)** — trabajo original de deduplicación
  e inferencia del que se bifurca este proyecto.

Contacto de prensa: [jcasique@kognis.org](mailto:jcasique@kognis.org).

---

## Detalles técnicos

### Instalación

```bash
pip install -r requirements.txt   # Python 3.10+ · pandas, requests, rapidfuzz
```

### Pipeline principal (API abierta)

```bash
python3 api_extractor.py                       # baja /personas → data/raw/api_personas.csv
python3 api_extractor.py --endpoint ingresos   # baja /ingresos → data/raw/api_ingresos.csv
python3 analizar_api.py                        # infiere sexo/edad, pirámides → data/processed/
python3 infografia_api_gen.py                  # genera docs/infografia_<fecha>.html
```

- La API entrega máx. 100 registros por página (120 req/min); el extractor pagina y re-intenta.
- `/ingresos` trae `id` repetidos (misma persona en varias listas) — se conserva una fila por `id`.
- `/ingresos` no trae sexo: se infiere escaneando todos los tokens del nombre contra el gazetteer
  (los nombres vienen APELLIDO-primero, la morfología -a/-o no sirve ahí).
- `infografia_api_gen.py` guarda un snapshot agregado por fecha en `docs/api_snapshots.json`
  (sin datos personales) para calcular la sección de tendencia.

### Inferencia de sexo y edad

100% offline y determinista, sin LLM ni red. **Sexo:** reportado → gazetteer
(`nombres_genero.csv`) → morfología del nombre → descripción. **Edad:** reportada → descripción →
vacío si no hay señal (nunca inventada). Grupos de edad estándar UN OCHA: `0-4`, `5-17`, `18-59`,
`60+`. Validación: 98,7% de coincidencia contra los casos con sexo reportado.
Ver `docs/plan_inferir_atributos.md`.

### Pipeline de respaldo (deduplicación propia)

Antes de existir la API, los reportes crudos (con duplicados) se deduplicaban aquí. El código se
conserva por si la API deja de estar disponible y como referencia metodológica:

```bash
python3 deduplicar.py --input data/raw/reportes.csv --output-dir data/processed
python3 deduplicar.py --incremental            # solo procesa reportes nuevos
python3 inferir_atributos.py                   # inferencia sobre el resultado
python3 infografia_gen.py                      # infografía del pipeline viejo
```

Criterio **conservador**: para personas desaparecidas, fusionar de más (juntar personas distintas)
es peor que dejar duplicados. Cédulas válidas distintas nunca se fusionan; el nombre solo no basta
(exige corroboración por edad, género o ubicación específica); ningún cluster puede contener dos
cédulas distintas. Bloqueo por cédula/teléfono/prefijo + `rapidfuzz` para evitar comparar N².
Ver `docs/plan_deduplicacion.md`.

Entrada mínima del CSV: `uuid, nombre, ubicacion, estado` (cédula, teléfonos, edad, género y foto
mejoran la precisión). Salidas: `reportes_dedup.csv` (todas las filas + `cluster_id`),
`personas_unicas.csv` (una fila por persona), `pares_revisar.csv` (confianza media, para revisión
humana).

### Webscraping (no publicado)

El sistema de recolección se mantiene privado a propósito: evitar que muchas personas lo ejecuten
en paralelo y sobrecarguen un registro humanitario que debe seguir disponible para quien busca a
un familiar. La recolección se hace de forma controlada; hoy la vía principal es la API abierta.

### Archivos

| Archivo | Descripción |
|---|---|
| `api_extractor.py` | Descarga `/personas` e `/ingresos` de la API abierta |
| `analizar_api.py` | Inferencia sexo/edad + pirámides + estadísticas (`data/processed/api_*`) |
| `infografia_api_gen.py` | Genera `docs/infografia_<fecha>.html` (trilingüe, autocontenida) |
| `docs/api_snapshots.json` | Cortes agregados por fecha (sin PII), base de la tendencia |
| `deduplicar.py` | Deduplicación propia (respaldo; reglas + fuzzy, conservador, incremental) |
| `inferir_atributos.py` | Inferencia de sexo y grupo de edad por persona |
| `nombres_genero.csv` | Gazetteer nombre → sexo (lista genérica, sin datos de personas) |
| `infografia_gen.py` · `docs/infografia.html` | Infografía del pipeline viejo (se conserva) |
| `docs/plan_deduplicacion.md` · `docs/plan_inferir_atributos.md` | Método y decisiones |
| `assets/olds_logo.png` | Logo OLDS incrustado en la infografía |

### Privacidad

Este repositorio versiona **solo código y agregados**. Los datos de personas (CSV/DB) **nunca se
versionan** (`.gitignore`): son información personal sensible de población vulnerable, sin
verificar. Quien use este código obtiene sus propios datos de la fuente. No redistribuir contactos
ni datos personales fuera del propósito de localizar personas.
