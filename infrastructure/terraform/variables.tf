variable "aws_region" {
  type        = string
  description = "The target AWS region for deployment"
  default     = "us-east-1"
}

variable "environment" {
  type        = string
  description = "Environment name (e.g. staging, production)"
  default     = "staging"
}

variable "postgres_db_url" {
  type        = string
  description = "Connection string for Neon Postgres DB (sensitive)"
  sensitive   = true
}

variable "redis_url" {
  type        = string
  description = "Connection string for Upstash Redis cache & Celery broker (sensitive)"
  sensitive   = true
}

variable "weaviate_url" {
  type        = string
  description = "Weaviate Cloud Console instance URL"
}

variable "weaviate_api_key" {
  type        = string
  description = "Weaviate API authentication token (sensitive)"
  sensitive   = true
}

variable "neo4j_uri" {
  type        = string
  description = "Neo4j AuraDB Connection Bolt URI"
}

variable "neo4j_user" {
  type        = string
  description = "Neo4j database user name"
  default     = "neo4j"
}

variable "neo4j_password" {
  type        = string
  description = "Neo4j database password (sensitive)"
  sensitive   = true
}

variable "skill_signing_key" {
  type        = string
  description = "HMAC-SHA256 Key for signing synthesized skills (sensitive)"
  sensitive   = true
}

# LLM Providers
variable "openai_api_key" {
  type        = string
  description = "OpenAI API Key (sensitive)"
  sensitive   = true
  default     = ""
}

variable "gemini_api_key" {
  type        = string
  description = "Google Gemini API Key (sensitive)"
  sensitive   = true
  default     = ""
}

variable "anthropic_api_key" {
  type        = string
  description = "Anthropic API Key (sensitive)"
  sensitive   = true
  default     = ""
}

# Observability
variable "langfuse_public_key" {
  type        = string
  description = "Langfuse LLM Telemetry Public Key"
}

variable "langfuse_secret_key" {
  type        = string
  description = "Langfuse LLM Telemetry Secret Key (sensitive)"
  sensitive   = true
}

variable "langfuse_host" {
  type        = string
  description = "Langfuse telemetry ingestion API endpoint"
  default     = "https://us.cloud.langfuse.com"
}
