# HalluGuard AI — Rapport des corrections (B1 → B24)

> Suite de [RAPPORT_ANALYSE.md](RAPPORT_ANALYSE.md). Les 24 défauts listés ont été traités dans le code.
> Rien n'a été commité : tout est dans l'arbre de travail (les suppressions de `vscode-extension/out/` et du `.vsix` sont indexées via `git rm --cached`, les fichiers restent sur disque).
> Les chiffres « avant / après » ci-dessous sont **mesurés** : le même script (`compare.py`) a été exécuté sur l'ancien code (`git archive HEAD`) et sur le nouveau, avec un faux registre PyPI/npm identique pour les deux. Les numéros de ligne renvoient au code actuel.

## 0. Résultat global

| Indicateur | Avant | Après |
|---|---|---|
| Tests | 70 collectés, 68 verts, **2 rouges** (réseau), **50,8 s** | **242 verts**, 3 ignorés (réseau réel, voir ci-dessous), **≈ 14 s**, sans Internet |
| Tests réseau réels (`HALLUGUARD_TEST_NETWORK=1`) | — | 3/3 verts (exécutés une fois) |
| Ruff | **34 erreurs** | **0** |
| mypy (`strict`, `core cli api`) | **5 erreurs** (sur `core`) | **0** (25 fichiers) |
| Exemple du README, premier appel | 5 969 ms | 747 ms ; 19 ms avec cache disque (réseau réel, mesures à des moments différents) |
| Installation | dépendances JS/TS absentes, entry point cassé | wheel construit et inspecté : bonnes dépendances, `halluguard = cli.analyzer:main`, import et CLI OK **depuis une copie installée hors du dépôt** |
| Code Python (cœur + CLI + API, hors tests) | 1 588 l. | 3 143 l. |

**Ce qui n'a PAS pu être vérifié** (à lire avant de faire confiance au reste) :
1. **RWKV réel** : aucun modèle ni package `rwkv`/`torch` sur cette machine. Le calcul par log-probabilités est testé avec un faux modèle (distributions connues), pas avec un vrai RWKV. Les valeurs par défaut de calibration sont des **placeholders** : tant qu'aucun fichier de calibration n'existe, le signal est volontairement désactivé.
2. **pandas** : l'installation a échoué (réseau). L'exemple `df.magic_transform_v2` de `tests/fixtures/hallucinated_code.py` n'est donc **pas détecté ici** (pandas n'est pas installé, l'attribut ne peut pas être vérifié). La logique (inférence `df = pd.DataFrame()`, classe dynamique) est testée avec `collections.OrderedDict`, `threading.Thread` et `xmlrpc.client.ServerProxy`, pas avec pandas.
3. **GitHub Action sur GitHub** : compilée (`tsc`), bundle `dist/` construit, fonctions pures testées sous Node, chaîne Action → CLI Python exécutée en local. Jamais lancée sur un vrai runner ni sur une vraie PR.
4. **Extension VSCode** : compilation TypeScript OK ; non exécutée dans VSCode, et le `.vsix` n'a pas été reconstruit.
5. **CI GitHub** (`ci.yml` modifié) : jamais exécutée.
6. Les mesures sur le registre utilisent un faux registre ; les 3 tests réseau réels ne couvrent que quelques paquets.

---

## 1. Priorité 1 — fiabilité des mesures

### B1 — Erreur réseau = « package inexistant » ✅
**Fait** : `exists` est tri-état (`True` / `False` / `None`). Nouveau module `core/verifier/common.py` : `http_get_json` classe chaque réponse `found` / `missing` / `error` (l.62), 3 tentatives avec backoff sur timeout, connexion, 429, 5xx ; 404/410 = inexistant ; 401/403 = erreur sans retry. Les erreurs ne sont jamais mises en cache. `pypi_verifier.py:232` et `npm_verifier.py` renvoient `exists=None, type="unverified"`. Le scorer ne signale rien pour `None` et range le nom dans `report.unverified` + `notes`.
**Avant → après** (timeout simulé sur `import requests; import numpy`) : 2 `unknown_import` HIGH → **0 issue**, `unverified = ['requests','numpy']`, `confidence = LOW`.
**Tests** : `tests/test_verifier_reliability.py` (`TestTriState`, `TestRetry`, 9 tests).
**Limite** : si le registre est injoignable, les imports vraiment inventés ne sont pas détectés (ils sont listés comme non vérifiés). C'est le comportement voulu.

### B2 — Décalage octets/caractères ✅
**Fait** : `core/parser/_common.py` (`Source.text`, l.21) découpe `code.encode("utf-8")` avec `start_byte`/`end_byte` puis décode. Utilisé par les deux parseurs.
**Avant → après** : `# é\nfoo(1)\nbar()` → `['oo(', 'ar(']` → **`['foo', 'bar']`** (Python et JS).
**Tests** : `test_parser_regressions.py::TestUnicodeOffsets` (accent, emoji, CJK).

### B3 — `line` toujours 0 ✅
**Fait** : les parseurs renvoient, en plus des listes existantes, `import_locations`, `function_call_locations`, `method_call_locations` au format `{name, line, col}` (ligne 1-based, colonne 0-based **en caractères**, `Source.location`, l.25). Le scorer propage `line` et `column` dans chaque issue ; `column` est exposé dans le JSON et l'API.
**Avant → après** : README `[fake_library → 0, fetchUserData → 0]` → **`[2, 4]`** (lignes réelles).
**Conséquences en aval** : la GitHub Action ne commente plus toujours la ligne 1 (B11) ; l'extension VSCode place le soulignement sur la position exacte (B21).
**Choix** : j'ai gardé les listes de chaînes existantes (compatibilité des tests et des clients) et ajouté les listes de positions à côté plutôt que de remplacer les types.
**Tests** : `TestPositions`, `TestLineNumbers`.

---

## 2. Priorité 2 — faux positifs sur du vrai code

### B4 — Import ≠ distribution ✅
**Fait** : `core/verifier/import_map.py` (`IMPORT_TO_DIST`, ≈ 55 entrées : `cv2`, `yaml`, `PIL`, `sklearn`, `bs4`, `dateutil`, `dotenv`, `attr`, `jwt`…). Un import connu est accepté sans requête (`type="known_mapping"`). Les autres sont interrogés par le **nom de distribution normalisé** (PEP 503, `pypi_verifier.py:141`+). Les modules installés dans l'environnement sont aussi acceptés.
**Avant → après** (`cv2`, `yaml`, `dateutil` + `PIL`, `sklearn`, `bs4`) : 3 faux positifs → **0**.
**Tests** : `TestImportMapping`.
**Limite** : la table est statique ; un import absent de la table et de PyPI sous le même nom reste signalé.

### B5 — Imports relatifs et modules locaux ✅
**Fait** : `python_parser.py:166-` lit `module_name` / `name` par champs ; un `relative_import` ne va **pas** dans `imports` (il va dans `relative_imports` et ses noms dans `defined_names`). `core/verifier/local_modules.py` (`candidate_roots`, `is_local_module`) reconnaît `x.py` / `x/` à côté du fichier analysé (remontée jusqu'à `pyproject.toml`/`.git`) ou sous `--project-root`. Côté npm : `./`, `../`, `/`, `#interne` = local.
**Avant → après** : `from . import utils`, `from .models import User`, `from ..core import x` → 3 `unknown_import` → **0**, **aucune requête réseau**.
**Tests** : `TestLocalImports`, `TestRelativeImports`.
**Limite** : sans fichier sur disque ni `project_root`, un module local ne peut pas être reconnu.

### B7 — Analyse de portée ✅
**Fait** : les parseurs collectent `defined_names` (fonctions, classes, paramètres incluant `*args`/`**kw`, cibles d'affectation et de dépaturation, `for`, `with … as`, `except … as`, `:=`, `lambda`, imports et alias) et `aliases`. Le scorer utilise `dir(builtins)` et une liste de globals JS/Node/navigateur (`hallucination_scorer.py:70-72`). `from x import *` désactive le contrôle des fonctions.
**Avant → après** : 17 faux positifs sur 20 builtins → **0** ; `helper()`, `A()`, `OD()` (alias), `cb()` (paramètre) → **0** ; les builtins Python ne fuient plus vers JS/TS.
**Tests** : `TestFalsePositives`, `TestScope` (19 tests).
**Limite assumée** : la portée est **au niveau du fichier**, pas par fonction (un nom défini ailleurs dans le fichier est considéré connu ; léger risque de faux négatif).

---

## 3. Priorité 3 — cœur du produit

### B6 — Vérifier les méthodes contre l'API réelle ✅
**Fait** : `core/verifier/api_checker.py`. Pour chaque appel `a.b.c(...)` dont la racine est un alias de module (`import requests as r`) ou une variable `var = Classe(...)` à affectation unique, la chaîne est résolue **contre le paquet réellement installé**, dans un sous-processus `python -I` isolé avec timeout 20 s (`_CHILD_SCRIPT`, l.51). Statuts : `ok`, `missing` (HIGH), `missing_instance` (MEDIUM), `dynamic_missing`, `skip`, `unknown`. Nouveau type d'issue `unknown_attribute`, avec « Did you mean » issu des vrais noms exportés (`difflib`). Désactivable : `check_attributes=False`, `--no-attr-check`, `HALLUGUARD_ATTR_CHECK=0`.
**Avant → après** : `requests.fetch_json('u')` → `risk 0, aucune issue` → **`unknown_attribute` HIGH, risk 44, ligne 2 col 4** ; `requests.get_all` → « Did you mean 'requests.get'? » ; `op.joinn` (alias de `os.path`) → « Did you mean 'op.join'? » ; `OrderedDict().magic_op()` → MEDIUM.
**Garde-fous** : les modules locaux ne sont jamais importés ; `antigravity`, `this`, `idlelib`, `turtledemo` sont refusés ; un module qui plante donne `unknown` (pas d'erreur) ; au plus 12 modules par analyse ; les classes à `__getattr__` (`Mock`, proxys RPC…) ne sont **pas** jugées, sauf liste explicite `pandas.DataFrame` / `pandas.Series` ; un résultat de fonction (`log = logging.getLogger()`) n'est pas inféré.
**Tests** : `tests/test_api_attributes.py` (20 tests, sur la stdlib et `requests`).
**Limites** (voir aussi §0.2) : seuls les paquets **installés** sont vérifiables ; importer un paquet exécute son code de premier niveau (isolé dans un sous-processus, mais cela reste du code tiers).

---

## 4. Priorité 4 — projet installable

### B8 — Packaging, entry point, Ruff, mypy ✅
- `pyproject.toml` : ajout de `tree-sitter-javascript` et `tree-sitter-typescript` (requis par `js_parser`), suppression de `click` (jamais utilisé), extras `api`, `rwkv`, `dev` (avec `httpx`, `types-requests`), entry point **`cli.analyzer:main`** (l.46), `cli/__init__.py` créé, config pytest (marqueur `network`) et Ruff (`E,F,I,UP,B`).
- `requirements.txt` aligné (`fastapi`, `uvicorn`, `httpx` ajoutés).
- `ci.yml` : matrice Python 3.11 / 3.13, `mypy core cli api`, plus un job **`clean-install`** qui installe le paquet seul puis exécute l'import et la CLI.
- Ruff : 34 → 0 (imports triés, `zip(strict=True)`, exemples de démo exclus car ils contiennent volontairement des noms non définis). mypy strict : 5 → 0.
**Vérifié** : wheel construit localement (`pip wheel`), métadonnées lues (`Requires-Dist` complets, `console_scripts`), installé avec `--target` dans un dossier vide, puis `import core.pipeline, cli.analyzer, api.server` et `python -m cli.analyzer` exécutés **hors du dépôt**.
**Non vérifié** : l'installation propre complète depuis PyPI (réseau instable) et la CI elle-même.

---

## 5. Priorité 5 — RWKV

### B9 — Signal calibré, `None` au lieu de 50 ✅ (non validé sur un vrai modèle)
**Fait** (`core/rwkv_engine/inference.py`) : le signal n'est plus du texte généré mais la **log-vraisemblance moyenne par token** (`mean_nll`, l.106) : le code est passé token par token dans le modèle récurrent et `-log p(token suivant)` est accumulé. Déterministe (aucun échantillonnage, donc plus de `temperature`). Conversion NLL → risque `[0,100]` par une logistique dont `midpoint`/`scale` viennent d'un fichier de calibration (`HALLUGUARD_RWKV_CALIBRATION`, défaut `models/rwkv_calibration.json`). **Sans calibration, le signal est retenu (`None`)** sauf opt-in explicite `HALLUGUARD_RWKV_UNCALIBRATED=1`. Toute panne renvoie `None`. `_parse_score` (réponses textuelles de modèles distants) ne renvoie plus jamais de défaut inventé : listes JSON gérées, `None` sinon.
**Avant → après** : `"Python 3.11 is used"` → 3.11 → **None** ; `""` → 50 → **None** ; `[{"validity":0}]` → 50 → **100** (liste lue, validité inversée).
**Tests** : `tests/test_rwkv.py` (33 tests) avec un faux modèle : log-softmax, NLL plus basse pour un texte attendu, troncature, calibration, retenue sans calibration, panne → `None`.
**À faire pour que ce soit utile** : installer `rwkv`, fournir un modèle, puis **calibrer** (`midpoint`/`scale`) sur un dataset étiqueté (benchmark). Le poids 0,20 n'est pas justifié tant que l'ablation n'est pas faite.

### B10 — Routage cohérent, cloud ✅
**Fait** (`router.py`) : une seule convention (**risque**). Escalade uniquement des scores **incertains** (bande 35-65, `UNCERTAIN_BAND` l.37) ; un score décisif, haut ou bas, reste local. **Le cloud est explicitement non implémenté** (`CLOUD_IMPLEMENTED = False`, l.38) : la clé `HALLUGUARD_CLOUD_API_KEY` est ignorée avec un avertissement, `_call_cloud_llm` renvoie toujours `None`, rien n'est envoyé nulle part. `final_score` vaut `None` quand il n'y a pas de score, et le pipeline ne fabrique plus de « 0 valide ».
**Avant → après** : avec une clé définie, `route = cloud_fallback` et le risque de `fooo()` tombait de **6 à 4** (poids RWKV actif sur un faux 0) → désormais `route = heuristic_only`, risque identique avec ou sans clé (**7 / 7**).
**Tests** : `TestRouting`, `TestPipelineIntegration`.

---

## 6. Priorité 6 — intégrations

### B11 — GitHub Action ✅ (non exécutée sur GitHub)
**Fait** :
- `github-action/dist/` **construit et suivi** (`.gitignore` : exception `!github-action/dist/`), `ncc build` OK.
- L'action **installe HalluGuard elle-même** depuis son propre dépôt (`pip install <racine>`, `analyzer.ts` `installHalluGuard`) puis lance `python -m cli.analyzer --project-root <workspace>` : elle ne dépend plus d'un `cli/analyzer.py` présent dans le dépôt analysé.
- Seuil par défaut **HIGH** (`action.yml`), documenté (MEDIUM ajoute les appels non résolus, heuristiques). Nouveaux inputs `offline`, `install`, `python`.
- Commentaires **en ligne uniquement sur les lignes du diff** (`parsePatchLines`), les autres résultats regroupés dans **un** commentaire de PR ; les trouvailles sous le seuil sont seulement journalisées ; pagination des fichiers (> 100) ; `unverified` remonté en notice.
**Vérifié** : `tsc` sans erreur ; `parsePatchLines`, `extractJsonArray`, `isSeverityThresholdMet` testés sous Node ; `runAnalyzer` exécuté en local contre le CLI Python (JSON parsé correctement).
**Non vérifié** : exécution réelle sur un runner et appels à l'API GitHub.

### B12 — Performance réseau ✅
**Fait** : requêtes **parallèles** (`parallel_map`, 8 threads), **cache disque** JSON avec TTL (24 h pour « existe », 1 h pour « n'existe pas », `DiskCache` l.100, écriture atomique, jamais bloquant), **mode `--offline`** / `HALLUGUARD_OFFLINE=1` (aucune requête ; seules des listes curatées de paquets courants comptent comme preuve positive ; le reste est « non vérifié »), en-tête npm abrégé (charge utile réduite).
**Mesures** (latence simulée de 300 ms par requête, 6 imports) : **1,81 s → 0,31 s** à froid ; « deuxième processus » avec cache disque : **0,03 s, 0 requête**.
**Tests** : `TestPerformanceAndOffline`.
**Limite** : le JSON complet d'un gros projet PyPI (pandas) reste lourd (jusqu'à plusieurs secondes sur un réseau lent) car il sert aussi aux signaux de B17.

---

## 7. Modérés

### B13 — Sévérité globale et `confidence` ✅
**Fait** : `report.severity` = sévérité de la **pire issue** (`NONE` si propre) — c'est ce qu'il faut utiliser pour bloquer une CI ; `risk_level` = étiquette du score agrégé, avec `0 → NONE` (`_severity_label` l.152 ; avant, `0 → LOW` alors que la plage commençait à 1) ; `confidence` = part du fichier réellement vérifiable (HIGH si tout est vérifié, MEDIUM si ≤ 50 % non vérifiable, LOW sinon ou si rien à vérifier), et non plus une fonction du risque. Avant, `severity` était calculé puis jeté (variable morte).
**Avant → après** : `import fake_pkg_zzz` → `severity` absent → **HIGH** ; tout non vérifiable : `confidence` MEDIUM → **LOW** ; fichier sans rien à vérifier : HIGH → **LOW**.
**Tests** : `TestSeverityAndConfidence`.

### B14 — Dilution et saturation ✅
**Fait** : modèle par **points** (`POINTS`, l.55) : import inconnu 50, attribut inconnu 40 (20 si instance), fonction inconnue 12, notes LOW 8 ; score de source = `100·(1 − e^(−points/échelle))` (échelles 30 et 60). Plus de `100/N`, plus de plafond à 7 fonctions.
**Avant → après** : 1 import inventé parmi 20 : **risque 3 → 49** (il était dilué par les 19 valides) ; 7 / 8 / 14 / 28 appels inconnus : **40 / 40 / 40 / 40** (plafond) → **30 / 32 / 38 / 40** (croissant).
**Effet de bord** : un test existant (`test_custom_weights`) exigeait `risk_score == 100` pour un import inventé avec poids (1,0 / 0 / 0) ; il vérifie maintenant 81 et `severity == HIGH` (changement de comportement voulu, documenté dans le test).
**Limite** : les points et échelles sont des constantes choisies à la main, **non calibrées** (pas de dataset). Ils ne deviendront défendables qu'avec le benchmark.

### B15 — Corrector ✅
**Fait** : plus de fuzzy matching sur les fonctions (seulement des noms exacts hallucinés connus, par langage : `fetchUserData` → `requests.get(url)` en Python, `fetch(url)` en JS) ; fuzzy sur les imports avec `FUZZY_CUTOFF = 0.8` et candidats = **noms d'import** réels ; un nom n'est jamais proposé à lui-même ; `language` normalisé (`py`, `PY`, `js`…) ; `COMMON_PATTERNS` ne garde que de vraies erreurs (suppression de `sklearn`, `cv2`, `yaml`, `PIL`, `dotenv`, `node-fetch`, `axios` qui étaient valides) ; nouvelles suggestions `unknown_attribute` (issues de l'API réelle) et `import PIL` pour `import pillow`.
**Avant → après** : `object()` → `sqlalchemy.create_engine(url)` → **None** ; `slice()` → `scikit-learn` → **None** ; `numpy` → « Did you mean 'numpy' ? » → **None** ; `utils` → `beautifulsoup4` → **None** ; `language="py"` → candidats npm (`express`) → **None** (candidats Python).
**Tests** : `TestCorrector` (17 cas).
**Compatibilité** : le test existant exigeant `beautifulsoup` → `beautifulsoup4` (HIGH) est conservé tel quel.

### B16 — API ✅
**Fait** (`api/server.py`) : endpoints en `def` (exécutés dans le pool de threads, plus de boucle d'événements bloquée par réseau/sous-processus/inférence, l.108 et l.129) ; langue inconnue → **HTTP 400** avec message clair (avant : 500) ; **CORS désactivé par défaut**, origines autorisées seulement via `HALLUGUARD_CORS_ORIGINS`, `*` jamais honoré ; modèle de réponse enrichi (`column`, `risk_level`, `severity`, `unverified`, `notes`) ; requête `project_root` / `offline`.
**Tests** : `TestApi` (8 tests, `TestClient`).

### B17 — « Existe sur PyPI » ne prouve rien ✅ (partiel par nature)
**Fait** : `DIST_NAME_NOT_IMPORTABLE` : un nom de **distribution** utilisé comme import (`import pillow`, `import beautifulsoup`, `scikit_learn`, `opencv_python`…) est signalé HIGH même si PyPI l'héberge, avec la correction (`import PIL`) ; métadonnées PyPI exploitées : paquet **déprécié** (résumé « deprecated », classifier Inactive) → LOW `deprecated_package`, paquet à **une seule release de moins de 90 jours** → LOW `suspicious_package` (profil de squatting).
**Avant → après** : `import pillow; import beautifulsoup` → 0 issue → **2 `unknown_import` HIGH** avec suggestion.
**Tests** : `TestSquattingSignals`.
**Limite** : ce sont des signaux faibles ; un paquet malveillant ancien et populaire passera. Il n'existe pas de vérification complète possible par simple recherche de nom.

---

## 8. Mineurs

| Bug | Fait | Preuve |
|---|---|---|
| **B18** `async_functions` vide | détection du jeton `async` enfant de `function_definition` (`python_parser.py:251`) | avant `[]` → après `['g']` ; `TestAsync` |
| **B19** `_routing_log` sans limite | `deque(maxlen=1000)` (`router.py:51`), taille via `HALLUGUARD_ROUTING_LOG_SIZE` | avant `list` → après `deque(maxlen=1000)` ; test à `maxlen=5` |
| **B20** `/health` ne vérifie pas `rwkv` | `model_loader.package_installed()`, `is_available()` = fichier **et** package, `status()` détaillé ; `/health` expose `rwkv_model_file_found`, `rwkv_package_installed`, `rwkv_loaded` | `TestAvailability`, `test_health_details` |
| **B21** réglages VSCode ignorés | `modelPath` → variable `HALLUGUARD_RWKV_MODEL` au lancement du serveur ; `sensitivity` = sévérité minimale affichée (`applySensitivity`) ; `useCloudFallback` **supprimé** (le cloud n'existe pas) ; position exacte via `line`/`column` | `tsc` OK ; non testé dans VSCode |
| **B22** licence/README | `pyproject` → **MIT** (aligné sur `LICENSE`, README, scope) ; README réécrit d'après le comportement réel (sortie réelle, limites, RWKV, offline, intégrations) ; `docs/architecture.md` corrigé (diagramme : RWKV reçoit le code brut, pas la sortie du parseur ; vérificateur, RWKV, scorer décrits fidèlement) | — |
| **B23** hygiène | `.vsix` et `vscode-extension/out/` retirés de l'index (`git rm --cached`) ; `.gitignore` : `*.egg-info/`, `*.vsix`, `out/`, `node_modules/`, caches ; fichiers orphelins déplacés : `test_snippet.py` → `tests/fixtures/sklearn_snippet.py`, `tests/hallucinated_code.py` → `tests/fixtures/`, `demo_hallucination.py` → `examples/` (via `git mv`) | `git status` |
| **B24** built-ins Node / stdlib | liste Node complète (+ `async_hooks`, `inspector`, `diagnostics_channel`, `trace_events`) ; préfixes `node:`, `bun:`, `deno:` toujours natifs ; stdlib = interpréteur courant **∪ modules retirés** (`distutils`, `imp`, `asyncore`… : du code ancien reste valide), plus de repli mort pour Python < 3.10 | avant : `async_hooks`, `inspector`, `node:test` → requête npm ; après : `node_builtin` ; `distutils` stdlib : `False` → `True` |

---

## 9. Tests ajoutés

| Fichier | Tests | Couvre |
|---|---|---|
| `tests/conftest.py` | fixture | faux registre déterministe (plus d'Internet), caches isolés, marqueur `network` |
| `test_verifier_reliability.py` | 44 | B1, B4, B5, B12, B17, B24 |
| `test_parser_regressions.py` | 18 | B2, B3, B5, B7, B18 |
| `test_scorer_model.py` | 25 | B3, B7, B13, B14 |
| `test_api_attributes.py` | 20 | B6 |
| `test_rwkv.py` | 33 | B9, B10, B19, B20 |
| `test_server_cli.py` | 32 | B8, B15, B16, B20 |
| `test_network_live.py` | 3 (ignorés par défaut) | contrôle réel de PyPI/npm |
| tests existants | 70 (2 rouges → verts ; 1 attendu modifié, voir B14) | — |

## 10. Reste à faire / risques résiduels

1. **Benchmark** (`benchmarks/` toujours vide) : indispensable pour justifier les points/échelles du scorer (B14), les poids 0,5 / 0,3 / 0,2 et la calibration RWKV (B9). Les corrections B1-B7 étaient le préalable demandé ; le dataset étiqueté peut maintenant être construit.
2. **RWKV réel** : installer `rwkv` + un modèle, mesurer la latence (génération token par token, bien au-dessus des cibles « < 100 ms » de `docs/scope.md` pour 384 tokens sur CPU : estimation, non mesurée), puis calibrer.
3. **Vérifier avec pandas installé** que `df.magic_transform_v2` est bien détecté (MEDIUM attendu).
4. **Lancer l'Action sur une vraie PR** et **la CI GitHub** ; reconstruire le `.vsix` (`npm ci && npm run package`) et tester l'extension dans VSCode.
5. **Index git mixte** : seules les suppressions (`.vsix`, `out/`) et le déplacement de la démo sont indexés ; le reste est en modifications non indexées. Rien n'est commité.
6. `docs/scope.md` et `docs/plan_detaille.md` n'ont pas été réécrits : ils décrivent des objectifs (latence, précision, GitHub, `GET /models`…) qui ne sont pas atteints ou pas implémentés ; ils sont à relire avec le benchmark.
