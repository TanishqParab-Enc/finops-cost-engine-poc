variable "subscription_id" {
  description = "Target Azure subscription ID. A non-secret identifier, mirrored in the stack registry."
  type        = string
}

# Shared with unrelated workloads, so it is read as a data source and is never
# created or destroyed by this configuration.
variable "resource_group_name" {
  description = "Name of the PRE-EXISTING resource group this sandbox deploys into."
  type        = string
}

variable "location" {
  description = "Azure region (Azure's equivalent of an AWS region)."
  type        = string
  default     = "eastus"
}

variable "environment" {
  description = "Environment segment; must match the stack registry entry."
  type        = string
  default     = "dev"
}

variable "application_name" {
  description = "Workload name prefix for every resource."
  type        = string
  default     = "azsandbox"
}

variable "vnet_address_space" {
  description = "VNet CIDR."
  type        = string
  default     = "10.60.0.0/16"
}

variable "app_subnet_prefix" {
  description = "Application subnet CIDR."
  type        = string
  default     = "10.60.1.0/24"
}

# Primary cost lever for brownfield incremental-cost testing.
variable "vm_size" {
  description = "Azure VM size."
  type        = string
  default     = "Standard_B2s"
}

variable "admin_username" {
  description = "Linux admin username."
  type        = string
  default     = "azureuser"
}

variable "admin_ssh_public_key" {
  description = "SSH PUBLIC key for the admin user. Public keys are not secrets; never put a private key here."
  type        = string
}

variable "os_disk_type" {
  description = "OS managed disk SKU."
  type        = string
  default     = "StandardSSD_LRS"
}

variable "data_disk_type" {
  description = "Data managed disk SKU."
  type        = string
  default     = "StandardSSD_LRS"
}

variable "data_disk_size_gb" {
  description = "Data managed disk size in GiB."
  type        = number
  default     = 32
}

variable "storage_replication_type" {
  description = "Storage account replication."
  type        = string
  default     = "LRS"
}

variable "tags" {
  description = "Additional tags merged onto every resource."
  type        = map(string)
  default     = {}
}
