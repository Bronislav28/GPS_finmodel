# GPS Finmodel v2 — Business Model Description

## 1. GPS Finmodel v2 — Purpose and operating principles
GPS Finmodel v2 is a monthly-first financial model for planning and evaluating an AI subsidiary (GPS). It translates product demand into compute demand, infrastructure strategy, costs, financial statements, funding requirements, and investment metrics.

Operating principles:
- Monthly rows are the calculation source of truth.
- Annual views are aggregated from monthly rows.
- Assumptions are declarative and centralized in YAML.
- HTML is an interactive reporting and scenario layer, not the permanent source of truth.

## 2. Source of truth and model architecture
- `assumptions.yaml` stores assumptions and declarative business logic.
- `gps_finmodel.py` reads YAML, runs all calculations, and generates report outputs.
- `output/gps_finmodel.html` is an Excel-like interface for review and scenario analysis.
- Scenario JSON export/import in HTML is temporary and does not automatically write back to YAML.

## 3. Forecast horizon and monthly-first calendar
The model starts at `model.forecast_start` and ends at `model.forecast_end`.

Calendar behavior:
- Model months are created exactly within that range.
- There is no artificial backfill of missing months (for example, if start is October 2026, January–September 2026 are not created).
- Annual reporting is calculated only as aggregation of calculated monthly rows.

## 4. Event logic: event_flag, event_ref, timing
Event logic controls when assumptions become active:
- `event_flag` defines a start point and active period duration.
- `event_ref` links one assumption to another event timeline.
- `timing` resolves effective timing (event start, event end, after event).

This logic is used for product development/revenue activation and datacenter construction phasing.

## 5. Product usage and token load
The model has two products:
- `Workplace.ai`
- `Contact_Center.ai`

Business demand is translated into token demand using product-specific drivers. Monthly and annual token loads are calculated and used as upstream drivers for compute and economics.

## 6. Compute model and GPU sizing
Compute layer converts token demand into required GPU capacity:
- Token load is mapped to model classes via `model_mix`.
- Effective throughput is calculated using harmonic weighting across model classes.
- Required GPU is derived from throughput, utilization, operating-time assumptions, and peak factor.

Conceptually:
`required_gpu ~ token_rate / (effective_throughput × utilization) × peak_buffer`.

## 7. Infrastructure scenarios and datacenter construction
Supported scenarios:
- `rent_gpu_only`
- `build_own_dc`
- `hybrid`

Scenario behavior:
- Rented vs owned GPU allocation depends on scenario.
- In `hybrid`, owned GPU availability starts after construction event timing.
- Construction event governs timing of own-datacenter activation.

## 8. CAPEX logic
CAPEX includes:
- GPU-related infrastructure CAPEX for owned capacity growth.
- Datacenter construction CAPEX (event-timed).
- Office CAPEX.
- Capitalized product development (intangible IP assets).

Construction CAPEX is recognized when construction event is active. Owned GPU CAPEX follows owned capacity increments.

## 9. Core team payroll and capitalization
Payroll is role-based and event-aware:
- Base salary driver: `salary_gross_monthly_rub_2026`.
- FTE dynamics: `fte_plan` with event timing.
- Salary indexation applies over time.
- Social contributions and bonus logic are included.

During product build windows, eligible core team costs are capitalized into intangible assets. Outside those windows, payroll remains in operating costs.

## 10. SG&A and office costs
SG&A includes non-delivery overhead (management, support functions, and related overhead).

Office economics include:
- Office rent and related costs (operating).
- Office CAPEX (separate investment block).

Both follow model timeline and indexation assumptions where configured.

## 11. Datacenter OPEX and GPU rental OPEX
Two cost patterns are modeled:
- Owned infrastructure: datacenter OPEX (e.g., power, maintenance, facility-related operating costs).
- Rented infrastructure: GPU rental OPEX.

Scenario design prevents double counting by applying the relevant cost mode according to rented/owned allocation.

## 12. Depreciation and amortization
D&A is split by asset type:
- Depreciation for tangible assets (GPU infrastructure, datacenter, office CAPEX).
- Amortization for capitalized intangible IP assets.

D&A feeds P&L and also enters pricing base logic unless assumptions specify otherwise.

## 13. Revenue model and target contribution margin
Revenue is not modeled as a fixed token price input.

Instead, revenue is computed from:
- Cost-based pricing base.
- Target contribution margin by scenario.
- Product/event timing for revenue start.

Pricing base includes COGS and D&A by default (unless YAML configuration overrides that behavior). Implied token price is an output metric.

## 14. P&L, cash flow and balance sheet
The engine produces integrated statements:
- P&L: revenue, cost layers, EBITDA/EBIT, interest, tax, net income.
- Cash flow: operating, investing, financing, and period cash bridge.
- Balance sheet: cash, assets, liabilities, and equity consistency.

Funding mechanics and D&A ensure cross-statement consistency and auditability.

## 15. Funding scenarios and custom funding mix
Funding scenarios:
- `equity_only`
- `revolver_only`
- `mix`

In HTML, custom funding mix allows user-defined equity/debt proportions for the mix logic.

Funding is calculated monthly with a minimum-cash concept, and debt service follows revolver rules (draw/repay based on cash needs and excess cash policy).

## 16. Investment metrics: NPV, IRR, payback, required investments
Investment analytics are computed from monthly cash flows:
- NPV
- IRR
- Payback
- Required investments/funding metrics

Payback output format is `YYYY-MM`; if not achieved, output is `Not reached`.

## 17. Annual aggregation policy
Annual tables are rollups of monthly calculations. There are no independent annual-only logic branches that override monthly mechanics.

## 18. HTML report and scenario workflow
`output/gps_finmodel.html` uses precomputed Python outputs as its base state.

Workflow:
- Select precomputed scenarios (e.g., infrastructure/funding/revenue modes).
- Review statement and analytics tables/charts.
- Keep baseline results reproducible from Python-generated outputs.

## 19. Editable assumptions, overrides and scenario export/import
HTML supports temporary user overrides for scenario analysis:
- Editable assumptions are browser-side overrides.
- `Apply Scenario` applies current override set to the report view.
- `Reset to Base` restores original Python-generated baseline/precomputed scenarios.
- Export/import JSON stores and reloads temporary override scenarios.

Important: no automatic write-back to `assumptions.yaml` occurs.

## 20. Visual analytics
Visual analytics present major KPI views for business review:
- Demand/token and compute capacity trends.
- Cost and margin dynamics.
- Funding/cash behavior.
- Scenario comparison summaries.

Charts are aligned to calculated monthly data and aggregated annual perspectives.

## 21. Audit and reconciliation outputs
V2 produces audit-oriented outputs for traceability:
- Validation report.
- Calendar/events outputs.
- Monthly demand/GPU, infrastructure, costs, financials, and funded layers.
- Annual report.
- Investment metrics.
- Scenario summary.
- Audit checks and reconciliation outputs.

These outputs support consistency checks across layer transitions.

## 22. Deprecated legacy structures
Deprecated structures note (must remain explicit):

The v2 model must not rely on:
- `years`
- `consumption_scenarios`
- `core_team_target_fte`
- legacy `salary_gross_monthly_rub` block
- `hiring_plan_monthly`
- `scaling_rules`
- `go_live_year` / `go_live_month`
- `construction_start_year`
- annual-only `construction_flag` logic
- `start-month`

## 23. Generated output files
Major generated outputs:
- `output/gps_finmodel_validation_report.csv`
- `output/gps_finmodel_calendar.csv`
- `output/gps_finmodel_events.csv`
- `output/gps_finmodel_monthly_demand_gpu.csv`
- `output/gps_finmodel_monthly_infrastructure.csv`
- `output/gps_finmodel_monthly_costs.csv`
- `output/gps_finmodel_monthly_financials.csv`
- `output/gps_finmodel_monthly_funded.csv`
- `output/gps_finmodel_investment_metrics.csv`
- `output/gps_finmodel_annual_report.csv`
- `output/gps_finmodel_scenario_summary.csv`
- `output/gps_finmodel_audit_checks.csv`
- `output/gps_finmodel_reconciliation.csv`
- `output/gps_finmodel.html`
