# GPS Finmodel v2 — Release Validation Checklist

Issue reference: #163 (V2-24)

## 1) Scope guardrails (must pass before release)
- [ ] No changes in financial calculation logic in `gps_finmodel.py`.
- [ ] No changes in legacy calculation logic in `calc_token_load.py`.
- [ ] No changes in `assumptions.yaml` for this checklist-only task.
- [ ] No manual edits in generated files under `output/`.

## 2) Regression run
- [ ] Run model from clean working tree:
  - `python gps_finmodel.py`
- [ ] Confirm script exits without errors.

## 3) Required output artifacts exist
- [ ] `output/gps_finmodel.html`
- [ ] `output/gps_finmodel_results.csv`
- [ ] `output/gps_finmodel_validation_report.csv`
- [ ] `output/gps_finmodel_calendar.csv`
- [ ] `output/gps_finmodel_events.csv`
- [ ] `output/gps_finmodel_monthly_demand_gpu.csv`
- [ ] `output/gps_finmodel_monthly_infrastructure.csv`
- [ ] `output/gps_finmodel_monthly_costs.csv`
- [ ] `output/gps_finmodel_monthly_financials.csv`
- [ ] `output/gps_finmodel_monthly_funded.csv`
- [ ] `output/gps_finmodel_investment_metrics.csv`
- [ ] `output/gps_finmodel_annual_report.csv`
- [ ] `output/gps_finmodel_scenario_summary.csv`
- [ ] `output/gps_finmodel_audit_checks.csv`
- [ ] `output/gps_finmodel_reconciliation.csv`

## 4) Consistency checks
- [ ] Validation report has no blocking status.
- [ ] Reconciliation output indicates statement consistency.
- [ ] Key scenario summary rows are present for infrastructure/revenue/funding combinations.

## 5) Release documentation checks
- [ ] `README.md` references release and QA checklists.
- [ ] `business_model_description.md` references checklist usage in release workflow.

## 6) Release sign-off
- [ ] QA reviewer sign-off.
- [ ] Finance/model owner sign-off.
- [ ] Release note references issue #163.
