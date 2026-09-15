resource "aws_db_subnet_group" "main" {
  name       = "${var.name_prefix}-db-subnets"
  subnet_ids = var.data_subnet_ids

  tags = merge(var.tags, { Name = "${var.name_prefix}-db-subnets" })
}

# Parameterised rather than inline so connection/logging behaviour is reviewable
# in the plan diff like any other change.
resource "aws_db_parameter_group" "main" {
  name   = "${var.name_prefix}-pg16"
  family = var.parameter_group_family

  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-pg16" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "main" {
  identifier = "${var.name_prefix}-orders-db"

  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type          = var.storage_type
  storage_encrypted     = true

  db_name  = "orders"
  username = "shopadmin"
  # Generated and rotated by RDS, so the master password never enters Terraform
  # state, a tfvars file or this repository.
  manage_master_user_password = true

  multi_az               = var.multi_az
  db_subnet_group_name   = aws_db_subnet_group.main.name
  parameter_group_name   = aws_db_parameter_group.main.name
  vpc_security_group_ids = [var.security_group_id]

  backup_retention_period = var.backup_retention_days
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:30-Mon:05:30"

  auto_minor_version_upgrade = true
  deletion_protection        = false
  skip_final_snapshot        = true
  apply_immediately          = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-orders-db" })
}
