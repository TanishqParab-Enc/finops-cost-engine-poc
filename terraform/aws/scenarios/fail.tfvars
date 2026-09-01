# Scenario 2 - scale-up expected to breach the FinOps threshold.
instance_type       = "m5.xlarge"
instance_count      = 2
root_volume_size_gb = 100
data_volume_count   = 2
data_volume_size_gb = 500
enable_nat_gateway  = true
