# Log groups are created here rather than implicitly by the instances, so
# retention is governed (an unbounded log group is a real cost leak) and the
# IAM policies can be scoped to these exact ARNs.
resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.name_prefix}/storefront"
  retention_in_days = var.retention_days

  tags = merge(var.tags, { Name = "${var.name_prefix}-storefront-logs", Tier = "application" })
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/${var.name_prefix}/worker"
  retention_in_days = var.retention_days

  tags = merge(var.tags, { Name = "${var.name_prefix}-worker-logs", Tier = "worker" })
}

resource "aws_cloudwatch_metric_alarm" "app_cpu" {
  alarm_name          = "${var.name_prefix}-storefront-cpu-high"
  alarm_description   = "Storefront tier is saturating CPU"
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 80
  period              = 300
  evaluation_periods  = 2
  treat_missing_data  = "notBreaching"

  dimensions = {
    AutoScalingGroupName = var.app_autoscaling_group_name
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-storefront-cpu-high" })
}

# 5xx from the target group means the storefront itself is failing, which the
# ALB's own health checks will not surface on their own.
resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.name_prefix}-storefront-5xx"
  alarm_description   = "Storefront is returning server errors"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 10
  period              = 300
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-storefront-5xx" })
}

resource "aws_cloudwatch_metric_alarm" "database_cpu" {
  alarm_name          = "${var.name_prefix}-database-cpu-high"
  alarm_description   = "Order database is CPU constrained"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 75
  period              = 300
  evaluation_periods  = 2
  treat_missing_data  = "notBreaching"

  dimensions = {
    DBInstanceIdentifier = var.database_identifier
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-database-cpu-high" })
}

# The business signal: orders are arriving faster than they are fulfilled.
resource "aws_cloudwatch_metric_alarm" "order_backlog" {
  alarm_name          = "${var.name_prefix}-order-backlog"
  alarm_description   = "Order queue is growing faster than the worker tier drains it"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Average"
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.queue_depth_threshold
  period              = 300
  evaluation_periods  = 2
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = var.order_queue_name
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-order-backlog" })
}

# Anything here is an order that failed every retry - always worth a human.
resource "aws_cloudwatch_metric_alarm" "dead_letters" {
  alarm_name          = "${var.name_prefix}-order-dead-letters"
  alarm_description   = "Orders have failed processing and landed in the dead-letter queue"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  period              = 300
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = var.order_dlq_name
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-order-dead-letters" })
}

resource "aws_cloudwatch_metric_alarm" "cache_evictions" {
  alarm_name          = "${var.name_prefix}-cache-evictions"
  alarm_description   = "Redis is evicting keys, so the cache is undersized"
  namespace           = "AWS/ElastiCache"
  metric_name         = "Evictions"
  statistic           = "Sum"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 1000
  period              = 300
  evaluation_periods  = 2
  treat_missing_data  = "notBreaching"

  dimensions = {
    ReplicationGroupId = var.cache_replication_group_id
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-cache-evictions" })
}
