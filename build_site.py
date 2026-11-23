"""Construit les données de la démo web (docs/data.js) à partir des résultats du pipeline.

Prérequis : load_data.py, filter1.py, filter2.py, (filter3.py), patterns.py déjà lancés.
Fond de carte : contours des communes des Yvelines (API Géo, geo.api.gouv.fr), mis en cache.

Usage :  python build_site.py      puis ouvrir docs/index.html
"""
import json
import math
from pathlib import Path

import pandas as pd
import requests

from patterns import CIBLES, FLAGS, charger, echeances, projets_sociaux, reguliers, score_prospects

DATA = Path("data/processed")
RAW = Path("data/raw")
RES = Path("results")
OUT = Path("docs/data.js")
GEO_URL = "https://geo.api.gouv.fr/communes"
GEO_CACHE = RAW / "communes78.geojson"
W = 1000  # largeur du viewBox SVG de la carte


# ------------------------------------------------------------------ carte
def charger_geo() -> dict:
    if not GEO_CACHE.exists():
        r = requests.get(GEO_URL, params={"codeDepartement": "78", "fields": "nom,code", "format": "geojson",
                                          "geometry": "contour"},
                         headers={"User-Agent": "etude-sitadel-78/0.1"}, timeout=60)
        r.raise_for_status()
        GEO_CACHE.write_bytes(r.content)
    return json.loads(GEO_CACHE.read_text(encoding="utf-8"))


def _rdp(pts, eps):
    """Simplification de Ramer-Douglas-Peucker (itérative)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    pile = [(0, len(pts) - 1)]
    while pile:
        a, b = pile.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        norme = math.hypot(dx, dy) or 1e-9
        dmax, imax = 0.0, a
        for i in range(a + 1, b):
            x0, y0 = pts[i]
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norme
            if d > dmax:
                dmax, imax = d, i
        if dmax > eps:
            keep[imax] = True
            pile += [(a, imax), (imax, b)]
    return [p for p, k in zip(pts, keep) if k]


def carte(geo: dict) -> dict:
    rings_par_commune = []
    for f in geo["features"]:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        rings_par_commune.append((f["properties"], [p[0] for p in polys]))  # anneaux extérieurs
    lons = [x for _, rs in rings_par_commune for r in rs for x, _ in r]
    lats = [y for _, rs in rings_par_commune for r in rs for _, y in r]
    lat0 = (min(lats) + max(lats)) / 2
    kx = math.cos(math.radians(lat0))
    xmin, xmax, ymax = min(lons) * kx, max(lons) * kx, max(lats)
    s = W / (xmax - xmin)
    h = (ymax - min(lats)) * s

    def proj(lon, lat):
        return ((lon * kx - xmin) * s, (ymax - lat) * s)

    communes = {}
    for props, rings in rings_par_commune:
        d, plus_grand, aire_max = [], None, -1
        for r in rings:
            brut = [proj(x, y) for x, y in r]
            pts = _rdp(brut, 1.0)
            if len(pts) < 4:  # très petite commune : on garde le contour non simplifié
                pts = brut
            d.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
            aire = abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2
            if aire > aire_max:
                plus_grand, aire_max = pts, aire
        cx = sum(x for x, _ in plus_grand) / len(plus_grand)
        cy = sum(y for _, y in plus_grand) / len(plus_grand)
        communes[props["code"]] = {"nom": props["nom"], "d": "".join(d), "c": [round(cx, 1), round(cy, 1)]}
    return {"w": W, "h": round(h, 1), "communes": communes}


# ------------------------------------------------------------------ données
def groupe_demandeur(fam) -> str:
    if fam in CIBLES:
        return "cible"
    if fam == "societe_civile_immo":
        return "sci"
    return "autre"  # promoteurs, entreprises, non qualifiés


def main() -> None:
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    ref = pd.Timestamp(meta["date_chargement"])
    permis, dem = charger()
    reg, proj = reguliers(permis, dem), projets_sociaux(permis, dem)
    ech = echeances(permis, dem, ref, 12)
    sc = score_prospects(dem, reg, proj, ech)
    geo = carte(charger_geo())
    noms = {k: v["nom"] for k, v in geo["communes"].items()}

    # entonnoir de qualification
    qual = dem["famille"].notna() & ~dem["famille"].isin(["association_fondation", "societe_civile_immo"])
    par_regle = qual & dem["methode"].fillna("").str.match(r"R(0|1)")
    par_finess = qual & dem["methode"].fillna("").str.match(r"R2")
    par_agent = qual & (dem["methode"] == "agent")

    def nb_permis_lignes(df):
        return df.sort_values("fichier").drop_duplicates("NUM_DAU")

    cibles = []
    for _, r in sc.iterrows():
        p = nb_permis_lignes(permis[permis["SIREN_DEM"] == r["siren"]]).sort_values("date_aut", ascending=False)
        e = ech[ech["SIREN_DEM"] == r["siren"]]
        cibles.append({
            "siren": r["siren"], "nom": r["denomination"], "famille": r["famille"], "confiance": r["confiance"],
            "methode": "agent" if r["methode"] == "agent" else ("FINESS" if str(r["methode"]).startswith("R2")
                                                                 else "règle"),
            "preuve": str(r["preuve"])[:400], "score": int(r["score"]), "regulier": bool(r["regulier"]),
            "projets": int(r["nb_projets_sociaux"]), "echeances": int(r["nb_echeances"]),
            "echeance_min": str(e["fin_validite_theorique"].min().date()) if len(e) else None,
            "nb_permis": int(r["nb_permis"]),
            "logements": int(p["NB_LGT_TOT_CREES"].sum()), "lls": int(p["NB_LGT_PRET_LOC_SOCIAL"].sum()),
            "permis": [{
                "num": q["NUM_DAU"], "date": q["DATE_REELLE_AUTORISATION"],
                "commune": noms.get(q["COMM"], q["ADR_LOCALITE_TER"] if isinstance(q["ADR_LOCALITE_TER"], str) else q["COMM"]),
                "lgt": int(q["NB_LGT_TOT_CREES"]), "lls": int(q["NB_LGT_PRET_LOC_SOCIAL"]),
                "res": ", ".join(v for k, v in FLAGS.items() if q[k]), "etat": q["ETAT_DAU"],
            } for _, q in p.iterrows()],
        })

    projets = [{
        "num": q["NUM_DAU"], "date": q["DATE_REELLE_AUTORISATION"], "comm": q["COMM"],
        "commune": noms.get(q["COMM"], q["COMM"]), "type": q["type_residence"], "lgt": int(q["NB_LGT_TOT_CREES"]),
        "demandeur": q["DENOM_DEM"], "famille": q["famille"] if isinstance(q["famille"], str) else None,
        "groupe": groupe_demandeur(q["famille"]), "asso": str(q["CJ_DEM"])[:2] in ("92", "93"),
    } for _, q in proj.iterrows()]

    echs = [{
        "num": q["NUM_DAU"], "aut": q["DATE_REELLE_AUTORISATION"], "fin": str(q["fin_validite_theorique"].date()),
        "regle": q["regle_validite"], "commune": noms.get(q["COMM"], q["COMM"]), "lgt": int(q["NB_LGT_TOT_CREES"]),
        "demandeur": q["DENOM_DEM"], "famille": q["famille"] if isinstance(q["famille"], str) else None,
    } for _, q in ech.iterrows()]

    evals = {}
    for nom, f in [("fuite", "evaluation_AVEC_FUITE.csv"), ("sans_naf", "evaluation_AVANT_NAF.csv"),
                   ("final", "evaluation_sans_finess.csv")]:
        e = pd.read_csv(RES / f, dtype=str)
        m = e[e["attendu"] == "medico_social"]
        b = e[e["attendu"] == "bailleur_social"]
        evals[nom] = {"medico": int((m["ok"] == "True").sum()), "medico_n": len(m),
                      "bailleur": int((b["ok"] == "True").sum()), "bailleur_n": len(b)}
    dec = pd.read_csv(RES / "decisions_agent.csv", dtype=str)

    data = {
        "meta": {"millesime": meta["sitadel_millesime"], "date": meta["date_chargement"],
                 "permis": meta["nb_permis_distincts"], "lignes": meta["nb_lignes"],
                 "demandeurs": meta["nb_demandeurs"], "dans_finess": meta["nb_demandeurs_dans_finess"]},
        "qualif": {"regles": int(par_regle.sum()), "finess": int(par_finess.sum()), "agent": int(par_agent.sum()),
                   "total": int(qual.sum()), "cibles": int(dem["famille"].isin(CIBLES).sum()),
                   "sci": int((dem["famille"] == "societe_civile_immo").sum()),
                   "asso": int((dem["famille"] == "association_fondation").sum()),
                   "indetermine": int(dem["famille"].isna().sum())},
        "reguliers": {"total": len(reg), "cibles": int(reg["famille"].isin(CIBLES).sum())},
        "agent": {"traites": len(dec), "familles": dec["famille"].value_counts().to_dict(),
                  "rejetees": int(dec["nb_preuves_rejetees"].astype(int).sum()),
                  "nouvelles_cibles": dec[dec["famille"].isin(CIBLES)]["denomination"].tolist()},
        "evals": evals, "cibles": cibles, "projets": projets, "echeances": echs, "carte": geo,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("window.DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    sans_commune = sum(1 for p in projets if p["comm"] not in geo["communes"])
    print(f"{OUT} : {OUT.stat().st_size / 1024:.0f} Ko | {len(cibles)} cibles | {len(projets)} projets "
          f"({sans_commune} hors fond de carte) | {len(echs)} échéances")


if __name__ == "__main__":
    main()
