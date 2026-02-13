import httpx
import logging
from typing import Dict, Optional

logger = logging.getLogger("momsclub_api")

import os
MOMSCLUB_API = os.getenv("MOMSCLUB_API", "http://127.0.0.1:8000")


async def check_momsclub_subscription(telegram_id: int) -> Dict:
    """
    Проверяет подписку в Moms Club.
    
    Returns:
        {"status": "active/expired/none/error", "end_date": str|None, "level": str|None}
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{MOMSCLUB_API}/api/vpn/subscription/{telegram_id}")
            if resp.status_code == 200:
                return resp.json()
            return {"status": "error", "end_date": None, "level": None}
    except Exception as e:
        logger.warning(f"check_momsclub_subscription error: {e}")
        return {"status": "error", "end_date": None, "level": None}


async def is_admin(telegram_id: int) -> bool:
    """Проверяет является ли пользователь VIP для VPN"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{MOMSCLUB_API}/api/vpn/is_admin/{telegram_id}")
            if resp.status_code == 200:
                return resp.json().get("is_admin", False)
    except Exception as e:
        logger.warning(f"is_admin error: {e}")
    return False


async def get_user_ip_limit(telegram_id: int) -> Optional[int]:
    """Получает лимит устройств для пользователя"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{MOMSCLUB_API}/api/vpn/is_admin/{telegram_id}")
            if resp.status_code == 200:
                return resp.json().get("ip_limit", 2)
    except Exception as e:
        logger.warning(f"get_ip_limit error: {e}")
    return 2


async def buy_device(telegram_id: int) -> Optional[str]:
    """Создаёт платёж на +1 устройство, возвращает URL оплаты"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{MOMSCLUB_API}/api/vpn/device/buy",
                json={"telegram_id": telegram_id}
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return data.get("payment_url")
    except Exception as e:
        logger.warning(f"buy_device error: {e}")
    return None
