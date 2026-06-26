"""
Genera docs/infografia.html a partir de la base de-duplicada.

Lee data/processed/{personas_unicas,reportes_dedup}.csv, calcula las cifras,
incrusta el logo de OLDS (assets/olds_logo.png) como data-URI y estampa la
fecha/hora de actualización en hora de Venezuela (UTC−4). Reproducible: re-correr
tras actualizar los datos regenera la infografía.

Uso:
  python inferir_atributos.py        # (antes) deja los CSV listos
  python infografia_gen.py
"""

import base64
import re
import unicodedata
from datetime import datetime, timezone, timedelta

import pandas as pd

PU = "data/processed/personas_unicas.csv"
RD = "data/processed/reportes_dedup.csv"
LOGO = "assets/olds_logo.png"
OUT = "docs/infografia.html"

CIUDADES = ["catia la mar", "la guaira", "caraballeda", "naiguata", "tanaguarena",
            "carayaca", "maiquetia", "macuto", "caracas", "carmen de uria",
            "los caracas", "chichiriviche", "el junko", "camuri", "anare",
            "la sabana", "todasana", "osma", "oricao"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
MARK = re.compile(r"\b(calle|av|avenida|edif|edificio|sector|urb|urbanizacion|callejon|"
                  r"carrera|manzana|casa|quinta|hospital|colegio|liceo|escuela|plaza|"
                  r"terminal|aeropuerto|estacion|km|playa|muelle|puerto|hotel|posada|"
                  r"iglesia|residencia|conjunto|barrio|parroquia|kilometro|entrada|club)\b")


def qa(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def mil(n):
    return f"{int(n):,}".replace(",", ".")

def pc(x):  # x ya en porcentaje (0-100)
    return f"{x:.1f}".replace(".", ",") + "%"


def ciudad(s):
    t = qa(s.lower())
    for c in CIUDADES:
        if c in t:
            return c.title()
    return "Otras / sin clasificar"

def nivel_ubic(s):
    t = qa(s.lower()).strip()
    if not t:
        return "vacio"
    toks = len(t.split())
    comma = "," in s
    if MARK.search(t) or (comma and toks >= 4):
        return "dir"
    if comma or toks >= 3:
        return "barrio"
    return "ciudad"


def bar(name, cnt, total, width, color=None, muted=False):
    col = f";background:{color}" if color else ""
    nm = ' style="color:var(--muted)"' if muted else ""
    return (f'      <div class="bar"><span class="name"{nm}>{name}</span>'
            f'<span class="track"><span class="fill" style="--w:{width:.1f}%{col}"></span></span>'
            f'<span class="val">{mil(cnt)}<small>{pc(100*cnt/total)}</small></span></div>')


def pyr_row(label, m, f, u, maxcell, total, nodata=False):
    wm, wf = 100 * m / maxcell, 100 * f / maxcell
    wu = 100 * (u / 2) / maxcell
    cls = "pyr-row nodata" if nodata else "pyr-row"
    lab = "Edad<br>sin dato" if nodata else label
    return (f'      <div class="{cls}">\n'
            f'        <div class="pyr-side left"><span class="v">{mil(m)}<small>{pc(100*m/total)}</small></span>'
            f'<span class="bar m" style="--w:{wm:.1f}%"></span><span class="bar u" style="--w:{wu:.2f}%"></span></div>\n'
            f'        <div class="pyr-label">{lab}</div>\n'
            f'        <div class="pyr-side right"><span class="bar u" style="--w:{wu:.2f}%"></span>'
            f'<span class="bar f" style="--w:{wf:.1f}%"></span><span class="v">{mil(f)}<small>{pc(100*f/total)}</small></span></div>\n'
            f'      </div>')


def main():
    pu = pd.read_csv(PU, dtype=str, keep_default_na=False)
    rd = pd.read_csv(RD, dtype=str, keep_default_na=False)
    N = len(pu)
    reportes = len(rd)
    dup = reportes - N

    se_busca = int((pu["estado_resuelto"] == "Se busca").sum())
    resuelto = int((pu["estado_resuelto"] == "Resuelto").sum())
    p_busca = 100 * se_busca / N

    # Sexo
    sx = pu["sexo_inferido"].value_counts().to_dict()
    F, M = sx.get("Femenino", 0), sx.get("Masculino", 0)
    DESC, OTRO = sx.get("Desconocido", 0), sx.get("Otro", 0)
    sin_sexo = DESC + OTRO
    cov_sexo = round(100 * (F + M + OTRO) / N)
    maxsx = max(F, M, DESC, OTRO)
    sexo_rows = "\n".join([
        bar("Femenino", F, N, 100 * F / maxsx, "var(--blue-bright)"),
        bar("Masculino", M, N, 100 * M / maxsx, "var(--blue-deep)"),
        bar("Desconocido", DESC, N, 100 * DESC / maxsx, "var(--slate)"),
        bar("Otro", OTRO, N, 100 * OTRO / maxsx, "var(--blue-soft)"),
    ])

    # Edad
    ge = pu["grupo_edad"].replace("", "Sin dato")
    ec = ge.value_counts().to_dict()
    e = {k: ec.get(k, 0) for k in ["0-4", "5-17", "18-59", "60+", "Sin dato"]}
    maxe = max(e.values())
    edad_rows = "\n".join([
        bar("0–4 (primera infancia)", e["0-4"], N, 100 * e["0-4"] / maxe, "var(--blue-soft)"),
        bar("5–17 (NNA)", e["5-17"], N, 100 * e["5-17"] / maxe, "#7ec0e8"),
        bar("18–59 (adultos)", e["18-59"], N, 100 * e["18-59"] / maxe, "var(--blue)"),
        bar("60+ (adultos mayores)", e["60+"], N, 100 * e["60+"] / maxe, "var(--blue-deep)"),
        bar("Sin dato", e["Sin dato"], N, 100 * e["Sin dato"] / maxe, "var(--slate)"),
    ])

    # Pirámide: sexo × edad
    pu["_ge"] = ge
    ct = pd.crosstab(pu["_ge"], pu["sexo_inferido"])
    for c in ["Masculino", "Femenino", "Desconocido", "Otro"]:
        if c not in ct.columns:
            ct[c] = 0
    def cell(b):
        m = int(ct.loc[b, "Masculino"]) if b in ct.index else 0
        f = int(ct.loc[b, "Femenino"]) if b in ct.index else 0
        u = (int(ct.loc[b, "Desconocido"]) + int(ct.loc[b, "Otro"])) if b in ct.index else 0
        return m, f, u
    bands = [("60+", *cell("60+")), ("18–59", *cell("18-59")),
             ("5–17", *cell("5-17")), ("0–4", *cell("0-4"))]
    sdm, sdf, sdu = cell("Sin dato")
    maxcell = max([max(b[1], b[2]) for b in bands] + [max(sdm, sdf)])
    pyr_rows = "\n\n".join([pyr_row(lb, m, f, u, maxcell, N) for lb, m, f, u in bands])
    pyr_rows += "\n\n" + pyr_row("", sdm, sdf, sdu, maxcell, N, nodata=True)
    mf_pct = 100 * (M + F) / N
    pyr_note = (f"Porcentajes sobre el total de personas ({mil(N)}). "
                f"Masculino + Femenino = {pc(mf_pct)}; el {pc(100*sin_sexo/N)} restante es "
                f"<b>sexo sin dato</b> (gris al centro).")
    pyr_legend = (
        f'<span class="leg"><span class="dot" style="background:var(--blue-deep)"></span>Masculino · {mil(M)} ({pc(100*M/N)})</span>\n'
        f'      <span class="leg"><span class="dot" style="background:var(--blue-bright)"></span>Femenino · {mil(F)} ({pc(100*F/N)})</span>\n'
        f'      <span class="leg"><span class="dot" style="background:var(--slate);opacity:.7"></span>Sexo sin dato · {mil(sin_sexo)} ({pc(100*sin_sexo/N)})</span>')

    # Ubicaciones
    cc = pu["ubicacion"].map(ciudad).value_counts()
    nombradas = [(k, int(v)) for k, v in cc.items() if k != "Otras / sin clasificar"][:8]
    otras = int(cc.get("Otras / sin clasificar", 0))
    maxc = nombradas[0][1] if nombradas else 1
    city_rows = "\n".join([bar(k, v, N, 100 * v / maxc, "var(--blue)") for k, v in nombradas])
    city_rows += "\n" + bar("Otras / sin clasificar", otras, N, 100 * otras / maxc, "var(--slate)", muted=True)

    # Especificidad de ubicación
    niv = pu["ubicacion"].map(nivel_ubic).value_counts().to_dict()
    n_ciudad = niv.get("ciudad", 0) + niv.get("vacio", 0)
    n_barrio = niv.get("barrio", 0)
    n_dir = niv.get("dir", 0)
    def cobertura(col):
        g = rd.groupby("cluster_id")[col].apply(lambda s: (s.str.strip() != "").any())
        return 100 * int(g.sum()) / N
    zona_p, dir_p, ult_p = cobertura("zona_barrio"), cobertura("direccion_precisa"), cobertura("ultima_ubicacion")

    # Logo + timestamp
    logo = "data:image/png;base64," + base64.b64encode(open(LOGO, "rb").read()).decode()
    now = datetime.now(timezone(timedelta(hours=-4)))
    ts = f"{now.day} de {MESES[now.month-1]} de {now.year}, {now:%H:%M} (hora de Venezuela, UTC−4)"

    tokens = {
        "__LOGO__": logo, "__TS__": ts,
        "__TOTAL__": mil(N), "__REPORTES__": mil(reportes), "__DUP_N__": mil(dup),
        "__DUP_PCT__": f"{round(100*dup/reportes)}%",
        "__SEBUSCA__": mil(se_busca), "__SEBUSCA_PCT__": pc(p_busca),
        "__RESUELTO__": mil(resuelto), "__RESUELTO_PCT__": pc(100*resuelto/N),
        "__DONUT_P__": f"{p_busca:.1f}",
        "__SEXO_ROWS__": sexo_rows, "__SEXO_COV__": f"{cov_sexo}%",
        "__EDAD_ROWS__": edad_rows,
        "__EDAD_COV__": f"{round(100*(N-e['Sin dato'])/N)}%",
        "__PYR_ROWS__": pyr_rows, "__PYR_NOTE__": pyr_note, "__PYR_LEGEND__": pyr_legend,
        "__CITY_ROWS__": city_rows,
        "__Q_CIUDAD_PCT__": pc(100*n_ciudad/N), "__Q_CIUDAD_N__": mil(n_ciudad),
        "__Q_BARRIO_PCT__": pc(100*n_barrio/N), "__Q_BARRIO_N__": mil(n_barrio),
        "__Q_DIR_PCT__": pc(100*n_dir/N), "__Q_DIR_N__": mil(n_dir),
        "__ZONA_P__": pc(zona_p), "__DIR_P__": pc(dir_p), "__ULT_P__": pc(ult_p),
    }
    html = TEMPLATE
    for k, v in tokens.items():
        html = html.replace(k, v)
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"Escrito: {OUT}")
    print(f"  personas={mil(N)} se_busca={mil(se_busca)} resuelto={mil(resuelto)} "
          f"F={mil(F)} M={mil(M)} sin_sexo={mil(sin_sexo)}")
    print(f"  actualizado: {ts}")


TEMPLATE = r"""<title>Personas desaparecidas · Venezuela 2026 — base de-duplicada</title>
<meta name="description" content="Retrato de la base de-duplicada de personas reportadas desaparecidas tras el terremoto de Venezuela 2026: sexo, edad, estado y calidad de las ubicaciones. Elaborado por OLDS2030.">
<style>
  :root{
    --paper:#eef3f8; --card:#ffffff; --ink:#13314a; --ink-soft:#4d6075; --muted:#8093a4;
    --line:#d6e1ec; --line-soft:#e9f0f6;
    --blue:#1f8fd0; --blue-deep:#0b4f7a; --navy:#0a3a5c; --blue-bright:#3aa6dd; --blue-soft:#bcdcf0;
    --green:#2f9c6a; --amber:#e0902f; --slate:#a9b9c8;
    --maxw:1060px;
  }
  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0; background:var(--paper); color:var(--ink);
    font:400 16px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    font-variant-numeric:tabular-nums;}
  .sdg{height:5px; background:linear-gradient(90deg,
    #e5243b 0 11%,#fd9d24 11% 22%,#fcc30b 22% 33%,#4c9f38 33% 47%,
    #1f8fd0 47% 64%,#19486a 64% 80%,#dd1367 80% 100%);}
  .band{background:linear-gradient(135deg,var(--navy),var(--blue-deep)); color:#fff;}
  .bandwrap{display:flex; gap:22px; align-items:flex-start; justify-content:space-between;
    max-width:var(--maxw); margin:0 auto; padding:clamp(22px,4vw,40px) clamp(18px,4vw,40px);}
  .band .eyebrow{font-size:.72rem; letter-spacing:.18em; text-transform:uppercase; color:var(--blue-soft); font-weight:600;}
  .band h1{font-size:clamp(1.8rem,4.4vw,2.9rem); line-height:1.04; margin:.3em 0 .3em; font-weight:800; letter-spacing:-.01em; text-wrap:balance; max-width:18ch;}
  .band .stand{font-size:clamp(.98rem,1.5vw,1.12rem); color:#dbe9f5; max-width:62ch; text-wrap:pretty;}
  .band .updated{margin-top:14px; font-size:.82rem; color:var(--blue-soft); font-weight:600;}
  .band .updated b{color:#fff; font-weight:700;}
  .brandmark{display:flex; flex-direction:column; align-items:center; gap:0; flex:0 0 auto;
    background:#fff; border-radius:10px; padding:12px 16px;}
  .olds-logo{display:inline-block; background:center/contain no-repeat url("__LOGO__");}
  .olds-logo--hd{width:152px; height:58px;}
  .olds-logo--ft{width:116px; height:45px;}
  .wrap{max-width:var(--maxw); margin:0 auto; padding:clamp(18px,3.5vw,34px) clamp(18px,4vw,40px) clamp(28px,4vw,48px);}
  .provenance{display:flex; flex-wrap:wrap; align-items:center; gap:10px 16px;
    padding:13px 18px; background:var(--card); border:1px solid var(--line); border-left:4px solid var(--blue);
    border-radius:10px; font-size:.95rem; color:var(--ink-soft); margin-top:clamp(-30px,-4vw,-22px); position:relative; box-shadow:0 6px 20px rgba(11,79,122,.07);}
  .provenance b{color:var(--ink); font-weight:700;}
  .flow{display:flex; align-items:center; gap:10px;}
  .flow .arrow{color:var(--blue); font-weight:800;}
  .method{background:#e7f1f9; border:1px solid #c7def0; border-left:4px solid var(--blue-deep);
    border-radius:10px; padding:15px 18px; margin-top:18px; font-size:.95rem; color:#234a64;}
  .method b{color:var(--blue-deep);}
  .srcnote{display:flex; gap:10px; align-items:baseline; margin-top:12px; padding:11px 16px;
    background:#fff; border:1px dashed var(--blue); border-radius:10px; font-size:.88rem; color:var(--ink-soft);}
  .srcnote .tag{flex:0 0 auto; font-size:.66rem; letter-spacing:.08em; text-transform:uppercase;
    font-weight:700; color:#fff; background:var(--blue); border-radius:5px; padding:3px 8px; translate:0 -1px;}
  .srcnote b{color:var(--blue-deep);}
  hr.rule{border:0; border-top:1px solid var(--line); margin:clamp(30px,4.5vw,46px) 0;}
  section{margin-top:clamp(28px,4vw,42px);}
  h2{font-size:1.08rem; letter-spacing:.01em; margin:0 0 4px; font-weight:700; color:var(--navy);}
  .sub{font-size:.9rem; color:var(--muted); margin:0 0 18px; max-width:74ch;}
  .kpis{display:grid; grid-template-columns:repeat(4,1fr); gap:14px;}
  .kpi{background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px; position:relative; overflow:hidden;}
  .kpi::before{content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--blue);}
  .kpi.amber::before{background:var(--amber);} .kpi.green::before{background:var(--green);} .kpi.slate::before{background:var(--muted);}
  .kpi .n{font-size:clamp(1.7rem,3.4vw,2.4rem); font-weight:800; line-height:1; color:var(--navy);}
  .kpi .lbl{margin-top:8px; font-size:.82rem; color:var(--ink-soft);}
  .kpi .delta{font-size:.76rem; color:var(--muted); margin-top:3px;}
  .cols{display:grid; grid-template-columns:1fr 1fr; gap:clamp(20px,3.5vw,40px); align-items:start;}
  .bars{display:flex; flex-direction:column; gap:11px;}
  .bar{display:grid; grid-template-columns:9rem 1fr auto; align-items:center; gap:12px; font-size:.92rem;}
  .bar .name{color:var(--ink); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
  .track{height:14px; background:var(--line-soft); border-radius:7px; overflow:hidden;}
  .fill{height:100%; width:var(--w); border-radius:7px; background:var(--blue);
        transform-origin:left; animation:grow .9s cubic-bezier(.22,.61,.36,1) both;}
  .bar .val{font-weight:700; color:var(--ink); white-space:nowrap;}
  .bar .val small{color:var(--muted); font-weight:400; margin-left:5px;}
  @keyframes grow{from{transform:scaleX(0)} to{transform:scaleX(1)}}
  @media(prefers-reduced-motion:reduce){.fill,.pyr-side .bar{animation:none}}
  .donut-wrap{display:flex; align-items:center; gap:26px; flex-wrap:wrap;}
  .donut{--p:90.6; width:168px; height:168px; border-radius:50%; flex:0 0 auto;
    background:conic-gradient(var(--blue) 0 calc(var(--p)*1%), var(--green) 0);
    -webkit-mask:radial-gradient(circle 50px at center,transparent 98%,#000 100%);
            mask:radial-gradient(circle 50px at center,transparent 98%,#000 100%);}
  .legend{display:flex; flex-direction:column; gap:12px;}
  .leg{display:flex; gap:10px; align-items:baseline;}
  .dot{width:11px; height:11px; border-radius:3px; flex:0 0 auto; translate:0 1px;}
  .leg .v{font-weight:700;} .leg .v small{color:var(--muted); font-weight:400; margin-left:4px;}
  .leg .t{font-size:.9rem; color:var(--ink-soft);}
  .pyr{display:flex; flex-direction:column; gap:9px; margin-top:4px;}
  .pyr-head{display:grid; grid-template-columns:1fr 5.4rem 1fr; align-items:center;
    font-size:.74rem; letter-spacing:.1em; text-transform:uppercase; color:var(--muted);}
  .pyr-head .l{text-align:right; padding-right:10px; color:var(--blue-deep); font-weight:700;}
  .pyr-head .r{text-align:left; padding-left:10px; color:var(--blue-bright); font-weight:700;}
  .pyr-row{display:grid; grid-template-columns:1fr 5.4rem 1fr; align-items:center;}
  .pyr-side{display:flex; align-items:center; height:20px; overflow:hidden;}
  .pyr-side.left{justify-content:flex-end;}
  .pyr-side.right{justify-content:flex-start;}
  .pyr-side .bar{height:100%; width:var(--w); min-width:2px; animation:grow .9s cubic-bezier(.22,.61,.36,1) both;}
  .pyr-side.left .bar{transform-origin:right;}
  .pyr-side.right .bar{transform-origin:left;}
  .bar.m{background:var(--blue-deep);}
  .bar.f{background:var(--blue-bright);}
  .bar.u{background:var(--slate); opacity:.7;}
  .pyr-side .v{font-size:.8rem; font-weight:700; color:var(--ink-soft); white-space:nowrap;}
  .pyr-side .v small{font-weight:400; color:var(--muted); margin-left:4px;}
  .pyr-side.left .v{padding-right:8px;} .pyr-side.right .v{padding-left:8px;}
  .pyr-label{text-align:center; font-size:.86rem; color:var(--ink); white-space:nowrap;}
  .pyr-row.nodata{margin-top:6px; padding-top:9px; border-top:1px dashed var(--line);}
  .pyr-row.nodata .pyr-label{color:var(--muted);}
  .pyr-legend{display:flex; gap:20px; flex-wrap:wrap; margin-top:16px; font-size:.86rem; color:var(--ink-soft);}
  .pyr-legend .leg{display:flex; gap:8px; align-items:center;}
  .pyr-legend .dot{width:11px; height:11px; border-radius:3px;}
  .qgrid{display:grid; grid-template-columns:repeat(3,1fr); gap:14px;}
  .qcard{background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px;}
  .qcard .p{font-size:1.9rem; font-weight:800; line-height:1;}
  .qcard .k{font-size:.86rem; color:var(--ink-soft); margin-top:6px;}
  .qcard.good{border-top:4px solid var(--green);} .qcard.mid{border-top:4px solid var(--blue);} .qcard.low{border-top:4px solid var(--muted);}
  .note{background:#e7f1f9; border:1px solid #c7def0; border-left:4px solid var(--blue); border-radius:10px;
        padding:14px 16px; font-size:.92rem; color:#234a64; margin-top:18px;}
  .note b{color:var(--blue-deep);}
  footer{margin-top:clamp(34px,5vw,52px); padding-top:24px; border-top:1px solid var(--line); text-align:center;}
  .credit{display:inline-flex; align-items:center; gap:12px; justify-content:center; flex-wrap:wrap;
    background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 22px; margin:0 auto 16px;
    color:var(--ink-soft); font-size:.92rem; max-width:78ch; text-align:left;}
  .credit b{color:var(--ink);}
  footer p{margin:.55em auto; max-width:80ch; color:var(--muted); font-size:.82rem;}
  footer b{color:var(--ink-soft);}
  footer a{color:var(--blue-deep); font-weight:600; text-decoration:none; border-bottom:1px solid var(--blue-soft);}
  footer a:hover{border-bottom-color:var(--blue-deep);}
  a:focus-visible,.qcard:focus-visible{outline:2px solid var(--blue); outline-offset:2px;}
  @media(max-width:760px){
    .kpis{grid-template-columns:repeat(2,1fr);}
    .cols{grid-template-columns:1fr;}
    .qgrid{grid-template-columns:1fr;}
    .bar{grid-template-columns:7rem 1fr auto;}
    .bandwrap{flex-direction:column; gap:14px;}
  }
</style>

<div class="sdg"></div>

<header class="band">
  <div class="bandwrap">
    <div>
      <div class="eyebrow">Terremoto de Venezuela · 2026 · Estado La Guaira</div>
      <h1>Personas reportadas desaparecidas</h1>
      <p class="stand">Retrato de la base <b style="color:#fff">de-duplicada</b>: una fila por persona,
         no por reporte. Datos ciudadanos en abierto, <b style="color:#fff">sin verificar</b>;
         información indicativa para apoyar la localización.</p>
      <div class="updated">Actualizado: <b>__TS__</b></div>
    </div>
    <div class="brandmark">
      <span class="olds-logo olds-logo--hd" role="img" aria-label="OLDS — Observatorio Latinoamericano de Desarrollo Sostenible"></span>
    </div>
  </div>
</header>

<div class="wrap">

  <div class="provenance">
    <span class="flow"><b>__REPORTES__</b>&nbsp;reportes crudos</span>
    <span class="flow"><span class="arrow">→</span> deduplicación conservadora</span>
    <span class="flow"><span class="arrow">→</span> <b>__TOTAL__</b>&nbsp;personas únicas</span>
    <span style="color:var(--muted)">(se descartaron __DUP_N__ reportes repetidos, __DUP_PCT__)</span>
  </div>

  <div class="srcnote">
    <span class="tag">Fuentes en expansión</span>
    <span>Por ahora los datos provienen <b>únicamente de Venezuela Reporta</b>. Se están integrando
    otras bases de datos para ampliar la cobertura; las cifras crecerán al sumar nuevas fuentes.</span>
  </div>

  <div class="method">
    <b>Cómo se de-duplicó.</b> Los reportes se agrupan en personas con reglas + coincidencia
    aproximada de texto: la <b>misma cédula</b> identifica a la misma persona; cuando no hay cédula,
    se exige que el <b>nombre</b> coincida y que además lo respalde la <b>edad, el sexo o una
    ubicación específica</b>. Cédulas distintas nunca se unen. El criterio es deliberadamente
    <b>conservador</b>: ante la duda no fusiona —es preferible un duplicado de más que juntar por
    error a dos personas distintas—.
  </div>

  <section aria-label="Cifras principales" style="margin-top:22px">
    <div class="kpis">
      <div class="kpi"><div class="n">__TOTAL__</div><div class="lbl">Personas únicas</div><div class="delta">de __REPORTES__ reportes</div></div>
      <div class="kpi amber"><div class="n">__SEBUSCA__</div><div class="lbl">Aún en búsqueda</div><div class="delta">__SEBUSCA_PCT__ de las personas</div></div>
      <div class="kpi green"><div class="n">__RESUELTO__</div><div class="lbl">Encontradas o a salvo</div><div class="delta">__RESUELTO_PCT__ de las personas</div></div>
      <div class="kpi slate"><div class="n">__DUP_PCT__</div><div class="lbl">Reportes duplicados</div><div class="delta">misma persona, varias veces</div></div>
    </div>
  </section>

  <hr class="rule">

  <div class="cols">
    <section style="margin-top:0">
      <h2>Estado de la búsqueda</h2>
      <p class="sub">Una persona se cuenta como resuelta si <em>cualquiera</em> de sus reportes la marca encontrada o a salvo.</p>
      <div class="donut-wrap">
        <div class="donut" style="--p:__DONUT_P__" role="img" aria-label="__SEBUSCA_PCT__ aún en búsqueda"></div>
        <div class="legend">
          <div class="leg"><span class="dot" style="background:var(--blue)"></span>
            <div><div class="v">__SEBUSCA__ <small>· __SEBUSCA_PCT__</small></div><div class="t">Aún en búsqueda</div></div></div>
          <div class="leg"><span class="dot" style="background:var(--green)"></span>
            <div><div class="v">__RESUELTO__ <small>· __RESUELTO_PCT__</small></div><div class="t">Encontradas / a salvo</div></div></div>
        </div>
      </div>
    </section>

    <section style="margin-top:0">
      <h2>Sexo</h2>
      <p class="sub">Inferido por persona (reportado → nombre → descripción). Cobertura __SEXO_COV__.</p>
      <div class="bars">
__SEXO_ROWS__
      </div>
    </section>
  </div>

  <hr class="rule">

  <section>
    <h2>Rango de edad</h2>
    <p class="sub">Grupos de vulnerabilidad estándar (UN OCHA). Inferido por persona; grupo de edad asignado al __EDAD_COV__.</p>
    <div class="bars">
__EDAD_ROWS__
    </div>
  </section>

  <hr class="rule">

  <section>
    <h2>Pirámide poblacional</h2>
    <p class="sub">Personas por sexo y grupo de edad (UN OCHA). El gris al centro = sin sexo
       determinado; la franja inferior = sin edad conocida. La incertidumbre del dato se muestra,
       no se oculta.</p>
    <div class="pyr">
      <div class="pyr-head"><span class="l">◀ Masculino</span><span></span><span class="r">Femenino ▶</span></div>

__PYR_ROWS__
    </div>
    <p class="sub" style="margin-top:11px">__PYR_NOTE__</p>
    <div class="pyr-legend">
      __PYR_LEGEND__
    </div>
  </section>

  <hr class="rule">

  <section>
    <h2>Ubicaciones, a grandes rasgos</h2>
    <p class="sub">Personas por localidad (clasificadas por palabra clave sobre el texto de ubicación). El terremoto golpeó la franja costera de La Guaira.</p>
    <div class="bars">
__CITY_ROWS__
    </div>
  </section>

  <hr class="rule">

  <section>
    <h2>¿Qué tan bien sirven estas ubicaciones para un mapa?</h2>
    <p class="sub">Toda persona tiene una ubicación (cobertura 100%), pero la precisión varía. Clasificación por nivel de detalle geográfico del texto.</p>
    <div class="qgrid">
      <div class="qcard low"><div class="p" style="color:var(--muted)">__Q_CIUDAD_PCT__</div>
        <div class="k"><b>Solo ciudad / municipio</b><br>__Q_CIUDAD_N__ personas. Geocodifica al centro de la localidad, no a un punto.</div></div>
      <div class="qcard mid"><div class="p" style="color:var(--blue)">__Q_BARRIO_PCT__</div>
        <div class="k"><b>Barrio o sector</b><br>__Q_BARRIO_N__ personas. Acerca a una zona, sin dirección exacta.</div></div>
      <div class="qcard good"><div class="p" style="color:var(--green)">__Q_DIR_PCT__</div>
        <div class="k"><b>Dirección o lugar específico</b><br>__Q_DIR_N__ personas. Calle, edificio, hospital, playa… geocodificable a un punto.</div></div>
    </div>
    <div class="note">
      <b>Hallazgo para el mapa:</b> los campos estructurados de dirección vienen casi vacíos
      —<b>dirección precisa __DIR_P__</b>, última ubicación __ULT_P__, zona/barrio __ZONA_P__—. Todo el
      detalle geográfico está embebido en el texto libre de <code>ubicacion</code>. Un mapa exigirá
      <b>geocodificación con NLP</b> sobre ese texto.
    </div>
  </section>

  <footer>
    <div class="credit">
      <span class="olds-logo olds-logo--ft" aria-hidden="true"></span>
      <span>Elaborado por el <b><a href="https://www.olds2030.org/">Observatorio Latinoamericano de
      Desarrollo Sostenible</a></b> con datos ciudadanos compartidos en abierto sin verificar. La
      información es <b>indicativa</b> y debe utilizarse con cuidado y contrastar con otras fuentes.</span>
    </div>
    <p><b>Fuente de datos (en expansión):</b> por ahora únicamente Venezuela Reporta — registro
       comunitario humanitario, sin verificar (<a href="https://venezuelareporta.org/buscar">venezuelareporta.org</a>).
       Se están integrando otras bases de datos. Cifras por persona sobre la base de-duplicada
       (__TOTAL__ personas de __REPORTES__ reportes).</p>
    <p><b>Metodología y código abierto:</b> <a href="https://github.com/alcastaro/venezuela-missing-persons-dedup">github.com/alcastaro/venezuela-missing-persons-dedup</a> — ahí se puede revisar el método de deduplicación y contribuir.</p>
    <p><b>Método:</b> deduplicación conservadora (cédulas distintas no se fusionan; el nombre solo no
       basta sin corroboración por edad, sexo o lugar específico). Sexo y edad inferidos 100% offline,
       nunca inventados: vacío cuando no hay señal.</p>
    <p><b>Uso responsable:</b> contiene datos personales sensibles de población vulnerable. Usar solo
       para apoyar su localización; no redistribuir contactos fuera de ese fin.</p>
  </footer>

</div>
"""


if __name__ == "__main__":
    main()
