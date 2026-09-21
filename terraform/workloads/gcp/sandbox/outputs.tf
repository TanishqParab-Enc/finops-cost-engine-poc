output "network_name" {
  value = google_compute_network.main.name
}

output "instance_name" {
  value = google_compute_instance.app.name
}

output "bucket_name" {
  value = google_storage_bucket.assets.name
}

output "service_account_email" {
  value = google_service_account.app.email
}

# Surfaced so post-destroy verification can assert on concrete identifiers.
output "verification_scope" {
  description = "Resources the post-destroy check confirms are gone."
  value = {
    project  = var.project_id
    zone     = var.zone
    instance = google_compute_instance.app.name
    network  = google_compute_network.main.name
    bucket   = google_storage_bucket.assets.name
  }
}

output "cost_levers" {
  description = "The parameters a brownfield change is expected to move."
  value = {
    machine_type      = var.machine_type
    data_disk_size_gb = var.data_disk_size_gb
    data_disk_type    = var.data_disk_type
    boot_disk_size_gb = var.boot_disk_size_gb
  }
}
