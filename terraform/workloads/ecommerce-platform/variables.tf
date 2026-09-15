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
  default     = "shopfront"
}

# -- networking --------------------------------------------------------------
variable "vpc_cidr" {
  description = "CIDR block for the VPC. Deliberately distinct from the web-platform workload so the two can coexist and peer later if ever needed."
  type        = string
  default     = "10.50.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "One public (edge/ALB) subnet per AZ."
  type        = list(string)
  default     = ["10.50.0.0/24", "10.50.1.0/24"]
}

variable "app_subnet_cidrs" {
  description = "One private application subnet per AZ. Hosts the storefront and worker instances."
  type        = list(string)
  default     = ["10.50.10.0/24", "10.50.11.0/24"]
}

variable "data_subnet_cidrs" {
  description = "One private data subnet per AZ. Hosts RDS and ElastiCache only; no route to the internet."
  type        = list(string)
  default     = ["10.50.20.0/24", "10.50.21.0/24"]
}

variable "nat_gateway_count" {
  description = "NAT gateways to create. 0 = none, 1 = shared, 2 = one per AZ. A NAT gateway carries an hourly charge plus per-GB processing, so this is a deliberate cost lever."
  type        = number
  default     = 1
}

# -- storefront (application) tier -------------------------------------------
variable "ami_id" {
  description = "AMI for the storefront and worker instances. Declared rather than looked up so plans stay hermetic and reproducible."
  type        = string
  default     = "ami-0c02fb55956c7d316"
}

variable "app_instance_type" {
  description = "Instance type for the storefront tier. A primary cost lever."
  type        = string
  default     = "t3.medium"
}

variable "app_desired_capacity" {
  description = "Steady-state storefront instance count. Infracost prices the group as desired_capacity x instance, so this is a primary cost lever."
  type        = number
  default     = 2
}

variable "app_min_capacity" {
  description = "Minimum storefront instance count."
  type        = number
  default     = 2
}

variable "app_max_capacity" {
  description = "Maximum storefront instance count."
  type        = number
  default     = 6
}

variable "app_root_volume_size" {
  description = "Root EBS volume size (GiB) for storefront instances."
  type        = number
  default     = 30
}

# -- worker tier -------------------------------------------------------------
variable "worker_instance_type" {
  description = "Instance type for the SQS-driven background worker tier."
  type        = string
  default     = "t3.small"
}

variable "worker_desired_capacity" {
  description = "Steady-state worker instance count."
  type        = number
  default     = 1
}

variable "worker_min_capacity" {
  description = "Minimum worker instance count."
  type        = number
  default     = 1
}

variable "worker_max_capacity" {
  description = "Maximum worker instance count. Workers scale on queue depth."
  type        = number
  default     = 4
}

variable "worker_root_volume_size" {
  description = "Root EBS volume size (GiB) for worker instances."
  type        = number
  default     = 20
}

variable "root_volume_type" {
  description = "EBS volume type for both compute tiers."
  type        = string
  default     = "gp3"
}

# -- database ----------------------------------------------------------------
variable "db_engine_version" {
  description = "PostgreSQL engine version."
  type        = string
  default     = "16.3"
}

variable "db_instance_class" {
  description = "RDS instance class. A primary cost lever."
  type        = string
  default     = "db.t3.small"
}

variable "db_allocated_storage" {
  description = "Allocated storage (GiB) for the order database."
  type        = number
  default     = 50
}

variable "db_storage_type" {
  description = "RDS storage type."
  type        = string
  default     = "gp3"
}

variable "db_multi_az" {
  description = "Run the order database across two AZs. Roughly doubles the instance cost, so it is an explicit lever rather than an implicit default."
  type        = bool
  default     = false
}

variable "db_backup_retention_days" {
  description = "Automated backup retention in days."
  type        = number
  default     = 7
}

# -- cache -------------------------------------------------------------------
variable "cache_node_type" {
  description = "ElastiCache Redis node type. A primary cost lever."
  type        = string
  default     = "cache.t3.micro"
}

variable "cache_node_count" {
  description = "Redis nodes in the replication group. 1 = primary only, 2 = primary plus one replica."
  type        = number
  default     = 2
}

# -- storage -----------------------------------------------------------------
variable "asset_noncurrent_expiration_days" {
  description = "Days before a superseded product-asset version is deleted."
  type        = number
  default     = 30
}

variable "asset_ia_transition_days" {
  description = "Days before a product asset moves to Standard-IA."
  type        = number
  default     = 60
}

# -- messaging ---------------------------------------------------------------
variable "order_queue_retention_seconds" {
  description = "How long an unprocessed order event is retained."
  type        = number
  default     = 345600
}

variable "order_queue_max_receive_count" {
  description = "Deliveries attempted before an order event is moved to the dead-letter queue."
  type        = number
  default     = 5
}

# -- edge --------------------------------------------------------------------
variable "enable_cdn" {
  description = "Create the CloudFront distribution. Disabling removes the edge tier entirely, which is a meaningful cost lever."
  type        = bool
  default     = true
}

variable "cdn_price_class" {
  description = "CloudFront price class. PriceClass_100 is the cheapest edge footprint."
  type        = string
  default     = "PriceClass_100"
}

variable "enable_dns" {
  description = "Create the Route 53 hosted zone and storefront record."
  type        = bool
  default     = true
}

variable "dns_zone_name" {
  description = "Hosted zone to create for the storefront."
  type        = string
  default     = "shopfront-poc.internal"
}

# -- monitoring --------------------------------------------------------------
variable "log_retention_days" {
  description = "CloudWatch Logs retention for both tiers."
  type        = number
  default     = 14
}

variable "queue_depth_alarm_threshold" {
  description = "Visible order events that indicate the worker tier is falling behind."
  type        = number
  default     = 100
}
