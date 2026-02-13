#!/usr/bin/env python3
"""
Cron job for syncing VPN user statuses with subscriptions.

Usage:
    python sync_vpn_subscriptions.py [--dry-run] [--notify]

Options:
    --dry-run   Only check, don't make changes
    --notify    Send Telegram notifications on status changes

Cron setup (every hour):
    0 * * * * cd /root/home/momsvpn-bot && /root/home/momsvpn-bot/venv/bin/python cron/sync_vpn_subscriptions.py >> /var/log/vpn_sync.log 2>&1
"""

import asyncio
import sys
import os
import logging
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("vpn_sync")


async def main(dry_run: bool = False, send_notifications: bool = False):
    """Main sync function."""
    from app.bot.services.subscription_sync import subscription_sync_service
    from app.api.services.remnawave import remnawave_service as marzban_service
    
    logger.info("=" * 50)
    logger.info(f"VPN Subscription Sync started at {datetime.now()}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}, Notifications: {send_notifications}")
    logger.info("=" * 50)
    
    if dry_run:
        # In dry run mode, just report what would be changed
        all_users = await marzban_service.get_all_users()
        if not all_users:
            logger.info("No users found in Marzban")
            return
        
        would_enable = 0
        would_disable = 0
        
        for user in all_users:
            username = user.get("username", "")
            if not username.startswith("user_"):
                continue
            
            try:
                telegram_id = int(username.replace("user_", ""))
            except ValueError:
                continue
            
            current_status = user.get("status", "active")
            has_access = await subscription_sync_service.check_subscription_status(telegram_id)
            
            if has_access and current_status == "disabled":
                logger.info(f"  [WOULD ENABLE] user_{telegram_id}: has active subscription but VPN disabled")
                would_enable += 1
            elif not has_access and current_status == "active":
                logger.info(f"  [WOULD DISABLE] user_{telegram_id}: subscription expired but VPN active")
                would_disable += 1
        
        logger.info("-" * 50)
        logger.info(f"Dry run complete. Would enable: {would_enable}, Would disable: {would_disable}")
        return
    
    # Live sync
    stats = await subscription_sync_service.sync_all_users(send_notifications=send_notifications)
    
    logger.info("-" * 50)
    logger.info(f"Sync complete!")
    logger.info(f"  Checked: {stats.get('checked', 0)}")
    logger.info(f"  Enabled: {stats.get('enabled', 0)}")
    logger.info(f"  Disabled: {stats.get('disabled', 0)}")
    logger.info(f"  No change: {stats.get('no_change', 0)}")
    logger.info(f"  Errors: {stats.get('errors', 0)}")
    logger.info("=" * 50)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    send_notifications = "--notify" in sys.argv
    
    asyncio.run(main(dry_run=dry_run, send_notifications=send_notifications))
