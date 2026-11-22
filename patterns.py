"""Patterns exploitables par Buddimm, à partir des demandeurs qualifiés (filtres 1-2, + agent si lancé).

1. Clients réguliers : structures cibles (médico-social, bailleur social, ESS) qui déposent des
   permis sur plusieurs années => besoin immobilier récurrent.
2. Projets sociaux / médico-sociaux « cachés » : permis de résidence pour personnes âgées,
   handicapées ou sociale, QUEL QUE SOIT le demandeur. Le demandeur n'est pas forcément
   l'exploitant (un promoteur peut construire pour une association) : c'est un projet à creuser,
   pas un client confirmé.
3. Échéances : permis autorisés, sans aucune déclaration de chantier, dont la validité théorique
   arrive à échéance dans les 12 prochains mois.
   Règle (Légifrance, consultée le 22/11/2026) : art. R*424-17 du code de l'urbanisme, permis
   périmé si les travaux ne sont pas entrepris dans les 3 ans de la notification ; décret
   n° 2025-461 du 26 mai 2025 : 5 ans pour les permis intervenus entre le 28/05/2022 et le 28/05/2024.
   Approximations : date d'autorisation utilisée à la place de la notification ; prorogations
   (art. R*424-21 à 23) et recours non pris en compte ; ~15 % des ouvertures de chantier ne sont
   jamais déclarées dans Sitadel. => signal à vérifier, jamais une certitude.

Sorties (results/) : prospects_reguliers.csv, projets_sociaux.csv, echeances.csv, fiches_prospects.md

Usage :  python patterns.py [--date AAAA-MM-JJ] [--horizon 12] [--top 10]
"""
import argparse
import json
from pathlib import Path

import pandas as pd

DATA = Path("data/processed")
OUT = Path("results")
CIBLES = {"medico_social", "bailleur_social", "ess_autre"}
FLAGS = {"RES_PERS_AGEES": "personnes âgées", "RES_HANDICAPES": "handicap", "RES_SOCIALE": "sociale"}
DECRET_DEBUT, DECRET_FIN = pd.Timestamp("2022-05-28"), pd.Timestamp("2024-05-28")
# ETAT_DAU : libellés non publiés dans la documentation consultée ; sens INFÉRÉ des données du 78 :
# 2 = aucune date de chantier (2 695/2 695), 5 = ouverture sans achèvement, 6 = achevé,
# 4 = surtout sans ouverture, probablement annulé => exclu des échéances.
ETAT_SANS_CHANTIER = "2"


# ------------------------------------------------------------------ chargement
def charger(data: Path = DATA):
    permis = pd.read_csv(data / "permis_78.csv", dtype=str)
    permis["date_aut"] = pd.to_datetime(permis["DATE_REELLE_AUTORISATION"], errors="coerce")
    for c in ("NB_LGT_TOT_CREES", "NB_LGT_PRET_LOC_SOCIAL"):
        permis[c] = pd.to_numeric(permis[c], errors="coerce").fillna(0).astype(int)
    for c in FLAGS:
        permis[c] = permis[c] == "True"
    dem = pd.read_csv(data / "demandeurs_f2.csv", dtype=str)
    dem["methode"] = dem["regle"].where(dem["famille"].notna(), None)
    return permis, appliquer_agent(dem, data / "agent_results.jsonl")


def appliquer_agent(dem: pd.DataFrame, fichier: Path) -> pd.DataFrame:
    """Reporte les décisions de l'agent (si lancé) sur les demandeurs que les règles n'avaient pas tranchés."""
    if not fichier.exists():
        return dem
    dem = dem.copy()
    idx = dem.set_index("siren").index
    for line in fichier.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        d = r["decision"]
        if d["famille"] == "non_determine" or r["siren"] not in idx:
            continue
        i = dem.index[dem["siren"] == r["siren"]][0]
        if pd.isna(dem.at[i, "famille"]) or dem.at[i, "famille"] in {"association_fondation", "societe_civile_immo"}:
            preuves = "; ".join(f"{p['tool']}.{p['field']}={p['value']}" for p in d["preuves_verifiees"])
            dem.loc[i, ["famille", "confiance", "methode", "preuve"]] = [
                d["famille"], d["confiance"], "agent", f"Agent ({r['modele']}) : {preuves}"]
    return dem


# ------------------------------------------------------------------ pattern 1
def reguliers(permis, dem, min_permis: int = 3, min_annees: int = 3) -> pd.DataFrame:
    g = permis.groupby("SIREN_DEM").agg(
        nb_permis=("NUM_DAU", "nunique"),  # un permis mixte a une ligne dans chaque fichier
        nb_annees=("date_aut", lambda s: s.dt.year.nunique()),
        annees=("date_aut", lambda s: ",".join(str(y) for y in sorted(s.dt.year.dropna().astype(int).unique()))),
        logements=("NB_LGT_TOT_CREES", "sum"),
        logements_sociaux=("NB_LGT_PRET_LOC_SOCIAL", "sum"),
        exemples_permis=("NUM_DAU", lambda s: ",".join(s.drop_duplicates().head(5))),
    ).reset_index().rename(columns={"SIREN_DEM": "siren"})
    g = g[(g["nb_permis"] >= min_permis) & (g["nb_annees"] >= min_annees)]
    cols = ["siren", "denomination", "famille", "confiance", "methode", "preuve"]
    return g.merge(dem[cols], on="siren").sort_values("nb_permis", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------ pattern 2
def projets_sociaux(permis, dem) -> pd.DataFrame:
    p = permis[permis[list(FLAGS)].any(axis=1)].copy()
    p["type_residence"] = p[list(FLAGS)].apply(lambda r: ", ".join(v for k, v in FLAGS.items() if r[k]), axis=1)
    p = p.merge(dem[["siren", "famille", "confiance"]], left_on="SIREN_DEM", right_on="siren", how="left")
    p["demandeur_cible"] = p["famille"].isin(CIBLES)
    cols = ["NUM_DAU", "DATE_REELLE_AUTORISATION", "COMM", "ADR_LOCALITE_TER", "type_residence",
            "NB_LGT_TOT_CREES", "NB_LGT_PRET_LOC_SOCIAL", "ETAT_DAU", "SIREN_DEM", "DENOM_DEM", "CJ_DEM",
            "famille", "confiance", "demandeur_cible", "source"]
    return p[cols].sort_values("DATE_REELLE_AUTORISATION", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------ pattern 3
def fin_validite(date_aut: pd.Series) -> tuple[pd.Series, pd.Series]:
    cinq = (date_aut >= DECRET_DEBUT) & (date_aut <= DECRET_FIN)
    fin = date_aut + pd.DateOffset(years=3)
    fin[cinq] = date_aut[cinq] + pd.DateOffset(years=5)
    regle = pd.Series("R*424-17 : 3 ans", index=date_aut.index).where(~cinq, "décret 2025-461 : 5 ans")
    return fin, regle


def echeances(permis, dem, ref: pd.Timestamp, horizon_mois: int = 12) -> pd.DataFrame:
    cible = set(dem.loc[dem["famille"].isin(CIBLES), "siren"])
    p = permis[(permis["ETAT_DAU"] == ETAT_SANS_CHANTIER) & permis["DATE_REELLE_DOC"].isna()
               & permis["date_aut"].notna()].copy()
    # permis mixte : une ligne par fichier ; on garde la ligne « logements » (porte les indicateurs)
    p = p.sort_values("fichier").drop_duplicates("NUM_DAU", keep="first")
    p = p[p["SIREN_DEM"].isin(cible) | p[list(FLAGS)].any(axis=1)]
    p["fin_validite_theorique"], p["regle_validite"] = fin_validite(p["date_aut"])
    fin_horizon = ref + pd.DateOffset(months=horizon_mois)
    p = p[(p["fin_validite_theorique"] >= ref) & (p["fin_validite_theorique"] <= fin_horizon)]
    p["mois_restants"] = ((p["fin_validite_theorique"] - ref).dt.days / 30.44).round(1)
    p = p.merge(dem[["siren", "famille", "confiance"]], left_on="SIREN_DEM", right_on="siren", how="left")
    cols = ["NUM_DAU", "DATE_REELLE_AUTORISATION", "fin_validite_theorique", "mois_restants", "regle_validite",
            "COMM", "ADR_LOCALITE_TER", "NB_LGT_TOT_CREES", "SIREN_DEM", "DENOM_DEM", "famille", "confiance", "source"]
    return p[cols].sort_values("fin_validite_theorique").reset_index(drop=True)


# ------------------------------------------------------------------ fiches
def score_prospects(dem, reg, proj, ech) -> pd.DataFrame:
    """Une ligne par structure cible, avec ses signaux. Score simple et explicable."""
    s = dem[dem["famille"].isin(CIBLES)][["siren", "denomination", "famille", "confiance", "methode",
                                          "preuve", "nb_permis"]].copy()
    s["regulier"] = s["siren"].isin(reg["siren"])
    s["nb_projets_sociaux"] = s["siren"].map(proj.groupby("SIREN_DEM").size()).fillna(0).astype(int)
    s["nb_echeances"] = s["siren"].map(ech.groupby("SIREN_DEM").size()).fillna(0).astype(int)
    s["score"] = (2 * s["regulier"] + 2 * (s["nb_echeances"] > 0) + (s["nb_projets_sociaux"] > 0)
                  + (s["confiance"] == "sur"))
    s["nb"] = s["nb_permis"].astype(int)
    return s.sort_values(["score", "nb"], ascending=False).drop(columns="nb").reset_index(drop=True)


def fiches_markdown(top: pd.DataFrame, permis, ech, ref: pd.Timestamp, meta: dict) -> str:
    out = [
        "# Fiches prospects — structures cibles ayant déposé des permis dans les Yvelines",
        "",
        f"Généré le {ref.date()} à partir de Sitadel (millésime {meta.get('sitadel_millesime')}) et FINESS. "
        "Aucun contact n'a été pris avec ces structures. Chaque information renvoie à sa source "
        "(n° de permis Sitadel, n° FINESS, règle de classement).",
        "",
        "**Score** = 2 si dépôts réguliers (≥ 3 permis sur ≥ 3 années) + 2 si un permis arrive à échéance "
        "sans ouverture de chantier déclarée + 1 si projet de résidence sociale / personnes âgées / handicap "
        "+ 1 si famille établie de façon sûre (règle ou FINESS).",
        "",
    ]
    for n, (_, r) in enumerate(top.iterrows(), 1):
        p = (permis[permis["SIREN_DEM"] == r["siren"]].sort_values("fichier")
             .drop_duplicates("NUM_DAU").sort_values("date_aut", ascending=False))
        e = ech[ech["SIREN_DEM"] == r["siren"]]
        pourquoi = []
        if r["regulier"]:
            ans = sorted(p["date_aut"].dt.year.dropna().astype(int).unique())
            pourquoi.append(f"dépose des permis régulièrement ({len(p)} permis, années {', '.join(map(str, ans))})")
        if r["nb_projets_sociaux"]:
            pourquoi.append(f"{r['nb_projets_sociaux']} permis de résidence sociale / personnes âgées / handicap")
        if r["nb_echeances"]:
            pourquoi.append(f"{r['nb_echeances']} permis autorisé(s) sans chantier déclaré, validité théorique "
                            f"échéant le {e['fin_validite_theorique'].min().date()}")
        out += [
            f"## {n}. {r['denomination']} (SIREN {r['siren']})",
            "",
            f"- **Famille** : {r['famille']} — confiance « {r['confiance']} » (méthode : {r['methode']})",
            f"- **Preuve** : {str(r['preuve'])[:300]}",
            f"- **Score** : {r['score']} — {'; '.join(pourquoi) if pourquoi else 'famille cible, pas d’autre signal'}",
            "",
            "| Permis (Sitadel) | Autorisé le | Commune du terrain | Logements | dont sociaux | Résidence | État* |",
            "|---|---|---|---|---|---|---|",
        ]
        for _, q in p.head(8).iterrows():
            res = ", ".join(v for k, v in FLAGS.items() if q[k]) or "—"
            out.append(f"| {q['NUM_DAU']} | {q['DATE_REELLE_AUTORISATION']} | {q['ADR_LOCALITE_TER']} "
                       f"| {q['NB_LGT_TOT_CREES']} | {q['NB_LGT_PRET_LOC_SOCIAL']} | {res} | {q['ETAT_DAU']} |")
        if len(p) > 8:
            out.append(f"| … {len(p) - 8} autres permis | | | | | | |")
        out += [
            "",
            "**À vérifier avant toute démarche** : le demandeur du permis n'est pas forcément l'exploitant ; "
            "un chantier peut avoir commencé sans être déclaré (≈ 15 % des cas) ; prorogations et recours non connus.",
            "",
        ]
    out += ["---", "*État (ETAT_DAU) : sens inféré des données — 2 = aucune date de chantier, 5 = chantier ouvert, "
            "6 = achevé, 4 = probablement annulé.*", ""]
    return "\n".join(out)


# ------------------------------------------------------------------ principal
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="date de référence (défaut : date de chargement des données)")
    ap.add_argument("--horizon", type=int, default=12, help="horizon des échéances, en mois")
    ap.add_argument("--top", type=int, default=10, help="nombre de fiches")
    a = ap.parse_args()
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    ref = pd.Timestamp(a.date or meta["date_chargement"])
    permis, dem = charger()

    reg = reguliers(permis, dem)
    proj = projets_sociaux(permis, dem)
    ech = echeances(permis, dem, ref, a.horizon)
    sc = score_prospects(dem, reg, proj, ech)

    OUT.mkdir(exist_ok=True)
    reg[reg["famille"].isin(CIBLES)].to_csv(OUT / "prospects_reguliers.csv", index=False)
    proj.to_csv(OUT / "projets_sociaux.csv", index=False)
    ech.to_csv(OUT / "echeances.csv", index=False)
    (OUT / "fiches_prospects.md").write_text(fiches_markdown(sc.head(a.top), permis, ech, ref, meta), encoding="utf-8")

    print(f"Date de référence : {ref.date()}")
    print(f"\n1. Demandeurs réguliers (≥3 permis, ≥3 années) : {len(reg)}, dont structures cibles : "
          f"{reg['famille'].isin(CIBLES).sum()}")
    print(reg["famille"].fillna("(non qualifié)").value_counts().to_string())
    print(f"\n2. Permis de résidence sociale / personnes âgées / handicap : {len(proj)} "
          f"({proj['SIREN_DEM'].nunique()} demandeurs)")
    print(f"   déposés par une structure cible : {proj['demandeur_cible'].sum()} ; "
          f"par une association/fondation (toutes) : {proj['CJ_DEM'].str[:2].isin(['92', '93']).sum()}")
    print("   familles des demandeurs :")
    print(proj["famille"].fillna("(non qualifié)").value_counts().to_string())
    print(f"\n3. Permis sans chantier déclaré, validité théorique échéant d'ici {a.horizon} mois : {len(ech)}")
    print(f"\nFiches : {min(a.top, len(sc))} (sur {len(sc)} structures cibles) -> {OUT / 'fiches_prospects.md'}")


if __name__ == "__main__":
    main()
