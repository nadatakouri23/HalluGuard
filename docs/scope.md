# 📋 SCOPE — LLM Truth Guard (HalluGuard AI)

> **Version:** 1.0  
> **Date:** April 2026  
> **Status:** Pre-Development  

---

## 1. 🎯 Project Objective

Build an open-source AI reliability layer that detects, explains, and corrects hallucinations in AI-generated code — powered at its core by a **locally-running RWKV model** for fast, private, on-device inference.

---

## 2. 🔭 In Scope

### 2.1 Core Engine
- AST-based code parser (Python + JavaScript/TypeScript)
- Hallucination detection pipeline
- RWKV-powered local inference engine (1.5B / 3B model)
- External knowledge verification (PyPI, npm, GitHub)
- Hallucination Risk Scoring system (0–100)
- Correction suggestion engine

### 2.2 Product Components
| Component | Description |
|---|---|
| VSCode Extension | Real-time inline hallucination warnings + one-click fix |
| GitHub Action Bot | PR-level scanning, merge blocking, automated comments |
| REST API | Headless mode for integration into any LLM pipeline |
| CLI Tool | Local terminal-based scanning for CI/CD pipelines |

### 2.3 RWKV Integration
- Local model loading and inference (RWKV.cpp or rwkv-pip)
- Token-level confidence scoring
- Streaming validation for real-time IDE feedback
- Hybrid routing: RWKV pre-screen → optional cloud LLM deep check

### 2.4 Developer Experience
- Full documentation (README, API docs, contribution guide)
- Demo video and benchmark report
- Open-source repository on GitHub (MIT License)

---

## 3. 🚫 Out of Scope (v1.0)

- Browser-based IDE integration (planned v2.0)
- JetBrains plugin (planned v2.0)
- Team-level analytics dashboard (planned v2.0)
- Support for languages beyond Python / JS / TS (v1.0 limited)
- Auto PR fixing agent (planned v2.0)
- Fine-tuning RWKV on custom codebases (enterprise roadmap)

---

## 4. 🧑‍💻 Target Users

| User Type | Need |
|---|---|
| Individual Developers | Safer AI-assisted coding, no trust issues with LLMs |
| Dev Teams | Prevent hallucinated code from entering production |
| Enterprises | Privacy-first: code never leaves the machine (RWKV local) |
| Researchers | Benchmark and study LLM hallucination rates |
| Educators | Teach correct API usage with real-time feedback |

---

## 5. 🏗️ System Boundaries

```
┌─────────────────────────────────────────────────────────┐
│                  LLM Truth Guard System                  │
│                                                          │
│  ┌──────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │  Input   │ → │  AST Parser  │ → │  RWKV Engine   │  │
│  │  Layer   │   │              │   │  (local)       │  │
│  └──────────┘   └──────────────┘   └────────────────┘  │
│                                           │              │
│                        ┌──────────────────▼──────────┐  │
│                        │  Knowledge Verification      │  │
│                        │  (PyPI / npm / GitHub)       │  │
│                        └──────────────────────────────┘  │
│                                           │              │
│                        ┌─────────────────▼───────────┐  │
│                        │  Scoring + Correction Engine │  │
│                        └─────────────────────────────┘  │
│                                           │              │
│          ┌──────────────┬────────────────▼────────┐     │
│          │ VSCode Ext.  │  GitHub Action  │  API  │     │
│          └──────────────┴─────────────────────────┘     │
└─────────────────────────────────────────────────────────┘
```

---

## 6. ⚙️ Technical Constraints

- RWKV model must run on CPU (no GPU required for v1.0)
- VSCode extension must not exceed 50MB bundle size
- API response time target: < 200ms for files under 300 lines
- RWKV local scan target: < 100ms pre-screen latency
- All local inference must be fully offline-capable

---

## 7. 📦 Deliverables

| # | Deliverable | Format |
|---|---|---|
| 1 | Core detection engine | Python package |
| 2 | VSCode Extension | `.vsix` publishable to marketplace |
| 3 | GitHub Action | Published to GitHub Marketplace |
| 4 | REST API | Docker container + OpenAPI spec |
| 5 | CLI Tool | npm + pip installable |
| 6 | Benchmark report | Markdown + PDF |
| 7 | Documentation site | GitHub Pages / Docusaurus |
| 8 | Demo video | YouTube / GitHub README |

---

## 8. 📊 Success Metrics (v1.0)

| Metric | Target |
|---|---|
| Hallucination detection accuracy | > 80% on benchmark suite |
| False positive rate | < 10% |
| Local inference latency (RWKV 3B) | < 100ms |
| VSCode extension install size | < 50MB |
| GitHub Stars at launch | > 500 |
| Supported languages | Python, JavaScript, TypeScript |

---

## 9. 🔗 Key Dependencies

- [RWKV.cpp](https://github.com/saharNooby/rwkv.cpp) or [rwkv-pip](https://pypi.org/project/rwkv/)
- [Tree-sitter](https://tree-sitter.github.io/) — AST parsing
- PyPI JSON API — package validation
- npm Registry API — package validation
- VSCode Extension API
- GitHub Actions API
- FastAPI — REST API layer

---

## 10. 🗓️ High-Level Timeline

| Phase | Duration | Milestone |
|---|---|---|
| Phase 0 — Setup | 1 week | Repo, tooling, architecture finalized |
| Phase 1 — Core Engine | 3 weeks | Parser + RWKV + scorer working |
| Phase 2 — VSCode Extension | 2 weeks | Extension beta published |
| Phase 3 — GitHub Action | 2 weeks | Action published to marketplace |
| Phase 4 — API + CLI | 1 week | REST API + CLI released |
| Phase 5 — Benchmarks + Docs | 2 weeks | Full launch ready |

**Total estimated duration: ~11 weeks**
