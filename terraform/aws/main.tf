terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Credentials are faked and all validation is skipped so `terraform plan` runs
# offline in the POC. A real pipeline uses OIDC federation instead.
provider "aws" {
  region                      = var.region
  access_key                  = "mock_access_key"
  secret_key                  = "mock_secret_key"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  skip_region_validation      = true

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
