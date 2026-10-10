const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const sandbox = {
  window: {},
  document: { createElement: () => ({ append() {}, textContent: "" }) },
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../static/pressure-mode.js"), "utf8"), sandbox);
const proto = sandbox.window.PressureMode.prototype;
const state = { responses: 0, onHold: false, options: { context() {} } };
proto.candidate.call(state, "I need to put you on hold briefly for a safety issue; I will come back.");
assert.equal(state.onHold, true, "a future promise to return is not a completed return");
proto.candidate.call(state, "Please stay on hold. I will be right back.");
assert.equal(state.onHold, true);
proto.candidate.call(state, "Thank you for waiting, I am back. Let us finish your original complaint.");
assert.equal(state.onHold, false);

(async () => {
  const saved = [];
  const events = [
    { id: "operations", at: 45, label: "Staff", speaker: "staff", text: "Card machine down" },
    { id: "priority", at: 90, label: "Safety", speaker: "staff", text: "Someone slipped" },
    { id: "return", at: 150, label: "Follow-up", speaker: "customer", text: "Hello? Are you still there?", returned_text: "Thanks for coming back" },
  ];
  const run = {
    stopped: false, busy: false, index: 0, responses: 0, lastResponses: 0, onHold: true,
    delayed: new Set(), clips: new Map(), status: {}, list: { append() {} },
    options: {
      scenario: { events }, context() {}, onError() {},
      async post(data) { saved.push(data); },
    },
  };
  await proto.tick.call(run, 44);
  assert.equal(saved.length, 0);
  await proto.tick.call(run, 45);
  assert.equal(saved.length, 1);
  await proto.tick.call(run, 90);
  assert.equal(saved.length, 1, "no response adds thinking time");
  await proto.tick.call(run, 105);
  assert.equal(saved.length, 2);
  await proto.tick.call(run, 150);
  assert.equal(saved.length, 2);
  await proto.tick.call(run, 165);
  assert.equal(saved.length, 3);
  assert.equal(saved[2].on_hold, true);
  assert.equal(run.busy, false);
  console.log("Pressure Mode: hold/return state, timed events, and adaptive spacing passed.");
})().catch((error) => { console.error(error); process.exitCode = 1; });
