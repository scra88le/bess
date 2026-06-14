output "ecr_repository_url" {
  description = "Push the image here, then set image_tag and apply."
  value       = aws_ecr_repository.app.repository_url
}

output "data_bucket" {
  description = "S3 bucket holding the prices/schedules/telemetry/state layout."
  value       = aws_s3_bucket.data.bucket
}

output "data_root" {
  description = "The s3:// root all components use."
  value       = local.s3_root
}

output "ecs_cluster" {
  value = aws_ecs_cluster.this.name
}

output "run_service" {
  value = aws_ecs_service.run.name
}

output "log_group" {
  description = "CloudWatch log group for all tasks."
  value       = aws_cloudwatch_log_group.app.name
}

output "bootstrap_commands" {
  description = "One-off commands to seed data before/after the first apply."
  value       = <<-EOT
    # Seed initial forecasts + schedules by running the tasks once (or locally
    # against the bucket): generate-prices then optimise for the current horizon.
    aws ecs run-task --cluster ${aws_ecs_cluster.this.name} \
      --launch-type FARGATE --task-definition ${var.name_prefix}-generate \
      --network-configuration "awsvpcConfiguration={subnets=[${join(",", data.aws_subnets.default.ids)}],securityGroups=[${aws_security_group.tasks.id}],assignPublicIp=ENABLED}"
  EOT
}
