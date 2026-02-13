"""
Remnawave Service - замена MarzbanService для работы с Remnawave API.
Полная совместимость с существующим кодом бота.
"""

import httpx
import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


class RemnawaveService:
    """Сервис для работы с Remnawave API (замена MarzbanService)."""
    
    def __init__(self):
        self.base_url = os.getenv("REMNAWAVE_URL", "https://panel.momscommunity.ru:444")
        self.api_key = os.getenv("REMNAWAVE_API_KEY")
        # SSL verification - use env var for self-signed certs
        verify_ssl = os.getenv("REMNAWAVE_VERIFY_SSL", "true").lower() != "false"
        self.client = httpx.AsyncClient(timeout=30.0, verify=verify_ssl)
        
        if not self.api_key:
            logger.warning("REMNAWAVE_API_KEY not set!")
    
    async def _get_headers(self) -> Dict[str, str]:
        """Заголовки авторизации для Remnawave API."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    # ==================== ПОЛЬЗОВАТЕЛИ ====================
    
    async def get_user(self, username: str, fetch_devices: bool = False) -> Optional[Dict[str, Any]]:
        """
        Получить пользователя по username.
        Совместимость: принимает username (user_123), ищет в Remnawave.
        fetch_devices: Если True, загружает список устройств через SSH.
        """
    async def get_user(self, username: str, fetch_devices: bool = False) -> Optional[Dict[str, Any]]:
        """
        Получить информацию о пользователе.
        Ищет по всем страницам через get_all_users, так как прямой поиск по API сломан.
        """
        try:
            # Получаем всех пользователей (с учетом пагинации)
            all_users = await self.get_all_users()
            
            target_user = None
            
            # 1. Точное совпадение username
            for user in all_users:
                if user.get("username") == username:
                    target_user = user
                    break
            
            # 2. Поиск по Telegram ID (если username = user_123)
            if not target_user and username.startswith("user_"):
                try:
                    tg_id = int(username.replace("user_", ""))
                    for user in all_users:
                        if user.get("telegram_id") == tg_id:
                            target_user = user
                            break
                except ValueError:
                    pass
            
            if target_user:
                # Если нужны устройства, подгружаем через SSH (так как get_all_users их не грузит)
                if fetch_devices:
                    # В target_user['sub_last_user_agent'] лежит сырая строка, если мы её не обогатили
                    # Но нам нужен UUID (он есть в hidden поле _uuid)
                    
                    user_uuid = target_user.get("_uuid")
                    if user_uuid:
                        model = await self._get_device_model_from_ssh(user_uuid)
                        if model:
                            target_user["sub_last_user_agent"] = model
                            
                return target_user
                
            return None
            
        except Exception as e:
            logger.error(f"Error fetching user {username}: {e}")
            return None
    
    async def get_all_users(self) -> List[Dict[str, Any]]:
        """Получить всех пользователей из Remnawave (с поддержкой пагинации)."""
        all_users = []
        # Используем running offset, так как сервер может возвращать меньше записей, чем limit
        current_offset = 0
        limit = 50 # Запрашиваем по 50, но сервер может отдать 25
        
        try:
            headers = await self._get_headers()
            
            while True:
                # API использует параметр 'start' для смещения
                response = await self.client.get(
                    f"{self.base_url}/api/users?start={current_offset}&limit={limit}",
                    headers=headers
                )
                
                if response.status_code == 200:
                    data = response.json()
                    response_data = data.get("response", {})
                    users = response_data.get("users", [])
                    
                    if not users:
                        break
                        
                    for u in users:
                        # Логируем имена для отладки
                        # logger.info(f"Found user: {u.get('username')} (ID: {u.get('telegramId')})")
                        all_users.append(await self._convert_user_format(u))
                    
                    # Увеличиваем смещение на реальное количество полученных пользователей
                    users_count = len(users)
                    current_offset += users_count
                    
                    # Если вернулось меньше чем мы ожидали (например 0), то выходим
                    if users_count == 0:
                        break
                        
                    # Защита от бесконечного цикла (5000 пользователей)
                    if current_offset > 5000:
                        logger.warning("Pagination limit reached (5000 users)")
                        break
                else:
                    logger.error(f"Error fetching users offset {current_offset}: {response.status_code}")
                    break
            
            logger.info(f"Total users fetched: {len(all_users)}. Usernames: {[u.get('username') for u in all_users]}")
            return all_users
            
        except Exception as e:
            logger.error(f"Error fetching all users: {e}")
            return []
    
    async def create_or_update_user(self, telegram_id: int, username: str = "User", ip_limit: int = 2) -> Dict[str, Any]:
        """
        Создать пользователя в Remnawave или вернуть существующего.
        ip_limit: 0 - безлимит, >0 - лимит
        """
        # Используем username если есть, иначе user_{id}
        if username and username != "User":
            # Очищаем username от спецсимволов если нужно, но обычно они ок
            remnawave_username = username
        else:
            remnawave_username = f"user_{telegram_id}"
        
        # Проверяем существование
        existing_user = await self.get_user(remnawave_username)
        if existing_user:
            logger.info(f"User {remnawave_username} already exists in Remnawave.")
            return existing_user
        
        headers = await self._get_headers()
        
        # 300 GB лимит -> 0 (Unlimited)
        TRAFFIC_LIMIT_UNKNOWN = 0
        
        # Дата истечения — 10 лет вперёд (фактически бессрочно, управляется через enable/disable)
        from datetime import timedelta
        expire_date = (datetime.utcnow() + timedelta(days=3650)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        # UUID Default-Squad для привязки к хостам
        DEFAULT_SQUAD_UUID = "28dc32e7-4091-4ef6-84e5-9cd7c5779b90"
        
        payload = {
            "username": remnawave_username,
            "telegramId": telegram_id,
            "description": f"TG: @{username}" if username != "User" else f"TG ID: {telegram_id}",
            "trafficLimitBytes": TRAFFIC_LIMIT_UNKNOWN,
            "trafficLimitStrategy": "NO_RESET",
            "status": "ACTIVE",
            "expireAt": expire_date,
            "hwidDeviceLimit": ip_limit,
            "activeInternalSquads": [DEFAULT_SQUAD_UUID]  # Привязка к хостам VPN
        }
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/users",
                json=payload,
                headers=headers
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                user = data.get("response", data)
                logger.info(f"Created new user {remnawave_username} in Remnawave.")
                return await self._convert_user_format(user)
            elif response.status_code == 400 and "User username already exists" in response.text:
                logger.warning(f"User {remnawave_username} exists (400), trying to find by Telegram ID...")
                # Попытка найти пользователя по Telegram ID через get_all_users (или другой метод если есть)
                # Remnawave API не имеет прямого поиска по TG ID, поэтому перебираем (кэширование бы не помешало)
                all_users = await self.get_all_users()
                for user in all_users:
                    if str(user.get("telegram_id")) == str(telegram_id):
                        return user
                
                # Если не нашли по ID, пробуем принудительно вернуть по username
                # Пытаемся сделать прямой запрос, вдруг API поддерживает /api/users/{username}
                try:
                    direct_resp = await self.client.get(f"{self.base_url}/api/users/{remnawave_username}", headers=headers)
                    if direct_resp.status_code == 200:
                        direct_data = direct_resp.json()
                        # Remnawave возвращает {response: {...}}
                        user_obj = direct_data.get("response", direct_data)
                        logger.info(f"Direct fetch for {remnawave_username} succeeded.")
                        return await self._convert_user_format(user_obj)
                except:
                    pass

                # Если ничего не помогло, кидаем ошибку
                logger.error(f"User {remnawave_username} reported as existing but not found by search.")
                raise Exception(f"User exists but cannot be retrieved: {response.text}")

            else:
                logger.error(f"Failed to create user: {response.status_code} - {response.text}")
                raise Exception(f"HTTP {response.status_code}: {response.text}")
                
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            raise
    
    async def enable_user(self, username: str) -> bool:
        """Активировать пользователя (status: ACTIVE)."""
        return await self._update_user_status(username, "ACTIVE")
    
    async def disable_user(self, username: str) -> bool:
        """Заблокировать пользователя (status: DISABLED)."""
        return await self._update_user_status(username, "DISABLED")
    
    async def _update_user_status(self, username: str, status: str) -> bool:
        """Обновить статус пользователя."""
        try:
            # Сначала получаем UUID пользователя
            user = await self.get_user(username)
            if not user:
                logger.warning(f"User {username} not found, cannot update status")
                return False
            
            uuid = user.get("_uuid")
            if not uuid:
                logger.error(f"User {username} has no UUID")
                return False
            
            headers = await self._get_headers()
            response = await self.client.put(
                f"{self.base_url}/api/users/{uuid}",
                json={"status": status},
                headers=headers
            )
            
            if response.status_code == 200:
                logger.info(f"{'Enabled' if status == 'ACTIVE' else 'Disabled'} user {username}")
                return True
            
            logger.error(f"Failed to update status: {response.status_code}")
            return False
            
        except Exception as e:
            logger.error(f"Error updating user status: {e}")
            return False
    
    async def delete_user(self, username: str) -> bool:
        """Удалить пользователя из Remnawave."""
        try:
            user = await self.get_user(username)
            if not user:
                logger.info(f"User {username} not found, nothing to delete")
                return True
            
            uuid = user.get("_uuid")
            headers = await self._get_headers()
            
            response = await self.client.delete(
                f"{self.base_url}/api/users/{uuid}",
                headers=headers
            )
            
            if response.status_code in [200, 204]:
                logger.info(f"Deleted user {username}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error deleting user: {e}")
            return False
    
    # ==================== ПОДПИСКА ====================
    
    async def get_subscription_info(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Получить информацию о подписке для бота."""
        user = await self.get_user(f"user_{telegram_id}")
        if not user:
            return None
        
        return {
            "subscription_url": user.get("subscription_url", ""),
            "status": user.get("status", ""),
            "data_limit": user.get("data_limit", 0),
            "used_traffic": user.get("used_traffic", 0),
            "expire": user.get("expire", 0),
            "links": user.get("links", []),
            "last_device": self._parse_user_agent(user.get("sub_last_user_agent", "")),
            "online_at": user.get("online_at")
        }
    
    async def revoke_subscription(self, username: str) -> Dict[str, Any]:
        """Перевыпустить ключ подписки (regenerate UUID)."""
        try:
            user = await self.get_user(username)
            if not user:
                raise Exception(f"User {username} not found")
            
            uuid = user.get("_uuid")
            headers = await self._get_headers()
            
            # Remnawave endpoint для revoke
            response = await self.client.post(
                f"{self.base_url}/api/users/{uuid}/revoke-subscription",
                headers=headers
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"Revoke failed: {response.status_code}")
                
        except Exception as e:
            raise Exception(f"Revoke failed: {e}")
    
    # ==================== СЕРВЕР ====================
    
    async def get_server_status(self) -> Dict[str, Any]:
        """Получить статус сервера."""
        try:
            headers = await self._get_headers()
            response = await self.client.get(
                f"{self.base_url}/api/system/stats",
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                stats = data.get("response", {})
                return {
                    "online": True,
                    "online_users": stats.get("onlineUsers", 0),
                    "cpu_usage": stats.get("cpu", {}).get("usage", 0),
                    "mem_usage": stats.get("memory", {}).get("usagePercent", 0)
                }
        except Exception as e:
            logger.error(f"Error checking server status: {e}")
        
        return {"online": False, "online_users": 0, "cpu_usage": 0, "mem_usage": 0}
    
    # ==================== УТИЛИТЫ ====================
    
    async def _convert_user_format(self, remnawave_user: Dict[str, Any], fetch_devices: bool = False) -> Dict[str, Any]:
        """
        Конвертировать формат Remnawave в формат Marzban для совместимости.
        fetch_devices: Если True, делает SSH запрос за списком устройств (медленно!).
        """
        traffic = remnawave_user.get("userTraffic", {})
        
        # Конвертация expire
        expire_at = remnawave_user.get("expireAt")
        expire_timestamp = 0
        if expire_at:
            try:
                dt = datetime.fromisoformat(expire_at.replace("Z", "+00:00"))
                expire_timestamp = int(dt.timestamp())
            except:
                pass
        
        user_dict = {
            # Сохраняем оригинальный UUID для API вызовов
            "_uuid": remnawave_user.get("uuid"),
            
            # Совместимость с Marzban полями
            "username": remnawave_user.get("username"),
            "status": remnawave_user.get("status", "ACTIVE").lower(),  # active/disabled
            "data_limit": remnawave_user.get("trafficLimitBytes", 0),
            "used_traffic": traffic.get("usedTrafficBytes", 0),
            "expire": expire_timestamp,
            "subscription_url": remnawave_user.get("subscriptionUrl", ""),
            "sub_last_user_agent": remnawave_user.get("subLastUserAgent", ""),
            "online_at": traffic.get("onlineAt"),
            "note": remnawave_user.get("description", ""),
            
            # Дополнительные поля Remnawave
            "telegram_id": remnawave_user.get("telegramId"),
            "short_uuid": remnawave_user.get("shortUuid"),
            "hwid_device_limit": remnawave_user.get("hwidDeviceLimit")
        }
        
        # Пытаемся получить красивую модель устройства через SSH (ТОЛЬКО ЕСЛИ ЗАПРОШЕНО)
        if fetch_devices:
            try:
                user_uuid = remnawave_user.get("uuid")
                logger.info(f"fetch_devices=True, user_uuid={user_uuid}")
                if user_uuid:
                    model = await self._get_device_model_from_ssh(user_uuid)
                    logger.info(f"SSH returned model: {model[:100] if model else 'None'}...")
                    if model is not None:
                        user_dict["sub_last_user_agent"] = model
            except Exception as e:
                logger.error(f"Error fetching devices via SSH: {e}")
            
        return user_dict
    
    async def _get_device_model_from_ssh(self, user_uuid: str) -> Optional[str]:
        """
        Получает список устройств напрямую из БД Remnawave через SSH туннель.
        Возвращает отформатированную строку с нумерованным списком.
        """
        try:
            import asyncio
            
            # Получаем топ-5 последних активных устройств
            cmd = (
                f"ssh -i /root/.ssh/id_rsa_remnawave -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=3 "
                f"root@85.192.29.22 "
                f"\"docker exec root-postgres-1 psql -U remnawave -d remnawave -t -c "
                f"\\\"SELECT device_model FROM hwid_user_devices WHERE user_uuid = '{user_uuid}' ORDER BY created_at ASC LIMIT 5;\\\"\""
            )
            
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if stdout:
                output = stdout.decode().strip()
                if not output:
                    return ""
                    
                # Разбиваем на строки и убираем дубликаты, сохраняя порядок
                raw_models = [line.strip() for line in output.split('\n') if line.strip()]
                unique_models = []
                seen = set()
                
                for model in raw_models:
                    if model not in seen:
                        unique_models.append(model)
                        seen.add(model)
                
                if not unique_models:
                    return ""
                
                # Формируем красивый список:
                # 1. 📱 iPhone 14 Pro Max
                # 2. 🤖 Samsung Galaxy S21
                formatted_lines = []
                for i, model in enumerate(unique_models, 1):
                    # Добавляем эмодзи если его нет
                    prefix = ""
                    if not any(x in model for x in ["📱", "🤖", "💻", ""]):
                        if "iPhone" in model or "iPad" in model:
                            prefix = "📱 "
                        elif "Android" in model or "Samsung" in model or "Pixel" in model or "Xiaomi" in model:
                            prefix = "🤖 "
                        elif "Mac" in model:
                            prefix = "💻 "
                        else:
                            prefix = "📱 "
                    
                    formatted_lines.append(f"{i}. {prefix}{model}")
                    
                return "\n".join(formatted_lines)
            
            # Если stdout пустой, но без ошибок (proc.returncode == 0), значит устройств нет
            if proc.returncode == 0:
                return ""
                
        except Exception:
            pass
        
        return None
        
    async def reset_user_devices(self, telegram_id: int) -> bool:
        """
        Сброс привязки устройств (очистка таблицы hwid_user_devices) через SSH.
        """
        try:
            user = await self.get_user(f"user_{telegram_id}")
            if not user:
                return False
                
            user_uuid = user.get("_uuid")
            if not user_uuid:
                return False
            
            import asyncio
            
            cmd = (
                f"ssh -i /root/.ssh/id_rsa_remnawave -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=3 "
                f"root@85.192.29.22 "
                f"\"docker exec root-postgres-1 psql -U remnawave -d remnawave -c "
                f"\\\"DELETE FROM hwid_user_devices WHERE user_uuid = '{user_uuid}';\\\"\""
            )
            
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Ждем завершения
            await proc.communicate()
            return proc.returncode == 0
            
        except Exception as e:
            logger.error(f"Error resetting devices: {e}")
            return False

    def _parse_user_agent(self, ua: str) -> Optional[str]:
        """Парсинг User-Agent для определения устройства."""
        # Этот метод теперь используется как fallback, если SSH не вернул модель
        if not ua:
            return None
        
        # Если это уже отформатированная модель из SSH (начинается с эмодзи), возвращаем как есть
        if ua.startswith("📱") or ua.startswith("") or ua.startswith("🤖"):
            return ua

        import re
        ua_lower = ua.lower()
        
        # Парсинг Happ User-Agent (если SSH не сработал)
        if "happ" in ua_lower:
            if "ios" in ua_lower or "darwin" in ua_lower:
                return " <b>iPhone</b> (Happ)"
            if "android" in ua_lower:
                return "🤖 <b>Android</b> (Happ)"
            return "📱 <b>Mobile</b>"

        if "ios" in ua_lower or "iphone" in ua_lower or "ipad" in ua_lower:
            device = "iPad" if "ipad" in ua_lower else "iPhone"
            return f" <b>{device}</b>"
        
        elif "android" in ua_lower:
            return f"🤖 <b>Android</b>"
        
        elif "windows" in ua_lower:
            return "💻 <b>Windows PC</b>"
        
        elif "mac" in ua_lower or "darwin" in ua_lower:
            return "🍎 <b>Mac</b>"
            
        return "📱 <b>Устройство</b>"


# Singleton instance
remnawave_service = RemnawaveService()

# Алиас для обратной совместимости
marzban_service = remnawave_service
