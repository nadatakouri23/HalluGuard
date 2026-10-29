import * as core from '@actions/core';
import * as github from '@actions/github';
import { runAnalyzer, Report } from './analyzer';
import { reportHallucinations, parsePatchLines } from './reporter';

async function run(): Promise<void> {
  try {
    const token = core.getInput('github-token', { required: true });
    const threshold = core.getInput('severity-threshold') || 'HIGH';
    const failOnHallucination = core.getInput('fail-on-hallucination') === 'true';
    const offline = core.getInput('offline') === 'true';
    const install = core.getInput('install') !== 'false';
    const python = core.getInput('python') || 'python';

    core.info('Fetching changed files...');

    const changed = await getChangedFiles(token);
    if (changed.size === 0) {
      core.info('No Python or JavaScript/TypeScript files changed.');
      return;
    }

    core.info(`Analyzing ${changed.size} file(s) for hallucinations...`);
    const reports: Report[] = await runAnalyzer([...changed.keys()], {
      install,
      offline,
      python
    });

    core.info('Publishing report and evaluating thresholds...');
    await reportHallucinations(token, reports, changed, threshold, failOnHallucination);
  } catch (error: any) {
    core.setFailed(error.message);
  }
}

/**
 * Changed, non-removed source files of the pull request, mapped to the set of
 * line numbers that are visible in the diff (right side).  Only those lines
 * accept inline review comments.
 */
async function getChangedFiles(token: string): Promise<Map<string, Set<number>>> {
  const octokit = github.getOctokit(token);
  const context = github.context;
  const result = new Map<string, Set<number>>();

  if (!context.payload.pull_request) {
    // If not a PR, we could potentially scan the whole repo context,
    // but for now we only support PRs.
    core.info('Not a PR, no changed files extracted.');
    return result;
  }

  const { owner, repo } = context.repo;
  const pull_number = context.payload.pull_request.number;

  // Paginate: a PR can touch far more than 100 files.
  const files = await octokit.paginate(octokit.rest.pulls.listFiles, {
    owner,
    repo,
    pull_number,
    per_page: 100
  });

  const supportedExtensions = ['.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.py'];

  for (const f of files) {
    if (f.status === 'removed') continue;
    if (!supportedExtensions.some((ext) => f.filename.endsWith(ext))) continue;
    result.set(f.filename, parsePatchLines(f.patch));
  }
  return result;
}

// Start the action
run();
