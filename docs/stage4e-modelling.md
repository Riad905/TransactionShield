# Stage 4E: chronological fraud modelling

Finalisation adds only descriptive fixed-budget ranking to the frozen experiments.
See [ranking, repeat hashes and current CI evidence](portfolio-finalisation.md).
The results and test counts below record the original Stage 4E run; final local
verification is 209 passed plus five PostgreSQL skips (214 collected), with 25
Python files compiled. No model or feature selection was revised.

## Scope and input gate

The September 11 request explicitly expands Stage 4E to modelling and evaluation.
Earlier documents used that name for final feature materialisation. This work
generates the approved features in memory for estimators; it does not introduce
a second feature definition or a new canonical file format.

Full-data PostgreSQL acceptance remains **NOT RUN**. Five small-fixture database
integration tests were subsequently verified in CI; no local server was installed.
The experiment therefore uses the independently verified local source and Stage
4C engine, not an unverified database export. A fresh pre-modelling replay passed
in 95.157 seconds: 1,720,181 source rows, 569,328 transfers, exact frozen splits,
zero chronological regressions and both approved feature hashes. The modelling
CLI repeats those source/feature gates before any fitting.

All valid transaction types enter history. Only TRANSFER examples reach the
models. Training is steps 0-95 (375,732 examples), validation 96-119 (94,503),
and test 120-143 (99,093). History is continuous; no current-step activity or
historical fraud labels enter features. Identifiers, source row and absolute
step are excluded from predictors. Labels are separate arrays and test labels
are not used for preprocessing, selection or explanation.

## Estimator representation

Core uses exactly the nine fields in the [feature contract](stage4c-feature-engine.md).
Enhanced adds only `initiator_balance_before` and `recipient_balance_before`.
The source and cumulative history remain exact Decimal values, and means retain
Stage 4C's explicit 28-digit HALF_EVEN policy. Exact numeric feature hashes are
checked against the approved Stage 4C results.

Only at the estimator boundary are those completed features converted to NumPy
float64. This representation is lossy, as ordinary sklearn estimators require
floating-point inputs; it does not replace the canonical Decimal values or
PostgreSQL NUMERIC contract. Overflow and unexpected nulls fail the input gate.
Missing mean/max become NaN until model-specific handling. No input matrices or
row-level predictions are persisted. The 569,328 by 11 matrix occupies 50,100,864
bytes before split copies and training workspace.

## Five fixed experiments

1. Training-prevalence reference (`DummyClassifier(strategy='prior')`). Its
   scores are constant; at 0.5 it is the majority/always-legitimate baseline.
2. Core Logistic Regression.
3. Core histogram gradient boosting.
4. Enhanced Logistic Regression.
5. Enhanced histogram gradient boosting.

Logistic Regression uses training-median imputation, training StandardScaler,
L2 regularisation with C=1, lbfgs and at most 1,000 iterations. Convergence warnings
fail the experiment before test evaluation. Coefficients describe standardised
imputed inputs, not raw-currency effects.

Boosting uses HistGradientBoostingClassifier: 100 iterations, learning rate 0.1,
15 leaves, minimum leaf size 50, L2=1, native missing-value handling and **no
early stopping/random internal validation split**. Its binning is fitted only
on training. It was chosen because sklearn is already required for baselines;
XGBoost would add another compiled dependency without a demonstrated need.
No hyperparameter search was performed. Seed=904; numerical thread pools=1.

No class weighting is applied. The transfer population has moderate imbalance
(approximately 31% fraud), and threshold choice is handled explicitly. Neither
class weighting nor a default threshold is assumed to express real fraud costs.

## Selection and final evaluation

Each threshold maximises **validation F1**, with the highest threshold breaking
ties. This is a transparent demonstration policy, not a bank's cost-optimal
rule: no intervention costs or alert capacity have been supplied. F1 treats
precision and recall symmetrically and ignores true negatives. Actual operations
would require a separately approved cost/capacity policy.

Validation Average Precision chooses the reported model; it does not choose
between models after seeing test results. The CLI writes `selection.json` before
test-label evaluation. All five predeclared experiments are then evaluated on
test once, without refitting, threshold adjustment or feature changes. Metrics
include ROC-AUC, Average Precision (not trapezoidal PR area), precision, recall,
F1, [[TN, FP], [FN, TP]], prevalence, alert rate and Brier score. Both selected
threshold and 0.5 results are retained. Scores are not claimed to be calibrated.

## Explanation and errors

Logistic coefficients and boosting permutation importance use no test data for
selection. Permutation importance measures validation AP decrease on a seeded
sample of up to 10,000 examples, with three repeats. Correlated features can
share or mask importance. Association is **not causation**, and no fairness claim
is possible from absent demographic attributes. SHAP is not added.

After selection, test-only descriptive error analysis shows three examples per
category (false positives, false negatives, high-scoring correct fraud, and
high-confidence errors). It reports only score, label, amount and prior outgoing
count, never account IDs or transaction identity. Amount-slice boundaries are
training quartiles, frozen before evaluating test. Error/slice findings do not
feed back into model or threshold selection.

## Reproduction

Use Python 3.12.8 and the pinned modelling extra (sklearn 1.8.0, NumPy 2.3.5,
SciPy 1.17.0, joblib 1.5.3, threadpoolctl 3.6.0):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,postgres,modelling]"
$env:LOKY_MAX_CPU_COUNT = "1"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m transactionshield.modelling --source data/raw/synthetic_mobile_money_transaction_dataset.csv --output artifacts/stage4e-reproduction
```

Use a new output directory; existing runs are refused. This run used a project
venv with access to existing host scientific packages at the pinned versions;
the fresh-venv commands above do not depend on those host packages. Psycopg is
optional for modelling and does not provision PostgreSQL.

Outputs are lightweight `selection.json`, `metrics.json`, and `runtime.json`.
Only a completed `metrics.json` represents a finished experiment; a lone selection
file is not success. No fitted model pickle or model-serving interface is saved.
Reproduction refits the fixed experiment; it is not a new tuning opportunity on
the disclosed test set. Actual estimators repeat deterministically on controlled
fixtures; cross-platform bitwise equality is not promised.

## Recorded experiment: 2026-09-11

Exact aggregate metrics, model parameters and input/code fingerprints are in
[`stage4e-results.json`](stage4e-results.json). The README gives the compact
comparison. Validation AP selected Enhanced boosting (0.357820 vs Core boosting
0.357518). Test AP was 0.352016 vs 0.353340 respectively: a decrease of 0.001323,
not evidence that balance access is worth adding. Enhanced Logistic Regression
also decreased test AP (0.341884 vs 0.342839). No statistical significance claim
is made from this single temporal holdout.

All selected thresholds were frozen from validation:

| Experiment | Threshold |
|---|---:|
| Prevalence reference | 0.3125658714189901 |
| Core Logistic Regression | 0.1277335054908508 |
| Core boosting | 0.20209035681678023 |
| Enhanced Logistic Regression | 0.1401145760760758 |
| Enhanced boosting | 0.18061394763175914 |

Selected Enhanced boosting produces [[4,890, 65,099], [15, 29,089]] on test.
Its 95.05% alert rate makes the high recall operationally misleading. At the
predeclared 0.5 reference it produces [[69,962, 27], [28,227, 877]]: approximately
97.01% precision at only 3.01% recall. Neither operating point establishes a
deployable policy. The reported model was **not** changed to Core after
seeing its slightly higher test AP; the declared winner remains validation-selected.

Validation permutation AP drops for Enhanced boosting were largest for prior
outgoing maximum (0.02370 +/- 0.00485 across three permutations) and current
amount (0.00711 +/- 0.00251). Core's prior maximum drop was 0.04813 +/- 0.00396.
Some recipient/balance importances were negative, so those cannot be presented
as reliable positive contributors. Core Logistic Regression's largest absolute
standardised coefficients were outgoing count (-1.186), amount (-0.786), distinct
recipients (+0.656) and outgoing total (+0.567). Collinearity limits interpretation.

Representative errors (synthetic values, no identifiers) included a legitimate
transfer of 45,949.05 scored 0.9667 with 55 prior outgoing transactions; missed
fraud of 474,703.82 scored 0.0200 with 1,171 prior outgoing transactions; and
correct fraud around 16,959 scored 0.9986. High-confidence wrong predictions
exist in both directions. These examples illustrate errors, not causal rules.

Training amount quartiles were 17,133.51, 19,718.38 and 27,190.74. Test slices
contained 24,691-24,833 examples each. All 15 false negatives occurred in the
highest amount band; its recall was 99.76%, versus 100% in the lower bands.
The lower bands nevertheless flagged over 99.7% of transactions. Differences in
prevalence (24.66% in the highest band vs roughly 31% elsewhere) matter when
interpreting precision and AP. No fairness conclusions are drawn.

The first run took 96.761 seconds for source/features and 110.779 seconds overall,
with a 487,694,336-byte Windows peak process working set (465.1 MiB). Final review
found a reporting-only bug: Windows newline translation meant its runtime report
hashed normalised text rather than actual output bytes. Explicit LF report writing
and a regression test corrected that issue; no modelling decision changed.

An identical full replay then took 103.519 seconds for source/features and
118.692 seconds overall, with peak working set 433,328,128 bytes (413.3 MiB).
All input gates, thresholds, validation/test metrics, explanations and error
summaries matched the first run exactly. The repeat was a reproducibility audit,
not another tuning round on test labels. Implementation identity changed solely
for report writing; cross-platform bitwise reproducibility is not promised.

The verified run's actual metrics-file SHA-256 is
`fd8e19999289ddf6c4aac26d705fc5aac76b70282d0e8e2589289f00b3c21df9`.
Its files are under ignored `artifacts/stage4e-verified/`; the original run remains
preserved under `artifacts/stage4e-first/`, with its incorrect file-checksum field
superseded. The tracked aggregate JSON omits representative rows, so its byte hash
differs. Memory includes history, arrays and estimators; timings are local
observations, not controlled database or production throughput benchmarks.

Final verification: 203 tests collected, 198 passed, five real-PostgreSQL tests
explicitly skipped. All 24 Python files compiled and whitespace checks passed.

## Limits

The data are synthetic and span only six days. Strong held-out results can reflect
simulator rules, not generalisation to real fraud, drift or seasonality. Enhanced
pre-balances still require an unproven synchronous deployment capability.
No financial-loss reduction, real-time prevention, production reliability or
production deployment is claimed. PostgreSQL numeric round trips are verified
on CI fixtures; the full-data database load, SQL plans, storage size and database
performance remain unverified.

References: [sklearn histogram boosting](https://scikit-learn.org/1.8/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html),
[precision-recall thresholds](https://scikit-learn.org/1.8/modules/generated/sklearn.metrics.precision_recall_curve.html),
[permutation importance](https://scikit-learn.org/1.8/modules/generated/sklearn.inspection.permutation_importance.html).
