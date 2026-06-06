# Trust policy for ECS task execution role
data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ECS Execution Role (used to pull images and fetch secrets)
resource "aws_iam_role" "ecs_execution" {
  name               = "company-brain-ecs-execution-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json

  tags = {
    Name        = "company-brain-ecs-execution-role-${var.environment}"
    Environment = var.environment
  }
}

# Managed Policy for standard ECS Execution rights
resource "aws_iam_role_policy_attachment" "ecs_execution_standard" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Custom policy to allow fetching specific secrets from Secrets Manager
resource "aws_iam_policy" "ecs_execution_secrets" {
  name        = "company-brain-ecs-secrets-policy-${var.environment}"
  description = "Allows fetching encrypted secret configurations from Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "kms:Decrypt"
        ]
        Resource = [
          "*" # For staging simplifications, or limit to aws_secretsmanager_secret.config.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_secrets_attach" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = aws_iam_policy.ecs_execution_secrets.arn
}

# ECS Task Role (used by the running application itself)
resource "aws_iam_role" "ecs_task" {
  name               = "company-brain-ecs-task-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json

  tags = {
    Name        = "company-brain-ecs-task-role-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_iam_policy" "ecs_task_policy" {
  name        = "company-brain-ecs-task-policy-${var.environment}"
  description = "Allows writing logs and general interaction with cloud services"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_policy_attach" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.ecs_task_policy.arn
}
