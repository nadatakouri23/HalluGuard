/**
 * HalluGuard AI — VSCode Extension Entry Point.
 *
 * Manages the lifecycle of:
 * - The Python analysis server (FastAPI on port 7432)
 * - Diagnostic decorations (underlines in editor)
 * - Hover tooltips
 * - Quick-fix code actions
 * - Status bar indicator
 */
import * as vscode from "vscode";
import { Analyzer, AnalysisReport } from "./analyzer";
import { DecorationManager } from "./decorations";
import { HalluGuardHoverProvider } from "./hover";
import { HalluGuardCodeActionProvider } from "./quickfix";

let analyzer: Analyzer;
let decorationManager: DecorationManager;
let statusBarItem: vscode.StatusBarItem;
let diagnosticCollection: vscode.DiagnosticCollection;

export function activate(context: vscode.ExtensionContext): void {
  console.log("HalluGuard AI extension activated.");

  // ── Core services ──────────────────────────────────────────
  diagnosticCollection =
    vscode.languages.createDiagnosticCollection("halluguard");
  analyzer = new Analyzer();
  decorationManager = new DecorationManager();

  // ── Status bar ─────────────────────────────────────────────
  statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100
  );
  statusBarItem.command = "halluguard.showReport";
  statusBarItem.text = "$(shield) HalluGuard: Ready";
  statusBarItem.tooltip = "Click to show full HalluGuard report";
  statusBarItem.show();

  // ── Commands ───────────────────────────────────────────────
  const analyzeCmd = vscode.commands.registerCommand(
    "halluguard.analyze",
    () => analyzeActiveEditor()
  );

  const reportCmd = vscode.commands.registerCommand(
    "halluguard.showReport",
    () => showFullReport(context)
  );

  // ── Event listeners ────────────────────────────────────────
  const onSave = vscode.workspace.onDidSaveTextDocument((doc) => {
    const config = vscode.workspace.getConfiguration("halluguard");
    if (!config.get<boolean>("enabled", true)) {
      return;
    }
    if (isSupportedLanguage(doc.languageId)) {
      runAnalysis(doc);
    }
  });

  const onOpen = vscode.workspace.onDidOpenTextDocument((doc) => {
    const config = vscode.workspace.getConfiguration("halluguard");
    if (!config.get<boolean>("enabled", true)) {
      return;
    }
    if (isSupportedLanguage(doc.languageId)) {
      runAnalysis(doc);
    }
  });

  // ── Providers ──────────────────────────────────────────────
  const hoverProvider = vscode.languages.registerHoverProvider(
    [
      { scheme: "file", language: "python" },
      { scheme: "file", language: "javascript" },
      { scheme: "file", language: "typescript" },
    ],
    new HalluGuardHoverProvider(analyzer)
  );

  const codeActionProvider = vscode.languages.registerCodeActionsProvider(
    [
      { scheme: "file", language: "python" },
      { scheme: "file", language: "javascript" },
      { scheme: "file", language: "typescript" },
    ],
    new HalluGuardCodeActionProvider(diagnosticCollection),
    { providedCodeActionKinds: HalluGuardCodeActionProvider.providedKinds }
  );

  // ── Disposables ────────────────────────────────────────────
  context.subscriptions.push(
    analyzeCmd,
    reportCmd,
    onSave,
    onOpen,
    hoverProvider,
    codeActionProvider,
    diagnosticCollection,
    statusBarItem
  );

  // Start the Python server
  analyzer.startServer();

  // Analyze the currently open file
  if (vscode.window.activeTextEditor) {
    const doc = vscode.window.activeTextEditor.document;
    if (isSupportedLanguage(doc.languageId)) {
      runAnalysis(doc);
    }
  }
}

export function deactivate(): void {
  analyzer?.stopServer();
  console.log("HalluGuard AI extension deactivated.");
}

// ── Helpers ────────────────────────────────────────────────────

function isSupportedLanguage(languageId: string): boolean {
  return ["python", "javascript", "typescript"].includes(languageId);
}

function mapLanguageId(languageId: string): string {
  const mapping: Record<string, string> = {
    python: "python",
    javascript: "javascript",
    typescript: "typescript",
  };
  return mapping[languageId] ?? "python";
}

const SEVERITY_RANK: Record<string, number> = {
  NONE: 0,
  LOW: 1,
  MEDIUM: 2,
  HIGH: 3,
  CRITICAL: 4,
};

/**
 * halluguard.sensitivity = minimum severity displayed:
 * LOW shows everything, MEDIUM (default) hides LOW notes, HIGH keeps only
 * HIGH/CRITICAL findings.
 */
function applySensitivity(report: AnalysisReport): AnalysisReport {
  const level = vscode.workspace
    .getConfiguration("halluguard")
    .get<string>("sensitivity", "MEDIUM")
    .toUpperCase();
  const min = SEVERITY_RANK[level] ?? SEVERITY_RANK.MEDIUM;
  return {
    ...report,
    hallucinations: (report.hallucinations ?? []).filter(
      (h) => (SEVERITY_RANK[(h.severity ?? "").toUpperCase()] ?? 0) >= min
    ),
  };
}

/** Store the latest report for the webview panel. */
let latestReport: any = null;

async function runAnalysis(doc: vscode.TextDocument): Promise<void> {
  const code = doc.getText();
  const language = mapLanguageId(doc.languageId);

  statusBarItem.text = "$(sync~spin) HalluGuard: Analyzing...";

  try {
    const raw = await analyzer.analyze(code, language, doc.fileName);
    const report = applySensitivity(raw);
    latestReport = report;

    // Update diagnostics
    const diagnostics = decorationManager.createDiagnostics(doc, report);
    diagnosticCollection.set(doc.uri, diagnostics);

    // Update decorations in active editor
    const editor = vscode.window.activeTextEditor;
    if (editor && editor.document.uri.toString() === doc.uri.toString()) {
      decorationManager.applyDecorations(editor, report);
    }

    // Update status bar
    const count = report.hallucinations?.length ?? 0;
    if (count === 0) {
      statusBarItem.text = "$(shield) HalluGuard: Clean";
      statusBarItem.backgroundColor = undefined;
    } else {
      statusBarItem.text = `$(alert) HalluGuard: ${count} warning${count > 1 ? "s" : ""}`;
      statusBarItem.backgroundColor = new vscode.ThemeColor(
        "statusBarItem.warningBackground"
      );
    }
  } catch (err: any) {
    statusBarItem.text = "$(error) HalluGuard: Server offline";
    statusBarItem.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.errorBackground"
    );
    console.error("HalluGuard analysis error:", err?.message);
  }
}

async function analyzeActiveEditor(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage("No active editor to analyze.");
    return;
  }
  await runAnalysis(editor.document);
}

function showFullReport(context: vscode.ExtensionContext): void {
  const panel = vscode.window.createWebviewPanel(
    "halluguardReport",
    "HalluGuard AI Report",
    vscode.ViewColumn.Beside,
    { enableScripts: false }
  );

  if (!latestReport) {
    panel.webview.html = `<html><body><h2>No report generated yet.</h2>
      <p>Open or save a Python / JS / TS file to trigger analysis.</p>
      </body></html>`;
    return;
  }

  const r = latestReport;
  const rows = (r.hallucinations ?? [])
    .map(
      (h: any) =>
        `<tr>
          <td>${h.line}</td>
          <td><code>${h.token}</code></td>
          <td>${h.type}</td>
          <td>${h.severity}</td>
          <td>${h.explanation}</td>
          <td>${h.suggestion}</td>
        </tr>`
    )
    .join("");

  panel.webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           padding: 20px; color: var(--vscode-editor-foreground);
           background: var(--vscode-editor-background); }
    h1 { border-bottom: 2px solid var(--vscode-panel-border); padding-bottom: 8px; }
    table { width: 100%; border-collapse: collapse; margin-top: 16px; }
    th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--vscode-panel-border); }
    th { background: var(--vscode-editor-selectionBackground); }
    .score { font-size: 2em; font-weight: bold; }
    .badge { display: inline-block; padding: 2px 10px; border-radius: 4px;
             font-size: 0.9em; font-weight: 600; }
    .badge-high { background: #e74c3c; color: white; }
    .badge-medium { background: #f39c12; color: white; }
    .badge-low { background: #f1c40f; color: #333; }
  </style>
</head>
<body>
  <h1>HalluGuard AI Report</h1>
  <p>File: <strong>${r.file}</strong></p>
  <p class="score">Risk Score: ${r.risk_score} / 100</p>
  <p>Confidence: <span class="badge badge-${(r.confidence ?? "medium").toLowerCase()}">${r.confidence}</span></p>

  <h2>Detected Hallucinations (${(r.hallucinations ?? []).length})</h2>
  <table>
    <thead><tr><th>Line</th><th>Token</th><th>Type</th><th>Severity</th><th>Explanation</th><th>Suggestion</th></tr></thead>
    <tbody>${rows || "<tr><td colspan='6'>No issues found.</td></tr>"}</tbody>
  </table>
</body>
</html>`;
}
