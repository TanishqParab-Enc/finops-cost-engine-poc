variable "region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "Dev"
}

variable "service" {
  type    = string
  default = "finops-poc"
}

variable "ami_id" {
  type    = string
  default = "ami-0c02fb55956c7d316"
}

variable "instance_type" {
  type    = string
  default = "t3.micro"
}

variable "instance_count" {
  type    = number
  default = 1
}

variable "root_volume_size_gb" {
  type    = number
  default = 20
}

variable "data_volume_count" {
  type    = number
  default = 0
}

variable "data_volume_size_gb" {
  type    = number
  default = 100
}

variable "enable_nat_gateway" {
  type    = bool
  default = false
}
