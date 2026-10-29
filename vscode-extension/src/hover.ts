/**
 * Hover Provider — rich tooltips when hovering over hallucinated code.
 *
 * Displays:
 * - Hallucination type
 * - Natural-language explanation
 * - Risk score
 * - Correction suggestion
 */
import * as vscode from "vscode";
import { Analyzer, HallucinationItem } from "./analyzer";

export class HalluGuardHoverProvider implements vscode.HoverProvider {
  constructor(private readonly analyzer: Analyzer) {}

  provideHover(
    document: vscode.TextDocument,
    position: vscode.Position,
    _token: vscode.CancellationToken
  ): vscode.Hover | null {
    // Check existing diagnostics for this position
    const diags = vscode.languages.getDiagnostics(document.uri);
    const matching = diags.filter(
      (d) => d.source === "HalluGuard AI" && d.range.contains(position)
    );

    if (matching.length === 0) {
      return null;
    }

    const parts: vscode.MarkdownString[] = [];

    for (const diag of matching) {
      const h: HallucinationItem | undefined = (diag as any)._halluguard;
      if (!h) {
        continue;
      }

      const md = new vscode.MarkdownString();
      md.isTrusted = true;
      md.supportThemeIcons = true;

      md.appendMarkdown(`### $(shield) HalluGuard AI\n\n`);
      md.appendMarkdown(`| | |\n|---|---|\n`);
      md.appendMarkdown(`| **Type** | \`${h.type}\` |\n`);
      md.appendMarkdown(`| **Token** | \`${h.token}\` |\n`);
      md.appendMarkdown(`| **Severity** | ${severityBadge(h.severity)} |\n`);
      md.appendMarkdown(`| **Explanation** | ${h.explanation} |\n`);
      md.appendMarkdown(`| **Suggestion** | ${h.suggestion || "—"} |\n`);

      parts.push(md);
    }

    return parts.length > 0 ? new vscode.Hover(parts) : null;
  }
}

function severityBadge(severity: string): string {
  switch ((severity ?? "").toUpperCase()) {
    case "CRITICAL":
      return "$(error) CRITICAL";
    case "HIGH":
      return "$(error) HIGH";
    case "MEDIUM":
      return "$(warning) MEDIUM";
    default:
      return "$(info) LOW";
  }
}
