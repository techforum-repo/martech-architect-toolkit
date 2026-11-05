const assert = require("node:assert/strict");
const test = require("node:test");

const { Jobs } = require("../src/jobs");

test("a cancel that arrives after the export finished leaves its result alone", () => {
  const jobs = new Jobs({ projectRoot: __dirname, historyRoot: __dirname });
  const job = { id: "1", profile: "prod", status: "cancelled", lines: [], runKey: null, finishedAt: null };
  jobs.finish(job, 0);
  assert.equal(job.status, "complete");
  assert.ok(job.lines.some(line => line.includes("already finished")));

  const stopped = { id: "2", profile: "prod", status: "cancelled", lines: [], runKey: null, finishedAt: null };
  jobs.finish(stopped, null);  // killed by the cancel
  assert.equal(stopped.status, "cancelled");
});
