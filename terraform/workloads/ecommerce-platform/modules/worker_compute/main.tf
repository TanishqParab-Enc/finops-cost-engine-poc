resource "aws_launch_template" "worker" {
  name_prefix   = "${var.name_prefix}-worker-lt-"
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
    tags          = merge(var.tags, { Name = "${var.name_prefix}-worker", Tier = "worker" })
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Workers are not behind the load balancer: they poll SQS, so the group uses
# EC2 health checks and registers with no target group.
resource "aws_autoscaling_group" "worker" {
  name                = "${var.name_prefix}-worker-asg"
  vpc_zone_identifier = var.app_subnet_ids

  desired_capacity = var.desired_capacity
  min_size         = var.min_capacity
  max_size         = var.max_capacity

  health_check_type         = "EC2"
  health_check_grace_period = 120

  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${var.name_prefix}-worker"
    propagate_at_launch = true
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Backlog per instance is the honest signal for queue-driven work: CPU stays
# low while a worker waits on I/O, so CPU-based scaling would never fire.
resource "aws_autoscaling_policy" "worker_backlog" {
  name                   = "${var.name_prefix}-worker-backlog-target"
  autoscaling_group_name = aws_autoscaling_group.worker.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    target_value = var.backlog_target_per_instance

    customized_metric_specification {
      metric_name = "ApproximateNumberOfMessagesVisible"
      namespace   = "AWS/SQS"
      statistic   = "Average"

      metric_dimension {
        name  = "QueueName"
        value = var.queue_name
      }
    }
  }
}
