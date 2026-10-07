# Historical pilot: preserve exact draft bytes across platforms

The first companion-cap source commit `237dba8a299f0a9de9f875640142858939bf0f92`
passed local installed tests and both Ubuntu jobs, but the two Windows jobs in
[adaptive-development run 37643464796](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37643464796)
failed. Validation and CodeQL passed. This failure was inspected, not hidden or
converted into a green qualification claim.

The Windows checkout's CRLF-converted draft had SHA-256
`80ced548a702bd975944b9c6330caa9ce039ee02b7a08515e2c327f243d44c56`,
not the fixed LF draft SHA-256
`d9347eeca568f6b8fc98a75645ffe484e27df2ce3cd84415b97f8b554d12e497`.
The helper correctly rejected the alternate bytes before budget admission.
Local Windows had retained LF, explaining why local tests passed.

The scoped fix adds `-text` to Git attributes for only
`development/adaptive_replay/historical-episodes-draft.json`, consistent with
the existing exact-byte receipt/protocol rules. It preserves the existing
committed plan blob and its fixed SHA across platforms. No plan content,
episode, cut, cap, hash validator, dependency or readiness gate is changed.
The already-existing tests check this real draft hash; no fake expected hash or
automatic newline normalization was substituted in the budget code.

No production ledger, API request or historical replay is involved in this fix.
The failed run remains retained; successor source commits must pass the same
four-job Windows/Linux and Python 3.11/3.14 matrix before handoff.
