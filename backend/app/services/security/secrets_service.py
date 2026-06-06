import os
import json
import logging
from uuid import UUID
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class SecretsService:
    """Manages tenant-scoped secrets and credentials.

    In production/staging, connects to AWS Secrets Manager.
    In local development, falls back to a JSON file store.
    """

    def __init__(self) -> None:
        self.env = os.getenv("ENVIRONMENT", "local")
        # Use AWS if not local AND credentials appear to be present (static or container IAM role)
        self.use_aws = self.env != "local" and (
            os.getenv("AWS_ACCESS_KEY_ID") is not None or 
            os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI") is not None
        )
        # Store local secrets in the app data/scratch directory for isolation
        self.local_store_path = os.getenv(
            "LOCAL_SECRETS_PATH", 
            os.path.join(os.path.dirname(__file__), "local_secrets.json")
        )

    def _load_local_store(self) -> dict:
        if not os.path.exists(self.local_store_path):
            return {}
        try:
            with open(self.local_store_path, "r") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Failed to load local secrets store, starting fresh: %s", exc)
            return {}

    def _save_local_store(self, data: dict) -> None:
        try:
            with open(self.local_store_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save local secrets store: %s", exc)

    def save_tenant_credentials(self, tenant_id: UUID, integration: str, credentials: dict) -> None:
        """Persist integration-specific credentials for a given tenant."""
        secret_name = f"company-brain/tenant-{tenant_id}/{integration}"
        if self.use_aws:
            try:
                client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
                try:
                    client.create_secret(
                        Name=secret_name,
                        SecretString=json.dumps(credentials),
                        Description=f"Credentials for tenant {tenant_id} and integration {integration}"
                    )
                    logger.info("AWS Secrets Manager: created secret %s", secret_name)
                except client.exceptions.ResourceExistsException:
                    client.put_secret_value(
                        SecretId=secret_name,
                        SecretString=json.dumps(credentials)
                    )
                    logger.info("AWS Secrets Manager: updated secret %s", secret_name)
            except ClientError as e:
                logger.error("AWS Secrets Manager error saving credentials: %s", e)
                raise RuntimeError(f"Failed to save secrets in Secrets Manager: {e}") from e
        else:
            # Fallback to local file store
            data = self._load_local_store()
            key = f"{tenant_id}:{integration}"
            data[key] = credentials
            self._save_local_store(data)
            logger.info("Local Secrets Store: saved credentials for tenant %s integration %s", tenant_id, integration)

    def get_tenant_credentials(self, tenant_id: UUID, integration: str) -> dict:
        """Retrieve integration-specific credentials for a given tenant."""
        secret_name = f"company-brain/tenant-{tenant_id}/{integration}"
        if self.use_aws:
            try:
                client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
                response = client.get_secret_value(SecretId=secret_name)
                return json.loads(response["SecretString"])
            except ClientError as e:
                logger.error("AWS Secrets Manager error retrieving credentials for %s: %s", secret_name, e)
                return {}
        else:
            data = self._load_local_store()
            key = f"{tenant_id}:{integration}"
            return data.get(key, {})
