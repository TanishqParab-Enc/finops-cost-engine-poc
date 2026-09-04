resource "aws_cloudwatch_log_group" "app" {
  name              = "/aws/${var.name_prefix}/application"
  retention_in_days = var.retention_days

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/${var.name_prefix}/access"
  retention_in_days = var.retention_days

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "${var.name_prefix}-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "Web tier CPU sustained above 80%"
  treat_missing_data  = "notBreaching"

  dimensions = {
    AutoScalingGroupName = var.autoscaling_group_name
  }

  tags = var.tags
}
