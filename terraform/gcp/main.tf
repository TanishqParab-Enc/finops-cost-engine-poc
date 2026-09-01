terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.30"
    }
  }
}

# A dummy access token keeps `terraform plan` offline for the POC; it avoids
# needing a real service-account key file. A real pipeline uses Workload
# Identity Federation.
provider "google" {
  project      = var.project_id
  region       = var.region
  zone         = var.zone
  access_token = "mock-access-token-for-plan-only"
}

resource "google_compute_instance" "app" {
  count = var.instance_count

  name         = "finops-poc-app-${count.index}"
  machine_type = var.machine_type
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = var.boot_disk_size_gb
      type  = var.boot_disk_type
    }
  }

  network_interface {
    network = "default"
  }

  labels = {
    environment = lower(var.environment)
    service     = var.service
  }
}

resource "google_compute_disk" "data" {
  count = var.data_disk_count

  name = "finops-poc-data-${count.index}"
  type = var.data_disk_type
  zone = var.zone
  size = var.data_disk_size_gb

  labels = {
    environment = lower(var.environment)
    service     = var.service
  }
}

resource "google_compute_address" "egress" {
  count = var.enable_static_ip ? 1 : 0

  name   = "finops-poc-ip"
  region = var.region
}
