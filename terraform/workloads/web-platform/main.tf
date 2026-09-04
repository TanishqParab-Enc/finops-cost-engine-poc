# Three-tier web platform used to exercise the FinOps gate against a realistic
# resource mix:
#
#   Route 53 -> CloudFront -> ALB -> Auto Scaling Group (EC2) -> RDS
#                    \-> S3 assets        CloudWatch, IAM, VPC supporting
#
# Every cost-significant value is a variable so a pull request can move exactly
# one lever and the incremental cost can be attributed to a single resource.

module "networking" {
  source = "./modules/networking"

  name_prefix          = local.name_prefix
  tags                 = local.common_tags
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  az_count             = local.az_count
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  nat_gateway_count    = var.nat_gateway_count
}

module "object_storage" {
  source = "./modules/object-storage"

  name_prefix                        = local.name_prefix
  tags                               = local.common_tags
  versioning_enabled                 = var.s3_versioning_enabled
  noncurrent_version_expiration_days = var.s3_noncurrent_version_expiration_days
}

module "alb" {
  source = "./modules/alb"

  name_prefix       = local.name_prefix
  tags              = local.common_tags
  vpc_id            = module.networking.vpc_id
  public_subnet_ids = module.networking.public_subnet_ids
  security_group_id = module.networking.alb_security_group_id
}

module "monitoring" {
  source = "./modules/monitoring"

  name_prefix            = local.name_prefix
  tags                   = local.common_tags
  retention_days         = var.log_retention_days
  autoscaling_group_name = module.compute.autoscaling_group_name
}

module "iam" {
  source = "./modules/iam"

  name_prefix       = local.name_prefix
  tags              = local.common_tags
  assets_bucket_arn = module.object_storage.bucket_arn
  log_group_arn     = module.monitoring.application_log_group_arn
}

module "compute" {
  source = "./modules/compute"

  name_prefix           = local.name_prefix
  tags                  = local.common_tags
  ami_id                = var.ami_id
  instance_type         = var.instance_type
  instance_profile_name = module.iam.instance_profile_name
  security_group_id     = module.networking.app_security_group_id
  private_subnet_ids    = module.networking.private_subnet_ids
  target_group_arn      = module.alb.target_group_arn
  desired_capacity      = var.desired_capacity
  min_capacity          = var.min_capacity
  max_capacity          = var.max_capacity
  root_volume_size      = var.root_volume_size
  root_volume_type      = var.root_volume_type
}

module "database" {
  source = "./modules/database"

  name_prefix        = local.name_prefix
  tags               = local.common_tags
  private_subnet_ids = module.networking.private_subnet_ids
  security_group_id  = module.networking.database_security_group_id
  engine             = var.rds_engine
  engine_version     = var.rds_engine_version
  instance_class     = var.rds_instance_class
  allocated_storage  = var.rds_storage
  storage_type       = var.rds_storage_type
  multi_az           = var.rds_multi_az
}

module "cdn" {
  source = "./modules/cdn"

  name_prefix               = local.name_prefix
  tags                      = local.common_tags
  enabled                   = var.cloudfront_enabled
  price_class               = var.cloudfront_price_class
  assets_bucket_domain_name = module.object_storage.bucket_regional_domain_name
  alb_dns_name              = module.alb.alb_dns_name
}

module "dns" {
  source = "./modules/dns"

  name_prefix        = local.name_prefix
  tags               = local.common_tags
  enabled            = var.dns_enabled
  zone_name          = var.dns_zone_name
  cdn_enabled        = var.cloudfront_enabled
  cdn_domain_name    = module.cdn.distribution_domain_name
  cdn_hosted_zone_id = module.cdn.distribution_hosted_zone_id
  alb_dns_name       = module.alb.alb_dns_name
  alb_zone_id        = module.alb.alb_zone_id
}
