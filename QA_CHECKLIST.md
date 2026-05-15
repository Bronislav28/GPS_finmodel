# GPS Finmodel v2 — Final Regression QA Checklist

Issue reference: #163 (V2-24)

## A. Pre-checks
- [ ] Working tree is clean before running regression.
- [ ] Python environment is prepared (`pip install -r requirements.txt`).

## B. Baseline execution
- [ ] Execute: `python gps_finmodel.py`
- [ ] No runtime errors.

## C. Artifact integrity
- [ ] All expected output files are generated in `output/`.
- [ ] HTML report opens and renders key sections.
- [ ] CSV files are readable and non-empty.

## D. Business-level validation
- [ ] Scenario selectors are available in HTML (`revenue`, `infrastructure`, `funding`).
- [ ] Investment metrics table contains NPV/IRR/payback fields.
- [ ] Annual report is consistent with monthly aggregation expectations.

## E. Audit and reconciliation
- [ ] `gps_finmodel_validation_report.csv` reviewed.
- [ ] `gps_finmodel_audit_checks.csv` reviewed.
- [ ] `gps_finmodel_reconciliation.csv` reviewed.

## F. Non-regression assertion for V2-24
- [ ] No edits in `assumptions.yaml`.
- [ ] No edits to financial logic scripts.
- [ ] No intentional changes to generated outputs in this documentation-only update.

## G. QA sign-off record
- [ ] Reviewer:
- [ ] Date (YYYY-MM-DD):
- [ ] Result: Pass / Pass with notes / Fail
- [ ] Notes:
