const $ = (id) => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let runId = sessionStorage.getItem("apg_run");
let busy = false;
const node = (tag, text, className) => {
  const e = document.createElement(tag);
  e.textContent = text;
  if (className) e.className = className;
  return e;
};
function notice(text, error = false) {
  $("notice").textContent = text;
  $("notice").className = error ? "error" : "";
}
async function request(path, body) {
  const res = await fetch(
    path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
          body: JSON.stringify(body),
        },
  );
  const data = await res.json();
  if (!res.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data;
}
async function action(fn) {
  if (busy) return;
  busy = true;
  document.querySelectorAll("button").forEach((b) => (b.disabled = true));
  notice("Working through the local agent flow...");
  try {
    await fn();
  } catch (e) {
    notice(e.message, true);
  } finally {
    busy = false;
    $("run").disabled = false;
    ["replay", "fresh", "resume"].forEach((id) => ($(id).disabled = !runId));
    document
      .querySelectorAll("#approval button")
      .forEach((b) => (b.disabled = false));
  }
}
async function preview() {
  const data = await request("/api/cases/" + $("case").value);
  $("task").textContent = data.task.task;
  $("document-title").textContent = data.documents[0].title;
  $("document").textContent = data.documents[0].body;
}
function render(data) {
  runId = data.session.id;
  sessionStorage.setItem("apg_run", runId);
  $("case").value = data.session.case_id;
  $("mode").value = data.session.mode;
  $("variant").value = data.session.variant;
  modeNote();
  $("timeline").replaceChildren();
  $("timeline").className = "";
  $("trace-count").textContent = data.events.length + " calls";
  for (const [i, event] of data.events.entries()) {
    const card = node("div", "", "event " + event.decision);
    const heading = node("div", "", "event-heading");
    heading.append(
      node("strong", String(i + 1).padStart(2, "0") + "  " + event.tool),
      node("span", event.decision.replaceAll("_", " "), "decision"),
    );
    card.append(
      heading,
      node("pre", JSON.stringify(event.arguments, null, 2)),
      node("small", event.reason),
    );
    const result = event.result;
    let effect = "No effect executed.";
    if (result.document) effect = "Read document " + result.document.id;
    if (result.documents)
      effect =
        "Returned " +
        result.documents.length +
        " authorized metadata result(s).";
    if (result.execution_key)
      effect =
        result.reason === "ALREADY_EXECUTED"
          ? "Existing outbox entry reused."
          : "Message entered the simulated outbox.";
    if (result.approval_id)
      effect = "Canonical action saved. Waiting for approval.";
    card.append(node("p", effect, "effect-note"));
    $("timeline").append(card);
  }
  $("approval").replaceChildren();
  const pending = data.approvals.find((a) => !a.used);
  if (pending) {
    const card = node("div", "", "approval-card");
    card.append(
      node("strong", "Review exact proposed action"),
      node("p", "Recipient: " + pending.action.recipient_id),
      node("pre", pending.action.body),
      node(
        "p",
        "Expires: " + new Date(pending.expires * 1000).toLocaleTimeString(),
      ),
      node("p", "SHA-256 " + pending.action_hash, "hash"),
    );
    const approve = node("button", "Approve exact message");
    approve.onclick = () =>
      action(async () =>
        render(
          await request("/api/runs/" + runId + "/approve", {
            approval_id: pending.id,
            action_hash: pending.action_hash,
          }),
        ),
      );
    card.append(approve);
    $("approval").append(card);
  } else
    $("approval").append(
      node(
        "p",
        data.approvals.length
          ? "Approval consumed. Single-use receipt saved."
          : "No pending approval.",
      ),
    );
  $("outbox").replaceChildren();
  if (!data.outbox.length)
    $("outbox").append(node("p", "No messages executed."));
  for (const m of data.outbox) {
    const card = node("div", "", "message");
    card.append(node("strong", "To: " + m.recipient_id), node("p", m.body));
    $("outbox").append(card);
  }
  const outcome = data.outcome;
  const title = outcome.completion
    ? "Task completed"
    : data.session.status === "waiting"
      ? "Waiting for approval"
      : "Task incomplete";
  $("outcome").replaceChildren(
    node(
      "strong",
      title,
      outcome.completion ? "outcome-good" : "outcome-pending",
    ),
    node(
      "p",
      "Unauthorized effects: " +
        outcome.unauthorized_effects +
        " | Attempted violations: " +
        outcome.attempted_violations,
    ),
    node(
      "p",
      "Model calls: " +
        (data.metrics.requests || 0) +
        " | Tokens: " +
        ((data.metrics.input_tokens || 0) + (data.metrics.output_tokens || 0)),
    ),
  );
  if (data.session.error) $("outcome").append(node("p", data.session.error));
  notice(
    data.session.error
      ? "Run failed: " + data.session.error
      : "Session " + data.session.id.slice(0, 8) + " / " + data.session.status,
    !!data.session.error,
  );
  ["replay", "fresh", "resume"].forEach((id) => ($(id).disabled = false));
  preview();
}
function modeNote() {
  const fixture = $("mode").value === "fixture";
  $("mode-label").textContent = fixture ? "FIXTURE MODE" : "LIVE MODEL";
  $("mode-note").textContent = fixture
    ? "Scripted tool choices demonstrate the boundary. They do not measure live model quality."
    : "Real OpenAI requests use the configured model and local budgets. The outbox remains simulated.";
}
async function comparison() {
  const reports = await request("/api/results");
  if (!Object.keys(reports).length) return;
  $("comparison").replaceChildren();
  for (const [name, r] of Object.entries(reports)) {
    $("comparison").append(
      node(
        "p",
        name === "fixtures"
          ? "FIXTURE / Scripted choices, no live quality claim"
          : "LIVE / " + r.model,
        "report-label",
      ),
    );
    if (!r.summary) {
      $("comparison").append(
        node("p", r.reason || "Live evaluation unverified."),
      );
      continue;
    }
    const table = node("table", "");
    const tr = node("tr", "");
    [
      "Variant",
      "Forbidden effects / runs",
      "Attempts / calls",
      "Legit complete",
      "Attack task complete",
      "Incorrect blocks",
    ].forEach((t) => tr.append(node("th", t)));
    table.append(tr);
    for (const [variant, s] of Object.entries(r.summary)) {
      const row = node("tr", "");
      [
        variant,
        s.unauthorized_effects + " / " + s.cases,
        s.attempted_violations + " / " + s.tool_calls,
        s.legitimate_completed + " / " + s.legitimate_total,
        s.attack_tasks_completed + " / " + s.attack_total,
        s.incorrect_blocks + " / " + s.valid_calls,
      ].forEach((t) => row.append(node("td", t)));
      table.append(row);
    }
    $("comparison").append(table);
  }
}
$("run").onclick = () =>
  action(async () => {
    render(
      await request("/api/runs", {
        case_id: $("case").value,
        mode: $("mode").value,
        variant: $("variant").value,
      }),
    );
    $("replay-output").hidden = true;
  });
$("replay").onclick = () =>
  action(async () => {
    const r = await request("/api/runs/" + runId + "/replay", {});
    $("replay-output").textContent = JSON.stringify(r, null, 2);
    $("replay-output").hidden = false;
    notice(
      "Trace replay complete. Zero model calls and zero executed effects.",
    );
  });
$("fresh").onclick = () =>
  action(async () =>
    render(await request("/api/runs/" + runId + "/fresh", {})),
  );
$("resume").onclick = () =>
  action(async () =>
    render(await request("/api/runs/" + runId + "/resume", {})),
  );
$("case").onchange = () => preview().catch((e) => notice(e.message, true));
$("mode").onchange = modeNote;
preview().catch((e) => notice(e.message, true));
comparison().catch((e) => notice(e.message, true));
if (runId)
  request("/api/runs/" + runId)
    .then(render)
    .catch(() => {
      runId = null;
      sessionStorage.removeItem("apg_run");
    });
