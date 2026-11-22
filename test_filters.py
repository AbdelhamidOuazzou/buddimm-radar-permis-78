"""Tests des filtres 1 et 2 (règles + FINESS), et contrôles de cohérence des données produites.

Lancer :  python -m pytest -q
Les tests unitaires tournent sans données ; les contrôles de cohérence demandent
d'avoir lancé load_data.py, filter1.py et filter2.py.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from filter1 import classify
from filter2 import resume_finess

DATA = Path("data/processed")
avec_donnees = pytest.mark.skipif(
    not (DATA / "demandeurs_f2.csv").exists(), reason="lancer d'abord load_data.py, filter1.py, filter2.py"
)


# ================================================================== filtre 1 : règles
@pytest.mark.parametrize(
    "cj, nom, famille, confiance",
    [
        ("7210", "COMMUNE DE TRAPPES", "public", "sur"),
        ("7220", "DEPARTEMENT DES YVELINES", "public", "sur"),
        ("7366", "EHPAD RICHARD", "medico_social", "sur"),
        ("5546", "VILOGIA SOCIETE ANONYME D'HLM", "bailleur_social", "sur"),
        ("9220", "FREHA", "association_fondation", "sur"),
        ("9300", "FONDATION MALLET", "association_fondation", "sur"),
        ("6541", "SCI ABLIS MOULINS BREAU", "societe_civile_immo", "sur"),
        ("6540", "KERBOAS MURZEAU - KM", "societe_civile_immo", "sur"),
        ("6598", "EARL FERME DE L'HIRONDELLE", "autre", "sur"),
        # règles par le nom : jamais « sur »
        ("4140", "OPH DE VERSAILLES", "bailleur_social", "probable"),
        ("4140", "OFFICE DE TOURISME COMMUNAUTAIRE RAMBOUILLET", "public", "probable"),
        ("5599", "ENTREPRISE SOCIALE POUR L'HABITAT DOMNIS", "bailleur_social", "probable"),
        ("5699", "EFIDIS SA HABITATION LOYER MODERE", "bailleur_social", "probable"),
        ("5699", "CDC HABITAT SOCIAL SOCIETE ANONYME D'HABITATIONS A LOYER MODERE", "bailleur_social", "probable"),
    ],
)
def test_filtre1_cas_connus(cj, nom, famille, confiance):
    fam, conf, regle = classify(cj, nom)
    assert (fam, conf) == (famille, confiance)
    assert regle != "—"


@pytest.mark.parametrize(
    "cj, nom",
    [
        ("5710", "SAS 52 RUE PIERRE TROUVE"),  # SAS : la forme ne dit rien
        ("5599", "BOUYGUES IMMOBILIER"),  # même code qu'un bailleur : ne doit PAS être classé bailleur
        ("5710", "HLM FANTAISISTE SAS"),  # la règle par le nom ne s'applique qu'aux formes SA
        ("5499", "MVD INVESTISSEMENT"),
        ("6599", "ARC PROMOTION ILE DE FRANCE"),
    ],
)
def test_filtre1_s_abstient_quand_la_forme_ne_dit_rien(cj, nom):
    assert classify(cj, nom)[0] is None


def test_filtre1_valeurs_vides_ne_plantent_pas():
    assert classify(float("nan"), float("nan"))[0] is None
    assert classify(None, None)[0] is None


# ================================================================== filtre 2 : FINESS
def _finess(rows):
    return pd.DataFrame(rows, columns=["siren", "agreg_code", "categ_lib", "nofinesset"])


def test_resume_finess_social_sanitaire_hospitalier():
    f = _finess([
        ("111111111", "4401", "EHPAD", "780000001"),  # social
        ("222222222", "2202", "Centre de santé", "780000002"),  # sanitaire, pas hospitalier
        ("333333333", "1107", "SSR privé", "780000003"),  # hospitalier
        ("444444444", "6101", "École sanitaire", "780000004"),  # formation : ne compte pas
        ("555555555", "3409", "Santé au travail", "780000005"),  # idem
    ])
    r = resume_finess(f).set_index("siren")
    assert r.loc["111111111", "finess_social"] and not r.loc["111111111", "finess_sanitaire"]
    assert r.loc["222222222", "finess_sanitaire"] and not r.loc["222222222", "finess_hospitalier"]
    assert r.loc["333333333", "finess_hospitalier"]
    assert not r.loc["444444444", ["finess_social", "finess_sanitaire", "finess_hospitalier"]].any()
    assert not r.loc["555555555", ["finess_social", "finess_sanitaire", "finess_hospitalier"]].any()
    assert "780000001" in r.loc["111111111", "finess_detail"], "le n° FINESS doit figurer dans la preuve"


# ================================================================== cohérence des données produites
@pytest.fixture(scope="module")
def d():
    permis = pd.read_csv(DATA / "permis_78.csv", dtype=str)
    f2 = pd.read_csv(DATA / "demandeurs_f2.csv", dtype=str)
    return permis, f2


@avec_donnees
def test_permis_sont_dans_le_perimetre(d):
    permis, _ = d
    assert (permis["TYPE_DAU"] == "PC").all()
    assert (permis["DEP_CODE"] == "78").all()
    assert permis["SIREN_DEM"].notna().all() and (permis["SIREN_DEM"].str.len() == 9).all()
    assert permis["source"].notna().all(), "chaque ligne doit renvoyer à sa source"
    assert permis["NUM_DAU"].is_unique or permis.duplicated(["NUM_DAU", "fichier"]).sum() == 0


@avec_donnees
def test_meta_correspond_aux_donnees(d):
    permis, _ = d
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    assert meta["nb_permis"] == len(permis)
    assert meta["nb_demandeurs"] == permis["SIREN_DEM"].nunique()
    assert meta["sitadel_millesime"] and meta["date_chargement"]


@avec_donnees
def test_aucune_donnee_de_personne_physique(d):
    permis, f2 = d
    for df in (permis, f2):
        assert not [c for c in df.columns if any(m in c.lower() for m in ("dirig", "prenom", "nom_pers"))]
    for f in DATA.glob("agent_results*.jsonl"):
        assert "dirigeants" not in f.read_text(encoding="utf-8"), f"dirigeants dans {f.name}"


@avec_donnees
def test_demandeurs_coherents(d):
    permis, f2 = d
    assert f2["siren"].is_unique
    assert set(f2["siren"]) == set(permis["SIREN_DEM"])
    assert f2["nb_permis"].astype(int).sum() == len(permis)
    ok = {"public", "medico_social", "bailleur_social", "association_fondation", "ess_autre",
          "societe_civile_immo", "autre", "sante"}
    assert set(f2["famille"].dropna()) <= ok
    classes = f2[f2["famille"].notna()]
    assert set(classes["confiance"]) <= {"sur", "probable"}
    assert (classes["preuve"].fillna("") != "").all(), "toute classification doit avoir une preuve"
    # les règles fondées sur le nom ne sont JAMAIS « sûres »
    par_nom = f2[f2["regle"].isin(["R02", "R03", "R11"])]
    assert (par_nom["confiance"] == "probable").all()
    # une preuve FINESS cite un n° FINESS
    finess = f2[f2["regle"].isin(["R20", "R21"])]
    assert finess["preuve"].str.contains("FINESS").all()


@avec_donnees
def test_filtre2_ne_touche_pas_aux_classements_surs(d):
    """Les familles déjà certaines par la forme juridique (commune, bailleur HLM...) ne bougent pas."""
    _, f2 = d
    for cj in ("7210", "7220", "5546", "5646"):
        sous = f2[f2["cj"] == cj]
        assert sous["famille"].isin(["public", "bailleur_social"]).all()


# ================================================================== audit des décisions de l'agent
def _lignes(nom):
    p = DATA / nom
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l] if p.exists() else []


def test_audit_decisions_agent_rejouees():
    """On rejoue le garde-fou sur toutes les décisions enregistrées : aucune preuve ne doit être fausse."""
    from filter3 import FAMILLES, preuve_verifiee

    lignes = [r for f in DATA.glob("agent_results*.jsonl") if "FUITE" not in f.name for r in _lignes(f.name)]
    if not lignes:
        pytest.skip("aucune décision d'agent enregistrée")
    for r in lignes:
        dec = r["decision"]
        assert dec["famille"] in FAMILLES
        assert dec["confiance"] != "sur"
        sorties = {a["outil"]: a["sortie"] for a in r["appels"]}
        if dec["famille"] != "non_determine":
            assert dec["preuves_verifiees"], f"{r['denomination']} : décision sans preuve"
        for p in dec["preuves_verifiees"]:
            if p["tool"] != "context":  # le contexte initial n'est pas enregistré dans les traces
                assert preuve_verifiee(p, sorties), f"{r['denomination']} : preuve introuvable {p}"


def test_audit_evaluation_sans_fuite():
    """Le fichier d'évaluation « sans FINESS » ne doit contenir ni l'outil FINESS ni le drapeau est_finess."""
    lignes = _lignes("agent_results_eval.jsonl")
    if not lignes:
        pytest.skip("évaluation non lancée")
    for r in lignes:
        assert r["sans_finess"] is True
        assert all(a["outil"] != "lookup_finess" for a in r["appels"])
        for a in r["appels"]:
            if a["outil"] == "lookup_sirene" and a["sortie"].get("found"):
                assert "est_finess" not in a["sortie"]["complements"], r["denomination"]
