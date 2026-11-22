"""Filtre 2 : confirmer avec FINESS (fichier officiel des établissements sanitaires et sociaux).

Si le SIREN d'un demandeur apparaît dans FINESS, on sait QUELS établissements il gère.
On lit alors la catégorie : un foyer pour adultes handicapés, c'est du médico-social ;
un centre hospitalier, c'est du sanitaire (pas notre cible) ; la santé au travail, ce n'est ni l'un ni l'autre.

Ce filtre ne MODIFIE que les demandeurs que le filtre 1 n'avait pas tranchés
(forme muette comme SAS/SARL) ou seulement à moitié (association, mutuelle : forme certaine,
activité inconnue). Il n'écrase jamais un classement sûr (commune, bailleur social...).
Pour tous les autres, il ajoute seulement l'information FINESS (colonne finess_social).

Usage :  python filter2.py   (après load_data.py et filter1.py)
Sortie : data/processed/demandeurs_f2.csv
"""
from pathlib import Path

import pandas as pd

F1 = Path("data/processed/demandeurs_f1.csv")
FINESS = Path("data/processed/finess.csv")
OUT = Path("data/processed/demandeurs_f2.csv")

MEDICO_SOCIAL = "medico_social"
SANTE = "sante"  # hôpitaux, cliniques, centres de santé : sanitaire, hors cible Buddimm

# Codes « agrégat de catégories » FINESS (colonne agreg_code), regroupés par leurs 2 premiers chiffres.
# Relevés dans le fichier FINESS de mai 2026 pour les demandeurs du 78 :
#   41 éducation spéciale (enfants handicapés)   43 adultes handicapés   44 personnes âgées
#   45 aide sociale à l'enfance                  46 adultes en difficulté, multi-clientèles, logements collectifs
SOCIAL = ("41", "43", "44", "45", "46")
#   11/12 hôpitaux, cliniques, soins   21/22 exercice libéral, centres de santé
SANITAIRE = ("11", "12", "21", "22")
# Pour une forme muette (SAS, SA...), seul un établissement hospitalier (11/12) est un indice fiable :
# un « centre de santé » (22) peut être le cabinet interne d'une grande entreprise
# (un premier essai classait Aéroports de Paris et le Crédit Lyonnais en « santé »).
HOSPITALIER = ("11", "12")
# Volontairement ignorés : 32 (commerce de biens médicaux), 34 (santé au travail, incendie),
# 61/62/63 (écoles de formation) : leur présence dans FINESS ne dit rien sur l'activité du
# demandeur. (Un premier essai avec 61-63 classait AFTRAL, école de transport, en « santé ».)

A_RAFFINER = {None, "association_fondation", "ess_autre"}


def resume_finess(finess: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par SIREN : a-t-il du social ? du sanitaire ? lesquels (avec n° FINESS) ?"""
    finess = finess.copy()
    finess["groupe"] = finess["agreg_code"].str[:2]
    rows = []
    for siren, g in finess.groupby("siren"):
        top = (
            g.groupby("categ_lib")
            .agg(n=("nofinesset", "count"), exemple=("nofinesset", "first"))
            .sort_values("n", ascending=False)
            .head(3)
        )
        rows.append(
            {
                "siren": siren,
                "finess_social": g["groupe"].isin(SOCIAL).any(),
                "finess_sanitaire": g["groupe"].isin(SANITAIRE).any(),
                "finess_hospitalier": g["groupe"].isin(HOSPITALIER).any(),
                "finess_nb_etab": len(g),
                "finess_detail": "; ".join(
                    f"{lib} x{r.n} (ex. FINESS {r.exemple})" for lib, r in top.iterrows()
                ),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    dem = pd.read_csv(F1, dtype=str)
    dem["famille"] = dem["famille"].where(dem["famille"].notna(), None)
    finess = pd.read_csv(FINESS, dtype=str)
    # on ne résume que les SIREN qui nous intéressent (47 000 SIREN en France : inutile et lent)
    res = resume_finess(finess[finess["siren"].isin(set(dem["siren"]))])
    dem = dem.merge(res, on="siren", how="left")
    for col in ("finess_social", "finess_sanitaire", "finess_hospitalier"):
        dem[col] = dem[col].fillna(False).astype(bool)

    # « résolu » = on connaît la famille ET l'activité (association : encore à préciser ; SCI : à creuser)
    attente = {"association_fondation", "societe_civile_immo"}
    avant = dem["famille"].notna() & ~dem["famille"].isin(attente)
    changes = []
    for i, r in dem.iterrows():
        forme_muette = pd.isna(r["famille"])  # pandas range le vide en NaN, pas en None
        if not (forme_muette or r["famille"] in A_RAFFINER) or pd.isna(r["finess_detail"]):
            continue
        # forme muette : l'activité vient de FINESS seul => « probable » ; association : « sûr »
        conf = "probable" if forme_muette else "sur"
        if r["finess_social"]:
            fam, regle = MEDICO_SOCIAL, "R20"
        elif r["finess_hospitalier"] if forme_muette else r["finess_sanitaire"]:
            fam, regle = SANTE, "R21"
        else:
            continue
        old = r["preuve"] if isinstance(r["preuve"], str) else ""
        dem.at[i, "famille"] = fam
        dem.at[i, "confiance"] = conf
        dem.at[i, "regle"] = regle
        dem.at[i, "preuve"] = (old + " | " if old else "") + f"FINESS: {r['finess_detail']}"
        changes.append(i)

    dem.to_csv(OUT, index=False)

    apres = dem["famille"].notna() & ~dem["famille"].isin(attente)
    print(f"Demandeurs vraiment résolus (hors SCI/SCCV) : {avant.sum()} -> {apres.sum()} / {len(dem)}")
    print(f"Modifiés par le filtre 2 : {len(changes)}")
    print("\nRésultat du filtre 2 :")
    print(dem.loc[changes].groupby(["famille", "confiance"]).size().to_string())
    print("\nNouveaux classés, à vérifier à l'œil :")
    cols = ["cj", "denomination", "famille", "confiance", "nb_permis"]
    print(dem.loc[changes, cols].sort_values(["famille", "confiance"]).to_string(index=False))
    sci = dem[(dem["famille"] == "societe_civile_immo") & dem["finess_social"]]
    print(f"\nSCI/SCCV présentes dans FINESS (social) : {len(sci)}")
    print(sci[["cj", "denomination", "finess_detail"]].head(8).to_string(index=False))
    rest = dem[dem["famille"].isna() & dem["finess_detail"].notna()]
    print(f"\nDans FINESS mais non classés ({len(rest)}) :")
    print(rest[["cj", "denomination", "finess_detail"]].head(8).to_string(index=False))


if __name__ == "__main__":
    main()
