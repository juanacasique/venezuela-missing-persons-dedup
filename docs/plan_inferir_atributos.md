# Plan — Inferir sexo e intervalo de edad

**Fecha:** 2026-06-25
**Entrada:** `salida/reportes_dedup.csv` (salida del dedup, ya tiene `cluster_id`)
**Objetivo:** rellenar/inferir **sexo** y **grupo de edad** sin perder datos originales, marcando siempre fuente y confianza.

---

## 1. Decisiones aprobadas

| Tema | Decisión |
|------|----------|
| **Método sexo** | Gazetteer venezolano/español + morfología (-a/-o + excepciones). 100% offline, cero tokens, determinista |
| **Grupos de edad** | Estándar humanitario OCHA: `0–4`, `5–17`, `18–59`, `60+` |
| **Salida** | Decidir 1 vez por persona (cluster), propagar a todas las filas. Escribir en `reportes_dedup.csv` Y `personas_unicas.csv` |

---

## 2. Realidad de los datos (verificada)

- **`genero`: solo 4% lleno** (135 Femenino, 124 Masculino, 2 Otro). 96% vacío → el motor real es **nombre → sexo**; propagar-en-grupo aporta poco.
- **`edad`: 74% lleno** → casi todo es bucketing + propagación. Solo 26% necesita inferencia desde texto.
- **`descripcion`: 53%** → señal secundaria pa' ambos.
- Cero pérdida: las columnas originales NUNCA se tocan; todo va a columnas nuevas.

---

## 3. Inferencia de SEXO (por cluster)

Orden de prioridad (lo más confiable primero); se decide una vez por `cluster_id` y se propaga:

1. **Reportado** — si algún miembro del grupo tiene `genero` lleno → usar (moda si varios). `fuente=reportado`, confianza 100.
2. **Gazetteer de nombres** — primer token del nombre canónico, normalizado sin acentos, contra lista curada venezolana/española.
   - Maneja nombres compuestos por primer token: `María José`→María→F; `José María`→José→M (correcto en español).
   - `fuente=nombre_gazetteer`, confianza 90.
3. **Morfología** (nombre no está en gazetteer):
   - termina en `a` → F; termina en `o` → M; con **lista de excepciones** (José, Andrea, Nicolás, Guadalupe, Jesús…).
   - `fuente=morfologia`, confianza 70.
4. **Descripción** (si nombre no resolvió) — regex: `niña|ella|femenina|señora|madre|hija`→F; `niño|él|masculino|señor|padre|hijo`→M.
   - `fuente=descripcion`, confianza 60.
5. **Nada** → `Desconocido`, confianza 0.

**Conflicto:** si el reportado dice M pero el nombre sugiere F → gana el reportado (dato humano), pero se marca `sexo_conflicto=True` para auditar.

**Columnas nuevas:** `sexo_inferido` (Masculino/Femenino/Desconocido), `sexo_fuente`, `sexo_confianza`, `sexo_conflicto`.

### Gazetteer
- Archivo bundled `nombres_genero.csv` (nombre normalizado → M/F), curado con nombres venezolanos/hispanos comunes, **extensible** (se le agregan nombres con el tiempo).
- Se siembra además con los nombres que YA traen `genero` reportado en la base (aprende del propio dato).
- La morfología cubre la cola larga de nombres no listados.

---

## 4. Inferencia de EDAD (por cluster)

1. **Reportado** — si algún miembro tiene `edad` → usar (mediana de los presentes; deberían coincidir dentro del grupo). `fuente=reportado`.
2. **Descripción** (si ninguno tiene edad) — regex:
   - número explícito: `(\d{1,3})\s*años?` → esa edad.
   - palabras: `bebé|recién nacido`→1, `adulto mayor|anciano|abuelo|tercera edad`→65, `adolescente`→15, `niñ[oa]`→8 (aprox).
   - `fuente=descripcion`, confianza media.
3. **Bucketing OCHA** sobre la edad obtenida → `grupo_edad` ∈ {`0-4`, `5-17`, `18-59`, `60+`}.
4. **Sin señal** → `edad_estimada` y `grupo_edad` vacíos. **No inventar.**

**Columnas nuevas:** `edad_estimada` (número o vacío), `grupo_edad` (string o vacío), `edad_fuente`, `edad_confianza`.
La columna original `edad` queda intacta.

---

## 5. Salidas
- **`reportes_dedup.csv`** — se reescribe agregando las columnas nuevas (cada fila del cluster recibe el valor del cluster).
- **`personas_unicas.csv`** — se reescribe agregando: `sexo_inferido`, `sexo_fuente`, `sexo_confianza`, `grupo_edad`, `edad_estimada`, `edad_fuente`.

---

## 6. Eficiencia / incremental
- Inferencia es **O(n)** (sin comparación por pares) → re-correr sobre 80k filas es rápido. No necesita modo incremental especial; basta re-ejecutar tras el dedup.
- Determinista: misma entrada → misma salida.

---

## 7. Entregable
- **Script:** `inferir_atributos.py` (español, estilo del proyecto, `argparse`).
- **Asset:** `nombres_genero.csv` (gazetteer bundled, editable).
- **CLI:**
  ```
  python inferir_atributos.py                              # usa salida/ por defecto
  python inferir_atributos.py --input salida/reportes_dedup.csv
  python inferir_atributos.py --personas salida/personas_unicas.csv
  python inferir_atributos.py --gazetteer nombres_genero.csv
  ```
- **Flujo:** `deduplicar.py --incremental` → `inferir_atributos.py`.
- **Dependencias:** solo `pandas`. Sin LLM, sin red, sin tokens.

---

## 8. Validación
Imprime resumen:
- cobertura de sexo antes (4%) vs después; distribución M/F/Desconocido por fuente.
- cobertura de grupo_edad; distribución por grupo OCHA.
- nº `sexo_conflicto`.
- **Asserts**: nombres comunes resuelven bien — `José`→M, `María`→F, `Carlos`→M, `Ana`→F (prueban el gazetteer, no identifican personas).

---

## 9. Límites
- Nombres unisex (Jean, Yorgelis, Anyelo) o muy raros → quedan `Desconocido` o baja confianza (no se fuerza). Por eso `sexo_confianza` permite filtrar.
- Edad inferida de texto es aproximada (confianza media) — sirve pa' el bucket, no como edad exacta.
- Gazetteer crece con uso; nombres nuevos que no estén → caen a morfología.
