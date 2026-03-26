"""Pytest: ensure Settings env exists before app imports (valid Fernet key)."""
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://test:test@127.0.0.1:5432/evamp_ops_test",
)
if not os.environ.get("ENCRYPTION_KEY"):
    from cryptography.fernet import Fernet

    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
