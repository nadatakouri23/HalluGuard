import * as exec from '@actions/exec';
import * as fs from 'fs';
import * as path from 'path';

export interface HallucinationItem {
  line: number;
  column?: number;
  type: string;
  token: string;
  explanation: string;
  suggestion: string;
  severity: string;
}

export interface Report {
  file: string;
  risk_score: number;
  risk_level?: string;
  severity?: string;
  confidence: string;
  hallucinations: HallucinationItem[];
  suggestions: any[];
  unverified?: string[];
  notes?: string[];
  error?: string;
}

export interface AnalyzerOptions {
  /** `pip install` HalluGuard from this action's own repository first. */
  install: boolean;
  /** Never query PyPI/npm (curated knowledge only). */
  offline: boolean;
  /** Python interpreter to use. */
  python: string;
}

/**
 * Install HalluGuard from the repository that ships this action.
 *
 * `GITHUB_ACTION_PATH` is the directory of the action (`.../github-action`);
 * its parent is the repository root that holds `pyproject.toml`.  This makes
 * the action usable from *any* repository: the analyzer no longer has to
 * exist in the workspace being scanned.
 */
async function installHalluGuard(python: string): Promise<void> {
  const actionPath = process.env.GITHUB_ACTION_PATH;
  if (!actionPath) {
    throw new Error('GITHUB_ACTION_PATH is not set; cannot locate HalluGuard sources.');
  }
  const repoRoot = path.resolve(actionPath, '..');
  if (!fs.existsSync(path.join(repoRoot, 'pyproject.toml'))) {
    throw new Error(`pyproject.toml not found in ${repoRoot}; cannot install HalluGuard.`);
  }
  await exec.exec(python, ['-m', 'pip', 'install', '--quiet', repoRoot]);
}

export async function runAnalyzer(
  files: string[],
  options: AnalyzerOptions
): Promise<Report[]> {
  if (files.length === 0) {
    return [];
  }

  const workspaceDir = process.env.GITHUB_WORKSPACE || process.cwd();

  if (options.install) {
    await installHalluGuard(options.python);
  }

  let stdout = '';
  let stderr = '';

  const execOptions: exec.ExecOptions = {
    cwd: workspaceDir,
    listeners: {
      stdout: (data: Buffer) => {
        stdout += data.toString();
      },
      stderr: (data: Buffer) => {
        stderr += data.toString();
      }
    },
    silent: true // stdout is JSON; keep the log readable
  };

  const args = ['-m', 'cli.analyzer', '--project-root', workspaceDir];
  if (options.offline) {
    args.push('--offline');
  }

  try {
    await exec.exec(options.python, [...args, ...files], execOptions);
  } catch (error) {
    console.error(`Error running the HalluGuard analyzer: ${error}`);
    if (stderr) {
      console.error(`Analyzer stderr: ${stderr}`);
    }
    throw new Error('Failed to run HalluGuard analysis.');
  }

  try {
    const reports: Report[] = JSON.parse(extractJsonArray(stdout));
    return reports;
  } catch (err: any) {
    console.error('Failed to parse analysis output.');
    console.error(`Stdout: ${stdout}`);
    throw new Error(`Parse error: ${err.message}`);
  }
}

/**
 * The analyzer prints exactly one JSON array line on stdout.  Take the last
 * line that looks like one, so stray output from imported modules is ignored.
 */
export function extractJsonArray(out: string): string {
  const lines = out.split(/\r?\n/).map((l) => l.trim());
  for (let i = lines.length - 1; i >= 0; i--) {
    if (lines[i].startsWith('[') && lines[i].endsWith(']')) {
      return lines[i];
    }
  }
  throw new Error('No JSON array found in stdout.');
}
