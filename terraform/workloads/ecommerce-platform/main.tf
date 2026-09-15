# E-commerce platform: customer -> Route 53 -> CloudFront -> ALB -> storefront
# tier, with orders handed to SQS and drained by a separate worker tier. See
# README.md for the full request and data flow.
#
# This workload is self-contained. It shares nothing with
# terraform/workloads/web-platform and keeps its own Terraform state
# (finops-poc/dev/ecommerce-platform/terraform.tfstate). FinOps governance is
# applied externally by the shared pipeline via the stack registry - there is
# no cost, policy or approval logic in this codebase.

locals {
  # Declared here rather than taken from the monitoring module's outputs so the
  # IAM module can scope its log permissions without depending on monitoring
  # (which in turn depends on the compute tiers that consume these roles).
  app_log_group_name    = "/${local.name_prefix}/storefront"
  worker_log_group_name = "/${local.name_prefix}/worker"
}

module "networking" {
  source = "./modules/networking"

  name_prefix         = local.name_prefix
  tags                = local.common_tags
  vpc_cidr            = var.vpc_cidr
  availability_zones  = var.availability_zones
  az_count            = local.az_count
  public_subnet_cidrs = var.public_subnet_cidrs
  app_subnet_cidrs    = var.app_subnet_cidrs
  data_subnet_cidrs   = var.data_subnet_cidrs
  nat_gateway_count   = var.nat_gateway_count
}

module "storage" {
  source = "./modules/storage"

  name_prefix                = local.name_prefix
  tags                       = local.common_tags
  noncurrent_expiration_days = var.asset_noncurrent_expiration_days
  ia_transition_days         = var.asset_ia_transition_days
}

module "messaging" {
  source = "./modules/messaging"

  name_prefix       = local.name_prefix
  tags              = local.common_tags
  retention_seconds = var.order_queue_retention_seconds
  max_receive_count = var.order_queue_max_receive_count
}

module "cache" {
  source = "./modules/cache"

  name_prefix       = local.name_prefix
  tags              = local.common_tags
  data_subnet_ids   = module.networking.data_subnet_ids
  security_group_id = module.networking.cache_security_group_id
  node_type         = var.cache_node_type
  node_count        = var.cache_node_count
}

module "database" {
  source = "./modules/database"

  name_prefix           = local.name_prefix
  tags                  = local.common_tags
  data_subnet_ids       = module.networking.data_subnet_ids
  security_group_id     = module.networking.database_security_group_id
  engine_version        = var.db_engine_version
  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage
  storage_type          = var.db_storage_type
  multi_az              = var.db_multi_az
  backup_retention_days = var.db_backup_retention_days
}

module "secrets" {
  source = "./modules/secrets"

  name_prefix     = local.name_prefix
  tags            = local.common_tags
  cache_endpoint  = module.cache.primary_endpoint
  order_queue_url = module.messaging.queue_url
  asset_bucket    = module.storage.bucket_id
}

module "iam" {
  source = "./modules/iam"

  name_prefix           = local.name_prefix
  tags                  = local.common_tags
  asset_bucket_arn      = module.storage.bucket_arn
  order_queue_arn       = module.messaging.queue_arn
  order_dlq_arn         = module.messaging.dlq_arn
  app_secret_arn        = module.secrets.secret_arn
  app_log_group_name    = local.app_log_group_name
  worker_log_group_name = local.worker_log_group_name
}

module "alb" {
  source = "./modules/alb"

  name_prefix       = local.name_prefix
  tags              = local.common_tags
  vpc_id            = module.networking.vpc_id
  public_subnet_ids = module.networking.public_subnet_ids
  security_group_id = module.networking.alb_security_group_id
}

module "app_compute" {
  source = "./modules/app_compute"

  name_prefix           = local.name_prefix
  tags                  = local.common_tags
  ami_id                = var.ami_id
  instance_type         = var.app_instance_type
  instance_profile_name = module.iam.app_instance_profile_name
  security_group_id     = module.networking.app_security_group_id
  app_subnet_ids        = module.networking.app_subnet_ids
  target_group_arn      = module.alb.target_group_arn
  desired_capacity      = var.app_desired_capacity
  min_capacity          = var.app_min_capacity
  max_capacity          = var.app_max_capacity
  root_volume_size      = var.app_root_volume_size
  root_volume_type      = var.root_volume_type
}

module "worker_compute" {
  source = "./modules/worker_compute"

  name_prefix           = local.name_prefix
  tags                  = local.common_tags
  ami_id                = var.ami_id
  instance_type         = var.worker_instance_type
  instance_profile_name = module.iam.worker_instance_profile_name
  security_group_id     = module.networking.worker_security_group_id
  app_subnet_ids        = module.networking.app_subnet_ids
  desired_capacity      = var.worker_desired_capacity
  min_capacity          = var.worker_min_capacity
  max_capacity          = var.worker_max_capacity
  root_volume_size      = var.worker_root_volume_size
  root_volume_type      = var.root_volume_type
  queue_name            = module.messaging.queue_name
}

module "edge" {
  source = "./modules/edge"

  name_prefix              = local.name_prefix
  tags                     = local.common_tags
  enabled                  = var.enable_cdn
  price_class              = var.cdn_price_class
  alb_dns_name             = module.alb.dns_name
  alb_zone_id              = module.alb.zone_id
  asset_bucket_domain_name = module.storage.bucket_regional_domain_name
  enable_dns               = var.enable_dns
  zone_name                = var.dns_zone_name
}

module "monitoring" {
  source = "./modules/monitoring"

  name_prefix                = local.name_prefix
  tags                       = local.common_tags
  retention_days             = var.log_retention_days
  app_autoscaling_group_name = module.app_compute.autoscaling_group_name
  alb_arn_suffix             = module.alb.arn_suffix
  database_identifier        = module.database.identifier
  order_queue_name           = module.messaging.queue_name
  order_dlq_name             = module.messaging.dlq_name
  cache_replication_group_id = module.cache.replication_group_id
  queue_depth_threshold      = var.queue_depth_alarm_threshold
}
