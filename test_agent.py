"""Tests de l'agent (outils + garde-fou + boucle) SANS appeler le vrai modèle.

Lancer :  python -m pytest -q
Nécessite d'avoir lancé load_data.py, filter1.py, filter2.py (données dans data/processed/).
Seul appel réseau : une requête Sirène publique, mise en cache ensuite.
"""
import json
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from filter3 import F2, FAMILLES, FINESS, PERMIS, garde_fou, run_agent
from tools import Tools

pytestmark = pytest.mark.skipif(
    not F2.exists(), reason="lancer d'abord load_data.py, filter1.py et filter2.py"
)


@pytest.fixture(scope="module")
def ctx():
    permis = pd.read_csv(PERMIS, dtype=str)
    finess = pd.read_csv(FINESS, dtype=str)
    dem = pd.read_csv(F2, dtype=str)
    row = dem[dem["denomination"].str.contains("FONDATION MALLET", na=False)].iloc[0]
    return NS(permis=permis, finess=finess, siren=row["siren"],
              tools=Tools(permis, finess, siren_courant=row["siren"]))


# ------------------------------------------------------------------ outils
def test_get_permis(ctx):
    p = ctx.tools.call("get_permis", {"siren": ctx.siren})
    assert p["found"] and p["nb_permis"] > 0 and p["exemples_num_permis"]


def test_lookup_finess(ctx):
    fi = ctx.tools.call("lookup_finess", {"siren": ctx.siren})
    assert fi["found"] and fi["categories"] and "exemple_finess" in fi["categories"][0]


def test_sirene_liste_blanche_et_libelles(ctx):
    si = ctx.tools.call("lookup_sirene", {"siren": ctx.siren})
    assert si["found"], si
    assert si["activite_principale_libelle"], "libellé NAF officiel manquant"
    assert si["nature_juridique_libelle"], "libellé de forme juridique manquant"
    assert "dirigeants" not in json.dumps(si), "aucun dirigeant (personne physique) ne doit passer"
    autorises = {"found", "source", "commune_siege", "complements", "nom_complet", "activite_principale",
                 "nature_juridique", "etat_administratif", "date_creation", "categorie_entreprise",
                 "nombre_etablissements_ouverts", "activite_principale_libelle", "nature_juridique_libelle"}
    assert set(si) <= autorises


def test_un_outil_refuse_un_autre_siren(ctx):
    assert "erreur" in ctx.tools.call("lookup_sirene", {"siren": "000000000"})
    assert "erreur" in ctx.tools.call("get_permis", {"siren": "000000000"})


def test_mode_sans_finess_ne_fuit_pas(ctx):
    t = Tools(ctx.permis, None, siren_courant=ctx.siren)
    assert "erreur" in t.call("lookup_finess", {"siren": ctx.siren})
    comp = t.call("lookup_sirene", {"siren": ctx.siren})["complements"]
    assert "est_finess" not in comp, "fuite : est_finess de Sirène vient de FINESS"
    assert "est_finess" in ctx.tools.call("lookup_sirene", {"siren": ctx.siren})["complements"]


# ------------------------------------------------------------------ garde-fou
@pytest.fixture(scope="module")
def sorties(ctx):
    return {"context": {"siren": ctx.siren},
            "lookup_finess": ctx.tools.call("lookup_finess", {"siren": ctx.siren}),
            "lookup_sirene": ctx.tools.call("lookup_sirene", {"siren": ctx.siren})}


def _bonne(sorties):
    cat = sorties["lookup_finess"]["categories"][0]["categorie"]
    return {"famille": "medico_social", "confiance": "probable", "explication": "x",
            "preuves": [{"tool": "lookup_finess", "field": "categorie", "value": cat}]}


def test_garde_fou_accepte_une_vraie_preuve(sorties):
    assert garde_fou(_bonne(sorties), sorties)["famille"] == "medico_social"


def test_garde_fou_rejette_preuve_inventee(sorties):
    a = _bonne(sorties)
    a["preuves"] = [{"tool": "lookup_finess", "field": "categorie", "value": "Casino de Monaco"}]
    d = garde_fou(a, sorties)
    assert d["famille"] == "non_determine" and d["garde_fou"] == "aucune preuve vérifiée"


def test_garde_fou_sans_preuve(sorties):
    assert garde_fou({**_bonne(sorties), "preuves": []}, sorties)["famille"] == "non_determine"


def test_garde_fou_famille_hors_liste(sorties):
    assert garde_fou({**_bonne(sorties), "famille": "licorne"}, sorties)["famille"] == "non_determine"


def test_garde_fou_jamais_sur(sorties):
    assert garde_fou({**_bonne(sorties), "confiance": "sur"}, sorties)["confiance"] == "a_verifier"


def test_garde_fou_outil_inexistant(sorties):
    a = _bonne(sorties)
    a["preuves"][0]["tool"] = "lookup_inexistant"
    assert garde_fou(a, sorties)["famille"] == "non_determine"


# ------------------------------------------------------------------ boucle avec un faux modèle
def faux_client(scenario):
    etapes = iter(scenario)

    def create(**kw):
        tcs = [NS(id=f"c{i}", function=NS(name=n, arguments=json.dumps(a)))
               for i, (n, a) in enumerate(next(etapes))]
        msg = NS(tool_calls=tcs, model_dump=lambda exclude_none=True: {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": c.id, "type": "function",
                            "function": {"name": c.function.name, "arguments": c.function.arguments}}
                           for c in tcs]})
        return NS(choices=[NS(message=msg)], usage=NS(total_tokens=10))

    return NS(chat=NS(completions=NS(create=create)))


def test_boucle_complete(ctx, sorties):
    cat = sorties["lookup_finess"]["categories"][0]["categorie"]
    scenario = [[("lookup_finess", {"siren": ctx.siren})],
                [("classify", {"famille": "medico_social", "confiance": "probable", "explication": "ok",
                               "preuves": [{"tool": "lookup_finess", "field": "categorie", "value": cat}]})]]
    dec, appels, tok = run_agent(faux_client(scenario), "faux", ctx.tools, {"siren": ctx.siren}, True)
    assert dec["famille"] == "medico_social" and len(appels) == 1 and tok == 20


def test_boucle_agent_qui_espionne_un_autre_siren(ctx):
    scenario = [[("lookup_sirene", {"siren": "111111111"})],
                [("classify", {"famille": "bailleur_social", "confiance": "probable", "explication": "?",
                               "preuves": [{"tool": "lookup_sirene", "field": "est_ess", "value": "true"}]})]]
    dec, _, _ = run_agent(faux_client(scenario), "faux", ctx.tools, {"siren": ctx.siren}, True)
    assert dec["famille"] == "non_determine"


def test_familles_fermees():
    assert "non_determine" in FAMILLES and len(set(FAMILLES)) == len(FAMILLES)
