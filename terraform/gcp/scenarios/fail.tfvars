# Scenario 2 - scale-up expected to breach the FinOps threshold.
machine_type      = "n2-standard-8"
instance_count    = 2
boot_disk_size_gb = 100
boot_disk_type    = "pd-ssd"
data_disk_count   = 2
data_disk_size_gb = 1000
data_disk_type    = "pd-ssd"
enable_static_ip  = true
