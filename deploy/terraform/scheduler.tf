# Daily optimiser: plan the upcoming day(s) from the latest forecast.
resource "aws_scheduler_schedule" "optimise" {
  name = "${var.name_prefix}-optimise"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = var.optimise_schedule
  schedule_expression_timezone = "UTC"

  target {
    arn      = aws_ecs_cluster.this.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.optimise.arn
      launch_type         = "FARGATE"

      network_configuration {
        subnets          = data.aws_subnets.default.ids
        security_groups  = [aws_security_group.tasks.id]
        assign_public_ip = var.assign_public_ip
      }
    }
  }
}

# Periodic forecast top-up so the optimiser always has prices ahead of it.
resource "aws_scheduler_schedule" "generate" {
  name = "${var.name_prefix}-generate"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = var.generate_schedule
  schedule_expression_timezone = "UTC"

  target {
    arn      = aws_ecs_cluster.this.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.generate.arn
      launch_type         = "FARGATE"

      network_configuration {
        subnets          = data.aws_subnets.default.ids
        security_groups  = [aws_security_group.tasks.id]
        assign_public_ip = var.assign_public_ip
      }
    }
  }
}
