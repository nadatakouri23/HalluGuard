/**
 * Decorations & Diagnostics — visual feedback in the editor.
 *
 * Creates:
 * - Colored underlines (red / orange / yellow) in the active editor.
 * - VSCode Diagnostics pushed to the "Problems" panel.
 */
import * as vscode from "vscode";
import { AnalysisReport, HallucinationItem } from "./analyzer";

export class DecorationManager {
  // Decoration types — created once, reused across calls
  private readonly highDecoration: vscode.TextEditorDecorationType;
  private readonly mediumDecoration: vscode.TextEditorDecorationType;
  private readonly lowDecoration: vscode.TextEditorDecorationType;

  constructor() {
    this.highDecoration = vscode.window.createTextEditorDecorationType({
      textDecoration: "underline wavy #e74c3c",       // red
      overviewRulerColor: "#e74c3c",
      overviewRulerLane: vscode.OverviewRulerLane.Right,
    });

    this.mediumDecoration = vscode.window.createTextEditorDecorationType({
      textDecoration: "underline wavy #f39c12",       // orange
      overviewRulerColor: "#f39c12",
      overviewRulerLane: vscode.OverviewRulerLane.Right,
    });

    this.lowDecoration = vscode.window.createTextEditorDecorationType({
      textDecoration: "underline wavy #f1c40f",       // yellow
      overviewRulerColor: "#f1c40f",
      overviewRulerLane: vscode.OverviewRulerLane.Right,
    });
  }

  // ── Diagnostics (Problems panel) ───────────────────────────

  /**
   * Build an array of `vscode.Diagnostic` objects from the analysis report.
   */
  createDiagnostics(
    doc: vscode.TextDocument,
    report: AnalysisReport
  ): vscode.Diagnostic[] {
    const diagnostics: vscode.Diagnostic[] = [];

    for (const h of report.hallucinations ?? []) {
      const range = this.findTokenRange(doc, h);
      const severity = this.mapSeverity(h.severity);

      const diag = new vscode.Diagnostic(range, h.explanation, severity);
      diag.code = h.type;
      diag.source = "HalluGuard AI";

      // Attach extra data used by the quick-fix provider
      (diag as any)._halluguard = h;

      diagnostics.push(diag);
    }

    return diagnostics;
  }

  // ── Editor decorations (underlines) ────────────────────────

  /**
   * Apply coloured underlines in the active editor for each hallucination.
   */
  applyDecorations(
    editor: vscode.TextEditor,
    report: AnalysisReport
  ): void {
    const highRanges: vscode.DecorationOptions[] = [];
    const mediumRanges: vscode.DecorationOptions[] = [];
    const lowRanges: vscode.DecorationOptions[] = [];

    for (const h of report.hallucinations ?? []) {
      const range = this.findTokenRange(editor.document, h);
      const opt: vscode.DecorationOptions = {
        range,
        hoverMessage: new vscode.MarkdownString(
          `**HalluGuard AI** — ${h.type}\n\n` +
            `${h.explanation}\n\n` +
            `*Suggestion:* ${h.suggestion}`
        ),
      };

      const sev = (h.severity ?? "MEDIUM").toUpperCase();
      if (sev === "HIGH" || sev === "CRITICAL") {
        highRanges.push(opt);
      } else if (sev === "MEDIUM") {
        mediumRanges.push(opt);
      } else {
        lowRanges.push(opt);
      }
    }

    editor.setDecorations(this.highDecoration, highRanges);
    editor.setDecorations(this.mediumDecoration, mediumRanges);
    editor.setDecorations(this.lowDecoration, lowRanges);
  }

  // ── Helpers ────────────────────────────────────────────────

  /**
   * Locate the token in the document. Falls back to its declared line
   * (or line 0) if not found.
   */
  private findTokenRange(
    doc: vscode.TextDocument,
    h: HallucinationItem
  ): vscode.Range {
    const token = h.token;

    // Precise position reported by the server (1-based line, 0-based column).
    if (h.line >= 1 && h.line <= doc.lineCount) {
      const line = doc.lineAt(h.line - 1);
      const col = h.column ?? 0;
      if (line.text.substr(col, token.length) === token) {
        return new vscode.Range(h.line - 1, col, h.line - 1, col + token.length);
      }
      // Token text differs from the node text (e.g. quoted JS specifier):
      // look for it on the reported line only, never elsewhere in the file.
      const inLine = line.text.indexOf(token);
      return inLine >= 0
        ? new vscode.Range(h.line - 1, inLine, h.line - 1, inLine + token.length)
        : line.range;
    }

    // Legacy servers (line 0): search the whole document for the token string
    const text = doc.getText();
    const idx = text.indexOf(token);

    if (idx >= 0) {
      const startPos = doc.positionAt(idx);
      const endPos = doc.positionAt(idx + token.length);
      return new vscode.Range(startPos, endPos);
    }

    // Fallback: use the reported line (clamped to valid range)
    const line = Math.min(h.line, doc.lineCount - 1);
    return doc.lineAt(Math.max(0, line)).range;
  }

  private mapSeverity(severity: string): vscode.DiagnosticSeverity {
    switch ((severity ?? "").toUpperCase()) {
      case "CRITICAL":
      case "HIGH":
        return vscode.DiagnosticSeverity.Error;
      case "MEDIUM":
        return vscode.DiagnosticSeverity.Warning;
      default:
        return vscode.DiagnosticSeverity.Information;
    }
  }
}
