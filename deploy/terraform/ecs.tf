resource "aws_ecs_cluster" "this" {
  name = var.name_prefix
}

# Egress-only security group (tasks reach ECR + S3 over the internet via the
# default VPC's public subnets). Lock this down with VPC endpoints in prod.
resource "aws_security_group" "tasks" {
  name        = "${var.name_prefix}-tasks"
  description = "BESS Fargate tasks (egress only)"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Builds one container definition with the given command + log stream prefix.
locals {
  container = {
    for kind, command in {
      run      = ["run", "--root", local.s3_root, "--config", "config.yaml", "--time-scale", tostring(var.run_time_scale)]
      optimise = ["optimise", "--root", local.s3_root, "--config", "config.yaml"]
      generate = ["generate-prices", "--root", local.s3_root, "--days", tostring(var.generate_days)]
      } : kind => jsonencode([{
        name        = "app"
        image       = local.image
        essential   = true
        command     = command
        environment = local.container_env
        logConfiguration = {
          logDriver = "awslogs"
          options = {
            "awslogs-group"         = aws_cloudwatch_log_group.app.name
            "awslogs-region"        = var.aws_region
            "awslogs-stream-prefix" = kind
          }
        }
    }])
  }
}

resource "aws_ecs_task_definition" "run" {
  family                   = "${var.name_prefix}-run"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions    = local.container["run"]
}

resource "aws_ecs_task_definition" "optimise" {
  family                   = "${var.name_prefix}-optimise"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions    = local.container["optimise"]
}

resource "aws_ecs_task_definition" "generate" {
  family                   = "${var.name_prefix}-generate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions    = local.container["generate"]
}

# Always-on simulator following the daily schedules.
resource "aws_ecs_service" "run" {
  name            = "${var.name_prefix}-run"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.run.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = var.assign_public_ip
  }
}
