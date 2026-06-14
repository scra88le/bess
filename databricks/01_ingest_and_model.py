# Databricks notebook source
# MAGIC %md
# MAGIC # BESS — ingest S3 data layout and build trader views
# MAGIC
# MAGIC Ingests the date-partitioned data written by the runtime
# MAGIC (`prices/`, `schedules/`, `telemetry/`, `state/`) from S3 into Unity Catalog
# MAGIC Delta tables using **Auto Loader**, then builds the **gold views** the
# MAGIC Lakeview trader dashboard reads.
# MAGIC
# MAGIC Prerequisite: a Unity Catalog **external location** granting this workspace
# MAGIC read access to the bucket (see `databricks/README.md`).
# MAGIC
# MAGIC Re-run (or schedule) this notebook to refresh — Auto Loader runs in
# MAGIC `availableNow` mode, so each run incrementally picks up new files then stops.

# COMMAND ----------

dbutils.widgets.text("catalog", "main", "Unity Catalog")
dbutils.widgets.text("schema", "bess", "Schema")
dbutils.widgets.text("s3_root", "s3://bess-data-945767338051", "S3 data root")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
ROOT = dbutils.widgets.get("s3_root").rstrip("/")
FQ = f"{CATALOG}.{SCHEMA}"

CHECKPOINTS = f"{ROOT}/_checkpoints"
SCHEMAS = f"{ROOT}/_schemas"

print(f"Ingesting {ROOT} -> {FQ}")

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {FQ}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Auto Loader: prices, schedules, telemetry
# MAGIC
# MAGIC `prices` and `schedules` have no in-file date, so the `date=` path partition
# MAGIC is inferred into a `date` column. `telemetry` records already carry `date`,
# MAGIC so partition inference is disabled there to avoid a column clash.

# COMMAND ----------

def autoload(source: str, table: str, partition_columns: str | None = None) -> None:
    """Incrementally load a parquet source from S3 into a Delta table."""
    reader = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .option("cloudFiles.schemaLocation", f"{SCHEMAS}/{table}")
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
    )
    if partition_columns is not None:
        # Empty string disables Hive-style partition inference.
        reader = reader.option("cloudFiles.partitionColumns", partition_columns)

    (
        reader.load(f"{ROOT}/{source}/")
        .writeStream.option("checkpointLocation", f"{CHECKPOINTS}/{table}")
        .option("mergeSchema", "true")
        .trigger(availableNow=True)
        .toTable(f"{FQ}.{table}")
    )


autoload("prices", "prices")                      # date from path partition
autoload("schedules", "schedules")                # date from path partition
autoload("telemetry", "telemetry", partition_columns="")  # date is in-file

# Wait for the availableNow streams to finish before building views.
for q in spark.streams.active:
    q.awaitTermination()

# COMMAND ----------

# MAGIC %md
# MAGIC ## State (single JSON, read as a batch snapshot)

# COMMAND ----------

state_df = spark.read.json(f"{ROOT}/state/battery_state.json")
state_df.write.mode("overwrite").saveAsTable(f"{FQ}.state")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold views for the trader dashboard

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {FQ}.v_telemetry AS
SELECT
  date,
  minute_index,
  to_timestamp(ts_utc)                              AS ts,
  soc_end,
  soc_end * 100                                     AS soc_pct,
  cell_temp_c_end,
  mean_power_mw,
  peak_discharge_mw,
  peak_charge_mw,
  mwh_discharged,
  mwh_charged,
  mean_target_mw,
  equivalent_full_cycles_end,
  capacity_loss_fraction_end,
  capacity_loss_fraction_end * 100                  AS capacity_loss_pct,
  cumulative_throughput_mwh_end,
  warranty_breached,
  (violations_ramp_limit + violations_grid_constrained + violations_planned_outage
   + violations_thermal_trip + violations_soc_nonlinear + violations_soc_floor
   + violations_soc_ceiling + violations_soc_limit + violations_other) AS violations_total
FROM {FQ}.telemetry
""")

# COMMAND ----------

# Current state: the single most recent minute record.
spark.sql(f"""
CREATE OR REPLACE VIEW {FQ}.v_latest AS
SELECT * FROM {FQ}.v_telemetry
QUALIFY ROW_NUMBER() OVER (ORDER BY date DESC, minute_index DESC) = 1
""")

# COMMAND ----------

# Price forecast vs. optimised dispatch, per period — the arbitrage overlay.
spark.sql(f"""
CREATE OR REPLACE VIEW {FQ}.v_price_dispatch AS
SELECT
  p.date,
  p.period,
  (p.period * p.resolution_minutes) / 60.0 AS hour,
  p.price_per_mwh,
  s.power_mw                               AS scheduled_power_mw
FROM {FQ}.prices p
LEFT JOIN {FQ}.schedules s
  ON p.date = s.date AND p.period = s.period
""")

# COMMAND ----------

# Realised P&L: each telemetry minute valued at its period's price.
spark.sql(f"""
CREATE OR REPLACE VIEW {FQ}.v_pnl_minute AS
SELECT
  t.date,
  t.ts,
  t.minute_index,
  (t.mwh_discharged - t.mwh_charged)                  AS net_mwh,
  pr.price_per_mwh,
  (t.mwh_discharged - t.mwh_charged) * pr.price_per_mwh AS revenue_gbp
FROM {FQ}.v_telemetry t
JOIN {FQ}.prices pr
  ON pr.date = t.date
 AND pr.period = floor(t.minute_index / pr.resolution_minutes)
""")

spark.sql(f"""
CREATE OR REPLACE VIEW {FQ}.v_pnl_daily AS
SELECT date, round(sum(revenue_gbp), 2) AS pnl_gbp,
       round(sum(net_mwh), 3)           AS net_mwh
FROM {FQ}.v_pnl_minute
GROUP BY date
""")

# COMMAND ----------

# Daily violation counts by reason.
spark.sql(f"""
CREATE OR REPLACE VIEW {FQ}.v_violations_daily AS
SELECT
  date,
  sum(violations_grid_constrained) AS grid_constrained,
  sum(violations_ramp_limit)       AS ramp_limit,
  sum(violations_thermal_trip)     AS thermal_trip,
  sum(violations_soc_nonlinear)    AS soc_nonlinear,
  sum(violations_soc_floor + violations_soc_ceiling + violations_soc_limit) AS soc_limits,
  sum(violations_planned_outage)   AS planned_outage,
  sum(violations_total)            AS total
FROM {FQ}.telemetry
GROUP BY date
""")

# COMMAND ----------

# Flattened checkpointed state.
spark.sql(f"""
CREATE OR REPLACE VIEW {FQ}.v_state AS
SELECT
  battery_state.soc,
  battery_state.soc * 100               AS soc_pct,
  battery_state.cell_temp_c,
  battery_state.equivalent_full_cycles,
  battery_state.capacity_loss_fraction,
  battery_state.warranty_breached,
  engine.prev_power_mw,
  clock.sim_now_iso,
  clock.time_scale
FROM {FQ}.state
""")

# COMMAND ----------

print("Tables and views ready under", FQ)
display(spark.sql(f"SHOW VIEWS IN {FQ}"))
