output "vpc_id" {
  value       = aws_vpc.main.id
  description = "The ID of the created VPC"
}

output "alb_dns_name" {
  value       = aws_lb.main.dns_name
  description = "Public DNS name of the Application Load Balancer"
}

output "ecs_cluster_name" {
  value       = aws_ecs_cluster.main.name
  description = "The name of the ECS cluster"
}

output "backend_ecr_url" {
  value       = aws_ecr_repository.backend.repository_url
  description = "Docker registry URL for the backend API service"
}

output "worker_ecr_url" {
  value       = aws_ecr_repository.worker.repository_url
  description = "Docker registry URL for the Celery worker service"
}

output "secrets_manager_arn" {
  value       = aws_secretsmanager_secret.config.arn
  description = "The ARN of the configuration secrets in AWS Secrets Manager"
}
