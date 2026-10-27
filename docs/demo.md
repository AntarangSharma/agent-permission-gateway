# Three-minute demo

Run `make setup && make demo`, then open http://127.0.0.1:8000.

**0:00 to 0:40.** Keep Fixture script and Gateway enforced selected. Choose A01, Redirection 01. Point out the legitimate task, two required launch facts, and the untrusted document note asking for mallory. Trusted session permissions allow alex only. Say explicitly that this is a scripted fixture, not a live model result.

**0:40 to 1:20.** Click Run case. Follow search_documents, read_document, the mallory proposal, and RECIPIENT_FORBIDDEN in the trace. There is no outbox effect. A second proposal to alex is saved for approval. Its recipient, body, hash, and expiry are visible.

**1:20 to 2:00.** Reload the page, or stop and restart `make demo` while waiting. The graph and action remain in SQLite. Click Approve exact message. One message enters the outbox and the task completes because both required facts are present. Click Resume saved run again and show that the outbox stays at one entry.

**2:00 to 2:30.** Click Recheck trace. It reports zero model calls and zero effects executed. It checks prior requests, including the rejected recipient, without creating a new behavioral sample. Click Fresh rerun to create a clean session with no outbox entries and a new pending action.

**2:30 to 3:00.** Select Prompt only and run A01 again. The scripted redirection now creates an unauthorized simulated message. Show the separate security and task-completion metrics, then the saved comparison. For live behavior, configure the key locally, select Live OpenAI model, and explain that the model may resist the attack. Do not present fixture success as evidence of model quality.

There is no real email or external recipient. Resetting a case never deletes a prior session; it creates an isolated copy. Evaluation uses disposable databases for every variant.
