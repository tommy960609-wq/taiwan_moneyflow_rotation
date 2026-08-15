# Taiwan Moneyflow Rotation — Hourly Continuation

Work only inside `C:\Workspace_CN\taiwan_moneyflow_rotation`.

At every wake-up:

1. Read `loop/PROJECT_STATE.md`, `loop/TASK_QUEUE.md`, `loop/BEHAVIOR_RULES.md`, `loop/ACCEPTANCE_MATRIX.md`, and the latest relevant acceptance report/evidence. Treat on-disk artifacts and fresh test output as truth.
2. Resume the first genuinely unfinished item from the recorded checkpoint. Do not redo milestones or gates already independently verified as passed.
3. Work on one bounded, verifiable segment at a time. Follow the existing maker/verifier separation and milestone gates. Do not claim completion from self-review alone.
4. Run the narrow tests first, then the appropriate full suite. Preserve honest `Null`/unavailable states; never invent data, loosen assertions, hide failures, or replace real evidence with mocks.
5. After each completed segment, update `loop/PROJECT_STATE.md` and `loop/CHANGELOG.md` with the exact result, remaining work, test count, evidence paths, and the next deterministic action. Keep checkpoint writes small and recoverable.
6. If usage quota, authentication, network, provider, or tool access is unavailable, stop that iteration safely. Do not fabricate progress, do not corrupt or advance the checkpoint, and let the next hourly wake-up retry from the last valid checkpoint. If the same non-quota blocker requires a user decision, record it once as `BLOCKED_REQUIRES_USER` and make no speculative change on later wakes.
7. Never commit, push, delete material data, modify files outside this project, change unrelated Antigravity/night-run behavior, or weaken deterministic risk controls without explicit user approval.
8. When the acceptance matrix shows the whole project is independently verified complete, make no further changes; report `PROJECT COMPLETE — LOOP CAN BE CANCELLED` in one line.

Immediate priority: verify the current M5a re-submission from fresh evidence. If and only if that gate passes, continue with M5b backtest core, including event study, P0-06 limit-up lockout handling, and momentum-baseline comparison, as already recorded in project state.
