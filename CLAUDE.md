# Grid-Scale Battery Physical Model - Project Specification

This repository contains a standalone Python runtime designed to simulate the high-fidelity physical states and operational constraints of a grid-scale battery storage system (BESS) subjected to 1-second resolution dispatch signals.

## 1. Quick Start Commands

### Environment Setup
* Create virtual environment: `python -m venv venv`
* Activate virtual environment: `source venv/bin/activate` (Unix) or `venv\Scripts\activate` (Windows)
* Install dependencies: `pip install -r requirements.txt`

### Running the Simulation
* Run simulation with defaults: `python main.py --config config.yaml --dispatch dispatch.csv`
* Run simulation with live plotting: `python main.py --config config.yaml --dispatch dispatch.csv --visualize`
* Run tests: `pytest`
* Type checking: `mypy src/`
* Linting & Formatting: `black src/ && ruff check src/`

---

## 2. Directory Structure

```text
├── CLAUDE.md                 # This specification file
├── requirements.txt          # Minimal third-party dependencies (numpy, matplotlib, pyyaml, click)
├── config.yaml               # Default parameters configuration file
├── dispatch.csv              # Default 24-hour time-series dispatch signal (1s resolution)
├── main.py                   # CLI entry point
├── src/
│   ├── __init__.py
│   ├── battery.py            # Battery physical state machine & core math
│   ├── config_loader.py      # Validation and loading of physical parameters
│   ├── dispatch_engine.py    # Time-series step loops, constraint enforcement & logging
│   └── telemetry.py          # Real-time state recording and terminal/chart visualization
└── tests/
    ├── __init__.py
    ├── test_battery.py       # Physics & state boundary tests
    └── test_constraints.py   # Ramping, thermal, and degradation edge cases

```

---

## 3. Physical State & Core Dynamics Requirements

The simulation operates on a **1-second discrete step loop ($dt = 1$)**. The model must track and evaluate the following state variables dynamically:

### State of Charge (SoC) & Non-linearity

* **Linear Range**: Normal operations between user-defined limits (e.g., 10% to 90%).
* **Non-linear Behavior**: Near $0\%$ and $100\%$, internal resistance must increase exponentially, reducing actual charge acceptance or discharge capability. This behavior must scale dynamically based on the configuration parameters.

### Thermal Dynamics

* Cell temperature transitions based on ambient temperature, internal $I^2R$ resistive heating (charging/discharging efficiency losses), and cooling power from the HVAC auxiliary load.

### Efficiency & Power Dynamics

* **Round-Trip Efficiency**: Applied separately during charging ($P_{actual} = P_{in} \times \eta$) and discharging ($P_{actual} = P_{out} / \eta$).
* **Ramping Limits**: Restrict step changes in power inputs ($MW/s$).
* **Auxiliary Load**: Constant base load (controller, inverter standby) plus dynamic load (HVAC power scaled by cell temperature deviation from optimal).

### Degradation & Boundaries

* **Rate of Degradation**: Tracks cycle-based and calendar-based capacity loss per second.
* **Warranty Limits**: Hard counters tracking cumulative throughput ($MWh$) or equivalent full cycles (EFC). Flag if the configuration limits are breached.
* **Planned Outages**: A schedule lookup masking dispatch inputs to $0\text{ MW}$ during maintenance windows.
* **Grid Constraints**: Hard absolute clip on real-time power export/import capabilities independent of battery physical capability.

---

## 4. Code Architecture & Component Design

### Configuration (`config.yaml`)

All physical constants must be strictly defined in a single configuration file. Example schema layout:

```yaml
nominal_capacity_mwh: 50.0
initial_soc: 0.50
efficiency: 0.92
ramping_limit_mw_per_sec: 2.0
thermal:
  initial_temp_c: 25.0
  ambient_temp_c: 20.0
  thermal_mass: 15000 # J/C equivalent
  hvac_cooling_rate_c_per_sec: 0.05
soc_non_linearity:
  lower_threshold: 0.10
  upper_threshold: 0.90
  exponential_factor: 2.5
auxiliary_load_kw:
  base: 50.0
  hvac_per_degree: 10.0
grid_constraints:
  max_export_mw: 45.0
  max_import_mw: 45.0
warranty:
  max_equivalent_full_cycles: 3000

```

### Constraint Enforcement Guardrails

* **Pre-step Checks**: Verify planned outages and grid constraints to clamp the target dispatch setpoint.
* **Intra-step Checks**: Evaluate cell ramping, non-linear boundaries, and thermal cutoffs.
* **Console Violations Logging**: Any difference between the injected dispatch signal and actual physics executed must log a standard alarm block to `stderr`:
`[VIOLATION][Timestamp] Desired: XX.X MW | Enforced Limit: YY.Y MW | Reason: [Ramp Limit Exceeded / Thermal Trip / Grid Constrained]`

### Visualization & Telemetry

* **CLI Inputs**: Control runtime flags using `click` or `argparse`.
* **Telemetry Stream**: Emits time-series rows of the state parameters to stdout or a local memory buffer.
* **Live Charts**: If `--visualize` is toggled, open a `matplotlib.animation` dashboard with subplots mapping:
1. Power (Target vs. Actual vs. Grid Limits)
2. SoC % over time
3. Cell Temperature vs. Ambient Temperature
4. Cumulative Capacity Loss / Degradation Counter



---

## 5. Coding Standards & Conventions

* **Type Hinting**: All functional signatures must use explicit Python type hints (`from typing import Dict, List, Tuple`).
* **State Separation**: The `Battery` class manages immediate physical transformations, while the `DispatchEngine` manages time orchestration and external system overrides.
* **Performance**: Use vectorized `numpy` steps where possible, but maintain readable, step-wise iteration to handle complex conditional feedback loops (e.g., Temp -> Aux Load -> Power Available -> SoC change -> Temp change).
* **No Silent Failures**: Uncaught boundary parameters or physical impossibilities (e.g., negative efficiency) must raise an explicit runtime configuration exception at startup.

```

```