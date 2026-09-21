# Committed baseline for the GCP sandbox. Editing this file changes cloud cost,
# which is exactly what the shared FinOps gate prices.
#
# project_id is environment-specific and is NOT committed with a real value -
# see terraform.tfvars.example. The workflow supplies it at plan time.

region           = "us-central1"
zone             = "us-central1-a"
environment      = "dev"
application_name = "gcpsandbox"

app_subnet_cidr = "10.70.1.0/24"

# -- compute (primary cost lever) --
machine_type      = "e2-small"
boot_disk_size_gb = 20
boot_disk_type    = "pd-balanced"

# -- storage --
data_disk_type       = "pd-balanced"
data_disk_size_gb    = 32
bucket_storage_class = "STANDARD"
