variable "project_id" {
  type    = string
  default = "finops-poc-project"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "zone" {
  type    = string
  default = "us-central1-a"
}

variable "environment" {
  type    = string
  default = "Dev"
}

variable "service" {
  type    = string
  default = "finops-poc"
}

variable "machine_type" {
  type    = string
  default = "e2-medium"
}

variable "instance_count" {
  type    = number
  default = 1
}

variable "boot_disk_size_gb" {
  type    = number
  default = 20
}

variable "boot_disk_type" {
  type    = string
  default = "pd-balanced"
}

variable "data_disk_count" {
  type    = number
  default = 0
}

variable "data_disk_size_gb" {
  type    = number
  default = 500
}

variable "data_disk_type" {
  type    = string
  default = "pd-ssd"
}

variable "enable_static_ip" {
  type    = bool
  default = false
}
