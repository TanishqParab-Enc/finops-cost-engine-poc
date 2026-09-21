variable "project_id" {
  description = "Target GCP project ID. A non-secret identifier, mirrored in the stack registry."
  type        = string
}

variable "region" {
  description = "GCP region."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone; must be inside var.region."
  type        = string
  default     = "us-central1-a"
}

variable "environment" {
  description = "Environment segment; must match the stack registry entry."
  type        = string
  default     = "dev"
}

variable "application_name" {
  description = "Workload name prefix for every resource."
  type        = string
  default     = "gcpsandbox"
}

variable "app_subnet_cidr" {
  description = "Application subnet CIDR."
  type        = string
  default     = "10.70.1.0/24"
}

# Primary cost lever for brownfield incremental-cost testing.
variable "machine_type" {
  description = "Compute Engine machine type."
  type        = string
  default     = "e2-small"
}

variable "boot_image" {
  description = "Boot image for the instance."
  type        = string
  default     = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
}

variable "boot_disk_size_gb" {
  description = "Boot persistent disk size in GB."
  type        = number
  default     = 20
}

variable "boot_disk_type" {
  description = "Boot persistent disk type."
  type        = string
  default     = "pd-balanced"
}

variable "data_disk_type" {
  description = "Data persistent disk type."
  type        = string
  default     = "pd-balanced"
}

variable "data_disk_size_gb" {
  description = "Data persistent disk size in GB."
  type        = number
  default     = 32
}

variable "bucket_storage_class" {
  description = "Cloud Storage class."
  type        = string
  default     = "STANDARD"
}

variable "labels" {
  description = "Additional labels merged onto every labelable resource."
  type        = map(string)
  default     = {}
}
