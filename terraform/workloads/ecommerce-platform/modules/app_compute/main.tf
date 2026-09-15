resource "aws_launch_template" "storefront" {
  name_prefix   = "${var.name_prefix}-app-lt-"
  image_id      = var.ami_id
  instance_type = var.instance_type

  iam_instance_profile {
    name = var.instance_profile_name
  }

  vpc_security_group_ids = [var.security_group_id]

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = var.root_volume_size
      volume_type           = var.root_volume_type
      delete_on_termination = true
      encrypted             = true
    }
  }

  # IMDSv2 only - blocks the SSRF-to-credential-theft path.
  metadata_options {
    http_tokens                 = "required"
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 1
  }

  monitoring {
    enabled = true
  }

  tag_specifications {
    resource_type = "instance"
    tags          = merge(var.tags, { Name = "${var.name_prefix}-storefront", Tier = "application" })
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Infracost prices the group as desired_capacity x launch-template instance, so
# instance_type and desired_capacity are both first-class cost levers.
resource "aws_autoscaling_group" "storefront" {
  name                = "${var.name_prefix}-app-asg"
  vpc_zone_identifier = var.app_subnet_ids
  target_group_arns   = [var.target_group_arn]

  desired_capacity = var.desired_capacity
  min_size         = var.min_capacity
  max_size         = var.max_capacity

  health_check_type         = "ELB"
  health_check_grace_period = 180

  launch_template {
    id      = aws_launch_template.storefront.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${var.name_prefix}-storefront"
    propagate_at_launch = true
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Storefront load is request-driven, so it tracks CPU rather than queue depth.
resource "aws_autoscaling_policy" "storefront_cpu" {
  name                   = "${var.name_prefix}-app-cpu-target"
  autoscaling_group_name = aws_autoscaling_group.storefront.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = var.cpu_target_percent
  }
}
