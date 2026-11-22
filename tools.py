"""Les 3 outils que l'agent (filtre 3) peut appeler.

Règles de conception :
- Chaque outil ne renvoie que des FAITS issus d'une source publique, avec leur source.
- Chaque outil ne répond que pour le SIREN en cours d'examen : l'agent ne peut pas aller
  fouiller d'autres entreprises (et un texte piégé dans une raison sociale n'y changera rien).
- Sirène : liste blanche de champs. Le champ « dirigeants » (personnes physiques) est renvoyé
  par l'API mais JAMAIS repris ici : le brief interdit de collecter des noms de personnes.
- Les réponses Sirène sont mises en cache (data/cache/sirene) : un SIREN n'est demandé qu'une fois.
"""
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

SIRENE_URL = "https://recherche-entreprises.api.gouv.fr/search"
HEADERS = {"User-Agent": "etude-sitadel-78/0.1"}  # nom générique, aucune info perso
CACHE_DIR = Path("data/cache/sirene")
PAUSE = 0.3  # secondes entre deux appels non mis en cache (limite de l'API : ~7 appels/s)

# Seuls ces champs de la réponse Sirène sont conservés (liste blanche).
SIRENE_CHAMPS = (
    "nom_complet",
    "activite_principale",  # code NAF (ex. 87.10A)
    "nature_juridique",
    "etat_administratif",  # A = actif, C = cessé
    "date_creation",
    "categorie_entreprise",
    "nombre_etablissements_ouverts",
)
SIRENE_COMPLEMENTS = (
    "est_ess",
    "est_association",
    "est_finess",
    "est_siae",
    "est_service_public",
    "est_organisme_formation",
)


def _charger_libelles(fichier: str) -> dict:
    p = Path("ref") / fichier
    if not p.exists():
        return {}
    d = pd.read_csv(p, dtype=str)
    return dict(zip(d["code"].str.strip(), d["libelle"].str.strip()))


# Libellés officiels de l'INSEE (nomenclatures NAF rév. 2 et catégories juridiques 2022-09) :
# sans eux, l'agent lirait « 88.99B » ou « 9220 » en s'appuyant sur sa mémoire, que rien ne vérifie.
NAF = _charger_libelles("naf_rev2_insee.csv")
CJ = _charger_libelles("cj_insee_2022-09.csv")


def _enrichir(out: dict) -> dict:
    """Ajoute les libellés officiels à une réponse Sirène (au moment de répondre, pas dans le cache)."""
    if out.get("found"):
        out = dict(out)
        out["activite_principale_libelle"] = NAF.get(str(out.get("activite_principale")))
        out["nature_juridique_libelle"] = CJ.get(str(out.get("nature_juridique")))
    return out


class Tools:
    def __init__(self, permis: pd.DataFrame, finess: pd.DataFrame | None, siren_courant: str = ""):
        self.permis = permis
        self.finess = finess  # None => outil FINESS indisponible (mode évaluation)
        self.siren_courant = siren_courant

    # ------------------------------------------------------------------ outils
    def get_permis(self, siren: str) -> dict:
        g = self.permis[self.permis["SIREN_DEM"] == siren]
        if g.empty:
            return {"found": False}
        num = lambda col: pd.to_numeric(g[col], errors="coerce").fillna(0).sum()  # noqa: E731
        flag = lambda col: int((g[col] == "True").sum())  # noqa: E731
        annees = sorted(g["DATE_REELLE_AUTORISATION"].dropna().str[:4].unique())
        return {
            "found": True,
            "nb_permis": int(len(g)),
            "nb_permis_fichier_logements": int((g["fichier"] == "logements").sum()),
            "nb_permis_fichier_locaux": int((g["fichier"] == "locaux").sum()),
            "annees_autorisation": annees,
            "communes_code_insee": sorted(g["COMM"].dropna().unique())[:5],
            "logements_crees_total": int(num("NB_LGT_TOT_CREES")),
            "logements_locatifs_sociaux_total": int(num("NB_LGT_PRET_LOC_SOCIAL")),
            "nb_permis_residence_personnes_agees": flag("RES_PERS_AGEES"),
            "nb_permis_residence_handicapes": flag("RES_HANDICAPES"),
            "nb_permis_residence_sociale": flag("RES_SOCIALE"),
            "exemples_num_permis": list(g["NUM_DAU"].head(5)),
            "source": "Sitadel (SDES, DiDo), permis du département 78",
        }

    def lookup_finess(self, siren: str) -> dict:
        if self.finess is None:
            return {"found": False, "erreur": "outil indisponible"}
        g = self.finess[self.finess["siren"] == siren]
        if g.empty:
            return {"found": False, "source": "FINESS (ministère des Solidarités et de la Santé)"}
        top = (
            g.groupby("categ_lib")
            .agg(nb=("nofinesset", "count"), exemple_finess=("nofinesset", "first"))
            .sort_values("nb", ascending=False)
            .head(5)
        )
        return {
            "found": True,
            "nb_etablissements": int(len(g)),
            "categories": [
                {"categorie": lib, "nb": int(r.nb), "exemple_finess": r.exemple_finess}
                for lib, r in top.iterrows()
            ],
            "source": "FINESS (ministère des Solidarités et de la Santé), extraction de mai 2026",
        }

    def lookup_sirene(self, siren: str) -> dict:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache = CACHE_DIR / f"{siren}.json"
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        out = {"found": False}
        try:
            for essai in range(3):
                r = requests.get(
                    SIRENE_URL, params={"q": siren, "per_page": 1}, headers=HEADERS, timeout=30
                )
                if r.status_code == 429:  # trop de requêtes : on attend
                    time.sleep(2 * (essai + 1))
                    continue
                r.raise_for_status()
                res = (r.json().get("results") or [None])[0]
                if res and res.get("siren") == siren:
                    out = {k: res.get(k) for k in SIRENE_CHAMPS}  # liste blanche
                    comp = res.get("complements") or {}
                    out["complements"] = {k: comp.get(k) for k in SIRENE_COMPLEMENTS}
                    siege = res.get("siege") or {}
                    out["commune_siege"] = siege.get("libelle_commune")
                    out["found"] = True
                    out["source"] = (
                        "Sirène (INSEE) via l'API Recherche d'entreprises (api.gouv.fr), "
                        f"consultée le {date.today().isoformat()}"
                    )
                break
        except requests.RequestException as e:
            return {"found": False, "erreur": f"{type(e).__name__}"}  # pas de mise en cache
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        time.sleep(PAUSE)
        return out

    # ------------------------------------------------------------------ appel
    def call(self, name: str, args: dict) -> dict:
        siren = str(args.get("siren", ""))
        if siren != self.siren_courant:
            return {"erreur": "SIREN non autorisé : tu ne peux interroger que le demandeur en cours."}
        fn = {
            "get_permis": self.get_permis,
            "lookup_finess": self.lookup_finess,
            "lookup_sirene": self.lookup_sirene,
        }.get(name)
        if fn is None or (name == "lookup_finess" and self.finess is None):
            return {"erreur": f"outil inconnu ou indisponible : {name}"}
        out = fn(siren)
        if name == "lookup_sirene":
            out = _enrichir(out)
        if name == "lookup_sirene" and self.finess is None and out.get("found"):
            # Mode évaluation « sans FINESS » : l'indicateur est_finess de Sirène vient de FINESS.
            # Le laisser passerait l'information par la fenêtre (fuite constatée lors d'un premier essai :
            # les 27 réussites citaient toutes est_finess). On le retire de la réponse, pas du cache.
            out = {**out, "complements": {k: v for k, v in out["complements"].items() if k != "est_finess"}}
        return out


def tool_schemas(avec_finess: bool = True) -> list[dict]:
    def schema(name: str, desc: str) -> dict:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": {"siren": {"type": "string", "description": "SIREN du demandeur"}},
                    "required": ["siren"],
                },
            },
        }

    out = [
        schema(
            "get_permis",
            "Résumé des permis de construire du demandeur dans les Yvelines : nombre, années, "
            "logements, logements sociaux, résidences pour personnes âgées / handicapées / sociales.",
        ),
        schema(
            "lookup_sirene",
            "Fiche officielle Sirène : code d'activité NAF, forme juridique, état (actif/cessé), "
            "indicateurs ESS / association / FINESS / SIAE.",
        ),
    ]
    if avec_finess:
        out.append(
            schema(
                "lookup_finess",
                "Établissements sanitaires, sociaux et médico-sociaux gérés par le demandeur "
                "(fichier officiel FINESS), avec leurs catégories et n° FINESS.",
            )
        )
    return out
