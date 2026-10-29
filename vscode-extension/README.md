# HalluGuard AI for Visual Studio Code

> **HalluGuard AI** analyzes your Python and JavaScript/TypeScript code in real-time to detect, explain, and correct hallucinated packages, functions, and standard library calls.

![HalluGuard Logo](images/icon.png)

## Features

- **Real-Time Detection:** Live analysis of your code straight from the editor.
- **Diagnostic Underlines:**
  - 🔴 **Red** wavy lines for `CRITICAL` / `HIGH` risk hallucinations (e.g., completely fake packages).
  - 🟠 **Orange** wavy lines for `MEDIUM` risk (e.g., suspicious unimported functions).
  - 🟡 **Yellow** wavy lines for `LOW` risk.
- **Hover Explanations:** Rich tooltips explain exactly *why* something is flagged.
- **Quick Fixes:** Replaces hallucinations with known valid APIs or correctly-named packages (e.g., `requests.get` instead of `fetchUserData`, or `beautifulsoup4` instead of `beautifulsoup`).
- **Ignore Directives:** Easily insert `// halluguard-ignore` or `# halluguard-ignore` rules for false positives.
- **Full Report View:** Click the status bar icon to see a comprehensive tabular breakdown of your file's risk score.

## Setup & Requirements

Because HalluGuard AI verifies APIs against live data and uses AST parsing under the hood, the extension relies on the **HalluGuard Core Engine** running locally.

1. **Install Python 3.11+**
2. Clone and setup the core engine:
   ```bash
   git clone https://github.com/halluguard/halluguard-ai.git
   cd halluguard-ai
   pip install -r requirements.txt
   ```
3. Install the VSCode Extension. The extension will automatically start the lightweight FastAPI backend when you open a supported file.

## Configuration

| Setting | Description | Default |
|---|---|---|
| `halluguard.enabled` | Turn analysis on or off globally. | `true` |
| `halluguard.serverPort` | Port for the local Python server. | `7432` |
| `halluguard.sensitivity` | Sensitivity threshold (`LOW`, `MEDIUM`, `HIGH`). | `MEDIUM` |
| `halluguard.modelPath` | (Optional) Path to your local RWKV `.pth` model for AI-powered heuristic scoring. | `""` |
| `halluguard.pythonPath` | The path to the Python interpreter used to start the server. | `python` |

## How it works

1. You write an import like `import nonexistent_package`.
2. The extension sends the file to the local `python -m uvicorn api.server:app`.
3. The server runs AST parsing using `tree-sitter`.
4. It calls out to the PyPI/npm registry APIs to verify the package doesn't exist.
5. The extension receives the JSON report and applies a red underline + diagnostic + quick fix.

## Release Notes

### 1.0.0
- Initial release.
- Support for Python, JavaScript, and TypeScript.
- Real-time diagnostic generation and hover cards.
- Pattern-matching and fuzzy-matching Quick Fixes.
