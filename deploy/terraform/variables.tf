variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "eu-west-2"
}

variable "name_prefix" {
  description = "Prefix for all resource names."
  type        = string
  default     = "bess"
}

variable "image_tag" {
  description = "ECR image tag to run (push this tag before applying / updating)."
  type        = string
  default     = "latest"
}

variable "data_bucket_name" {
  description = "S3 bucket for the data layout. Defaults to <prefix>-data-<account_id>."
  type        = string
  default     = null
}

variable "run_time_scale" {
  description = "Sim-seconds per wall-second for the long-running service (1 = real time)."
  type        = number
  default     = 1
}

variable "optimise_schedule" {
  description = "EventBridge cron for the daily optimiser (UTC). Plans tomorrow each morning."
  type        = string
  default     = "cron(30 8 * * ? *)"
}

variable "generate_schedule" {
  description = "EventBridge cron for topping up price forecasts (UTC)."
  type        = string
  default     = "cron(0 9 ? * MON *)"
}

variable "generate_days" {
  description = "How many days of forecasts the generate job writes per run."
  type        = number
  default     = 14
}

variable "task_cpu" {
  description = "Fargate task CPU units (256, 512, 1024, …)."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate task memory (MiB)."
  type        = number
  default     = 1024
}

variable "assign_public_ip" {
  description = "Assign public IPs (true for default-VPC public subnets; false with NAT/VPC endpoints)."
  type        = bool
  default     = true
}
