/**
 * Quick Fix (Code Actions) — auto-correction for hallucinated code.
 *
 * Provides three actions for each HalluGuard diagnostic:
 * 1. **Apply fix** — replace the hallucinated token with the suggestion.
 * 2. **Ignore this warning** — insert a `halluguard-ignore` comment.
 * 3. **Show full report** — open the webview report panel.
 */
import * as vscode from "vscode";
import { HallucinationItem } from "./analyzer";

export class HalluGuardCodeActionProvider implements vscode.CodeActionProvider {
  static readonly providedKinds = [
    vscode.CodeActionKind.QuickFix,
  ];

  constructor(
    private readonly diagnosticCollection: vscode.DiagnosticCollection
  ) {}

  provideCodeActions(
    document: vscode.TextDocument,
    range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext,
    _token: vscode.CancellationToken
  ): vscode.CodeAction[] {
    const actions: vscode.CodeAction[] = [];

    for (const diag of context.diagnostics) {
      if (diag.source !== "HalluGuard AI") {
        continue;
      }

      const h: HallucinationItem | undefined = (diag as any)._halluguard;
      if (!h) {
        continue;
      }

      // ── 1. Apply fix ────────────────────────────────────
      if (h.suggestion && h.suggestion !== "—") {
        const fixAction = new vscode.CodeAction(
          `HalluGuard: Apply fix → ${h.suggestion}`,
          vscode.CodeActionKind.QuickFix
        );
        fixAction.diagnostics = [diag];
        fixAction.isPreferred = true;

        const edit = new vscode.WorkspaceEdit();

        if (h.type === "unknown_import") {
          // Replace the import name
          edit.replace(document.uri, diag.range, h.suggestion);
        } else {
          // Replace the function/method call token
          edit.replace(document.uri, diag.range, h.suggestion);
        }

        fixAction.edit = edit;
        actions.push(fixAction);
      }

      // ── 2. Ignore this warning ──────────────────────────
      const ignoreAction = new vscode.CodeAction(
        "HalluGuard: Ignore this warning",
        vscode.CodeActionKind.QuickFix
      );
      ignoreAction.diagnostics = [diag];

      const ignoreEdit = new vscode.WorkspaceEdit();
      const lineNum = diag.range.start.line;
      const lineText = document.lineAt(lineNum).text;
      const indent = lineText.match(/^(\s*)/)?.[1] ?? "";

      // Determine the comment prefix based on language
      const langId = document.languageId;
      const commentPrefix =
        langId === "python" ? "# halluguard-ignore" : "// halluguard-ignore";

      ignoreEdit.insert(
        document.uri,
        new vscode.Position(lineNum, 0),
        `${indent}${commentPrefix}\n`
      );
      ignoreAction.edit = ignoreEdit;
      actions.push(ignoreAction);

      // ── 3. Show full report ─────────────────────────────
      const reportAction = new vscode.CodeAction(
        "HalluGuard: Show full report",
        vscode.CodeActionKind.QuickFix
      );
      reportAction.diagnostics = [diag];
      reportAction.command = {
        command: "halluguard.showReport",
        title: "Show HalluGuard Report",
      };
      actions.push(reportAction);
    }

    return actions;
  }
}
