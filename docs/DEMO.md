# Three-minute demonstration

Start with `bash scripts/dev.sh` and open http://localhost:5173. Default operation requires no credentials.

1. **Explore.** Reset the scenario to seed 42. Aircraft move immediately. Select UAL214, inspect its units and path, then try Top and the accessible traffic table. Pause to inspect a fixed state.
2. **Disrupt.** Open Inject a disruption, close runway 28R, then select Propose movement plan → Verify. Expand the runway, wake, surface and motion checks. Commit only if the result passes. Play to observe the changed trajectories.
3. **Test uncertainty.** Inject Delay observations. Propose and verify again: the result is unresolved and commitment is unavailable. Reset to restore the baseline observations.
4. **Experiment.** Open Learning and keep Offline fixture selected. Run bounded experiment. Inspect the parent, candidate observation order, validation results, cost and rejection reasons. A rejection is an expected valid outcome, not a failed demo. Live Crusoe results from the implementation run are documented separately; fixtures do not claim new inference.
5. **Compare and reproduce.** Compare a candidate with FCFS from the same checkpoint. Play the shared trajectory replay. Close it, scrub Checkpoint replay, return to current state, and download Export evidence bundle. Reload to confirm that experiment records persist.

For the recorded live result and a reproducible final evaluator, see [live-program reevaluation](evaluation/live-program-reevaluation.md). For independent seeded fixture evaluation, run `PYTHONPATH=backend .venv/bin/python scripts/evaluate.py`.

All traffic and control actions remain in the research simulator. The supported configuration uses conservative shared runway dependencies and a simplified surface network; it is not an operational SFO procedure implementation.
