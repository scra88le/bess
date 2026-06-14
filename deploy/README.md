# Phase 2 — Containerise & deploy to AWS

This directory holds everything to package the BESS runtime as a container and
run the three components on AWS, coordinated through an S3 data root:

```
ECR (one image, all subcommands)
 ├─ Fargate service        ── run             (always-on, follows daily schedules)
 ├─ EventBridge cron ─ ECS  ── optimise        (daily, plans the upcoming day)
 └─ EventBridge cron ─ ECS  ── generate-prices (periodic, tops up forecasts)
S3 (prices/ schedules/ telemetry/ state/)  ← all three read/write
CloudWatch Logs + IAM roles
```

The same image runs every component; only the **command** differs
(`run` / `optimise` / `generate-prices`). The data layout is identical to local
runs — only the `--root` changes from `./data` to `s3://…`.

---

## 0. Prerequisites

- Docker, the AWS CLI (authenticated), and Terraform ≥ 1.5 installed.
- An AWS account/region you can create ECR, S3, ECS, IAM, and EventBridge in.

> None of these tools are required to develop the code — see the local mirror
> below, which only needs Docker.

---

## 1. Try it locally first (docker-compose + MinIO)

The repo root has a `docker-compose.yml` that mirrors the AWS topology using
**MinIO** as an S3-compatible store — no AWS account needed:

```bash
# from the repo root
docker compose up --build
```

This seeds 3 days of prices, optimises them, then runs the simulator streaming
minute telemetry to `s3://bess/telemetry/` inside MinIO. Browse it at the MinIO
console <http://localhost:9001> (`minioadmin` / `minioadmin`).

Override the window:

```bash
BESS_START=2026-07-01 BESS_TIME_SCALE=86400 docker compose up --build
```

The container reaches MinIO because `BESS_S3_ENDPOINT_URL` is set; against real
AWS that variable is unset and the standard credential/role chain is used.

---

## 2. Deploy to AWS

### a. Validate the plan

```bash
cd deploy/terraform
terraform init
terraform validate
terraform plan          # review: ECR, S3, ECS cluster/tasks, EventBridge, IAM
```

### b. Create the registry, then push the image

The ECS service pulls `image_tag` (default `latest`), so the image must exist
**before** the service starts. Create ECR first:

```bash
terraform apply -target=aws_ecr_repository.app
REPO=$(terraform output -raw ecr_repository_url)
REGION=eu-west-2                                    # match var.aws_region

# Build (from repo root) and push
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${REPO%/*}"
docker build -t "$REPO:latest" ../..
docker push "$REPO:latest"
```

### c. Apply the rest

```bash
terraform apply
```

Outputs include the bucket, the `s3://` root, the cluster, the run service, and
the log group.

### d. Bootstrap the initial data

The schedules drive everything, and the daily optimiser only plans *ahead*, so
seed an initial horizon once. Easiest is to run the two one-shot tasks now (the
`bootstrap_commands` output prints a ready-to-run `aws ecs run-task`), or run the
image locally against the bucket if you have AWS creds:

```bash
ROOT=$(terraform output -raw data_root)
docker run --rm -e AWS_DEFAULT_REGION=$REGION \
  -v ~/.aws:/root/.aws "$REPO:latest" \
  generate-prices --root "$ROOT" --days 14
docker run --rm -e AWS_DEFAULT_REGION=$REGION \
  -v ~/.aws:/root/.aws "$REPO:latest" \
  optimise --root "$ROOT" --date $(date -u +%F) --days 14
```

Once a schedule exists for the current day, the Fargate `run` service follows it
and writes telemetry; thereafter the EventBridge jobs keep the horizon topped up.

---

## 3. Configuration knobs (Terraform variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `aws_region` | `eu-west-2` | Deployment region. |
| `name_prefix` | `bess` | Prefix for all resource names. |
| `image_tag` | `latest` | ECR tag the tasks run. |
| `run_time_scale` | `1` | Sim-seconds per wall-second (1 = real time). |
| `optimise_schedule` | `cron(30 8 * * ? *)` | Daily optimiser (UTC). |
| `generate_schedule` | `cron(0 9 ? * MON *)` | Forecast top-up (UTC). |
| `generate_days` | `14` | Forecast horizon per generate run. |
| `task_cpu` / `task_memory` | `512` / `1024` | Fargate task size. |
| `assign_public_ip` | `true` | Use default-VPC public subnets. |

Set them in a `terraform.tfvars` or via `-var`.

---

## 4. Operating

```bash
# Logs (all components share one group, streamed by prefix run/optimise/generate)
aws logs tail /ecs/bess --follow

# Inspect telemetry
aws s3 ls s3://<bucket>/telemetry/ --recursive | tail

# Scale the simulator down/up
aws ecs update-service --cluster bess --service bess-run --desired-count 0
```

The `run` service **checkpoints to `state/` every minute**, so a task
restart/redeploy resumes from where it left off rather than from `--start`.

---

## 5. Notes, trade-offs & production hardening

- **Default VPC / public IPs.** Tasks run in the default VPC's public subnets
  with egress-only security and `assign_public_ip = true` so they can pull from
  ECR and reach S3. For production, move to private subnets with a NAT gateway or
  (cheaper) **S3 + ECR VPC endpoints**, and set `assign_public_ip = false`.
- **One always-on task.** The `run` service is a single Fargate task
  (`desired_count = 1`); it is a stateful simulator, not horizontally scalable.
  The minute checkpoint makes restarts safe.
- **No silent fallback.** If the optimiser hasn't produced a schedule for the day
  the runner reaches, the task exits non-zero (visible in CloudWatch) rather than
  coasting — keep `optimise`/`generate` ahead of `run`.
- **Costs.** A 24/7 Fargate task plus two short daily tasks and S3/CloudWatch are
  the cost drivers — modest, but it is always-on.
- **Phase 3** (Databricks) reads this same S3 layout via Auto Loader; nothing here
  needs to change for it.
