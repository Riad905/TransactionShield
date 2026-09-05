# Project specification

## Purpose

TransactionShield will be a portfolio-scale transaction risk decisioning platform for a **hypothetical mobile-money provider**. Its primary users are fraud/risk analysts and payment-operations staff. It is not an actual bank system, and results from synthetic data must not be presented as evidence of performance on a real financial institution.

## Decision and prediction contract

For each transaction, the eventual model will estimate a fraud-risk score: the model's estimate, under its training data and assumptions, that the transaction belongs to the dataset's simulated fraud class. A score is not proof of fraud and is not automatically a business action.

A separately configured decision threshold will convert the score into an operational route. The MVP will support two routes:

1. allow normal processing; or
2. send the transaction for review or protective intervention.

The threshold and action policy remain separate from model training so they can be evaluated against review capacity and explicit trade-offs. An automatic decline is outside the initial MVP because the synthetic data cannot justify that consequence.

## Error consequences

- **False positive:** a legitimate transaction is routed as suspicious, causing customer friction, delay, avoidable analyst workload, and potentially reduced trust.
- **False negative:** a fraudulent transaction is treated as legitimate, potentially allowing loss, customer harm, investigation work, and regulatory or reputational consequences.

No monetary costs are assigned at this stage. Any later cost-sensitive analysis must label its cost inputs as scenarios unless defensible real operating data becomes available.

## Evaluation principles

Accuracy is inappropriate as a headline metric because fraud is the minority class and a model can achieve high accuracy by mostly predicting legitimate transactions. Evaluation will eventually include:

- **area under the precision-recall curve (PR-AUC)** as the primary threshold-independent ranking metric;
- **precision and recall at the chosen operating point**, including recall at a stated minimum precision or alert-volume limit;
- **confusion-matrix counts** so the operational scale of both error types remains visible;
- **probability calibration**, using reliability plots and a proper score such as Brier score, if outputs are described as risk probabilities;
- **ROC-AUC** as a secondary comparison metric, not the sole result;
- **amount-weighted detection summaries** only after the meaning of the synthetic amount unit is verified, reported alongside count-based metrics; and
- **inference latency and throughput** once an API exists.

All model selection and threshold tuning must use time-aware validation. The final temporal test window must remain untouched until evaluation.

## MVP scope

Authoritative artifact acquisition and pre-development auditing were completed in Stage 2. The remaining MVP capabilities below are planned, not yet implemented:

- Load typed transactions into PostgreSQL with auditable data-quality checks.
- Use SQL for profiling and analyst-oriented transaction summaries.
- Build point-in-time-correct, explainable features from information available at decision time.
- Compare a simple baseline with one justified tree-based model using temporal train/validation/test windows.
- Calibrate scores if necessary and select a threshold using declared operational scenarios.
- Persist a versioned model, feature contract, evaluation report, and provenance metadata.
- Serve single-transaction scoring through a tested FastAPI endpoint.
- Provide a small analyst dashboard for scores, reason codes or feature contributions, and aggregate monitoring views.
- Add focused unit/integration tests, containerised local execution, and a lightweight CI workflow.

## Later extensions

- Graph features or a graph model using initiator-recipient relationships.
- Streaming ingestion and event-time processing.
- Workflow orchestration for scheduled retraining or batch scoring.
- Drift monitoring, a model registry, shadow deployment, or other advanced MLOps.
- More realistic cost/capacity optimisation if defensible operational inputs become available.
- Robustness evaluation on a second dataset such as PaySim.
- Authentication, role-based access, case management, and human feedback loops.
- Cloud deployment and infrastructure as code.
- Carefully scoped GenAI assistance only if it solves a real analyst workflow problem.

## Current implementation boundary

Implemented through Stage 2: repository foundation, project documentation, a paper-defined MoMTSim dataset-version-1 column contract, CSV header/row-shape validation, lazy string-row iteration, authoritative artifact acquisition, a reproducible streaming integrity/quality audit, a verified data dictionary, leakage review, temporal/entity feasibility analysis, and focused unit tests.

Not implemented now: data cleaning, a typed production ingestion pipeline, database design or ingestion, production feature engineering, modelling, threshold selection, model persistence, API, dashboard, Docker, CI, orchestration, event streaming, or cloud resources.
