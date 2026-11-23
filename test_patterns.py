"""Tests des patterns (données synthétiques) + contrôles sur les sorties réelles.

Lancer :  python -m pytest -q
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from patterns import appliquer_agent, echeances, fin_validite, projets_sociaux, reguliers, score_prospects

REF = pd.Timestamp("2026-11-22")


def _permis(rows):
    cols = ["NUM_DAU", "SIREN_DEM", "fichier", "DATE_REELLE_AUTORISATION", "DATE_REELLE_DOC", "ETAT_DAU",
            "RES_PERS_AGEES", "RES_HANDICAPES", "RES_SOCIALE", "NB_LGT_TOT_CREES", "NB_LGT_PRET_LOC_SOCIAL"]
    p = pd.DataFrame(rows, columns=cols)
    for c in ("COMM", "ADR_LOCALITE_TER", "DENOM_DEM", "CJ_DEM", "source"):
        p[c] = "x"
    p["date_aut"] = pd.to_datetime(p["DATE_REELLE_AUTORISATION"])
    return p


def _dem(rows):
    d = pd.DataFrame(rows, columns=["siren", "denomination", "famille", "confiance", "nb_permis"])
    d["methode"], d["preuve"] = "R04", "p"
    return d


# ------------------------------------------------------------------ règle de validité
@pytest.mark.parametrize(
    "aut, attendu, regle",
    [
        ("2022-05-27", "2025-05-27", "3 ans"),  # veille de la fenêtre du décret
        ("2022-05-28", "2027-05-28", "5 ans"),  # premier jour de la fenêtre
        ("2024-05-28", "2029-05-28", "5 ans"),  # dernier jour
        ("2024-05-29", "2027-05-29", "3 ans"),  # lendemain
        ("2025-01-10", "2028-01-10", "3 ans"),
    ],
)
def test_fin_validite_bornes_du_decret(aut, attendu, regle):
    fin, r = fin_validite(pd.Series([pd.Timestamp(aut)]))
    assert fin.iloc[0] == pd.Timestamp(attendu)
    assert regle in r.iloc[0]


# ------------------------------------------------------------------ échéances
def test_echeances_filtres():
    p = _permis([
        ("A", "111111111", "logements", "2024-09-01", None, "2", False, False, False, 10, 10),  # échéance 2027-09 : oui
        ("B", "111111111", "logements", "2024-09-01", None, "4", False, False, False, 10, 10),  # annulé (4) : non
        ("C", "111111111", "logements", "2024-09-01", "2025-01-01", "5", False, False, False, 1, 1),  # commencé : non
        ("D", "111111111", "logements", "2019-01-01", None, "2", False, False, False, 1, 1),  # déjà périmé : non
        ("E", "222222222", "logements", "2024-10-01", None, "2", False, False, False, 1, 1),  # pas cible : non
        ("F", "222222222", "logements", "2024-10-01", None, "2", True, False, False, 50, 0),  # résidence seniors : oui
        ("G", "111111111", "logements", "2023-01-01", None, "2", False, False, False, 1, 1),  # 5 ans -> 2028 : non
        ("A", "111111111", "locaux", "2024-09-01", None, "2", False, False, False, 0, 0),  # doublon mixte de A
    ])
    d = _dem([("111111111", "BAILLEUR", "bailleur_social", "sur", 4), ("222222222", "SAS", None, None, 2)])
    e = echeances(p, d, REF, 12)
    assert sorted(e["NUM_DAU"]) == ["A", "F"], e["NUM_DAU"].tolist()


# ------------------------------------------------------------------ réguliers
def test_reguliers_seuils_et_permis_mixtes():
    rows = [(f"P{i}", "111111111", "logements", f"{2015 + i}-01-01", None, "6", False, False, False, 1, 0)
            for i in range(3)]
    rows.append(("P0", "111111111", "locaux", "2015-01-01", None, "6", False, False, False, 0, 0))  # mixte
    rows += [("Q1", "222222222", "logements", "2020-01-01", None, "6", False, False, False, 1, 0),
             ("Q2", "222222222", "logements", "2020-06-01", None, "6", False, False, False, 1, 0),
             ("Q3", "222222222", "logements", "2021-01-01", None, "6", False, False, False, 1, 0)]  # 2 années
    d = _dem([("111111111", "A", "medico_social", "sur", 3), ("222222222", "B", "medico_social", "sur", 3)])
    r = reguliers(_permis(rows), d)
    assert r["siren"].tolist() == ["111111111"]
    assert r["nb_permis"].iloc[0] == 3, "le permis mixte ne doit compter qu'une fois"


# ------------------------------------------------------------------ projets sociaux
def test_projets_sociaux_quel_que_soit_le_demandeur():
    p = _permis([
        ("A", "111111111", "logements", "2024-01-01", None, "2", True, False, False, 80, 0),
        ("B", "222222222", "logements", "2024-01-01", None, "2", False, True, True, 20, 20),
        ("C", "222222222", "logements", "2024-01-01", None, "2", False, False, False, 5, 0),
    ])
    d = _dem([("111111111", "PROMOTEUR", "autre", "probable", 1), ("222222222", "ASSO", "medico_social", "sur", 2)])
    pr = projets_sociaux(p, d).set_index("NUM_DAU")
    assert set(pr.index) == {"A", "B"}
    assert not pr.loc["A", "demandeur_cible"] and pr.loc["B", "demandeur_cible"]
    assert pr.loc["B", "type_residence"] == "handicap, sociale"


# ------------------------------------------------------------------ score
def test_score_explicable():
    d = _dem([("1", "A", "medico_social", "sur", 5), ("2", "B", "bailleur_social", "probable", 1),
              ("3", "C", "autre", "sur", 9)])
    reg = pd.DataFrame({"siren": ["1"]})
    proj = pd.DataFrame({"SIREN_DEM": ["2"]})
    ech = pd.DataFrame({"SIREN_DEM": ["1"]})
    s = score_prospects(d, reg, proj, ech).set_index("siren")
    assert "3" not in s.index, "une famille non cible n'a pas de fiche"
    assert s.loc["1", "score"] == 2 + 2 + 0 + 1 and s.loc["2", "score"] == 1


# ------------------------------------------------------------------ décisions de l'agent
def test_appliquer_agent_ne_remplace_que_les_cas_non_tranches(tmp_path):
    d = _dem([("111111111", "SAS", None, None, 1), ("222222222", "COMMUNE", "public", "sur", 1),
              ("333333333", "ASSO", "association_fondation", "sur", 1)])
    f = tmp_path / "agent_results.jsonl"
    lignes = [
        {"siren": s, "modele": "m", "decision": {"famille": fam, "confiance": "probable",
                                                 "preuves_verifiees": [{"tool": "t", "field": "f", "value": "v"}]}}
        for s, fam in [("111111111", "autre"), ("222222222", "medico_social"), ("333333333", "non_determine")]
    ]
    f.write_text("\n".join(json.dumps(x) for x in lignes), encoding="utf-8")
    r = appliquer_agent(d, f).set_index("siren")
    assert r.loc["111111111", "famille"] == "autre" and r.loc["111111111", "methode"] == "agent"
    assert r.loc["222222222", "famille"] == "public", "un classement sûr n'est jamais écrasé par l'agent"
    assert r.loc["333333333", "famille"] == "association_fondation", "non_determine ne remplace rien"


# ------------------------------------------------------------------ sorties réelles
RES = Path("results")


@pytest.mark.skipif(not ((RES / "echeances.csv").exists() and Path("data/processed/permis_78.csv").exists()),
                    reason="lancer load_data.py, les filtres puis patterns.py")
def test_sorties_reelles_tracables():
    permis = pd.read_csv("data/processed/permis_78.csv", dtype=str)
    connus = set(permis["NUM_DAU"])
    for f in ("echeances.csv", "projets_sociaux.csv"):
        df = pd.read_csv(RES / f, dtype=str)
        assert set(df["NUM_DAU"]) <= connus, f"{f} : permis inconnu"
        assert df["NUM_DAU"].is_unique, f"{f} : permis en double"
        assert df["source"].notna().all()
    e = pd.read_csv(RES / "echeances.csv", dtype=str)
    assert (pd.to_datetime(e["fin_validite_theorique"]) >= pd.Timestamp("2026-11-22")).all()
    fiches = (RES / "fiches_prospects.md").read_text(encoding="utf-8")
    assert "dirigeant" not in fiches.lower()
