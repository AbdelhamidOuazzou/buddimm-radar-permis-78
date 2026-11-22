"""Filtre 1 : classer les demandeurs par règles, à partir de la forme juridique.

Principe : le code CJ_DEM (catégorie juridique INSEE) ne tranche que si la forme
juridique dit VRAIMENT ce qu'est le demandeur. Une commune est une collectivité.
Mais une SAS (5710) peut être n'importe qui : le filtre ne devine pas, il laisse
passer (famille vide) et le demandeur continue vers FINESS puis vers l'agent.

Les libellés viennent de la nomenclature officielle INSEE (ref/cj_insee_2022-09.csv).

Usage :  python filter1.py
Sortie : data/processed/demandeurs_f1.csv
"""
import re
import unicodedata
from pathlib import Path

import pandas as pd

PERMIS = Path("data/processed/permis_78.csv")
CJ_REF = Path("ref/cj_insee_2022-09.csv")
OUT = Path("data/processed/demandeurs_f1.csv")

# Familles (liste fermée : l'agent ne pourra pas en inventer d'autres)
PUBLIC = "public"
MEDICO_SOCIAL = "medico_social"
BAILLEUR_SOCIAL = "bailleur_social"
ASSO_FONDATION = "association_fondation"  # forme certaine ; médico-social ? => FINESS
ESS_AUTRE = "ess_autre"
SOCIETE_CIVILE_IMMO = "societe_civile_immo"  # SCI / SCCV : coquille, à creuser
AUTRE = "autre"  # hors cible évidente (agricole, banque, copropriété...)

SUR = "sur"  # la forme juridique suffit
PROBABLE = "probable"  # indice dans le nom : à confirmer


def norm(text: str) -> str:
    """Majuscules sans accents, pour comparer des noms."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return text.upper()


# Un bailleur social peut être codé 5599, 5699, 5515... (SA, SEM) : la forme ne le dit pas,
# mais le nom parfois oui. Règle volontairement étroite : peu de faux positifs.
NOM_BAILLEUR = re.compile(
    r"HABITATIONS? (A )?LOYERS? MODERES?|\bHLM\b|\bOPH\b|OFFICE PUBLIC (DE L )?HABITAT"
    r"|ENTREPRISE SOCIALE POUR L['\s]?HABITAT"
)

# (préfixe ou code, famille, id de règle) — du plus précis au plus général
def classify(cj: str, denom: str) -> tuple[str | None, str | None, str]:
    """Retourne (famille, confiance, règle). famille=None => le filtre ne sait pas."""
    cj = "" if pd.isna(cj) else str(cj).strip()  # une valeur vide arrive en NaN (float)
    nom = "" if pd.isna(denom) else norm(denom)

    if cj == "7366":  # Établissement public local social et médico-social (ex. EHPAD public)
        return MEDICO_SOCIAL, SUR, "R01"
    if cj == "4140":  # Établissement public local industriel/commercial : OPH, mais pas que
        if NOM_BAILLEUR.search(nom) or "HABITAT" in nom or "LOGEMENT" in nom:
            return BAILLEUR_SOCIAL, PROBABLE, "R02"
        return PUBLIC, PROBABLE, "R03"
    if cj in {"5546", "5646", "5547"}:  # SA de HLM (conseil d'adm., directoire), SCOP de HLM
        return BAILLEUR_SOCIAL, SUR, "R04"
    if cj[:2] in {"71", "72", "73", "74", "41"}:  # État, collectivités, établissements publics
        return PUBLIC, SUR, "R05"
    if cj[:2] in {"92", "93"}:  # association déclarée, ARUP, fondation, congrégation
        return ASSO_FONDATION, SUR, "R06"
    if cj[:2] == "82":  # mutuelle
        return ESS_AUTRE, SUR, "R07"
    if cj in {"6540", "6541", "6542", "6543"}:  # SCI, SCCV, SC d'attribution, coop. construction
        return SOCIETE_CIVILE_IMMO, SUR, "R08"
    if cj in {"6316", "6317", "6533", "6534", "6536", "6538", "6597", "6598"}:  # agricole
        return AUTRE, SUR, "R09"
    if cj in {"6100", "6596", "5192", "9110", "9150", "2700"} or cj[:2] in {"81", "83", "84"}:
        return AUTRE, SUR, "R10"  # banques, copropriété, ASL, paroisse, sécu, CSE, ordres
    if cj[:2] == "55" or cj in {"5699", "5515", "5560", "5615"}:  # SA : forme muette sur l'activité
        if NOM_BAILLEUR.search(nom):
            return BAILLEUR_SOCIAL, PROBABLE, "R11"
    return None, None, "—"


def main() -> None:
    permis = pd.read_csv(PERMIS, dtype=str)
    labels = pd.read_csv(CJ_REF, dtype=str).set_index("code")["libelle"].str.strip()

    dem = (
        permis.groupby("SIREN_DEM")
        .agg(
            denomination=("DENOM_DEM", "first"),
            cj=("CJ_DEM", "first"),
            nb_permis=("NUM_DAU", "nunique"),  # un permis mixte a une ligne dans chaque fichier
            dans_finess=("dans_finess", "first"),
        )
        .reset_index()
        .rename(columns={"SIREN_DEM": "siren"})
    )
    dem["cj_libelle"] = dem["cj"].map(labels)

    res = [classify(cj, nom) for cj, nom in zip(dem["cj"], dem["denomination"])]
    dem["famille"] = [r[0] for r in res]
    dem["confiance"] = [r[1] for r in res]
    dem["regle"] = [r[2] for r in res]
    def preuve(cj, lib, fam, regle, nom):
        if not fam:
            return ""
        txt = f"CJ {cj} = {lib} (INSEE, nomenclature 2022-09)"
        m = NOM_BAILLEUR.search(norm(nom)) if regle in {"R02", "R11"} and isinstance(nom, str) else None
        if m:  # pour les règles par le nom, la preuve est le motif trouvé dans la dénomination
            txt += f" ; dénomination contient « {m.group(0)} »"
        return txt

    dem["preuve"] = [
        preuve(*v) for v in zip(dem["cj"], dem["cj_libelle"], dem["famille"], dem["regle"], dem["denomination"])
    ]
    dem.to_csv(OUT, index=False)

    n, p = len(dem), dem["nb_permis"].astype(int).sum()
    done = dem["famille"].notna()
    print(f"Demandeurs classés par le filtre 1 : {done.sum()} / {n} ({done.mean():.0%})")
    print(
        f"Permis couverts : {dem.loc[done, 'nb_permis'].astype(int).sum()} / {p}"
        f" ({dem.loc[done, 'nb_permis'].astype(int).sum() / p:.0%})"
    )
    print("\nPar famille et confiance :")
    print(dem[done].groupby(["famille", "confiance"]).size().to_string())
    print("\nCe que le filtre laisse passer (formes juridiques les plus fréquentes) :")
    rest = dem[~done].groupby(["cj", "cj_libelle"]).size().sort_values(ascending=False).head(8)
    print(rest.to_string())
    print("\nRègles par nom (R02, R03, R11) à vérifier à l'œil :")
    chk = dem[dem["regle"].isin(["R02", "R03", "R11"])][["regle", "cj", "denomination"]]
    print(chk.to_string(index=False))


if __name__ == "__main__":
    main()
