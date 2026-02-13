"""
Subscription Sync Service - syncs VPN key status with subscription status.

When subscription expires → disable VPN key in Marzban
When subscription is renewed → enable VPN key in Marzban
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SubscriptionSyncService:
    """Service for syncing VPN user statuses with subscription status."""
    
    def __init__(self):
        self.stats = {
            "checked": 0,
            "enabled": 0,
            "disabled": 0,
            "errors": 0,
            "no_change": 0
        }
    
    async def check_subscription_status(self, telegram_id: int) -> bool:
        """
        Check if user has active subscription (MC or local).
        Returns True if user has access, False otherwise.
        """
        from app.bot.utils.momsclub_api import check_momsclub_subscription
        from app.bot.utils.users_db import has_local_subscription
        
        # Check local subscription first (faster)
        if has_local_subscription(telegram_id):
            return True
        
        # Check Moms Club subscription
        try:
            sub_data = await check_momsclub_subscription(telegram_id)
            if sub_data.get("status") == "active":
                return True
        except Exception as e:
            logger.error(f"Error checking MC subscription for {telegram_id}: {e}")
        
        return False
    
    async def sync_user(self, telegram_id: int, marzban_status: str) -> str:
        """
        Sync single user's VPN status with subscription.
        
        Returns:
            "enabled" - user was enabled
            "disabled" - user was disabled  
            "no_change" - no action needed
            "error" - error occurred
        """
        from app.api.services.remnawave import remnawave_service as marzban_service
        
        username = f"user_{telegram_id}"
        has_access = await self.check_subscription_status(telegram_id)
        
        try:
            # User has access but VPN is disabled → enable
            if has_access and marzban_status == "disabled":
                success = await marzban_service.enable_user(username)
                if success:
                    logger.info(f"✅ Enabled VPN for user {telegram_id} (subscription active)")
                    return "enabled"
                else:
                    return "error"
            
            # User has no access but VPN is active → disable
            elif not has_access and marzban_status == "active":
                success = await marzban_service.disable_user(username)
                if success:
                    logger.info(f"🔒 Disabled VPN for user {telegram_id} (subscription expired)")
                    return "disabled"
                else:
                    return "error"
            
            # No change needed
            return "no_change"
            
        except Exception as e:
            logger.error(f"Error syncing user {telegram_id}: {e}")
            return "error"
    
    async def sync_all_users(self, send_notifications: bool = False) -> Dict:
        """
        Sync all VPN users with their subscription status.
        
        Args:
            send_notifications: If True, send Telegram notifications on status change
            
        Returns:
            Dict with sync statistics
        """
        from app.api.services.remnawave import remnawave_service as marzban_service
        
        # Reset stats
        self.stats = {
            "checked": 0,
            "enabled": 0,
            "disabled": 0,
            "errors": 0,
            "no_change": 0,
            "started_at": datetime.now().isoformat()
        }
        
        # Get all Marzban users
        all_users = await marzban_service.get_all_users()
        if not all_users:
            logger.warning("No users found in Marzban")
            return self.stats
        
        for user in all_users:
            username = user.get("username", "")
            
            # Only process user_* accounts (Telegram users)
            if not username.startswith("user_"):
                continue
            
            try:
                telegram_id = int(username.replace("user_", ""))
            except ValueError:
                continue
            
            current_status = user.get("status", "active")
            
            # Sync this user
            result = await self.sync_user(telegram_id, current_status)
            
            self.stats["checked"] += 1
            if result == "enabled":
                self.stats["enabled"] += 1
                if send_notifications:
                    await self._send_enabled_notification(telegram_id)
            elif result == "disabled":
                self.stats["disabled"] += 1
                if send_notifications:
                    await self._send_disabled_notification(telegram_id)
            elif result == "error":
                self.stats["errors"] += 1
            else:
                self.stats["no_change"] += 1
        
        self.stats["finished_at"] = datetime.now().isoformat()
        logger.info(f"Sync completed: {self.stats}")
        return self.stats
    
    async def _send_enabled_notification(self, telegram_id: int):
        """Send notification when VPN is enabled."""
        try:
            from aiogram import Bot
            import os
            
            bot = Bot(token=os.getenv("BOT_TOKEN"))
            await bot.send_message(
                telegram_id,
                "✅ <b>Твой VPN ключ снова активен!</b>\n\n"
                "Подписка возобновлена, можешь пользоваться VPN 🎉",
                parse_mode="HTML"
            )
            await bot.session.close()
        except Exception as e:
            logger.error(f"Failed to send enabled notification to {telegram_id}: {e}")
    
    async def _send_disabled_notification(self, telegram_id: int):
        """Send notification when VPN is disabled."""
        try:
            from aiogram import Bot
            import os
            
            bot = Bot(token=os.getenv("BOT_TOKEN"))
            await bot.send_message(
                telegram_id,
                "⚠️ <b>Твой VPN ключ приостановлен</b>\n\n"
                "Подписка Mom's Club истекла.\n"
                "Возобнови подписку, чтобы продолжить пользоваться VPN 💝",
                parse_mode="HTML"
            )
            await bot.session.close()
        except Exception as e:
            logger.error(f"Failed to send disabled notification to {telegram_id}: {e}")


# Singleton instance
subscription_sync_service = SubscriptionSyncService()
