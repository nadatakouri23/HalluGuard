# 🗺️ PLAN DÉTAILLÉ — LLM Truth Guard (HalluGuard AI)
### Toutes les phases, étape par étape

> **Version:** 1.0  
> **Date:** April 2026  
> **Durée totale estimée:** ~11 semaines  

---

# 📌 VUE D'ENSEMBLE DES PHASES

| Phase | Nom | Durée |
|---|---|---|
| Phase 0 | Setup & Architecture | 1 semaine |
| Phase 1 | Core Engine + RWKV Integration | 3 semaines |
| Phase 2 | VSCode Extension | 2 semaines |
| Phase 3 | GitHub Action Bot | 2 semaines |
| Phase 4 | REST API + CLI Tool | 1 semaine |
| Phase 5 | Benchmarks, Docs & Launch | 2 semaines |

---

# 🟣 PHASE 0 — Setup & Architecture
**Durée:** 1 semaine  
**Objectif:** Poser des fondations solides avant d'écrire une seule ligne de code métier.

---

## Étape 0.1 — Création du dépôt GitHub

- [ ] Créer le repo `halluguard-ai` sur GitHub (public, MIT License)
- [ ] Configurer le `.gitignore` (Python, Node, VSCode, models)
- [ ] Créer la structure de dossiers :
```
halluguard-ai/
├── core/               # moteur Python
│   ├── parser/         # AST parsing
│   ├── rwkv_engine/    # intégration RWKV
│   ├── verifier/       # vérification PyPI/npm
│   ├── scorer/         # scoring hallucination
│   └── corrector/      # suggestions de correction
├── vscode-extension/   # extension VSCode (TypeScript)
├── github-action/      # GitHub Action (Node.js)
├── api/                # REST API (FastAPI)
├── cli/                # CLI tool
├── benchmarks/         # suite de tests + benchmarks
├── docs/               # documentation
└── models/             # dossier local pour les modèles RWKV
```
- [ ] Créer les fichiers de base : `README.md`, `CONTRIBUTING.md`, `LICENSE`
- [ ] Configurer GitHub Issues + Project Board (Kanban)

---

## Étape 0.2 — Choix et validation des technologies

- [ ] Valider le stack technique :
  - Backend core : **Python 3.11+**
  - AST parsing : **Tree-sitter** (Python + JS/TS grammars)
  - RWKV runtime : **rwkv-pip** ou **RWKV.cpp bindings**
  - API : **FastAPI + Uvicorn**
  - Extension VSCode : **TypeScript + VSCode Extension API**
  - GitHub Action : **Node.js 20**
  - CLI : **Click (Python)** ou **Commander.js (Node)**
- [ ] Tester l'import du modèle RWKV localement (1.5B d'abord)
- [ ] Valider l'accès aux APIs PyPI et npm en JSON

---

## Étape 0.3 — Design de l'architecture

- [ ] Dessiner le diagramme de flux complet (input → output)
- [ ] Définir les interfaces entre les modules (contrats d'API interne)
- [ ] Décider du format d'output universel :
```json
{
  "file": "example.py",
  "risk_score": 74,
  "confidence": "HIGH",
  "hallucinations": [
    {
      "line": 12,
      "type": "unknown_function",
      "token": "fetchUserData()",
      "explanation": "Function not found in known libraries",
      "suggestion": "Use requests.get() instead",
      "severity": "HIGH"
    }
  ]
}
```
- [ ] Documenter les décisions d'architecture dans `docs/architecture.md`

---

## Étape 0.4 — Environnement de développement

- [ ] Créer `pyproject.toml` avec toutes les dépendances
- [ ] Configurer `pre-commit` hooks (black, ruff, mypy)
- [ ] Configurer GitHub Actions pour CI (lint + tests automatiques)
- [ ] Créer `Makefile` avec les commandes essentielles (`make test`, `make run`, etc.)

---

# 🔵 PHASE 1 — Core Engine + RWKV Integration
**Durée:** 3 semaines  
**Objectif:** Construire le cerveau du projet — le moteur de détection fonctionnel.

---

## Semaine 1 — AST Parser + Knowledge Verifier

### Étape 1.1 — AST Parser (Python)

- [ ] Installer et configurer Tree-sitter avec la grammaire Python
- [ ] Écrire le module `core/parser/python_parser.py`
- [ ] Extraire de tout fichier Python :
  - Toutes les fonctions appelées
  - Tous les imports (`import X`, `from X import Y`)
  - Toutes les méthodes de classes
  - Toutes les dépendances externes
- [ ] Écrire les tests unitaires pour le parser
- [ ] Gérer les edge cases : decorators, async functions, nested calls

### Étape 1.2 — AST Parser (JavaScript / TypeScript)

- [ ] Installer Tree-sitter avec la grammaire JS/TS
- [ ] Écrire `core/parser/js_parser.py`
- [ ] Extraire : imports ES6, require(), appels de méthodes, fetch/axios calls
- [ ] Tester sur des snippets réels générés par Copilot/Cursor

### Étape 1.3 — Knowledge Verifier (PyPI)

- [ ] Écrire `core/verifier/pypi_verifier.py`
- [ ] Pour chaque import Python extrait :
  - Appel à `https://pypi.org/pypi/{package}/json`
  - Vérifier si le package existe
  - Vérifier si la version est valide
  - Vérifier si la fonction/méthode existe dans le package
- [ ] Implémenter un cache local (TTL 24h) pour éviter les appels redondants
- [ ] Gérer les packages standard library (ne pas checker PyPI pour `os`, `sys`, etc.)

### Étape 1.4 — Knowledge Verifier (npm)

- [ ] Écrire `core/verifier/npm_verifier.py`
- [ ] Pour chaque import JS/TS extrait :
  - Appel à `https://registry.npmjs.org/{package}`
  - Vérifier existence + version
- [ ] Implémenter le cache (même stratégie que PyPI)

---

## Semaine 2 — RWKV Integration (Le cœur différenciateur)

### Étape 1.5 — Setup RWKV Runtime

- [ ] Installer `rwkv` pip package
- [ ] Télécharger et tester le modèle **RWKV-4 1.5B** (plus léger pour dev)
- [ ] Écrire un script de test basique : chargement du modèle + inférence simple
- [ ] Documenter les requirements hardware (RAM minimum, CPU temps)
- [ ] Tester aussi avec **RWKV-4 3B** pour comparer accuracy vs latency

### Étape 1.6 — RWKV Inference Engine

- [ ] Créer `core/rwkv_engine/model_loader.py`
  - Chargement lazy du modèle (seulement quand nécessaire)
  - Gestion du chemin du modèle (configurable via env var)
  - Fallback graceful si modèle absent
- [ ] Créer `core/rwkv_engine/inference.py`
  - Fonction `score_code_snippet(code: str) -> float` : retourne un score de confiance
  - Streaming token-by-token pour les gros fichiers
  - Prompt engineering spécialisé pour la détection de hallucinations
- [ ] Créer le prompt template RWKV :
```
Analyze this code snippet for potential hallucinations.
For each function call or API usage, rate its validity (0-100).
Code:
{code}
Output JSON only.
```
- [ ] Tester la latence : mesurer le temps sur 50 / 100 / 300 lignes de code

### Étape 1.7 — Hybrid Routing (RWKV + Cloud LLM)

- [ ] Créer `core/rwkv_engine/router.py`
- [ ] Logique de routing :
  - Score RWKV < 60 → envoyer au cloud LLM pour vérification approfondie
  - Score RWKV ≥ 60 → réponse locale suffisante
  - Si pas de modèle RWKV → fallback direct au cloud
- [ ] Rendre le cloud LLM optionnel (configurable via API key)
- [ ] Logger toutes les décisions de routing pour les benchmarks

---

## Semaine 3 — Scorer + Corrector + Pipeline complet

### Étape 1.8 — Hallucination Scorer

- [ ] Créer `core/scorer/hallucination_scorer.py`
- [ ] Algorithme de scoring combiné :
  - Score AST (fonctions inconnues = points négatifs)
  - Score RWKV (confidence du modèle)
  - Score Knowledge (résultat PyPI/npm check)
  - Pondération configurable entre les 3 sources
- [ ] Output final : `HallucinationReport` dataclass avec tous les champs
- [ ] Calibrer les seuils : LOW / MEDIUM / HIGH / CRITICAL

### Étape 1.9 — Correction Engine

- [ ] Créer `core/corrector/suggestion_engine.py`
- [ ] Pour chaque hallucination détectée :
  - Si import inconnu → chercher l'alternative la plus proche (fuzzy match sur PyPI/npm)
  - Si fonction inconnue → suggérer l'équivalent dans la lib correcte
  - Si syntaxe dépréciée → proposer la syntaxe moderne
- [ ] Écrire la logique de génération d'explication humaine
- [ ] Créer un dictionnaire de patterns communs d'hallucinations

### Étape 1.10 — Pipeline end-to-end

- [ ] Créer `core/pipeline.py` — le point d'entrée principal :
```python
def analyze(code: str, language: str) -> HallucinationReport:
    tokens = parser.extract(code, language)
    knowledge = verifier.check(tokens)
    rwkv_score = rwkv_engine.score(code)
    report = scorer.compute(tokens, knowledge, rwkv_score)
    report.suggestions = corrector.suggest(report)
    return report
```
- [ ] Écrire les tests d'intégration end-to-end
- [ ] Créer une suite de benchmarks avec 50 exemples annotés manuellement

---

# 🟢 PHASE 2 — VSCode Extension
**Durée:** 2 semaines  
**Objectif:** Interface IDE en temps réel pour les développeurs.

---

## Semaine 1 — Extension de base

### Étape 2.1 — Setup du projet Extension

- [ ] Initialiser avec `yo code` (Yeoman VSCode generator)
- [ ] Configurer TypeScript strict mode
- [ ] Créer la structure :
```
vscode-extension/
├── src/
│   ├── extension.ts      # point d'entrée
│   ├── analyzer.ts       # appel au core Python
│   ├── decorations.ts    # soulignements + couleurs
│   ├── hover.ts          # tooltip au survol
│   └── quickfix.ts       # auto-fix actions
├── package.json
└── tsconfig.json
```

### Étape 2.2 — Communication Extension ↔ Core

- [ ] Créer un serveur local FastAPI léger lancé par l'extension
- [ ] Écrire `analyzer.ts` : appel HTTP à `localhost:7432/analyze`
- [ ] Gérer le lifecycle du serveur Python (start/stop avec l'extension)
- [ ] Implémenter un timeout + fallback si le serveur ne répond pas

### Étape 2.3 — Décorations et Diagnostics

- [ ] Implémenter `decorations.ts` :
  - Soulignement rouge pour hallucinations HIGH/CRITICAL
  - Soulignement orange pour MEDIUM
  - Soulignement jaune pour LOW
- [ ] Utiliser `vscode.languages.createDiagnosticCollection`
- [ ] Ajouter les diagnostics dans le panneau "Problems"

### Étape 2.4 — Hover Tooltips

- [ ] Implémenter `HoverProvider` dans `hover.ts`
- [ ] Afficher au survol :
  - Type de hallucination
  - Explication en langage naturel
  - Score de risque
  - Suggestion de correction

---

## Semaine 2 — Features avancées + publication

### Étape 2.5 — Quick Fix (Auto-correction)

- [ ] Implémenter `CodeActionProvider` dans `quickfix.ts`
- [ ] Action "Apply fix" : remplace automatiquement le code hallucine
- [ ] Action "Ignore this warning" : ajoute un commentaire `// halluguard-ignore`
- [ ] Action "Show full report" : ouvre un webview panel avec le rapport complet

### Étape 2.6 — Status Bar + Settings

- [ ] Ajouter un item dans la Status Bar : `🛡️ HalluGuard: 2 warnings`
- [ ] Créer les settings VSCode configurables :
  - `halluguard.enabled` : activer/désactiver
  - `halluguard.modelPath` : chemin vers le modèle RWKV local
  - `halluguard.sensitivity` : LOW / MEDIUM / HIGH
  - `halluguard.useCloudFallback` : activer le fallback cloud

### Étape 2.7 — Tests + Publication

- [ ] Écrire les tests avec `@vscode/test-electron`
- [ ] Tester sur Windows, macOS, Linux
- [ ] Créer l'icône, le logo, et le README pour le marketplace
- [ ] Publier sur le **VSCode Marketplace** avec `vsce publish`

---

# 🟡 PHASE 3 — GitHub Action Bot
**Durée:** 2 semaines  
**Objectif:** Validation automatique de tous les PRs contenant du code AI-généré.

---

## Semaine 1 — Action de base

### Étape 3.1 — Setup du projet GitHub Action

- [ ] Créer `github-action/action.yml` :
```yaml
name: 'HalluGuard AI'
description: 'Detect hallucinations in AI-generated code'
inputs:
  sensitivity:
    description: 'Detection sensitivity (low/medium/high)'
    default: 'medium'
  fail-on:
    description: 'Minimum score to fail PR (0-100)'
    default: '70'
  rwkv-model:
    description: 'Path to local RWKV model (optional)'
runs:
  using: 'node20'
  main: 'dist/index.js'
```
- [ ] Initialiser le projet Node.js avec `@actions/core`, `@actions/github`

### Étape 3.2 — Scan des diffs de PR

- [ ] Utiliser l'API GitHub pour récupérer les fichiers modifiés du PR
- [ ] Filtrer les fichiers : `.py`, `.js`, `.ts` uniquement
- [ ] Extraire uniquement les lignes ajoutées (lignes `+` du diff)
- [ ] Envoyer chaque fichier diff à l'API HalluGuard pour analyse

### Étape 3.3 — Commentaires automatiques sur PR

- [ ] Créer un commentaire PR structuré :
```markdown
## 🛡️ HalluGuard AI Report

| File | Risk Score | Issues Found |
|------|-----------|--------------|
| `api/users.py` | 🔴 78/100 | 2 hallucinations |
| `utils/fetch.js` | 🟡 45/100 | 1 warning |

### Detected Issues:
- **Line 23** `fetchUserDataFromAPI()` — Function not found. Use `axios.get()`
- **Line 31** `import magiclib` — Package does not exist on PyPI

❌ **Merge blocked** — Risk score exceeds threshold (70/100)
```
- [ ] Implémenter la logique block/approve du PR (`core.setFailed()`)

---

## Semaine 2 — Features avancées + publication

### Étape 3.4 — Inline Review Comments

- [ ] Utiliser l'API GitHub Reviews pour poster des commentaires sur les lignes exactes
- [ ] Chaque hallucination = un commentaire inline sur la ligne concernée
- [ ] Ajouter les suggestions de correction directement dans le commentaire GitHub

### Étape 3.5 — Configuration via fichier projet

- [ ] Supporter un fichier `.halluguard.yml` à la racine du repo :
```yaml
sensitivity: high
fail_on_score: 65
ignore_paths:
  - tests/
  - mocks/
languages:
  - python
  - typescript
rwkv_model: ./models/rwkv-3b.bin
```

### Étape 3.6 — Tests + Publication

- [ ] Écrire des tests avec `jest` pour la logique de l'action
- [ ] Tester l'action sur un vrai repo de test avec des PRs simulées
- [ ] Créer `branding` (logo, description) pour le GitHub Marketplace
- [ ] Publier sur le **GitHub Actions Marketplace**

---

# 🟠 PHASE 4 — REST API + CLI Tool
**Durée:** 1 semaine  
**Objectif:** Permettre l'intégration dans n'importe quel pipeline LLM.

---

## Étape 4.1 — REST API (FastAPI)

- [ ] Créer `api/main.py` avec FastAPI
- [ ] Endpoints :
  - `POST /analyze` — analyser un snippet de code
  - `POST /analyze/file` — analyser un fichier entier (upload)
  - `GET /health` — status de l'API + modèle RWKV chargé
  - `GET /models` — lister les modèles RWKV disponibles
- [ ] Ajouter authentification par API Key (optionnel)
- [ ] Implémenter rate limiting
- [ ] Générer le spec **OpenAPI** automatiquement
- [ ] Écrire le `Dockerfile` pour containerisation
- [ ] Créer `docker-compose.yml` pour démarrage en une commande

## Étape 4.2 — CLI Tool

- [ ] Créer `cli/halluguard.py` avec Click :
```
halluguard analyze file.py
halluguard analyze src/ --recursive
halluguard analyze file.py --format json
halluguard analyze file.py --model ./models/rwkv-3b.bin
halluguard report --last
```
- [ ] Support des formats de sortie : `text` (humain), `json`, `sarif` (pour GitHub)
- [ ] Publier sur **PyPI** (`pip install halluguard`)
- [ ] Publier sur **npm** (`npx halluguard`)

---

# 🔴 PHASE 5 — Benchmarks, Documentation & Launch
**Durée:** 2 semaines  
**Objectif:** Prouver la valeur du projet et le lancer publiquement.

---

## Semaine 1 — Benchmarks

### Étape 5.1 — Créer la suite de benchmarks

- [ ] Collecter 100 exemples de code AI-généré (Copilot, Cursor, GPT-4)
- [ ] Annoter manuellement chaque exemple : hallucination présente ou non
- [ ] Catégoriser les types : fake API, wrong import, deprecated syntax, wrong params
- [ ] Stocker dans `benchmarks/dataset/` au format JSON

### Étape 5.2 — Mesurer les performances

- [ ] Calculer sur le dataset :
  - Precision (vrais positifs / (vrais positifs + faux positifs))
  - Recall (vrais positifs / (vrais positifs + faux négatifs))
  - F1 Score
  - Latence moyenne par fichier
- [ ] Comparer les modes :
  - RWKV seul (1.5B)
  - RWKV seul (3B)
  - AST seul (sans RWKV)
  - Hybride RWKV + AST + Knowledge Check
- [ ] Produire le rapport comparatif :

| Mode | Precision | Recall | F1 | Latency |
|---|---|---|---|---|
| AST only | 65% | 70% | 67% | 12ms |
| RWKV 1.5B | 71% | 75% | 73% | 45ms |
| RWKV 3B | 78% | 82% | 80% | 95ms |
| **Full Hybrid** | **85%** | **88%** | **86%** | **110ms** |

### Étape 5.3 — Comparaison avec les alternatives

- [ ] Benchmarker vs Ruff (linter Python)
- [ ] Benchmarker vs ESLint
- [ ] Montrer ce que HalluGuard détecte que les linters ratent

---

## Semaine 2 — Documentation & Launch

### Étape 5.4 — Documentation complète

- [ ] `README.md` principal avec :
  - GIF de démo du VSCode Extension en action
  - Badge de score benchmark
  - Instructions d'installation en 3 lignes
  - Tableau de comparaison RWKV vs alternatives
- [ ] `docs/getting-started.md` — guide de démarrage 5 minutes
- [ ] `docs/architecture.md` — diagrammes détaillés
- [ ] `docs/rwkv-integration.md` — guide complet sur RWKV dans le projet
- [ ] `docs/api-reference.md` — spec OpenAPI en Markdown
- [ ] `docs/contributing.md` — guide pour les contributeurs open-source

### Étape 5.5 — Démo et contenu de lancement

- [ ] Créer une démo vidéo (screen recording 3-5 min) montrant :
  - Copilot génère du code hallucine
  - HalluGuard le détecte en temps réel dans VSCode
  - Le GitHub Action bloque le PR
  - La correction auto appliquée
- [ ] Préparer le post de lancement pour :
  - GitHub (README + Release notes)
  - Hacker News (Show HN)
  - Reddit r/MachineLearning + r/programming
  - Dev.to article technique sur RWKV pour la détection

### Étape 5.6 — Release officielle

- [ ] Créer la release `v1.0.0` sur GitHub
- [ ] Taguer tous les composants avec la version
- [ ] Activer GitHub Discussions pour la communauté
- [ ] Créer le `ROADMAP.md` listant la v2.0

---

# 📌 RÉCAPITULATIF DES MILESTONES

| Milestone | Date cible | Critère de succès |
|---|---|---|
| **M0** — Architecture validée | Fin semaine 1 | Repo créé, stack décidé, RWKV importé |
| **M1** — Core Engine fonctionnel | Fin semaine 4 | Pipeline end-to-end détecte 80%+ sur les tests |
| **M2** — VSCode Extension beta | Fin semaine 6 | Extension installable et détecte en temps réel |
| **M3** — GitHub Action publishée | Fin semaine 8 | Action disponible sur le Marketplace |
| **M4** — API + CLI disponibles | Fin semaine 9 | pip install halluguard fonctionnel |
| **M5** — Launch public | Fin semaine 11 | 500+ stars GitHub dans les 7 premiers jours |

---

# ⚠️ RISQUES ET MITIGATION

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| RWKV trop lent sur CPU | Moyen | Haut | Utiliser quantization (INT4/INT8) |
| Trop de faux positifs | Haut | Haut | Calibrage fin des seuils + whitelist standard libs |
| PyPI/npm API indisponible | Faible | Moyen | Cache local + fallback offline |
| Modèle RWKV trop lourd pour VSCode | Moyen | Haut | Serveur local séparé, pas bundlé dans l'extension |
| Concurrence (Snyk, Copilot) | Haut | Moyen | Différenciation par privacy-first + RWKV local |

---

*Document généré pour le projet HalluGuard AI — v1.0*
