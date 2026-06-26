"""
Inferir sexo e intervalo de edad de los reportes deduplicados.

Lee la salida del dedup (reportes_dedup.csv, ya con cluster_id), decide UNA vez
por persona (cluster) y propaga a todas sus filas. Cero pérdida: las columnas
originales nunca se tocan; todo va a columnas nuevas con su fuente y confianza.

SEXO (96% sin género en crudo -> el motor real es nombre->sexo):
  1. reportado    -> algún miembro trae 'genero'           (conf 100)
  2. gazetteer    -> primer nombre en nombres_genero.csv   (conf 90)
  3. morfologia   -> termina en -a (F) / -o (M) + excepc.   (conf 70)
  4. descripcion  -> regex (niña/señor/ella/...)            (conf 60)
  5. desconocido                                            (conf 0)
  El gazetteer se siembra además con los nombres que YA traen género en la base.

EDAD (74% presente -> casi todo es bucketing + propagación):
  1. reportado    -> mediana de las edades del grupo
  2. descripcion  -> "N años", "bebé", "adulto mayor", ...
  3. sin señal    -> vacío (NO inventar)
  Bucket humanitario OCHA: 0-4, 5-17, 18-59, 60+.

Salida: reescribe reportes_dedup.csv y personas_unicas.csv con las columnas nuevas.

Uso:
  python inferir_atributos.py
  python inferir_atributos.py --input data/processed/reportes_dedup.csv \\
                              --personas data/processed/personas_unicas.csv \\
                              --gazetteer nombres_genero.csv

Dependencias: solo pandas. Sin LLM, sin red, sin tokens. O(n).
"""

import argparse
import os
import re
import unicodedata
from collections import Counter, defaultdict

import pandas as pd


# --------------------------------------------------------------------------- #
# Normalización
# --------------------------------------------------------------------------- #

def quitar_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def primer_nombre(nombre: str) -> str:
    """Primer token del nombre, minúsculas, sin acentos, solo letras."""
    if not nombre:
        return ""
    t = quitar_acentos(nombre.lower())
    t = re.sub(r"[^a-z ]", " ", t)
    toks = t.split()
    return toks[0] if toks else ""


def norm_genero_reportado(valor: str) -> str:
    t = quitar_acentos((valor or "").lower()).strip()
    if t.startswith("masc") or t == "m":
        return "Masculino"
    if t.startswith("fem") or t == "f":
        return "Femenino"
    if t.startswith("otro"):
        return "Otro"
    return ""


def parse_edad(valor: str):
    if not valor:
        return None
    m = re.search(r"\d{1,3}", valor)
    if not m:
        return None
    n = int(m.group())
    return n if 0 <= n <= 120 else None


# --------------------------------------------------------------------------- #
# Gazetteer + morfología
# --------------------------------------------------------------------------- #

# Nombres masculinos que terminan en -a (rompen la morfología -a=F).
EXCEPC_M_TERMINA_A = {"joshua", "elias", "tobias", "matias", "lucas"}
# Nombres femeninos que terminan en -o (rompen la morfología -o=M).
EXCEPC_F_TERMINA_O = {"rosario", "consuelo", "amparo", "socorro"}


def cargar_gazetteer(ruta: str) -> dict:
    g = {}
    if ruta and os.path.exists(ruta):
        gz = pd.read_csv(ruta, dtype=str, keep_default_na=False)
        for _, r in gz.iterrows():
            nom = primer_nombre(r["nombre"]) or quitar_acentos(r["nombre"].lower()).strip()
            sx = r["genero"].strip().upper()
            if nom and sx in ("M", "F"):
                g[nom] = sx
    return g


def sexo_por_nombre(token: str, gaz: dict):
    """Devuelve ('Masculino'|'Femenino', confianza, fuente) o (None, 0, '')."""
    if not token:
        return None, 0, ""
    if token in gaz:
        return ("Masculino" if gaz[token] == "M" else "Femenino"), 90, "gazetteer"
    if token.endswith("a") and token not in EXCEPC_M_TERMINA_A:
        return "Femenino", 70, "morfologia"
    if token.endswith("o") and token not in EXCEPC_F_TERMINA_O:
        return "Masculino", 70, "morfologia"
    return None, 0, ""


# --------------------------------------------------------------------------- #
# Inferencia desde descripción
# --------------------------------------------------------------------------- #

PAT_FEM = re.compile(
    r"\b(ni[ñn]a|hija|hermana|madre|mam[aá]|esposa|se[ñn]ora|femenin\w*|mujer|"
    r"ella|abuela|t[ií]a|sobrina|nieta|adolescente femenina)\b", re.I)
PAT_MASC = re.compile(
    r"\b(ni[ñn]o|hijo|hermano|padre|pap[aá]|esposo|se[ñn]or|masculin\w*|hombre|"
    r"abuelo|t[ií]o|sobrino|nieto)\b", re.I)


def sexo_por_descripcion(texto: str):
    if not texto:
        return None, 0, ""
    t = quitar_acentos(texto.lower())
    f = len(PAT_FEM.findall(t))
    m = len(PAT_MASC.findall(t))
    if f > m:
        return "Femenino", 60, "descripcion"
    if m > f:
        return "Masculino", 60, "descripcion"
    return None, 0, ""


def edad_por_descripcion(texto: str):
    """Devuelve (edad_int, confianza, fuente) o (None, 0, '')."""
    if not texto:
        return None, 0, ""
    t = quitar_acentos(texto.lower())
    m = re.search(r"(\d{1,3})\s*a[nñ]os?\b", t)
    if m:
        e = int(m.group(1))
        if 0 <= e <= 120:
            return e, 75, "descripcion"
    m = re.search(r"edad\s*:?\s*(\d{1,3})", t)
    if m:
        e = int(m.group(1))
        if 0 <= e <= 120:
            return e, 75, "descripcion"
    if re.search(r"\b(bebe|recien nacid)", t):
        return 1, 55, "descripcion"
    if re.search(r"\b(adulto mayor|anciano|abuel[oa]|tercera edad)\b", t):
        return 65, 55, "descripcion"
    if re.search(r"\badolescente\b", t):
        return 15, 50, "descripcion"
    if re.search(r"\bni[nñ][oa]\b", t):
        return 8, 45, "descripcion"
    return None, 0, ""


def bucket_ocha(edad):
    if edad is None:
        return ""
    if edad <= 4:
        return "0-4"
    if edad <= 17:
        return "5-17"
    if edad <= 59:
        return "18-59"
    return "60+"


# --------------------------------------------------------------------------- #
# Proceso
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="Infiere sexo e intervalo de edad por persona.")
    ap.add_argument("--input", default="data/processed/reportes_dedup.csv")
    ap.add_argument("--personas", default="data/processed/personas_unicas.csv")
    ap.add_argument("--gazetteer", default="nombres_genero.csv")
    args = ap.parse_args()

    print(f"Cargando {args.input} ...")
    df = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    n = len(df)
    print(f"  {n} filas")
    if "cluster_id" not in df.columns:
        raise SystemExit("Falta la columna cluster_id: corre primero deduplicar.py")

    gaz = cargar_gazetteer(args.gazetteer)
    print(f"  gazetteer: {len(gaz)} nombres curados")

    # Sembrar gazetteer con los nombres que YA traen género reportado en la base.
    aprendido = defaultdict(Counter)
    for nombre, genero in zip(df["nombre"], df["genero"]):
        g = norm_genero_reportado(genero)
        tok = primer_nombre(nombre)
        if tok and g in ("Masculino", "Femenino"):
            aprendido[tok]["M" if g == "Masculino" else "F"] += 1
    nuevos = 0
    for tok, cnt in aprendido.items():
        if tok not in gaz:
            gaz[tok] = "M" if cnt["M"] >= cnt["F"] else "F"
            nuevos += 1
    print(f"  + {nuevos} nombres aprendidos del dato reportado -> {len(gaz)} total")

    # Agrupar índices por cluster.
    miembros_de = defaultdict(list)
    for i, cid in enumerate(df["cluster_id"]):
        miembros_de[cid].append(i)

    # Mejor nombre por cluster (el más largo/completo).
    descripciones = df["descripcion"].tolist()
    nombres = df["nombre"].tolist()
    generos = df["genero"].tolist()
    edades = df["edad"].tolist()

    dec = {}  # cluster_id -> dict de decisiones
    for cid, idxs in miembros_de.items():
        # ---- SEXO ----
        reportados = [norm_genero_reportado(generos[i]) for i in idxs]
        reportados = [r for r in reportados if r]
        # Pista por nombre (para detectar conflicto aunque haya reportado).
        nombre_canon = max((nombres[i] for i in idxs), key=lambda s: len(s or ""))
        tok = primer_nombre(nombre_canon)
        sx_nombre, _, _ = sexo_por_nombre(tok, gaz)

        if reportados:
            sexo = Counter(reportados).most_common(1)[0][0]
            sx_fuente, sx_conf = "reportado", 100
        else:
            sexo, sx_conf, sx_fuente = sexo_por_nombre(tok, gaz)
            if sexo is None:
                texto = " ".join(descripciones[i] for i in idxs)
                sexo, sx_conf, sx_fuente = sexo_por_descripcion(texto)
            if sexo is None:
                sexo, sx_conf, sx_fuente = "Desconocido", 0, ""

        conflicto = bool(reportados and sx_nombre and sexo in ("Masculino", "Femenino")
                         and sx_nombre != sexo)

        # ---- EDAD ----
        edades_grupo = [e for e in (parse_edad(edades[i]) for i in idxs) if e is not None]
        if edades_grupo:
            edades_grupo.sort()
            ed = edades_grupo[len(edades_grupo) // 2]  # mediana
            ed_fuente, ed_conf = "reportado", 100
        else:
            texto = " ".join(descripciones[i] for i in idxs)
            ed, ed_conf, ed_fuente = edad_por_descripcion(texto)

        dec[cid] = {
            "sexo_inferido": sexo,
            "sexo_fuente": sx_fuente,
            "sexo_confianza": sx_conf,
            "sexo_conflicto": conflicto,
            "edad_estimada": ed if ed is not None else "",
            "grupo_edad": bucket_ocha(ed),
            "edad_fuente": ed_fuente if ed is not None else "",
            "edad_confianza": ed_conf if ed is not None else 0,
        }

    # ---- Propagar a cada fila de reportes_dedup ----
    cols = ["sexo_inferido", "sexo_fuente", "sexo_confianza", "sexo_conflicto",
            "edad_estimada", "grupo_edad", "edad_fuente", "edad_confianza"]
    for c in cols:
        df[c] = [dec[cid][c] for cid in df["cluster_id"]]
    df.to_csv(args.input, index=False)
    print(f"Reescrito: {args.input}")

    # ---- personas_unicas ----
    if os.path.exists(args.personas):
        pu = pd.read_csv(args.personas, dtype=str, keep_default_na=False)
        for c in cols:
            pu[c] = [dec.get(cid, {}).get(c, "") for cid in pu["cluster_id"]]
        pu.to_csv(args.personas, index=False)
        print(f"Reescrito: {args.personas}")

    _resumen(df, dec)


def _resumen(df, dec):
    n = len(df)
    print("\n===== RESUMEN =====")
    crudo = (df["genero"].str.strip() != "").sum()
    inferido = (df["sexo_inferido"] != "Desconocido").sum()
    print(f"Sexo  — crudo: {crudo}/{n} ({100*crudo/n:.0f}%)  ->  "
          f"inferido: {inferido}/{n} ({100*inferido/n:.0f}%)")
    print("  por fuente (filas):")
    print(df["sexo_fuente"].replace("", "(desconocido)").value_counts().to_string())
    print("  distribución:")
    print(df["sexo_inferido"].value_counts().to_string())
    print(f"  conflictos reportado-vs-nombre: {(df['sexo_conflicto'] == True).sum()}")

    con_edad = (df["grupo_edad"].str.strip() != "").sum()
    print(f"\nEdad  — grupo_edad asignado: {con_edad}/{n} ({100*con_edad/n:.0f}%)")
    print("  por grupo OCHA:")
    print(df[df["grupo_edad"] != ""]["grupo_edad"].value_counts().to_string())

    print("\n===== VALIDACIÓN (nombres claros) =====")
    casos = {"jose": "Masculino", "maria": "Femenino", "carlos": "Masculino",
             "ana": "Femenino", "carmen": "Femenino", "luis": "Masculino"}
    for tok, esperado in casos.items():
        sel = df[df["nombre"].str.lower().str.startswith(tok)]
        if len(sel):
            top = sel["sexo_inferido"].value_counts().idxmax()
            print(f"  {tok}* -> {top}  [{'OK' if top == esperado else 'REVISAR'}]")


if __name__ == "__main__":
    main()
