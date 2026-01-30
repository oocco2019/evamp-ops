"""
Security utilities: encryption, hashing, validation
"""
import hmac
import hashlib
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import settings


class EncryptionService:
    """
    Service for encrypting and decrypting sensitive data like API keys.
    Uses Fernet (symmetric encryption) with key from environment.
    """
    
    def __init__(self):
        """Initialize cipher with encryption key from settings"""
        try:
            self.cipher = Fernet(settings.ENCRYPTION_KEY.encode())
        except Exception as e:
            raise ValueError(
                f"Invalid ENCRYPTION_KEY. Generate with: "
                f"python -c \"from cryptography.fernet import Fernet; "
                f"print(Fernet.generate_key().decode())\". Error: {e}"
            )
    
    def encrypt(self, value: str) -> str:
        """
        Encrypt a string value.
        
        Args:
            value: Plain text string to encrypt
            
        Returns:
            Base64-encoded encrypted string
        """
        if not value:
            return ""
        return self.cipher.encrypt(value.encode()).decode()
    
    def decrypt(self, encrypted_value: str) -> str:
        """
        Decrypt an encrypted string.
        
        Args:
            encrypted_value: Base64-encoded encrypted string
            
        Returns:
            Decrypted plain text string
            
        Raises:
            ValueError: If decryption fails (invalid token or wrong key)
        """
        if not encrypted_value:
            return ""
        try:
            return self.cipher.decrypt(encrypted_value.encode()).decode()
        except InvalidToken:
            raise ValueError("Failed to decrypt value. Invalid token or wrong encryption key.")


class WebhookValidator:
    """Validate webhook signatures from external services"""
    
    @staticmethod
    def validate_ebay_webhook(
        payload: str,
        signature: str,
        secret: Optional[str] = None
    ) -> bool:
        """
        Verify that a webhook came from eBay using HMAC signature.
        
        Args:
            payload: Raw request body as string
            signature: X-EBAY-SIGNATURE header value
            secret: Webhook secret (defaults to settings.EBAY_WEBHOOK_SECRET)
            
        Returns:
            True if signature is valid, False otherwise
        """
        if not secret:
            secret = settings.EBAY_WEBHOOK_SECRET
        
        if not secret:
            # If no secret configured, accept all (for initial development)
            # TODO: Make this stricter in production
            return True
        
        expected_signature = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)


# Global instances
encryption_service = EncryptionService()
webhook_validator = WebhookValidator()
