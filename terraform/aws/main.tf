terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Backend config is supplied at init time via -backend-config flags in CI.
  # Local runs: `terraform init -backend=false` to skip state.
  backend "s3" {}
}

# Credentials come from the OIDC role assumed in the workflow.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Environment = var.environment
      Service     = var.service
    }
  }
}

resource "aws_instance" "app" {
  count = var.instance_count

  ami           = var.ami_id
  instance_type = var.instance_type

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size_gb
  }

  tags = {
    Name = "finops-poc-app-${count.index}"
  }
}

resource "aws_ebs_volume" "data" {
  count = var.data_volume_count

  availability_zone = "${var.region}a"
  type              = "gp3"
  size              = var.data_volume_size_gb

  tags = {
    Name = "finops-poc-data-${count.index}"
  }
}

resource "aws_nat_gateway" "egress" {
  count = var.enable_nat_gateway ? 1 : 0

  allocation_id = "eipalloc-0123456789abcdef0"
  subnet_id     = "subnet-0123456789abcdef0"

  tags = {
    Name = "finops-poc-nat"
  }
}
