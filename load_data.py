"""Brique 1 : charger et préparer les données Sitadel (Yvelines) + FINESS.

Ce que fait ce script, dans l'ordre :
  1. télécharge Sitadel (fichier logements + fichier locaux) pour le département 78
  2. télécharge FINESS (établissements sanitaires et sociaux, toute la France)
  3. garde seulement les permis de construire (PC) dont le demandeur est une personne morale
  4. ajoute une colonne "source" pour que chaque ligne renvoie à sa source publique
  5. écrit des fichiers propres dans data/processed/ + un fichier meta.json (traçabilité)

Les téléchargements sont mis en cache dans data/raw/ : on ne retélécharge jamais
un fichier déjà présent (cadence de requêtes raisonnable, comme demandé par le brief).

Usage :  python load_data.py
"""
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

# ---------------------------------------------------------------- paramètres
DEPARTEMENT = "78"
MILLESIME = "2026-10"  # version mensuelle de Sitadel : à citer dans la note

DIDO = "https://data.statistiques.developpement-durable.gouv.fr/dido/api/v1/datafiles"
SITADEL_FILES = {  # identifiants des fichiers dans l'API DiDo du ministère
    "logements": "8b35affb-55fc-4c1f-915b-7750f974446a",
    "locaux": "f8f0700f-806c-40a7-83b1-f21cf507e7c4",
}
FINESS_URL = (
    "https://static.data.gouv.fr/resources/finess-extraction-du-fichier-des-etablissements/"
    "20260512-091308/etalab-cs1100502-stock-20260512-0339.csv"
)

RAW = Path("data/raw")
OUT = Path("data/processed")
PAUSE = 1.0  # secondes entre deux téléchargements
HEADERS = {"User-Agent": "etude-sitadel-78/0.1"}  # nom générique, aucune info perso

# Colonnes inutiles pour nous (25 paires de parcelles cadastrales)
CADASTRE_PREFIXES = ("SEC_CADASTRE", "NUM_CADASTRE")
DATE_COLUMNS = [
    "DATE_REELLE_AUTORISATION",
    "DATE_REELLE_DOC",
    "DATE_REELLE_DAACT",
    "DR_DEPOT",
]

# FINESS : le fichier n'a pas d'en-tête, on nomme les colonnes qui nous servent.
# (positions relevées sur le fichier de mai 2026 ; la ligne 1 est un en-tête de lot)
FINESS_COLUMNS = {
    1: "nofinesset",  # numéro FINESS de l'établissement
    2: "nofinessej",  # numéro FINESS de l'entité juridique (le gestionnaire)
    3: "rs",  # raison sociale
    13: "dep_code",
    18: "categ_code",
    19: "categ_lib",  # ex. « Foyer de Vie pour Adultes Handicapés »
    20: "agreg_code",
    21: "agreg_lib",  # regroupement plus large de catégories
    22: "siret",
    23: "ape",
}


# ---------------------------------------------------------------- téléchargement
def download(url: str, dest: Path, params: dict | None = None) -> Path:
    """Télécharge url vers dest, sauf si le fichier existe déjà (cache)."""
    if dest.exists():
        print(f"  [cache] {dest}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  [téléchargement] {dest.name} ...")
    resp = requests.get(url, params=params, headers=HEADERS, timeout=180)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"    {len(resp.content) / 1e6:.1f} Mo")
    time.sleep(PAUSE)
    return dest


# ---------------------------------------------------------------- Sitadel
def load_sitadel(kind: str) -> pd.DataFrame:
    """Charge un fichier Sitadel (logements ou locaux) pour le département choisi."""
    url = f"{DIDO}/{SITADEL_FILES[kind]}/csv"
    params = {
        "millesime": MILLESIME,
        "withColumnName": "true",
        "withColumnDescription": "false",
        "DEP_CODE": f"eq:{DEPARTEMENT}",
    }
    path = download(url, RAW / f"sitadel_{kind}_{DEPARTEMENT}_{MILLESIME}.csv", params)
    df = pd.read_csv(path, sep=";", dtype=str)

    n_total = len(df)
    df = df.drop(columns=[c for c in df.columns if c.startswith(CADASTRE_PREFIXES)])

    # on ne garde que les permis de construire dont le demandeur est une personne morale
    df = df[df["TYPE_DAU"] == "PC"]
    df = df[df["SIREN_DEM"].notna() & (df["SIREN_DEM"].str.strip() != "")]
    print(f"  {kind}: {n_total} lignes -> {len(df)} PC de personnes morales")

    for col in DATE_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in [c for c in df.columns if c.startswith("RES_") and c != "RES_PRINCIP_OU_SECOND"]:
        df[col] = df[col].map({"true": True, "false": False})
    for col in df.columns:
        if col.startswith(("NB_", "SURF_")):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["fichier"] = kind
    # traçabilité : chaque ligne renvoie à sa source publique
    df["source"] = (
        "Sitadel (SDES, DiDo) " + MILLESIME + " - fichier " + kind + " - permis " + df["NUM_DAU"]
    )
    return df.reset_index(drop=True)


# ---------------------------------------------------------------- FINESS
def load_finess() -> pd.DataFrame:
    path = download(FINESS_URL, RAW / "finess_etablissements_2026-05.csv")
    df = pd.read_csv(
        path,
        sep=";",
        header=None,
        skiprows=1,  # ligne d'en-tête de lot
        dtype=str,
        usecols=[0, *FINESS_COLUMNS.keys()],
        encoding="utf-8",
    )
    df = df[df[0] == "structureet"].drop(columns=[0])  # on ignore les autres types de lignes
    df = df.rename(columns=FINESS_COLUMNS)
    df["siren"] = df["siret"].str[:9]
    df = df[df["siren"].str.fullmatch(r"\d{9}", na=False)]
    print(f"  FINESS: {len(df)} établissements, {df['siren'].nunique()} SIREN distincts")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------- principal
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("Sitadel :")
    logements = load_sitadel("logements")
    locaux = load_sitadel("locaux")
    print("FINESS :")
    finess = load_finess()

    permis = pd.concat([logements, locaux], ignore_index=True)

    # Un même SIREN dans Sitadel ET dans FINESS : première preuve officielle
    permis["dans_finess"] = permis["SIREN_DEM"].isin(set(finess["siren"]))

    permis.to_csv(OUT / "permis_78.csv", index=False)
    finess.to_csv(OUT / "finess.csv", index=False)

    meta = {
        "date_chargement": date.today().isoformat(),
        "departement": DEPARTEMENT,
        "sitadel_millesime": MILLESIME,
        "sitadel_fichiers": SITADEL_FILES,
        "finess_url": FINESS_URL,
        "nb_permis": int(len(permis)),
        "nb_demandeurs": int(permis["SIREN_DEM"].nunique()),
        "nb_demandeurs_dans_finess": int(permis.loc[permis["dans_finess"], "SIREN_DEM"].nunique()),
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nRésumé :")
    for k, v in meta.items():
        if k.startswith("nb_"):
            print(f"  {k}: {v}")
    print(f"\nFichiers écrits dans {OUT}/")


if __name__ == "__main__":
    main()
