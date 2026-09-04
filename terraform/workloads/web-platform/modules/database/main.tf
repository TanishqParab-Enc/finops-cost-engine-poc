resource "aws_db_subnet_group" "main" {
  name       = "${var.name_prefix}-db-subnets"
  subnet_ids = var.private_subnet_ids

  tags = var.tags
}

resource "aws_db_instance" "main" {
  identifier = "${var.name_prefix}-db"

  engine         = var.engine
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage = var.allocated_storage
  storage_type      = var.storage_type
  storage_encrypted = true

  db_name  = "appdb"
  username = "appadmin"
  # Managed by RDS rather than held in state or a variable.
  manage_master_user_password = true

  multi_az               = var.multi_az
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.security_group_id]

  backup_retention_period = var.backup_retention_days
  skip_final_snapshot     = true
  apply_immediately       = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-db" })
}
