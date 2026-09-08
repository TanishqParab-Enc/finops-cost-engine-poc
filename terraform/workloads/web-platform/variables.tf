variable "region" {
  description = "AWS region for the whole workload."
  type        = string
  default     = "us-east-1"
}

variable "availability_zones" {
  description = "AZs to spread subnets across. Declared rather than discovered so the workload plans hermetically, with no AWS API calls."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "environment" {
  description = "Environment label applied as a default tag."
  type        = string
  default     = "Dev"
}

variable "application_name" {
  description = "Short name used to prefix every resource."
  type        = string
  default     = "webplatform"
}

# -- networking --------------------------------------------------------------
variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "One public subnet per AZ."
  type        = list(string)
  default     = ["10.40.0.0/24", "10.40.1.0/24"]
}

variable "private_subnet_cidrs" {
  description = "One private subnet per AZ."
  type        = list(string)
  default     = ["10.40.10.0/24", "10.40.11.0/24"]
}

variable "nat_gateway_count" {
  description = "NAT gateways to create. 0 = none, 1 = shared, 2 = one per AZ. A NAT gateway carries an hourly charge, so this is a deliberate cost lever."
  type        = number
  default     = 1
}

# -- compute -----------------------------------------------------------------
variable "instance_type" {
  description = "EC2 instance type for the web tier."
  type        = string
  default     = "t3.large"
}

variable "ami_id" {
  description = "AMI for the web tier. Pinned rather than resolved via SSM so the plan is deterministic and needs no AWS credentials."
  type        = string
  default     = "ami-0c02fb55956c7d316"
}

variable "desired_capacity" {
  description = "Desired number of web instances."
  type        = number
  default     = 1
}

variable "min_capacity" {
  description = "Minimum number of web instances."
  type        = number
  default     = 1
}

variable "max_capacity" {
  description = "Maximum number of web instances."
  type        = number
  default     = 3
}

variable "root_volume_size" {
  description = "Root EBS volume size per instance, in GB."
  type        = number
  default     = 30
}

variable "root_volume_type" {
  description = "Root EBS volume type."
  type        = string
  default     = "gp3"
}

# -- database ----------------------------------------------------------------
variable "rds_engine" {
  description = "RDS engine."
  type        = string
  default     = "postgres"
}

variable "rds_engine_version" {
  description = "RDS engine version."
  type        = string
  default     = "16.3"
}

variable "rds_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.small"
}

variable "rds_storage" {
  description = "Allocated RDS storage in GB."
  type        = number
  default     = 50
}

variable "rds_storage_type" {
  description = "RDS storage type."
  type        = string
  default     = "gp3"
}

variable "rds_multi_az" {
  description = "Run RDS across two AZs. Roughly doubles the instance charge."
  type        = bool
  default     = false
}

# -- object storage ----------------------------------------------------------
variable "s3_storage_gb" {
  description = "Expected steady-state size of the asset bucket, in GB. S3 is usage-priced, so this value is mirrored in the Infracost usage file; the two must be changed together."
  type        = number
  default     = 20
}

variable "s3_versioning_enabled" {
  description = "Keep non-current object versions."
  type        = bool
  default     = true
}

variable "s3_noncurrent_version_expiration_days" {
  description = "Days before a non-current version is expired."
  type        = number
  default     = 30
}

# -- cdn / dns ---------------------------------------------------------------
variable "cloudfront_enabled" {
  description = "Front the platform with CloudFront."
  type        = bool
  default     = true
}

variable "cloudfront_price_class" {
  description = "CloudFront price class."
  type        = string
  default     = "PriceClass_100"
}

variable "dns_enabled" {
  description = "Create a private-style hosted zone and records."
  type        = bool
  default     = true
}

variable "dns_zone_name" {
  description = "Hosted zone name. Uses a reserved, non-routable example domain so nothing here can resolve publicly."
  type        = string
  default     = "web-platform.example.com"
}

# -- monitoring --------------------------------------------------------------
variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 30
}
