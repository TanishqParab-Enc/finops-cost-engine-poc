resource "aws_db_subnet_group" "main" {
  name       = "${var.name_prefix}-db-subnets"
  subnet_ids = var.private_subnet_ids

  tags = var.tags
}

# Explicit rather than implicit-null so the deploy role's narrowly-scoped
# KmsKeyNotAccessibleFault fix (see backend/modules/finops-environment) can
# target these two specific keys instead of granting KMS access account-wide.
data "aws_kms_key" "rds" {
  key_id = "alias/aws/rds"
}

data "aws_kms_key" "secretsmanager" {
  key_id = "alias/aws/secretsmanager"
}

resource "aws_db_instance" "main" {
  identifier = "${var.name_prefix}-db"

  engine         = var.engine
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage = var.allocated_storage
  storage_type      = var.storage_type
  storage_encrypted = true
  kms_key_id        = data.aws_kms_key.rds.arn

  db_name  = "appdb"
  username = "appadmin"
  # Managed by RDS rather than held in state or a variable.
  manage_master_user_password   = true
  master_user_secret_kms_key_id = data.aws_kms_key.secretsmanager.arn

  multi_az               = var.multi_az
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.security_group_id]

  backup_retention_period = var.backup_retention_days
  skip_final_snapshot     = true
  apply_immediately       = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-db" })
}
