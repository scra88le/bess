provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

# Use the account's default VPC + its subnets so no networking has to be built.
# For production, swap these for private subnets with NAT or VPC endpoints.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

locals {
  prefix      = var.name_prefix
  account_id  = data.aws_caller_identity.current.account_id
  bucket_name = coalesce(var.data_bucket_name, "${var.name_prefix}-data-${data.aws_caller_identity.current.account_id}")
  image       = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
  s3_root     = "s3://${local.bucket_name}"

  # Common env so the container talks to the data bucket (real S3; no endpoint override).
  container_env = [
    { name = "AWS_DEFAULT_REGION", value = var.aws_region },
  ]
}
