/**
 * Analyzer — communicates with the HalluGuard Python server.
 *
 * Manages:
 * - Spawning / stopping the FastAPI server process.
 * - HTTP calls to POST /analyze and GET /health.
 * - Timeout + fallback when the server is unreachable.
 */
import * as vscode from "vscode";
import * as http from "http";
import { ChildProcess, spawn } from "child_process";

/** Shape of a single hallucination returned by the server. */
export interface HallucinationItem {
  /** 1-based line of the finding (0 only for legacy servers). */
  line: number;
  /** 0-based character column of the token on that line. */
  column?: number;
  type: string;
  token: string;
  explanation: string;
  suggestion: string;
  severity: string;
}

/** Shape of a correction suggestion. */
export interface SuggestionItem {
  token: string;
  original_type?: string;
  suggestion?: string;
  explanation?: string;
  confidence?: string;
}

/** Full analysis report returned by the server. */
export interface AnalysisReport {
  file: string;
  risk_score: number;
  risk_level?: string;
  /** Severity of the worst issue (NONE when clean). */
  severity?: string;
  confidence: string;
  /** Imports/attributes that could not be verified (offline, network error). */
  unverified?: string[];
  notes?: string[];
  hallucinations: HallucinationItem[];
  suggestions: SuggestionItem[];
}

export class Analyzer {
  private serverProcess: ChildProcess | null = null;
  private baseUrl: string;

  constructor() {
    const config = vscode.workspace.getConfiguration("halluguard");
    const port = config.get<number>("serverPort", 7432);
    this.baseUrl = `http://127.0.0.1:${port}`;
  }

  // ── Server lifecycle ─────────────────────────────────────────

  /** Spawn the FastAPI Python server as a child process. */
  startServer(): void {
    if (this.serverProcess) {
      return; // already running
    }

    const config = vscode.workspace.getConfiguration("halluguard");
    const pythonPath = config.get<string>("pythonPath", "python");
    const port = config.get<number>("serverPort", 7432);
    const modelPath = config.get<string>("modelPath", "").trim();

    // Determine the project root (parent of vscode-extension/)
    const extRoot =
      vscode.extensions.getExtension("halluguard.halluguard-ai")?.extensionPath;

    // The server module lives one level up from the extension
    const cwd = extRoot
      ? vscode.Uri.joinPath(vscode.Uri.file(extRoot), "..").fsPath
      : undefined;

    console.log(
      `[HalluGuard] Starting server: ${pythonPath} -m uvicorn api.server:app --port ${port}`
    );

    this.serverProcess = spawn(
      pythonPath,
      ["-m", "uvicorn", "api.server:app", "--host", "127.0.0.1", "--port", String(port)],
      {
        cwd,
        stdio: "pipe",
        // halluguard.modelPath -> local RWKV model used by the server.
        env: modelPath
          ? { ...process.env, HALLUGUARD_RWKV_MODEL: modelPath }
          : process.env,
      }
    );

    this.serverProcess.stdout?.on("data", (data) =>
      console.log(`[HalluGuard Server] ${data}`)
    );
    this.serverProcess.stderr?.on("data", (data) =>
      console.log(`[HalluGuard Server] ${data}`)
    );
    this.serverProcess.on("exit", (code) =>
      console.log(`[HalluGuard Server] exited with code ${code}`)
    );
  }

  /** Kill the Python server process. */
  stopServer(): void {
    if (this.serverProcess) {
      this.serverProcess.kill();
      this.serverProcess = null;
      console.log("[HalluGuard] Server stopped.");
    }
  }

  // ── Analysis ─────────────────────────────────────────────────

  /**
   * Send code to the analysis server and return the report.
   * Times out after 10 seconds.
   */
  async analyze(
    code: string,
    language: string,
    fileName?: string
  ): Promise<AnalysisReport> {
    const payload = JSON.stringify({
      code,
      language,
      file_name: fileName ?? null,
    });

    return new Promise<AnalysisReport>((resolve, reject) => {
      const config = vscode.workspace.getConfiguration("halluguard");
      const port = config.get<number>("serverPort", 7432);

      const options: http.RequestOptions = {
        hostname: "127.0.0.1",
        port,
        path: "/analyze",
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(payload),
        },
        timeout: 10_000,
      };

      const req = http.request(options, (res) => {
        let body = "";
        res.on("data", (chunk) => (body += chunk));
        res.on("end", () => {
          try {
            const report: AnalysisReport = JSON.parse(body);
            resolve(report);
          } catch {
            reject(new Error("Failed to parse server response."));
          }
        });
      });

      req.on("error", (err) => reject(err));
      req.on("timeout", () => {
        req.destroy();
        reject(new Error("Analysis request timed out (10 s)."));
      });

      req.write(payload);
      req.end();
    });
  }

  // ── Health ───────────────────────────────────────────────────

  /** Check if the server is reachable. */
  async isServerHealthy(): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      const config = vscode.workspace.getConfiguration("halluguard");
      const port = config.get<number>("serverPort", 7432);

      const req = http.get(
        `http://127.0.0.1:${port}/health`,
        { timeout: 3_000 },
        (res) => {
          resolve(res.statusCode === 200);
        }
      );
      req.on("error", () => resolve(false));
      req.on("timeout", () => {
        req.destroy();
        resolve(false);
      });
    });
  }

  /** Return the latest report stored by the analyzer (for hover). */
  private _cachedReports = new Map<string, AnalysisReport>();

  cacheReport(uri: string, report: AnalysisReport): void {
    this._cachedReports.set(uri, report);
  }

  getCachedReport(uri: string): AnalysisReport | undefined {
    return this._cachedReports.get(uri);
  }
}
