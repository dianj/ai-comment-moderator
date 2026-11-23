# Calibration: moderator.outcome

Model `gemma-4-26b-a4b-it`, prompt `76e9344633ab`, 101 labelled cases, fitted temperature **T = 1.0** (2026-11-23).

| | accuracy | ECE | Brier |
|---|---|---|---|
| raw (T = 1) | 1.000 | 0.006 | 0.000 |
| calibrated, 5-fold cross-validated | 1.000 | 0.006 | 0.000 |

Risk-coverage (calibrated): the share of cases at or above each threshold and their accuracy.

| threshold | coverage | accuracy | n |
|---|---|---|---|
| 0.5 | 1.00 | 1.000 | 101 |
| 0.6 | 1.00 | 1.000 | 101 |
| 0.7 | 0.99 | 1.000 | 100 |
| 0.8 | 0.99 | 1.000 | 100 |
| 0.85 | 0.99 | 1.000 | 100 |
| 0.9 | 0.98 | 1.000 | 99 |
| 0.95 | 0.97 | 1.000 | 98 |
| 0.99 | 0.93 | 1.000 | 94 |

![Reliability diagram](moderator.outcome.svg)
