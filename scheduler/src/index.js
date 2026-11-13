// Clock for LMS Guardian: presses "run" on the workflow every 2 minutes, on time.
// GitHub's own `schedule` trigger drifts and drops runs; API dispatches start within seconds.

const WORKFLOW_FILE = "lms-guardian.yml";

export default {
  async scheduled(event, env) {
    const url = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`;
    const response = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "lms-guardian-scheduler",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: env.GITHUB_REF || "main" }),
      redirect: "manual", // never replay the Authorization header at another host
    });
    if (response.status !== 204) {
      throw new Error(`dispatch failed: ${response.status} ${await response.text()}`);
    }
    console.log(`dispatched ${WORKFLOW_FILE}`);
  },
};
