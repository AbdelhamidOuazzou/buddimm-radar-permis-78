# Radar des demandeurs de permis de construire (Yvelines) — cas métier Buddimm, sujet Sitadel

Prototype réalisé pour le cas métier « qualification des permis de construire (Sitadel) » du stage
« IA agentique et développement web » (Buddimm). **Ce n'est pas un produit fini.**

**Question traitée** : dans les permis de construire de logements et de locaux des Yvelines (78) déposés
par des personnes morales, *qui est le demandeur* (famille), et lesquels ressemblent aux clients de
Buddimm (structures médico-sociales, ESS, bailleurs sociaux) ?

## Sources (toutes publiques et primaires)

| Source | Usage | Version |
|---|---|---|
| Sitadel, liste des autorisations d'urbanisme (SDES, API DiDo) : fichiers *logements* et *locaux* | les permis | millésime 2026-10 |
| FINESS, extraction du fichier des établissements (ministère des Solidarités et de la Santé, data.gouv.fr) | confirmer qu'un demandeur gère des établissements sociaux / médico-sociaux | mai 2026 |
| Nomenclatures INSEE : catégories juridiques (2022-09) et NAF rév. 2 | libellés officiels des codes (`ref/`) | — |
| API « Recherche d'entreprises » (Sirène, api.gouv.fr) | activité et état d'un demandeur, pour l'agent | consultée à l'exécution |

Chaque ligne produite garde sa source (`source`, n° de permis, n° FINESS dans la colonne `preuve`).

## Architecture : un entonnoir à trois filtres

```
Sitadel 78 (PC, personnes morales)     FINESS (toute la France)
        └──────────── load_data.py ─────────────┘
                           │  7 608 permis, 3 957 demandeurs (SIREN distincts)
                 filter1.py │ règles sur la forme juridique (INSEE) — s'abstient si elle ne dit rien
                 filter2.py │ FINESS : le demandeur gère-t-il des établissements sociaux / médico-sociaux ?
                 filter3.py │ agent LLM + outils (permis, Sirène, FINESS) + garde-fou, sur une sélection
                           ▼
          famille · confiance (sur / probable / a_verifier) · règle · preuve · source
```

Principe : l'IA n'intervient qu'en dernier, là où les règles ne suffisent pas. Un demandeur non classable
reste **« non déterminé »**.

**Agent** (`filter3.py`, `tools.py`) : reçoit un demandeur, appelle des outils (`get_permis`, `lookup_sirene`,
`lookup_finess`), puis décide. Le code vérifie ensuite sa réponse :
- famille dans une liste fermée ;
- chaque preuve citée doit se retrouver telle quelle dans la réponse réelle d'un outil, sinon elle est écartée ;
- sans preuve vérifiée → `non_determine` ;
- l'agent ne peut jamais répondre « sûr » (réservé aux règles et à FINESS) ;
- il ne peut interroger que le demandeur en cours ; le champ « dirigeants » de Sirène n'est jamais repris.

## Résultats mesurés

Sur les 3 957 demandeurs :

| Étape | Résultat |
|---|---|
| Filtre 1 (forme juridique) | 2 314 classés, **dont 1 721 SCI/SCCV seulement repérées** (on ne sait pas qui est derrière) |
| Filtre 2 (FINESS) | 124 demandeurs retrouvés dans FINESS ; **33 associations/fondations confirmées sociales ou médico-sociales** (sûr), 7 sociétés (probable), 5 cliniques (probable) |
| **Demandeurs réellement qualifiés (famille et activité connues)** | **497 sur 3 957 (13 %)** |
| Reste | 1 721 SCI/SCCV, ~1 630 sans famille, 108 associations d'activité inconnue |

**Évaluation de l'agent, sans l'outil FINESS** (`evaluate.py`, 40 cas, vérité terrain = FINESS + forme juridique) :

| Version | Médico-sociaux retrouvés (33) | Bailleurs témoins (7) |
|---|---|---|
| Première évaluation — **invalide** (fuite : l'indicateur `est_finess` de Sirène vient de FINESS) | 27 / 33 | 7 / 7 |
| Après correction de la fuite | 12 / 33 (36 %) | 7 / 7 |
| Après ajout des libellés officiels NAF et forme juridique dans l'outil Sirène | **22 / 33 (67 %)** | 7 / 7 |

Les trois jeux de résultats sont conservés dans `results/`. Le passage de 36 % à 67 % a été mesuré **sur les
mêmes 33 cas** qui avaient servi à repérer la faiblesse : ce chiffre est optimiste et n'a pas été confirmé sur
un échantillon neuf. L'agent se trompe surtout vers la prudence (« association », « santé »), pas vers
des familles absurdes.

## Ce qui est établi, fragile, ou manque

- **Établi** : les chiffres ci-dessus sont reproductibles (`load_data.py` puis filtres) ; 42 tests passent ;
  les décisions enregistrées de l'agent sont rejouées par un test d'audit.
- **Fragile** :
  - la vérité terrain ne couvre que des demandeurs présents dans FINESS : elle mesure le rappel, pas les fausses alertes ;
  - 40 cas seulement ; les 7 bailleurs sont faciles (le nom contient « HLM ») ;
  - le mot `medico_social` recouvre aussi du *social* (résidences sociales, protection de l'enfance) ;
  - « absent de FINESS » est un indice faible (il compte parfois comme preuve pour l'agent) ;
  - les règles par le nom (bailleurs sociaux) sont volontairement étroites et marquées « probable ».
- **Manque / non fait** :
  - l'agent n'a été lancé que sur 4 + 40 + 40 demandeurs (essais et évaluation), **pas sur la sélection de 200** prévue ;
  - les **patterns** (clients réguliers, projets médico-sociaux « cachés » derrière une société, signal de
    timing) ont été explorés à la main (nombre de demandeurs réguliers, 68 permis de résidences sociales,
    seniors ou handicap dont presque aucun n'est déposé par une association) mais **ne sont pas encore codés** ;
  - pas de fiches de prospects ;
  - la durée de validité d'un permis (pour le signal « autorisé depuis longtemps sans ouverture de chantier »)
    n'a pas été vérifiée sur Légifrance ; ce signal est de toute façon fragile (≈ 15 % des ouvertures de
    chantier ne sont jamais déclarées).

Limites de la base Sitadel prises en compte : dénomination diffusée seulement pour les personnes morales
retrouvées dans Sirène ; ouvertures et achèvements de chantier parfois non déclarés ; une ligne par permis
(dernier état), pas d'historique des modificatifs ; le demandeur du permis n'est pas forcément l'exploitant.

## Installer et lancer

```bash
pip install -r requirements.txt
python load_data.py      # télécharge ~50 Mo (Sitadel 78 + FINESS), mis en cache dans data/raw/
python filter1.py
python filter2.py
cp .env.example .env     # puis renseigner OPENAI_API_KEY (jamais commitée)
python filter3.py --dry-run          # voir qui serait envoyé à l'agent
python filter3.py --max 20           # lancer l'agent (reprend là où il s'est arrêté)
python evaluate.py                   # évaluer l'agent sans FINESS
python -m pytest -q                  # tests
```

L'agent utilise une API compatible OpenAI (`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`).

## Contenu

| Fichier | Rôle |
|---|---|
| `load_data.py` | téléchargement (avec cache), filtrage PC / personnes morales, traçabilité |
| `filter1.py` | règles sur la forme juridique |
| `filter2.py` | croisement FINESS |
| `filter3.py`, `tools.py` | agent, outils, garde-fou |
| `evaluate.py` | évaluation sans FINESS |
| `test_filters.py`, `test_agent.py` | 42 tests (règles, FINESS, outils, garde-fou, cohérence des données, audit des décisions) |
| `ref/` | nomenclatures officielles INSEE |
| `results/` | résultats des évaluations |

## Données personnelles et cadence

Seules des personnes morales sont traitées. Aucun nom de personne physique n'est collecté : les dirigeants
renvoyés par l'API Sirène sont écartés par une liste blanche dans le code, et un test le vérifie. Les appels
aux API sont mis en cache (une requête par SIREN) avec une pause entre deux appels. Aucune prise de contact
avec les demandeurs.

## Outils et temps passé

- Assistant de code : **Claude (Claude Code)** pour la conception et l'écriture du code, revue par l'auteur.
- Modèle de l'agent : `azure_ai/gpt-5.4`, via le proxy compatible OpenAI d'un établissement universitaire.
- Python, pandas, requests, openai, pytest.
- Temps passé : *à compléter par l'auteur (heures réelles).*
