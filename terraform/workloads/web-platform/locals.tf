locals {
  name_prefix = "${var.application_name}-${lower(var.environment)}"

  # Subnets are zipped with AZs, so the shorter of the two wins. This keeps a
  # mismatched CIDR list from silently creating subnets in the wrong AZ.
  az_count = min(
    length(var.availability_zones),
    length(var.public_subnet_cidrs),
    length(var.private_subnet_cidrs),
  )

  common_tags = {
    Environment = var.environment
    Application = var.application_name
    Workload    = "web-platform"
  }
}
