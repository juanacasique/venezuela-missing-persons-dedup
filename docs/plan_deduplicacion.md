# Plan — Deduplicación de venezolanos desaparecidos

**Fecha:** 2026-06-25
**Entrada:** `venezolanos_desaparecidos copy.csv` (6300 filas)
**Fuente:** CSV de reportes (registro comunitario humanitario)
**Objetivo:** agrupar reportes que son la MISMA persona (mismo desaparecido reportado varias veces, a veces luego "Encontrado"), asignar clave única de grupo + porcentaje de confianza de que el agrupamiento es correcto.

---

## 1. Decisiones aprobadas (vía brainstorming)

| Tema | Decisión |
|------|----------|
| **Salida** | Ambos archivos: (A) todas las filas + columnas nuevas, (B) vista colapsada 1 fila/persona |
| **Método de match** | Reglas + fuzzy (cédula exacta = fuerte; si no, nombre normalizado + fuzzy + bloqueo por ubicación/teléfono) |
| **% confianza** | Fuerza del match = certeza de que los reportes agrupados son la misma persona |
| **Estado final** | `Encontrado`/`A salvo` gana: si CUALQUIER reporte del grupo está resuelto, el grupo se marca resuelto |

---

## 2. Realidad de los datos (verificada)

- **CSV con comas y saltos de línea dentro de comillas** → obligatorio parsear con `pandas`, no con `cut`/`awk`.
- **Estados válidos reales:** `Se busca` (4693), `Encontrado` (352), `A salvo` (121), vacío (~1011). Otros valores son ruido de descripciones multilínea — se ignoran al parsear bien.
- **Cédula:** solo 261/6300 llenas, formatos sucios (ejemplos sintéticos del formato: `V-12345678`, `1234567`, `V9876543`, `V 1.234.567`) → normalizar a solo dígitos.
- **Teléfonos:** 4 columnas (`contacto_persona`, `contacto_emergencia1-3`, `contacto_reporter`), formato `+58...` → normalizar a dígitos, usar como señal fuerte de match.
- **Foto:** URL única por subida; misma persona reportada 2 veces tiene fotos distintas → señal débil.
- **Patrones de duplicado** (descritos en abstracto, sin datos reales): mismo nombre + misma cédula → mismo grupo; variante de nombre + misma cédula → mismo grupo; mismo nombre + ciudad genérica pero edades incompatibles → personas distintas.

---

## 3. Algoritmo

### Paso 1 — Cargar y normalizar
- `pandas.read_csv(dtype=str, keep_default_na=False)`.
- **Cero pérdida de datos:** las 25 columnas originales NUNCA se modifican ni se borran. Toda normalización va en columnas NUEVAS. La salida A conserva todo el original + las nuevas.
- Columnas auxiliares (no destruyen las originales):
  - `nombre_norm`: minúsculas, sin acentos (`unicodedata`), sin puntuación, espacios colapsados.
  - `cedula_norm`: solo dígitos (quita `V/E`, puntos, guiones, espacios); válida si 6–9 dígitos, si no → vacía.
  - `tels_norm`: conjunto de teléfonos normalizados (dígitos, últimos 10 / sin `+58`) de las 5 columnas.
  - `ubic_norm`: minúsculas sin acentos, para bloqueo (palabras clave: guaira, catia, caracas, corales…).
  - `genero_norm`, `edad_int`, `fecha_reporte` parseada a datetime.

### Paso 2 — Bloqueo (evita comparar 6300² ≈ 40M pares)
Genera pares candidatos solo dentro de bloques:
- Bloque por `cedula_norm` (cuando existe).
- Bloque por cada teléfono normalizado.
- Bloque por `(primeras 3 letras del primer nombre + bucket de ubicación)`.
Unión de bloques → conjunto de pares candidatos.

### Paso 3 — Puntuar cada par (score 0–100) — **conservador** (ver nota)
> **Filosofía (post-implementación):** para personas desaparecidas, fusionar de más es peor que
> dejar duplicados. La primera versión fusionaba por nombre+ciudad y creó mega-clusters (uno con
> 1581 reportes y 118 cédulas distintas). Las reglas se endurecieron así:
- **Cédulas válidas distintas → 0** (bloqueo duro: son personas distintas).
- **Cédula igual → 100** (única señal que llega a 100).
- **Teléfono compartido** + nombre razonable → alto (tope 96); pero si edad/género en conflicto → 70 (revisar).
- Sin cédula ni teléfono, **todo depende del nombre** (`token_sort_ratio`):
  - nombre < 90 → 0 (insuficiente).
  - mismo nombre pero **edad (>3 años) o género incompatible → 0** (personas distintas).
  - nombre ≥ 90 **requiere corroboración**: edad ±1, o mismo género, o **ubicación específica**
    (compartida por ≤ `UMBRAL_UBIC_ESPECIFICA`=40 reportes; una ciudad genérica como "La Guaira"
    NO corrobora). Con corroboración → alto (tope 97). Sin nada que confirme → 78 (no fusiona;
    queda dudoso para revisión / comparador de imágenes).
- **Umbrales:** `>=92` enlace automático; `80–92` enlace marcado `revisar_manual=True`; `<80` no enlaza.

### Paso 4 — Clustering + split anti-contaminación
- Grafo con los pares enlazados → componentes conexas vía **union-find**.
- **Split anti-contaminación:** si un componente quedó puenteado (por registros sin cédula) y mezcla
  cédulas válidas distintas, se separa por cédula; los registros sin cédula → individuos. Garantiza
  **0 clusters con 2 cédulas distintas**.
- Cada componente final = una persona = un `cluster_id` (`PER-000123`).
- Reportes sin pareja = cluster propio (singleton).

### Paso 5 — Confianza por reporte
- `confianza_pct`: certeza de que el reporte pertenece a su grupo.
  - cédula compartida → 100
  - si no → score que lo enlazó (máximo enlace a otro miembro)
  - singleton → 100 (es único, sin riesgo de fusión)
- `confianza_nivel`: `ALTA` (≥92 o cédula) · `MEDIA` (80–92) · `BAJA` (<80, solo aparece si se conserva enlace dudoso).
- `revisar_manual`: bool, True si algún enlace del grupo cayó en zona 80–92.

### Paso 6 — Estado resuelto
- Normalizar `estado` al conjunto válido `{Se busca, Encontrado, A salvo}`.
- Por grupo: si **algún** miembro está en `{Encontrado, A salvo}` → `estado_resuelto = "Resuelto"`; si no → `"Se busca"`.
- Conservar lista cruda de estados del grupo para auditar.

---

## 4. Archivos de salida

### A) `reportes_dedup.csv` — todas las 6300 filas + columnas nuevas
Las 25 columnas originales **intactas** + auxiliares de normalización (`nombre_norm`, `cedula_norm`, `tels_norm`, `ubic_norm`) + `cluster_id`, `es_duplicado` (bool), `n_reportes_cluster`, `confianza_pct`, `confianza_nivel`, `revisar_manual`, `estado_resuelto`.

### B) `personas_unicas.csv` — 1 fila por persona
Campos canónicos (valor más completo/frecuente por campo): `cluster_id`, `nombre` (mejor versión), `cedula`, `edad`, `genero`, `ubicacion`, `n_reportes`, `estados_todos`, `estado_resuelto`, `fecha_primer_reporte`, `fecha_ultimo_reporte`, `confianza_min`, `revisar_manual`, `telefonos`.
- **Enlaces conservados completos** (nada se pierde, base pa' futuro comparador de imágenes):
  - `uuids_miembros` — todos los uuid del grupo
  - `urls_reporte` — TODAS las `url_reporte` de los miembros
  - `fotos_urls` — TODAS las `foto_url` de los miembros (no una sola)

### C) `pares_revisar.csv` — opcional, control de calidad
Pares en zona 80–92 (`uuid_a`, `uuid_b`, `score`, motivo) para revisión humana.

---

## 5. Validación
Al terminar imprime resumen:
- total reportes → nº clusters → nº personas únicas → nº duplicados colapsados
- conteo por `estado_resuelto`
- nº `revisar_manual`, distribución de confianza
- **Asserts**: invariante "0 clusters con cédulas válidas distintas". Los casos con nombres reales son opcionales y viven en `casos_prueba.json` (privado, gitignored) para no exponer datos personales.

---

## 6. Modo incremental (base que crece)
La base crece con nuevos reportes. Re-deduplicar todo cada vez es caro.
- `--incremental` reutiliza el `reportes_dedup.csv` de la corrida anterior (en `--output-dir`, o ruta `--state`).
- Los reportes ya vistos **conservan su `cluster_id`**; dos reportes viejos NO se vuelven a comparar entre sí.
- Solo se procesan pares donde interviene al menos un reporte **nuevo**.
- Si dos grupos viejos se fusionan por un puente nuevo, se conserva el id menor (estable y determinista).
- **Match por nombre** integrado: aunque no haya cédula ni teléfono, nombres similares (`token_sort_ratio`) + ubicación enlazan.

Verificado: base 5000 → llegan 1000 nuevos → 32 649 pares (vs 112 935 completo, −71 %), **mismo resultado** (4845 personas) y `cluster_id` viejos intactos.

## 7. Entregable
- **Script:** `deduplicar.py` (español, `argparse`).
- **CLI:**
  ```
  python deduplicar.py                                    # entrada/salida por defecto
  python deduplicar.py --input archivo.csv
  python deduplicar.py --output-dir ./salida
  python deduplicar.py --umbral-auto 92 --umbral-revisar 80
  python deduplicar.py --output-dir ./salida --incremental # tras llegar nuevos datos
  ```
- **Flujo recomendado:** nuevos reportes en el CSV → `python deduplicar.py --incremental`.
- **Dependencias:** `pandas` (ya instalado), `rapidfuzz` → `pip install rapidfuzz`. Acentos con `unicodedata` (stdlib, sin dependencia extra).

---

## 7. Riesgos / límites
- Nombres muy comunes + ubicación genérica ("La Guaira") pueden fusionar de más → mitigado con umbral alto y `revisar_manual`.
- Cédula presente en solo 4% → la mayoría de matches dependen de nombre+ubicación+teléfono.
- Sin verificación humana, ningún auto-merge es 100% salvo cédula. Por eso `pares_revisar.csv`.
