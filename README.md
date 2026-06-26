# venezuela-missing-persons-dedup

**Para qué sirve.** Tras el terremoto de Venezuela (2026), miles de personas fueron reportadas como
desaparecidas en registros comunitarios. La misma persona suele aparecer **muchas veces** —reportada
por distintos familiares, reposteada, y luego marcada como "Encontrada"—. Este repositorio toma ese
CSV de reportes y:

1. **Deduplica** los reportes → **una fila por persona** (no por reporte), de forma conservadora.
2. **Infiere** sexo y rango de edad (estándar UN OCHA) por persona, cuando la información lo permite.

El objetivo es pasar de una lista inflada de reportes a un **conteo real de personas**: apoyar su
localización y dar cifras fiables a quienes coordinan la búsqueda.

## Datos y webscraping

Este repositorio contiene **solo el código de deduplicación e inferencia**. Ni los datos ni el
sistema de **webscraping** que los recolecta se publican aquí, a propósito:

- **No saturar la fuente.** El scraper se mantiene privado para evitar que muchas personas lo
  ejecuten en paralelo y **sobrecarguen las páginas** del registro humanitario, que deben seguir
  disponibles para quien busca a un familiar. La recolección se hace **una sola vez, de forma
  controlada y responsable**.
- **Datos sensibles.** Los reportes son información personal de población vulnerable, sin verificar;
  **nunca se versionan** (ver *Privacidad*).

Para usar el código, aporta tu propio CSV de reportes con el formato de abajo.

## Infografía

`docs/infografia.html` resume la base de-duplicada: estado de búsqueda, sexo, **pirámide poblacional**
por edad (incluyendo "sin dato"), ubicaciones y calidad geográfica de los datos. Es autocontenida
(sin dependencias externas). GitHub no renderiza HTML; ábrela localmente o vía:

<https://htmlpreview.github.io/?https://github.com/alcastaro/venezuela-missing-persons-dedup/blob/main/docs/infografia.html>

## Instalación

```bash
pip install -r requirements.txt
```

Python 3.10+. Dependencias: `pandas`, `rapidfuzz`.

## Entrada esperada

Un CSV de reportes (uno por fila) con, al menos, estas columnas (las demás se conservan intactas):

```
uuid, nombre, edad, genero, cedula, ubicacion, zona_barrio, direccion_precisa,
ultima_ubicacion, otros_lugares, estado, fecha_reporte, ultima_vez_visto, foto_url,
contacto_persona, contacto_emergencia1..3, reportado_por, contacto_reporter,
descripcion, fuente, url_reporte, pagina_listing, scraped_at
```

Imprescindibles para deduplicar: `uuid`, `nombre`, `ubicacion`, `estado`. El resto (cédula,
teléfonos, edad, género, foto) mejora la precisión cuando está presente.

## Uso

```bash
# 1) Deduplicar (lee data/raw/, escribe data/processed/)
python3 deduplicar.py --input data/raw/reportes.csv --output-dir data/processed
python3 deduplicar.py --incremental          # tras nuevos datos: solo procesa lo nuevo

# 2) Inferir sexo + grupo de edad (reescribe data/processed/*.csv)
python3 inferir_atributos.py
```

Genera en `data/processed/`:
- `reportes_dedup.csv` — todas las filas originales + `cluster_id`, confianza, estado del grupo y atributos inferidos.
- `personas_unicas.csv` — una fila por persona (reportes y fotos consolidados).
- `pares_revisar.csv` — pares de confianza media para revisión humana.

## Deduplicación — criterio conservador

Para personas desaparecidas, **fusionar de más (juntar personas distintas) es peor** que dejar
duplicados: equivale a borrar a alguien de la lista. Por eso el matching es estricto:

- **Cédulas válidas distintas → nunca se fusionan.**
- **Mismo nombre pero edad (>3 años) o género incompatible → no se fusionan.**
- **El nombre solo no basta:** exige corroboración por edad, género o **ubicación específica**
  (una ciudad genérica como "La Guaira" no distingue personas). Sin corroboración → queda como
  candidato dudoso, no se fusiona.
- Solo la **cédula igual** llega a 100% de confianza.
- **Split anti-contaminación:** tras agrupar, ningún cluster puede contener dos cédulas distintas.

Bloqueo (cédula / teléfono / prefijo de nombre) + `rapidfuzz` para no comparar N². Modo
`--incremental` reutiliza la corrida previa y solo procesa reportes nuevos. Ver
`docs/plan_deduplicacion.md`.

## Inferencia de sexo y edad

`inferir_atributos.py` corre después del dedup y decide **por persona** (propagando al grupo), sin
perder datos (columnas nuevas, con fuente y confianza). 100% offline, sin LLM ni red.

- **Sexo:** reportado → gazetteer de nombres (`nombres_genero.csv`) → morfología → descripción.
- **Edad:** reportada (mediana del grupo) → descripción → vacío si no hay info. Grupos **UN OCHA**:
  `0-4`, `5-17`, `18-59`, `60+`.

Ver `docs/plan_inferir_atributos.md`.

## Archivos

| Archivo | Descripción |
|---|---|
| `deduplicar.py` | Deduplicación (reglas + fuzzy, conservador, incremental) |
| `inferir_atributos.py` | Inferencia de sexo y grupo de edad por persona |
| `nombres_genero.csv` | Gazetteer curado de nombres → sexo (lista genérica, no contiene datos de personas) |
| `docs/plan_deduplicacion.md` | Método y decisiones de la deduplicación |
| `docs/plan_inferir_atributos.md` | Método y decisiones de la inferencia sexo/edad |
| `docs/infografia.html` | Infografía autocontenida de la base de-duplicada (agregados) |
| `requirements.txt` | Dependencias Python |

## Privacidad

Este repositorio contiene **solo código**. Los datos de personas (CSV/DB) **nunca se versionan**
(`.gitignore`) — son información personal sensible de población vulnerable, sin verificar. Quien use
este código aporta su propio CSV de entrada.

Úsese de forma responsable y acorde a su propósito: ayudar a localizar personas. No redistribuir
contactos ni datos personales fuera de ese contexto.
