// Stands in for master-exporter.js in the app tests: prints what a run
// prints, then waits FAKE_SECONDS (for cancelling) and exits FAKE_EXIT.
const profile = process.argv[2] || "default";
console.log(`[MASTER] Environment: ${profile}`);
console.log(`[MASTER] Run key:     env-${profile}/2026-11-05_120000Z`);
console.log(`[MASTER] History dir: ${process.env.HISTORY_DIR}`);
console.log(`[MASTER] Leaked: ${process.env.AEM_AUTHOR_URL || "none"}`);
setTimeout(() => process.exit(Number(process.env.FAKE_EXIT || 0)), Number(process.env.FAKE_SECONDS || 0) * 1000);
