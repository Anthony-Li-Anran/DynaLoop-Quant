# Reference implementation review

Reviewed 2026-11-13. These are implementation references, not claims that their reported results reproduce on our data. No third-party source code has been copied into the application in this review.

| Project and inspected source | Relevant mechanism | DynaLoop decision |
|---|---|---|
| [AlphaGen linear factor pool](https://github.com/ICT-FinD-Lab/alphagen/blob/master/alphagen/models/linear_alpha_pool.py) | Evaluates individual and mutual IC, optimizes pool weights and records additions/removals. The objective evaluates the ensemble. | Add a fixed, simple factor-pool baseline before training more complex candidate generators. Measure candidate contribution to the pool as well as standalone scores. Our current single-candidate temporal experiment does not reproduce this method. |
| [AlphaForge combination](https://github.com/DulyHao/AlphaForge/blob/master/combine_AFF.py) | Loads a mined factor zoo, calculates daily cross-sectional metrics, and selects using historical metrics cut off by a 21-day shift. | Separate formula discovery from rolling selection. Implement label maturity from actual timestamps and horizon rather than copying the literal shift. Its NaN-to-zero metric handling is unsuitable for our coverage contract. |
| [Qlib rolling workflow](https://github.com/microsoft/qlib/blob/main/qlib/contrib/rolling/base.py) | Creates rolling tasks, trains them and collects recorded predictions. Explicitly distinguishes offline rolling evaluation from online serving. | Keep replay experiments separate from a persistent research service. Preserve run configuration, predictions and maturity events. Do not claim automatic operation based only on a historical loop. |

The immediate experiment remains the pre-specified fixed momentum diagnostic. After the data contract is verified, the next comparison is fixed factors and a simple rolling pool under identical membership, labels and evaluation dates. Candidate mining and replay must demonstrate incremental value over those controls.

Direct reuse requires inspecting the relevant license and dependency compatibility, pinning a version and reproducing its data/label contract. Repository popularity is not evidence of effectiveness. In particular, a published mining pipeline does not establish that our historical replay improves adaptation.

## Research UI integration

The CSI 300 view follows [Alphalens' information tear sheet](https://github.com/quantopian/alphalens/blob/master/alphalens/tears.py) in pairing a period-level IC table with time-indexed evidence. [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/) provides the reference for associating metrics, parameters and provenance with a run. The research catalog reads the versioned `panel_discovery.json` produced by the panel experiment, with decision dates, matured-label cutoffs, coverage, both controls and the archive fingerprint.

The Factor research page reads actual `factor_library.json`, `summary.json` and `manifest.json` artifacts through `/api/research/runs`. Configure `DYNALOOP_RESEARCH_DIRECTORY` to a directory containing run subdirectories. The default is the application's state directory plus `research`; development artifacts can be inspected by explicitly pointing it at `experiments/factor_stream`.

The page currently exposes formula search, selected-decision metrics, post-selection first-six/next-six/all-period baseline tables and source fingerprints. All imported legacy libraries remain exploratory. Forward-evidence charts, lifecycle events and ongoing-run controls still need integration before the frontend requirement is complete.

Browser verification used the actual v4 artifacts with an isolated state directory. Switching runs and searching formulas exposed the expected 29-factor library and the recorded post-selection scores. API integration, catalog tests and three frontend tests passed; the frontend production build passed. Windows sandbox socket initialization blocked the API test client, so the isolated integration test was run outside the sandbox.
