// Export runs started from the app: each is master-exporter.js <profile> in a
// child process, with its output kept for the page to show as it comes.
//
// The child gets this machine's own environment plus HISTORY_DIR, never the
// values of another settings file: settings that were already set win over
// a file's (Node's rule), so the app keeps them out of its own environment.
// One run at a time per settings file.

const path = require("node:path");
const { spawn } = require("node:child_process");

const store = require("./store");

const MAX_LINES = 5000;
const KEEP_FINISHED = 20;

class Jobs {
  constructor({ projectRoot, historyRoot, script = path.join(projectRoot, "src", "master-exporter.js"), env = process.env }) {
    this.projectRoot = projectRoot;
    this.historyRoot = historyRoot;
    this.script = script;
    this.env = env;
    this.jobs = new Map();
    this.next = 1;
  }

  list() {
    return [...this.jobs.values()].map(job => this.view(job)).reverse();
  }

  get(id) {
    return this.jobs.get(String(id)) || null;
  }

  running(profile) {
    return [...this.jobs.values()].find(job => job.profile === profile && job.status === "running") || null;
  }

  view(job, from = 0) {
    const { child, lines, ...rest } = job;
    return { ...rest, lineCount: lines.length, lines: lines.slice(from) };
  }

  start(profile) {
    if (this.running(profile)) {
      const error = new Error(`An export with ${profile} is already running`);
      error.status = 409;
      throw error;
    }
    const id = String(this.next++);
    const args = profile === "default" ? [this.script] : [this.script, profile];
    const child = spawn(process.execPath, args, {
      cwd: this.projectRoot,
      env: { ...this.env, HISTORY_DIR: this.historyRoot, COMPARE_UI_NO_BROWSER: "1" },
      // Its own process group, so Cancel stops the steps it starts too.
      detached: process.platform !== "win32",
      windowsHide: true
    });
    const job = { id, profile, status: "running", exitCode: null, runKey: null,
                  startedAt: new Date().toISOString(), finishedAt: null, lines: [], child };
    this.jobs.set(id, job);

    const take = stream => {
      let partial = "";
      stream.setEncoding("utf8");
      stream.on("data", chunk => {
        const parts = (partial + chunk).split(/\r?\n/);
        partial = parts.pop();
        for (const line of parts) this.line(job, line);
      });
      stream.on("end", () => partial && this.line(job, partial));
    };
    take(child.stdout);
    take(child.stderr);
    child.on("error", error => this.line(job, `[APP] Couldn't start the export: ${error.message}`));
    child.on("close", code => this.finish(job, code));
    this.prune();
    return job;
  }

  line(job, text) {
    const key = text.match(/^\[MASTER\] Run key:\s+(\S+\/\S+)/);
    if (key) job.runKey = key[1];
    job.lines.push(text);
    if (job.lines.length > MAX_LINES) job.lines.splice(0, job.lines.length - MAX_LINES);
  }

  finish(job, code) {
    job.exitCode = code;
    job.finishedAt = new Date().toISOString();
    if (job.status === "cancelled" && (code === 0 || code === 2)) {
      // Cancel came after the export had finished by itself: it stands.
      job.status = code === 0 ? "complete" : "warnings";
      this.line(job, "[APP] The export had already finished; nothing was cancelled.");
    } else if (job.status === "cancelled") {
      this.markRun(job, { status: "failed", error: "Cancelled in the app" });
    } else {
      job.status = code === 0 ? "complete" : code === 2 ? "warnings" : "failed";
    }
    delete job.child;
  }

  cancel(id) {
    const job = this.get(id);
    if (!job || job.status !== "running") return false;
    job.status = "cancelled";
    this.line(job, "[APP] Cancelled.");
    try {
      if (process.platform === "win32") {
        spawn("taskkill", ["/pid", String(job.child.pid), "/T", "/F"], { windowsHide: true });
      } else {
        process.kill(-job.child.pid, "SIGTERM");
      }
    } catch {
      // already finished
    }
    return true;
  }

  // A cancelled run's folder still says "running": record what happened.
  markRun(job, changes) {
    if (!job.runKey) return;
    const [envId, runId] = job.runKey.split("/");
    const dir = path.join(store.environmentsDir(this.historyRoot), envId, runId);
    try {
      store.updateRun(dir, { ...changes, finishedAt: new Date().toISOString() });
    } catch {
      // the run folder wasn't created yet
    }
  }

  prune() {
    const finished = [...this.jobs.values()].filter(job => job.status !== "running");
    for (const job of finished.slice(0, Math.max(0, finished.length - KEEP_FINISHED))) this.jobs.delete(job.id);
  }
}

module.exports = { Jobs };
