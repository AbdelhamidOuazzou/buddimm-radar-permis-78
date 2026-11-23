# Qualifier les demandeurs de permis de construire des Yvelines — cas métier Sitadel

Abdelhamid Ouazzou · Stage « IA agentique et développement web » 2027 · Novembre 2026
Dépôt : https://github.com/AbdelhamidOuazzou/buddimm-radar-permis-78

## 1. L'angle choisi, et pourquoi

Pour Buddimm, un permis de construire déposé par une personne morale est un signal : la structure a un projet immobilier. Sitadel dit *qui* construit, pas *ce qu'est* le demandeur. Et la clientèle de Buddimm y est rare : sur 3 957 personnes morales qui ont déposé un permis de logements ou de locaux dans le 78 depuis 2013, 140 seulement sont des associations ou des fondations. J'ai donc cherché d'abord à **trier sans me tromper**, puis à **repérer ce qui intéresse un acteur de l'immobilier médico-social**.

J'ai construit un entonnoir où l'IA n'intervient qu'en dernier :

- **Règles sur la forme juridique** (nomenclature INSEE). Une commune est une collectivité, une SA d'HLM un bailleur social. Quand la forme ne dit rien (une SAS peut être n'importe qui), la règle s'abstient.
- **Croisement avec FINESS**, le fichier officiel des établissements sanitaires et sociaux : c'est la preuve qu'un demandeur gère un EHPAD, un foyer, un IME…
- **Un agent LLM** pour les cas restants. Il appelle trois outils (ses permis, sa fiche Sirène, FINESS), puis un garde-fou codé vérifie sa réponse : chaque preuve citée doit figurer mot pour mot dans la réponse d'un outil, sinon le demandeur reste « non déterminé ». L'agent ne peut jamais répondre « sûr ».

Ce choix réduit le coût, rend les résultats reproductibles et, surtout, permet d'expliquer chaque classement. Chaque ligne garde sa source : n° de permis Sitadel, n° FINESS, règle appliquée.

## 2. Ce que j'ai trouvé

Périmètre : 7 092 permis de construire (Sitadel, millésime d'octobre 2026) déposés par 3 957 personnes morales.

- **Les projets médico-sociaux sont surtout portés par d'autres que les associations.** 68 permis créent une résidence pour personnes âgées, handicapées ou à vocation sociale. 4 seulement sont déposés par une association ou une fondation, 29 par des bailleurs sociaux ou des structures médico-sociales, et 39 par des promoteurs ou des SCI/SCCV. Pour 14 de ces 39 permis, la fiche Sirène indique « promotion immobilière de logements » (Bouygues Immobilier, Eiffage, Linkcity, Altarea Cogedim…), et 9 autres relèvent surtout de marchands de biens ou de sociétés immobilières. Un ciblage « associations » raterait donc l'essentiel de ces projets. La vraie question commerciale devient : **qui exploitera ces résidences ?**
- **Des clients au besoin récurrent.** 39 structures cibles déposent des permis sur au moins trois années différentes : 25 bailleurs sociaux et 14 structures sociales ou médico-sociales. Parmi elles, Fondation Mallet (33 permis), Avenir APEI, Association Delos APEI 78, APAJH Yvelines, L'Arche d'Aigrefoin, la Croix-Rouge et Sauvegarde Enfance Adolescence Yvelines.
- **Des projets peut-être en difficulté.** 16 permis de structures cibles ou de résidences sociales sont autorisés sans aucune déclaration de chantier et atteignent la fin de leur validité dans les 12 mois. La règle est celle de l'art. R\*424-17 du code de l'urbanisme (3 ans), portée à 5 ans pour les permis délivrés entre le 28/05/2022 et le 28/05/2024 (décret n° 2025-461). Un projet qui ne démarre pas a peut-être besoin d'aide, mais c'est un signal à vérifier, pas une certitude.
- **10 fiches prospects sourcées** rassemblent ces signaux par structure (`results/fiches_prospects.md`).

## 3. Ce qui est établi, ce qui est fragile, ce qui manque

**Établi.** 497 demandeurs (13 %) ont une famille et une activité connues de façon traçable. Les chiffres sont reproductibles. 53 tests couvrent les règles, le garde-fou, les patterns, la cohérence des données et l'audit des décisions de l'agent. Aucune donnée de personne physique n'est collectée : les dirigeants renvoyés par Sirène sont filtrés dans le code.

**Fragile.**

- **La mesure de l'agent.** Sans FINESS, il retrouve 22 des 33 structures que FINESS confirme médico-sociales, et 7 bailleurs témoins sur 7. Ma première mesure (27/33) était fausse : un indicateur de Sirène, issu de FINESS, laissait passer la réponse. Après correction, le score est tombé à 12/33, puis remonté à 22/33 quand j'ai fourni à l'agent les libellés officiels des codes d'activité. Ce 67 % est mesuré sur les cas qui m'ont servi à corriger : il est optimiste. Il porte sur 40 cas et ne mesure pas les fausses alertes.
- **Les codes et les seuils.** Le sens des codes d'état du permis n'est pas documenté dans les sources que j'ai consultées : je l'ai déduit des données. Les seuils (3 permis, 3 années, 12 mois) sont des choix.
- **Le périmètre de la famille.** Ma famille « médico-social » englobe aussi le social (résidences sociales, protection de l'enfance).

**Manque.**

- Après les règles, 3 461 demandeurs restaient à qualifier. L'agent en a traité 106 avant que le plafond de dépense de la clé API soit atteint. Il n'a trouvé aucune nouvelle cible : il trie (67 associations hors champ, 22 promoteurs) plus qu'il ne découvre.
- On ne sait pas qui est derrière les 1 721 SCI et SCCV.
- La base ne dit ni qui exploitera le bâtiment, ni ce que contiennent les permis modificatifs. Environ 15 % des ouvertures de chantier ne sont jamais déclarées.

## 4. Ce que je ferais ensuite

1. **Trouver l'exploitant des résidences.** Croiser l'adresse du permis avec les établissements FINESS géolocalisés, et avec les autorisations délivrées après un appel à projets ARS ou département (le second sujet du test) : une association autorisée doit ensuite trouver ou construire ses locaux.
2. **Rattacher les SCCV à leur groupe**, en ne retenant que les associés et gérants personnes morales.
3. **Mesurer l'agent honnêtement** sur un échantillon neuf, étiqueté à la main, avec des cas négatifs (promoteurs, SCI), puis le passer sur tous les demandeurs non qualifiés.
4. **Valider la grille des familles** avec les équipes de Buddimm.

## 5. Brancher le résultat sur la prospection

Chaque mois, le nouveau millésime Sitadel repasserait dans l'entonnoir et produirait trois alertes :

- nouveau permis d'une structure cible ;
- résidence sociale, seniors ou handicap déposée par un promoteur (qui l'exploitera ?) ;
- permis proche de l'échéance sans chantier.

Les fiches iraient à un chargé d'affaires qui valide avant tout contact. Ses retours (bon ou mauvais signal) serviraient à ajuster les règles et à mesurer l'agent.

**Temps passé** : [à compléter] heures.
**Outils** : Python (pandas, requests, pytest). Modèle de l'agent : gpt-5.4, via le proxy compatible OpenAI d'un établissement universitaire. Assistant Claude Code pour écrire le code et rédiger une première version de cette note.
