"""
Análisis sexo + edad y pirámide poblacional sobre los datos de la API abierta
de Venezuela Reporta (ya deduplicados en origen).

Entrada:  data/raw/api_personas.csv          (de api_extractor.py)
Reusa la inferencia de sexo/edad de inferir_atributos.py para que la comparación
contra la infografía anterior sea manzana-con-manzana (aquella también infería).

Decide UNA vez por persona (la API ya entrega 1 fila = 1 persona canónica):
  sexo: genero reportado -> gazetteer nombre -> morfología -> descripción -> Desconocido
  edad: edad reportada -> descripción -> (menor=True y sin edad -> señal de <18) -> vacío

Salidas (data/processed/):
  api_personas_inferido.csv   filas + columnas sexo_inferido/grupo_edad/...
  api_piramide.csv            bandas quinquenales x sexo (para la pirámide)
  api_stats.json              todos los números (alimenta la infografía/artefacto)
  + compara contra personas_unicas.csv (infografía anterior) si existe

Uso:  python3 analizar_api.py
"""

import argparse
import json
import os

import pandas as pd

from inferir_atributos import (
    bucket_ocha, cargar_gazetteer, edad_por_descripcion, norm_genero_reportado,
    parse_edad, primer_nombre, quitar_acentos, sexo_por_descripcion, sexo_por_nombre,
)

BANDAS_5 = [(0, 4), (5, 9), (10, 14), (15, 19), (20, 24), (25, 29), (30, 34),
            (35, 39), (40, 44), (45, 49), (50, 54), (55, 59), (60, 64),
            (65, 69), (70, 74), (75, 79), (80, 200)]
OCHA = ["0-4", "5-17", "18-59", "60+"]


BANDAS_LBL = [f"{lo}-{hi}" if lo < 80 else "80+" for lo, hi in BANDAS_5]


def banda5(edad):
    if edad is None:
        return ""
    for lo, hi in BANDAS_5:
        if lo <= edad <= hi:
            return "80+" if lo == 80 else f"{lo}-{hi}"
    return ""


def piramide_de(df):
    """band -> {Masculino, Femenino}. Solo cuenta filas con sexo M/F y banda5."""
    p = {}
    for b in BANDAS_LBL:
        sub = df[df["banda5"] == b]
        p[b] = {"Masculino": int((sub["sexo_inferido"] == "Masculino").sum()),
                "Femenino": int((sub["sexo_inferido"] == "Femenino").sum())}
    return p


def construir_gazetteer(df, ruta_gaz):
    gaz = cargar_gazetteer(ruta_gaz)
    from collections import Counter, defaultdict
    aprendido = defaultdict(Counter)
    for nombre, genero in zip(df["nombre"], df["genero"]):
        g = norm_genero_reportado(genero)
        tok = primer_nombre(nombre)
        if tok and g in ("Masculino", "Femenino"):
            aprendido[tok]["M" if g == "Masculino" else "F"] += 1
    for tok, cnt in aprendido.items():
        if tok not in gaz:
            gaz[tok] = "M" if cnt["M"] >= cnt["F"] else "F"
    return gaz


def inferir(df, gaz):
    sexos, sx_fuentes, edades_est, grupos = [], [], [], []
    for nombre, genero, edad_raw, menor, desc in zip(
            df["nombre"], df["genero"], df["edad"], df["menor"], df["descripcion"]):
        nombre = nombre or ""
        desc = desc or ""
        # ---- SEXO ----
        g = norm_genero_reportado(genero)
        if g:
            sexo, fuente = g, "reportado"
        else:
            tok = primer_nombre(nombre)
            sexo, _, fuente = sexo_por_nombre(tok, gaz)
            if sexo is None:
                sexo, _, fuente = sexo_por_descripcion(desc)
            if sexo is None:
                sexo, fuente = "Desconocido", ""
        # ---- EDAD ----
        e = parse_edad(str(edad_raw)) if edad_raw not in (None, "", "nan") else None
        if e is None:
            e, _, _ = edad_por_descripcion(desc)
        if e is None and str(menor).lower() in ("true", "1"):
            e = 12   # menor de edad sin edad exacta: ubicar en 5-17 (no inventa valor fino)
        sexos.append(sexo)
        sx_fuentes.append(fuente)
        edades_est.append(e if e is not None else "")
        grupos.append(bucket_ocha(e))
    df["sexo_inferido"] = sexos
    df["sexo_fuente"] = sx_fuentes
    df["edad_estimada"] = edades_est
    df["grupo_edad"] = grupos
    df["banda5"] = [banda5(e if e != "" else None) for e in edades_est]
    return df


def medir_precision(df, gaz):
    """Acierto de la inferencia por nombre contra el genero REPORTADO por la API.
    Mide qué tan fiable es inferir sexo cuando la API no lo trae."""
    agree = conflict = noname = 0
    for nombre, genero in zip(df["nombre"], df["genero"]):
        rep = norm_genero_reportado(genero)
        if rep not in ("Masculino", "Femenino"):
            continue
        guess, _, _ = sexo_por_nombre(primer_nombre(nombre or ""), gaz)
        if guess is None:
            noname += 1
        elif guess == rep:
            agree += 1
        else:
            conflict += 1
    tot = agree + conflict
    return {"con_reportado": agree + conflict + noname, "evaluables": tot,
            "acierto": agree, "conflicto": conflict, "sin_senal_nombre": noname,
            "acierto_pct": round(100 * agree / tot, 1) if tot else None}


def _tokens(nombre):
    import re
    t = quitar_acentos((nombre or "").lower())
    return [x for x in re.sub(r"[^a-z ]", " ", t).split() if x]


def sexo_ingreso(nombre, gaz):
    """En /ingresos el nombre suele venir APELLIDO-primero ('PALMA JULIA').
    Tomar el primer token agarra el apellido. En su lugar escaneamos TODOS los
    tokens contra el gazetteer curado de NOMBRES de pila; el apellido casi nunca
    está en el gazetteer, así que el primer match es el nombre de pila.
    Sin morfología (-a/-o sobre un apellido daría errores como 'Palma' -> F)."""
    for tok in _tokens(nombre):
        if tok in gaz:
            return "Masculino" if gaz[tok] == "M" else "Femenino"
    return "Desconocido"


def inferir_ingresos(df, gaz):
    """/ingresos: sexo viene null -> 100% por nombre (gazetteer, todos los tokens).
    edad solo del campo `edad`. No hay descripcion ni menor."""
    sexos, edades, bandas = [], [], []
    sexo_col = df["sexo"] if "sexo" in df.columns else [""] * len(df)
    for nombre, sx_raw, edad_raw in zip(df["nombre"], sexo_col, df["edad"]):
        g = norm_genero_reportado(sx_raw) or sexo_ingreso(nombre, gaz)
        e = parse_edad(str(edad_raw)) if str(edad_raw).strip() not in ("", "nan") else None
        sexos.append(g)
        edades.append(e if e is not None else "")
        bandas.append(banda5(e))
    df["sexo_inferido"] = sexos
    df["edad_estimada"] = edades
    df["banda5"] = bandas
    df["grupo_edad"] = [bucket_ocha(e if e != "" else None) for e in edades]
    return df


def dist(series, claves):
    vc = series.value_counts()
    return {k: int(vc.get(k, 0)) for k in claves}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/raw/api_personas.csv")
    ap.add_argument("--ingresos", default="data/raw/api_ingresos.csv")
    ap.add_argument("--gazetteer", default="nombres_genero.csv")
    ap.add_argument("--previo", default="data/processed/personas_unicas.csv")
    ap.add_argument("--outdir", default="data/processed")
    args = ap.parse_args()

    df = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    N = len(df)
    print(f"API personas: {N}")

    gaz = construir_gazetteer(df, args.gazetteer)
    df = inferir(df, gaz)
    prec = medir_precision(df, gaz)

    # ---- coberturas crudas ----
    cov_genero = int((df["genero"].str.strip() != "").sum())
    cov_edad = int(sum(1 for v in df["edad"] if str(v).strip() not in ("", "nan")))
    cov_menor = int((df["menor"].str.strip() != "").sum())

    sexo_d = dist(df["sexo_inferido"], ["Femenino", "Masculino", "Otro", "Desconocido"])
    ocha_d = dist(df["grupo_edad"].replace("", "Sin dato"), OCHA + ["Sin dato"])
    status_d = {k: int(v) for k, v in df["status"].value_counts().to_dict().items()}

    # ---- pirámides quinquenales por subpoblación ----
    encontrados = df[df["status"].isin(["encontrado", "a_salvo"])]
    buscando = df[df["status"] == "buscando"]
    pir = piramide_de(df)
    pir_buscando = piramide_de(buscando)
    pir_encontrados = piramide_de(encontrados)

    # ---- resumen stdout ----
    print("\n== SEXO (inferido) ==")
    for k, v in sexo_d.items():
        print(f"  {k:12} {v:6}  {100*v/N:5.1f}%")
    print(f"  cobertura genero reportado: {cov_genero}/{N} ({100*cov_genero/N:.1f}%)")
    print(f"  fuentes: " + ", ".join(f"{k}={v}" for k, v in
                                      df['sexo_fuente'].replace('', '(desc)').value_counts().items()))
    print("\n== EDAD (OCHA) ==")
    for k in OCHA + ["Sin dato"]:
        print(f"  {k:9} {ocha_d[k]:6}  {100*ocha_d[k]/N:5.1f}%")
    print(f"  cobertura edad reportada: {cov_edad}/{N} ({100*cov_edad/N:.1f}%)  ·  menor: {cov_menor}/{N}")
    print("\n== STATUS ==")
    for k, v in status_d.items():
        print(f"  {k:11} {v:6}")

    print("\n== PRECISIÓN inferencia-por-nombre vs genero REPORTADO ==")
    print(f"  evaluables: {prec['evaluables']}  ·  acierto: {prec['acierto']} "
          f"({prec['acierto_pct']}%)  ·  conflicto: {prec['conflicto']}")

    # ---- comparación con infografía anterior ----
    comp = None
    if os.path.exists(args.previo):
        pu = pd.read_csv(args.previo, dtype=str, keep_default_na=False)
        Np = len(pu)
        sexo_p = dist(pu["sexo_inferido"], ["Femenino", "Masculino", "Otro", "Desconocido"])
        ocha_p = dist(pu["grupo_edad"].replace("", "Sin dato"), OCHA + ["Sin dato"])
        comp = {"N": Np, "sexo": sexo_p, "ocha": ocha_p}
        print("\n== COMPARACIÓN  (API ahora  vs  infografía anterior) ==")
        print(f"  {'':14}{'API':>10}{'antes':>10}{'Δ':>9}")
        print(f"  {'personas':14}{N:>10}{Np:>10}{N-Np:>+9}")
        for k in ["Femenino", "Masculino", "Desconocido"]:
            print(f"  sexo {k:9}{sexo_d[k]:>10}{sexo_p[k]:>10}{sexo_d[k]-sexo_p[k]:>+9}")
        for k in OCHA + ["Sin dato"]:
            print(f"  edad {k:9}{ocha_d[k]:>10}{ocha_p[k]:>10}{ocha_d[k]-ocha_p[k]:>+9}")

    # ---- /ingresos (hospitales): sexo 100% inferido por nombre ----
    ingresos = None
    if os.path.exists(args.ingresos):
        di = pd.read_csv(args.ingresos, dtype=str, keep_default_na=False)
        di = inferir_ingresos(di, gaz)
        Ni = len(di)
        sexo_i = dist(di["sexo_inferido"], ["Femenino", "Masculino", "Desconocido"])
        ocha_i = dist(di["grupo_edad"].replace("", "Sin dato"), OCHA + ["Sin dato"])
        cov_edad_i = int((di["edad"].astype(str).str.strip().replace("nan", "") != "").sum())
        pir_ingresos = piramide_de(di)
        top_ubic = {k: int(v) for k, v in di["ubicacion"].value_counts().head(8).items()}
        ingresos = {"N": Ni, "sexo": sexo_i, "ocha": ocha_i, "cov_edad": cov_edad_i,
                    "piramide": pir_ingresos, "top_ubicaciones": top_ubic}
        di.to_csv(os.path.join(args.outdir, "api_ingresos_inferido.csv"), index=False)
        print("\n== /INGRESOS (hospitales/refugios) ==")
        print(f"  N={Ni}  ·  sexo (todo por nombre): F {sexo_i['Femenino']} · M {sexo_i['Masculino']} "
              f"· Desc {sexo_i['Desconocido']}  ·  edad reportada {cov_edad_i} ({100*cov_edad_i/Ni:.0f}%)")
    else:
        print(f"\n(aviso) {args.ingresos} no existe aún — corre: python3 api_extractor.py --endpoint ingresos")

    # ---- salidas ----
    os.makedirs(args.outdir, exist_ok=True)
    df.to_csv(os.path.join(args.outdir, "api_personas_inferido.csv"), index=False)

    def _csv(pir_dict, nombre):
        pd.DataFrame([{"banda": b, "Masculino": pir_dict[b]["Masculino"],
                       "Femenino": pir_dict[b]["Femenino"]} for b in pir_dict]
                     ).to_csv(os.path.join(args.outdir, nombre), index=False)
    _csv(pir, "api_piramide.csv")
    _csv(pir_buscando, "api_piramide_buscando.csv")
    _csv(pir_encontrados, "api_piramide_encontrados.csv")
    if ingresos:
        _csv(ingresos["piramide"], "api_piramide_ingresos.csv")

    stats = {
        "fuente": "Venezuela Reporta — venezuelareporta.org (API abierta)",
        "generado": "2026-06-30",
        "N": N, "cov_genero": cov_genero, "cov_edad": cov_edad, "cov_menor": int(cov_menor),
        "sexo": sexo_d, "ocha": ocha_d, "status": status_d,
        "precision_inferencia": prec,
        "piramide": pir, "piramide_buscando": pir_buscando,
        "piramide_encontrados": pir_encontrados,
        "n_buscando": len(buscando), "n_encontrados": len(encontrados),
        "ingresos": ingresos,
        "comparacion": comp,
    }
    with open(os.path.join(args.outdir, "api_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\nEscrito: {args.outdir}/ api_personas_inferido.csv, api_ingresos_inferido.csv, "
          f"api_piramide*.csv, api_stats.json")


if __name__ == "__main__":
    main()
