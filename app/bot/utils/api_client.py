"""
API Client for Bot-to-Backend communication.
Uses Marzban service directly for production deployment.
"""
import logging

logger = logging.getLogger(__name__)


class APIClient:
    """API Client that uses Marzban service directly."""
    
    def __init__(self):
        pass

    async def close(self):
        """No session to close in direct mode."""
        pass

    async def create_user(self, telegram_id: int, username: str, full_name: str, ip_limit: int = 2):
        """Create user via Marzban directly."""
        try:
            from app.api.services.remnawave import remnawave_service as marzban_service
            return await marzban_service.create_or_update_user(telegram_id, username, ip_limit=ip_limit)
        except Exception as e:
            logger.error(f"create_user error: {e}")
            return None

    async def reset_user_subscription(self, telegram_id: int):
        """Reset user subscription (revoke UUID)."""
        try:
            from app.api.services.remnawave import remnawave_service as marzban_service
            username = f"user_{telegram_id}"
            # Пробуем найти по username если есть
            return await marzban_service.revoke_subscription(username)
        except Exception as e:
            logger.error(f"reset_user_subscription error: {e}")
            return None

    async def reset_devices(self, telegram_id: int) -> bool:
        """Reset bound devices for user via SSH."""
        try:
            from app.api.services.remnawave import remnawave_service as marzban_service
            return await marzban_service.reset_user_devices(telegram_id)
        except Exception as e:
            logger.error(f"reset_devices error: {e}")
            return False

    async def get_user(self, telegram_id: int):
        """Get user from Marzban directly."""
        try:
            from app.api.services.remnawave import remnawave_service as marzban_service
            username = f"user_{telegram_id}"
            return await marzban_service.get_user(username)
        except Exception as e:
            logger.error(f"get_user error: {e}")
            return None

    async def get_subscription(self, telegram_id: int, fetch_devices: bool = False):
        """Get subscription data from Marzban directly."""
        try:
            from app.api.services.remnawave import remnawave_service as marzban_service
            username = f"user_{telegram_id}"
            user = await marzban_service.get_user(username, fetch_devices=fetch_devices)
            if user:
                return {
                    "subscription_url": user.get("subscription_url"),
                    "traffic_used": user.get("used_traffic", 0),
                    "traffic_limit": user.get("data_limit", 0),
                    "expire": user.get("expire"),
                    "status": user.get("status"),
                    "sub_last_user_agent": user.get("sub_last_user_agent", ""),
                    "online_at": user.get("online_at")
                }
            return None
        except Exception as e:
            logger.error(f"get_subscription error: {e}")
            return None

    async def create_payment(self, telegram_id: int, amount: float, description: str):
        """Create payment - placeholder for YooKassa integration."""
        logger.warning("Payment system not integrated yet")
        return None

    async def get_server_status(self):
        """Get server status from Marzban directly."""
        try:
            from app.api.services.remnawave import remnawave_service as marzban_service
            return await marzban_service.get_server_status()
        except Exception as e:
            logger.error(f"get_server_status error: {e}")
            return {"online": False}


# Singleton instance
    async def reset_user_subscription(self, telegram_id: int):
        """Reset user subscription URL (regenerate keys without resetting traffic)"""
        try:
            from app.api.services.remnawave import remnawave_service as marzban_service
            username = f"user_{telegram_id}"
            # Revoke subscription to regenerate UUID
            result = await marzban_service.revoke_subscription(username)
            return result
        except Exception as e:
            raise Exception(f"Failed to reset subscription: {e}")


api = APIClient()
