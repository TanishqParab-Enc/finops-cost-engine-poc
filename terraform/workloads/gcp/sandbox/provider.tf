# Credentials come from the workflow's Workload Identity Federation exchange
# (google-github-actions/auth writes an ADC credentials file and exports
# GOOGLE_APPLICATION_CREDENTIALS). No service-account key is ever used.
provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}
