import * as github from '@actions/github';
import * as core from '@actions/core';
import { Report, HallucinationItem } from './analyzer';

const SEVERITY_LEVELS: Record<string, number> = {
  LOW: 1,
  MEDIUM: 2,
  HIGH: 3,
  CRITICAL: 4
};

/**
 * Lines of the new file that appear in a unified-diff `patch` (added and
 * context lines).  GitHub only accepts inline review comments on those lines.
 */
export function parsePatchLines(patch: string | undefined): Set<number> {
  const lines = new Set<number>();
  if (!patch) return lines;

  let newLine = 0;
  for (const raw of patch.split('\n')) {
    if (raw.startsWith('@@')) {
      const m = /\+(\d+)(?:,\d+)?/.exec(raw);
      newLine = m ? parseInt(m[1], 10) : 0;
      continue;
    }
    if (newLine === 0 || raw.startsWith('-') || raw.startsWith('\\')) {
      continue; // removed line or "\ No newline at end of file"
    }
    lines.add(newLine);
    newLine++;
  }
  return lines;
}

export function isSeverityThresholdMet(severity: string, threshold: string): boolean {
  const sevVal = SEVERITY_LEVELS[(severity || '').toUpperCase()] || 0;
  const threshVal = SEVERITY_LEVELS[(threshold || '').toUpperCase()] || SEVERITY_LEVELS.HIGH;
  return sevVal >= threshVal;
}

function buildCommentBody(issue: HallucinationItem): string {
  const suggestionTxt = issue.suggestion ? `\n\n**Suggestion:** \`${issue.suggestion}\`` : '';

  let severityEmoji = 'ℹ️';
  if (issue.severity === 'CRITICAL' || issue.severity === 'HIGH') severityEmoji = '🚨';
  if (issue.severity === 'MEDIUM') severityEmoji = '⚠️';

  return `### ${severityEmoji} HalluGuard AI: ${issue.type}

**Token:** \`${issue.token}\`
**Severity:** ${issue.severity}

${issue.explanation}${suggestionTxt}`;
}

export async function reportHallucinations(
  token: string,
  reports: Report[],
  diffLines: Map<string, Set<number>>,
  thresholdSeverity: string,
  failOnHallucination: boolean
): Promise<void> {
  const octokit = github.getOctokit(token);
  const context = github.context;
  const pullRequest = context.payload.pull_request;

  let violations = 0;
  let totalIssues = 0;
  const offDiff: string[] = [];

  for (const report of reports) {
    if (report.error) {
      core.warning(`HalluGuard failed on ${report.file}: ${report.error}`);
      continue;
    }
    if (report.unverified && report.unverified.length > 0) {
      core.notice(
        `HalluGuard could not verify in ${report.file}: ${report.unverified.join(', ')}`
      );
    }

    for (const issue of report.hallucinations || []) {
      totalIssues++;
      const meets = isSeverityThresholdMet(issue.severity, thresholdSeverity);
      if (meets) violations++;

      // Findings below the threshold are logged, not posted: they would only
      // add noise to the review.
      if (!meets) {
        core.info(`${report.file}:${issue.line} [${issue.severity}] ${issue.token} (${issue.type})`);
        continue;
      }
      if (!pullRequest) continue;

      const lineOk = issue.line >= 1 && (diffLines.get(report.file)?.has(issue.line) ?? false);
      if (!lineOk) {
        offDiff.push(
          `- \`${report.file}\` line ${issue.line || '?'}: **${issue.severity}** ` +
            `\`${issue.token}\` — ${issue.explanation}`
        );
        continue;
      }

      try {
        await octokit.rest.pulls.createReviewComment({
          owner: context.repo.owner,
          repo: context.repo.repo,
          pull_number: pullRequest.number,
          commit_id: pullRequest.head.sha,
          path: report.file,
          line: issue.line,
          side: 'RIGHT',
          body: buildCommentBody(issue)
        });
      } catch (err: any) {
        core.warning(
          `Could not post comment on ${report.file}:${issue.line} - ${err.message}`
        );
        offDiff.push(`- \`${report.file}\` line ${issue.line}: \`${issue.token}\` — ${issue.explanation}`);
      }
    }
  }

  // Findings on lines that are not part of the diff cannot be inline
  // comments; gather them in a single PR comment instead of dropping them.
  if (pullRequest && offDiff.length > 0) {
    try {
      await octokit.rest.issues.createComment({
        owner: context.repo.owner,
        repo: context.repo.repo,
        issue_number: pullRequest.number,
        body: `### HalluGuard AI — findings outside the diff\n\n${offDiff.join('\n')}`
      });
    } catch (err: any) {
      core.warning(`Could not post the summary comment - ${err.message}`);
    }
  }

  if (violations > 0 && failOnHallucination) {
    core.setFailed(
      `HalluGuard: ${violations} finding(s) at or above ${thresholdSeverity} (${totalIssues} total).`
    );
  } else if (totalIssues > 0) {
    core.warning(`HalluGuard: ${totalIssues} finding(s), ${violations} at or above ${thresholdSeverity}.`);
  } else {
    core.info('HalluGuard: Clean. No hallucinations detected.');
  }
}
