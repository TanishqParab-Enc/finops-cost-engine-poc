# GCP sandbox: the smallest workload that still exercises the full governed
# lifecycle on a third cloud, using GCP-native services rather than a
# resource-for-resource translation of the AWS or Azure workloads.

locals {
  name_prefix = "${var.application_name}-${var.environment}"

  # GCP labels are the equivalent of AWS/Azure tags. Label values are
  # restricted to lowercase alphanumerics, '-' and '_'.
  labels = merge(
    {
      project     = "finops-poc"
      environment = var.environment
      workload    = var.application_name
      managed_by  = "terraform"
    },
    var.labels,
  )
}

resource "google_compute_network" "main" {
  name                    = "${local.name_prefix}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "app" {
  name          = "${local.name_prefix}-subnet-app"
  ip_cidr_range = var.app_subnet_cidr
  region        = var.region
  network       = google_compute_network.main.id
}

# Internal-only. No public ingress rule is created; the instance has no
# external IP (see the absence of an access_config block below).
resource "google_compute_firewall" "internal" {
  name    = "${local.name_prefix}-allow-internal"
  network = google_compute_network.main.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = [var.app_subnet_cidr]
  target_tags   = ["${local.name_prefix}-app"]
}

# Primary cost lever: machine_type drives the brownfield incremental-cost test.
resource "google_compute_instance" "app" {
  name         = "${local.name_prefix}-vm"
  machine_type = var.machine_type
  zone         = var.zone
  tags         = ["${local.name_prefix}-app"]
  labels       = local.labels

  boot_disk {
    initialize_params {
      image = var.boot_image
      size  = var.boot_disk_size_gb
      type  = var.boot_disk_type
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.app.id
    # No access_config: deliberately no external IP.
  }

  # Avoids the legacy default service account having broad scopes.
  service_account {
    email  = google_service_account.app.email
    scopes = ["cloud-platform"]
  }
}

# Second cost lever: an explicitly sized persistent disk.
resource "google_compute_disk" "data" {
  name   = "${local.name_prefix}-data-disk"
  type   = var.data_disk_type
  zone   = var.zone
  size   = var.data_disk_size_gb
  labels = local.labels
}

resource "google_compute_attached_disk" "data" {
  disk     = google_compute_disk.data.id
  instance = google_compute_instance.app.id
}

# Workload identity for the instance - the GCP counterpart of the AWS
# workloads' instance role. Not the deploy identity.
resource "google_service_account" "app" {
  account_id   = "${local.name_prefix}-sa"
  display_name = "FinOps POC GCP sandbox workload identity"
}

# Consumption-priced: contributes only via infracost-usage.yml assumptions.
resource "google_storage_bucket" "assets" {
  name                        = "${local.name_prefix}-assets-${var.project_id}"
  location                    = var.region
  storage_class               = var.bucket_storage_class
  force_destroy               = true
  uniform_bucket_level_access = true
  labels                      = local.labels

  versioning {
    enabled = true
  }
}
