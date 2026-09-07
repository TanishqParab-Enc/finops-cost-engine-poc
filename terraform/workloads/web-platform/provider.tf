provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Environment = var.environment
      Application = var.application_name
      ManagedBy   = "Terraform"
      Workload    = "web-platform"
    }
  }
}
