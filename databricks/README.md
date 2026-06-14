# Phase 3 — Databricks trader dashboard

Surfaces the BESS data in S3 (`prices/`, `schedules/`, `telemetry/`, `state/`) as a
**Lakeview dashboard** for a trader, via Unity Catalog Delta tables.

```
S3 (s3://bess-data-945767338051)
   │  Auto Loader (incremental)
   ▼
Unity Catalog  main.bess.{prices, schedules, telemetry, state}
   │  gold views (v_latest, v_pnl_daily, v_price_dispatch, v_telemetry, v_violations_daily, v_state)
   ▼
Lakeview dashboard  bess_trader.lvdash.json
```

Files:
- `01_ingest_and_model.py` — Databricks notebook: Auto Loader S3 → Delta + the gold views.
- `bess_trader.lvdash.json` — the Lakeview dashboard.

---

## 1. Prerequisite — give the workspace read access to the bucket (Unity Catalog)

The data lives in **your** S3 bucket; Unity Catalog needs an external location over it.
This is a one-time setup and requires an AWS IAM role Databricks can assume.

1. **Create the IAM role** Databricks will use (trust the Databricks UC principal +
   `sts:AssumeRole`; grant `s3:GetObject`, `s3:ListBucket`, and
   `s3:PutObject`/`DeleteObject` on `arn:aws:s3:::bess-data-945767338051[/*]`).
   Databricks documents the exact trust policy under *Catalog → External Data →
   Credentials → Create credential*.

2. **Create the storage credential + external location** (SQL, run in a notebook or
   Databricks SQL):

   ```sql
   CREATE STORAGE CREDENTIAL IF NOT EXISTS bess_s3
     WITH IAM ROLE 'arn:aws:iam::945767338051:role/<your-databricks-uc-role>';

   CREATE EXTERNAL LOCATION IF NOT EXISTS bess_data
     URL 's3://bess-data-945767338051/'
     WITH (STORAGE CREDENTIAL bess_s3);

   GRANT READ FILES, WRITE FILES ON EXTERNAL LOCATION bess_data TO `account users`;
   ```

   Write access is needed because Auto Loader keeps its schema + checkpoint state
   under `s3://…/_schemas/` and `s3://…/_checkpoints/`.

> If your workspace is **classic (hive_metastore)** instead of UC, skip this and
> instead attach an **instance profile** with the same S3 permissions to the
> cluster; the notebook works unchanged (set the catalog widget to `hive_metastore`).

---

## 2. Ingest + build the views

1. Import `01_ingest_and_model.py` into the workspace
   (*Workspace → Import → File*) — it imports as a notebook.
2. Attach it to a cluster/SQL warehouse with the external location access.
3. Set the widgets at the top if needed:
   - `catalog` (default `main`), `schema` (default `bess`),
   - `s3_root` (default `s3://bess-data-945767338051`).
4. **Run all.** It creates `main.bess.{prices,schedules,telemetry,state}` and the
   `v_*` gold views, and prints the views at the end.

Auto Loader runs in `availableNow` mode — each run incrementally ingests new files
then stops. **To keep the dashboard fresh**, schedule the notebook as a job (e.g.
every 5 minutes) via *Workflows → Create job*. The telemetry minute files accrue
once per minute, so a 5-minute cadence is plenty.

---

## 3. Import the dashboard

1. *Dashboards → Create dashboard → ⋯ → Import dashboard from file* and choose
   `bess_trader.lvdash.json`.
2. Bind it to a SQL warehouse when prompted.
3. The datasets reference `main.bess.v_*`. **If you changed the catalog/schema**,
   open each dataset and update the table name (or find/replace `main.bess.` in the
   JSON before importing — Lakeview SQL can't parameterise identifiers).

### What the trader sees

- **KPI row** — current SoC %, selected-day P&L (£), equivalent full cycles,
  capacity loss %, cell temperature, cumulative throughput.
- **Price forecast vs. optimised dispatch** — the arbitrage view, by hour.
- **State of charge** and **delivered power** over the day.
- **Cell temperature** and a **constraint-violations** table.
- A **Trading day** filter scopes the time-series and P&L to a chosen date.

---

## Notes

- **Dashboard JSON portability.** `bess_trader.lvdash.json` targets the current
  Lakeview schema and is valid JSON, but it was authored without a live workspace to
  import-test against. If import reports a schema issue, the **gold views are the
  tested foundation** — you can drop these fields onto widgets in the Lakeview editor
  in a few minutes, or send me the import error and I'll adjust the JSON.
- **Price vs. dispatch** is shown as two aligned single-measure charts (price £/MWh,
  dispatch MW) rather than a dual-axis overlay, which keeps the spec robust. You can
  merge them into one dual-axis chart in the editor if preferred.
- **P&L** values each telemetry minute at its period's day-ahead price
  (`v_pnl_minute`/`v_pnl_daily`) — realised arbitrage, net of the efficiency/aux
  losses the physics model applies.
