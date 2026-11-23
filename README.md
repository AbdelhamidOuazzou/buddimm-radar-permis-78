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
| Code de l'urbanisme, art. R*424-17, et décret n° 2025-461 du 26 mai 2025 (Légifrance) | durée de validité d'un permis | consultés le 22/11/2026 |

Chaque ligne produite garde sa source (`source`, n° de permis, n° FINESS dans la colonne `preuve`).

## Architecture : un entonnoir à trois filtres, puis les patterns

```
Sitadel 78 (PC, personnes morales)     FINESS (toute la France)
        └──────────── load_data.py ─────────────┘
                           │  7 092 permis distincts (7 608 lignes : 516 permis mixtes sont dans
                           │  les deux fichiers), 3 957 demandeurs (SIREN distincts)
                 filter1.py │ règles sur la forme juridique (INSEE) — s'abstient si elle ne dit rien
                 filter2.py │ FINESS : le demandeur gère-t-il des établissements sociaux / médico-sociaux ?
                 filter3.py │ agent LLM + outils (permis, Sirène, FINESS) + garde-fou, sur une sélection
                           ▼
          famille · confiance (sur / probable / a_verifier) · règle · preuve · source
                           │
                patterns.py │ clients réguliers · projets sociaux « cachés » · échéances · fiches
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

## Résultats

### Qualification des 3 957 demandeurs

| Étape | Résultat |
|---|---|
| Filtre 1 (forme juridique) | 2 314 classés, **dont 1 721 SCI/SCCV seulement repérées** (on ne sait pas qui est derrière) |
| Filtre 2 (FINESS) | 124 demandeurs retrouvés dans FINESS ; **33 associations/fondations confirmées sociales ou médico-sociales** (sûr), 7 sociétés (probable), 5 cliniques (probable) |
| **Demandeurs réellement qualifiés (famille et activité connues)** | **497 sur 3 957 (13 %)** |
| Reste | 1 721 SCI/SCCV, ~1 630 sans famille, 108 associations d'activité inconnue |

### Patterns (`patterns.py`, sorties dans `results/`)

| Pattern | Résultat | Fichier |
|---|---|---|
| **Clients réguliers** (≥ 3 permis sur ≥ 3 années) | 362 demandeurs réguliers, dont **39 structures cibles** (25 bailleurs sociaux, 14 médico-sociaux) | `prospects_reguliers.csv` |
| **Projets sociaux / médico-sociaux « cachés »** : permis de résidence pour personnes âgées, handicapées ou sociale | **68 permis (55 demandeurs), dont 4 seulement déposés par une association ou fondation** ; 39 par un demandeur qui n'est pas une structure cible : 23 classés « autre » par l'agent (dont 14 en « promotion immobilière de logements » d'après Sirène : Bouygues Immobilier, Eiffage, Linkcity, Altarea Cogedim… ; les autres surtout marchands de biens ou sociétés immobilières) et 16 SCI/SCCV | `projets_sociaux.csv` |
| **Échéances** : permis autorisés, sans aucune déclaration de chantier, dont la validité théorique échoit dans les 12 mois | **16 permis** à vérifier | `echeances.csv` |
| **Fiches prospects** : les 10 structures cibles au score le plus élevé, avec leurs permis sourcés | 10 fiches | `fiches_prospects.md` |

Lecture métier : un filtre « associations seulement » raterait presque tous les projets de résidences
sociales, seniors ou handicap du département — ils sont déposés par des bailleurs, des promoteurs ou des
sociétés de projet. Le demandeur n'est pas forcément l'exploitant : ces projets sont des pistes à creuser,
pas des clients confirmés.

Règle de validité utilisée pour les échéances : art. R*424-17 (permis périmé si les travaux ne sont pas
entrepris dans les 3 ans de la notification) ; décret n° 2025-461 : 5 ans pour les permis intervenus entre le
28/05/2022 et le 28/05/2024. Approximations : date d'autorisation à la place de la notification ;
prorogations et recours ignorés ; ≈ 15 % des ouvertures de chantier ne sont jamais déclarées dans Sitadel.

### Passage de l'agent sur la sélection

Sélection de 200 demandeurs non tranchés par les règles : d'abord ceux qui ont un permis de résidence
sociale / seniors / handicap (39), puis les associations d'activité inconnue (108), puis les plus actifs.
**L'agent en a traité 106** : le plafond de dépense fixé sur la clé API utilisée a été atteint avant la fin
(`python filter3.py` reprend au demandeur suivant).

| Décision de l'agent | Nombre |
|---|---|
| association_fondation (activité non médico-sociale ou inconnue : sport, culte, enseignement…) | 67 |
| autre (essentiellement promotion immobilière, preuve : libellé NAF Sirène) | 22 |
| societe_civile_immo (SCI/SCCV, rien de plus trouvé) | 16 |
| sante | 1 |

Toutes les décisions ont au moins une preuve vérifiée ; **aucune preuve citée n'a été rejetée** par le garde-fou ;
toutes sont « probable » (103) ou « à vérifier » (3). Détail : `results/decisions_agent.csv`.

Ce que ça apprend : l'agent n'a trouvé **aucune nouvelle structure cible** parmi ces 106 demandeurs. Son
apport ici est de *trier* : il écarte les associations hors champ et confirme que les projets de résidences
« cachés » sont portés par des promoteurs — l'exploitant reste à identifier, ce que les sources utilisées ne
permettent pas.

### Évaluation de l'agent, sans l'outil FINESS

`evaluate.py`, 40 cas, vérité terrain = FINESS + forme juridique :

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

- **Établi** : les chiffres ci-dessus sont reproductibles (`load_data.py`, filtres, `patterns.py`) ;
  53 tests passent ; les décisions enregistrées de l'agent sont rejouées par un test d'audit.
- **Fragile** :
  - la vérité terrain ne couvre que des demandeurs présents dans FINESS : elle mesure le rappel, pas les fausses alertes ;
  - 40 cas seulement ; les 7 bailleurs sont faciles (le nom contient « HLM ») ;
  - le mot `medico_social` recouvre aussi du *social* (résidences sociales, protection de l'enfance) ;
  - « absent de FINESS » est un indice faible (il compte parfois comme preuve pour l'agent) ;
  - les règles par le nom (bailleurs sociaux) sont volontairement étroites et marquées « probable » ;
  - le sens des codes `ETAT_DAU` n'est pas documenté dans les sources consultées : il est **inféré des données**
    (2 = aucune date de chantier, 5 = chantier ouvert, 6 = achevé, 4 = probablement annulé) ;
  - les seuils (3 permis, 3 années, 12 mois) sont des choix, pas des normes.
- **Manque / non fait** :
  - l'agent n'a traité que **106 des 200 demandeurs sélectionnés** (budget de la clé épuisé), et aucun des
    ~3 250 autres demandeurs non tranchés : ils restent « non déterminés » ;
  - les SCCV ne sont pas rattachées à leur groupe (promoteur, bailleur) ;
  - pas de lien avec les appels à projets médico-sociaux (piste naturelle : une association autorisée après
    un appel à projets doit ensuite construire ou trouver des locaux).

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
python patterns.py                   # patterns + fiches dans results/
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
| `patterns.py` | clients réguliers, projets sociaux, échéances, fiches prospects |
| `test_filters.py`, `test_agent.py`, `test_patterns.py` | 53 tests (règles, FINESS, outils, garde-fou, patterns, cohérence des données, audit des décisions) |
| `ref/` | nomenclatures officielles INSEE |
| `results/` | évaluations et décisions de l'agent, patterns et fiches |

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
