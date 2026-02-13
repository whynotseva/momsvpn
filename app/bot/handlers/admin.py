"""
Admin Handler - Telegram bot admin commands.
/admin command with inline keyboard for management.
Enhanced with user details, traffic/days management.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import os
import logging
from datetime import datetime, timedelta

from app.bot.utils.api_client import APIClient

router = Router()
logger = logging.getLogger(__name__)

# Admin IDs (can be moved to .env)
ADMIN_IDS = [44054166]  # Add your Telegram ID


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return user_id in ADMIN_IDS


def extract_tg_username(user: dict) -> str:
    """Extract Telegram username from Marzban note field.
    Note format: 'TG ID: 123456 (username)'
    """
    import re
    note = user.get("note", "")
    if note:
        # Try to extract username from note
        match = re.search(r'\(([^)]+)\)', note)
        if match:
            username = match.group(1)
            if username and username != "User":
                return f"@{username}"
    # Fallback to internal username
    return user.get("username", "unknown")


class AdminStates(StatesGroup):
    """Admin FSM states for input."""
    waiting_add_days = State()
    waiting_add_traffic = State()
    current_username = State()
    waiting_search = State()  # NEW: search user
    waiting_local_sub = State()  # NEW: add local subscription


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    """Main admin menu keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users:0")],
        [InlineKeyboardButton(text="📋 Не подписчики MC", callback_data="admin:nonmc:0")],
        [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin:search")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="admin:close")]
    ])


@router.message(Command("admin"))
async def admin_command(message: Message):
    """Admin panel entry point."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    text = """
🔐 <b>Админ-панель MomsVPN</b>

Выберите раздел:
"""
    await message.answer(text, reply_markup=admin_menu_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery):
    """Show statistics."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    api = APIClient()
    try:
        # Get server status
        server = await api.get_server_status()
        
        # Get all users from Marzban via direct call
        from app.api.services.remnawave import remnawave_service as marzban_service
        users = await marzban_service.get_all_users()
        
        total_users = len(users) if users else 0
        active_users = sum(1 for u in users if u.get("status") == "active") if users else 0
        disabled_users = sum(1 for u in users if u.get("status") == "disabled") if users else 0
        total_traffic = sum(u.get("used_traffic", 0) for u in users) if users else 0
        total_traffic_gb = round(total_traffic / (1024**3), 2)
        
        online_users = server.get("online_users", 0) if server.get("online") else 0
        server_status = "🟢 Online" if server.get("online") else "🔴 Offline"
        
        text = f"""
📊 <b>Статистика MomsVPN</b>

👥 <b>Пользователи:</b>
├ Всего: <b>{total_users}</b>
├ Активных: <b>{active_users}</b>
├ Заблокированных: <b>{disabled_users}</b>
└ Онлайн сейчас: <b>{online_users}</b>

📊 <b>Трафик:</b>
└ Использовано: <b>{total_traffic_gb} ГБ</b>

🖥️ <b>Сервер:</b> {server_status}
"""
    except Exception as e:
        text = f"❌ Ошибка получения статистики: {e}"
    finally:
        await api.close()
    
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:stats")],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="admin:menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=back_kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("admin:users:"))
async def admin_users(callback: CallbackQuery):
    """Show users list with pagination - merged from Marzban and local DB."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    # Get page number from callback data
    page = int(callback.data.split(":")[2])
    per_page = 8
    
    try:
        from app.api.services.remnawave import remnawave_service as marzban_service
        from app.bot.utils.users_db import get_users_with_subscription
        from datetime import datetime
        
        # Get Marzban users
        marzban_users = await marzban_service.get_all_users() or []
        
        # Get local users with active subscriptions
        local_users = get_users_with_subscription() or []
        
        # Create a set of Marzban telegram IDs for deduplication
        marzban_tg_ids = set()
        for user in marzban_users:
            uname = user.get("username", "")
            if uname.startswith("user_"):
                try:
                    marzban_tg_ids.add(int(uname.replace("user_", "")))
                except:
                    pass
        
        # Merge: start with Marzban users
        merged_users = []
        for user in marzban_users:
            merged_users.append({
                "type": "marzban",
                "username": user.get("username"),
                "status": user.get("status", "unknown"),
                "used_traffic": user.get("used_traffic", 0),
                "display_name": extract_tg_username(user)
            })
        
        # Add local users who are NOT in Marzban yet
        for local_user in local_users:
            tg_id = local_user.get("telegram_id")
            if tg_id and tg_id not in marzban_tg_ids:
                # Check if subscription is active
                expires = local_user.get("subscription_expires")
                if expires:
                    try:
                        exp_date = datetime.fromisoformat(expires)
                        if exp_date > datetime.now() or exp_date.year >= 2100:
                            username = local_user.get("username")
                            first_name = local_user.get("first_name") or "User"
                            display = f"@{username}" if username else first_name
                            merged_users.append({
                                "type": "local",
                                "telegram_id": tg_id,
                                "username": f"user_{tg_id}",
                                "status": "local",
                                "used_traffic": 0,
                                "display_name": display
                            })
                    except:
                        pass
        
        if not merged_users:
            text = "👥 Пользователей нет"
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Меню", callback_data="admin:menu")]
            ]), parse_mode="HTML")
            return
        
        # Pagination
        total = len(merged_users)
        total_pages = (total + per_page - 1) // per_page
        start = page * per_page
        end = start + per_page
        page_users = merged_users[start:end]
        
        text = f"👥 <b>Все VPN пользователи</b> ({page + 1}/{total_pages})\n\nНажмите для управления:"
        
        # User buttons
        buttons = []
        for user in page_users:
            if user["type"] == "marzban":
                status_emoji = {"active": "🟢", "disabled": "🔴", "limited": "🟡", "expired": "⏰"}
                emoji = status_emoji.get(user.get("status"), "❓")
                used_gb = round(user.get("used_traffic", 0) / (1024**3), 1)
                buttons.append([
                    InlineKeyboardButton(
                        text=f"{emoji} {user['display_name']} ({used_gb} ГБ)",
                        callback_data=f"user:{user['username']}"
                    )
                ])
            else:
                # Local user (not yet in Marzban)
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🆕 {user['display_name']} (локальный)",
                        callback_data=f"localuser:{user['telegram_id']}"
                    )
                ])
        
        # Navigation buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"admin:users:{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"admin:users:{page + 1}"))
        
        if nav_buttons:
            buttons.append(nav_buttons)
        
        buttons.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="admin:menu")])
        
        await callback.message.edit_text(
            text, 
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), 
            parse_mode="HTML"
        )
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(F.data.startswith("user:") & ~F.data.startswith("user:action:"))
async def user_detail(callback: CallbackQuery):
    """Show user details with actions."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    username = callback.data.split(":")[1]
    
    from app.api.services.remnawave import remnawave_service as marzban_service
    # Explicitly fetch devices for detail view
    user = await marzban_service.get_user(username, fetch_devices=True)
    
    if not user:
        await callback.answer(f"❌ Пользователь не найден", show_alert=True)
        return
    
    # Format user info
    status_emoji = {"active": "🟢", "disabled": "🔴", "limited": "🟡", "expired": "⏰"}
    emoji = status_emoji.get(user.get("status"), "❓")
    
    used_traffic = user.get("used_traffic", 0)
    data_limit = user.get("data_limit", 0)
    used_gb = round(used_traffic / (1024**3), 2)
    limit_gb = round(data_limit / (1024**3), 0) if data_limit else "∞"
    
    # Calculate percentage
    if data_limit and data_limit > 0:
        percent = min(100, round(used_traffic / data_limit * 100))
        progress = "▓" * (percent // 10) + "░" * (10 - percent // 10)
    else:
        percent = 0
        progress = "░" * 10
    
    # Get REAL subscription from Moms Club API (not Marzban expire)
    import httpx
    from datetime import datetime
    from app.bot.utils.users_db import has_local_subscription, get_user as get_local_user
    
    # Extract telegram ID from user object (preferable) or username
    tg_id = user.get("telegram_id")
    if not tg_id:
        tg_id = username.replace("user_", "") if username.startswith("user_") else "N/A"
    
    mc_sub_status = "❌ Нет"
    has_mc_sub = False
    has_any_sub = False
    
    # Check Moms Club subscription
    if tg_id != "N/A":
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"http://127.0.0.1:8000/api/vpn/subscription/{tg_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "active":
                        has_mc_sub = True
                        has_any_sub = True
                        end_date = data.get("end_date")
                        if end_date:
                            from datetime import datetime
                            try:
                                exp_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                                if exp_dt.year >= 2100:
                                    mc_sub_status = "♾️ Бессрочно (MC)"
                                else:
                                    days_left = (exp_dt - datetime.now(exp_dt.tzinfo)).days
                                    mc_sub_status = f"✅ до {exp_dt.strftime('%d.%m.%Y')} ({days_left} дн.) (MC)"
                            except:
                                mc_sub_status = "✅ Активна (MC)"
                        else:
                            mc_sub_status = "✅ Активна (MC)"
                    elif data.get("status") == "expired":
                        mc_sub_status = "❌ Истекла (MC)"
        except:
            mc_sub_status = "⚠️ Ошибка проверки MC"
    
    # Check local subscription (for non-MC users)
    if not has_mc_sub:
        tg_id_int = int(tg_id) if tg_id != "N/A" else 0
        if tg_id_int and has_local_subscription(tg_id_int):
            has_any_sub = True
            local_user = get_local_user(tg_id_int)
            if local_user:
                expires = local_user.get("subscription_expires")
                if expires:
                    from datetime import datetime
                    try:
                        exp_dt = datetime.fromisoformat(expires)
                        if exp_dt.year >= 2100:
                            mc_sub_status = "♾️ Бессрочно (Локальная)"
                        else:
                            days_left = (exp_dt - datetime.now()).days
                            mc_sub_status = f"✅ до {exp_dt.strftime('%d.%m.%Y')} ({days_left} дн.) (Локальная)"
                    except:
                        mc_sub_status = "✅ Активна (Локальная)"
    
    # Online status
    online_at = user.get("online_at")
    if online_at:
        try:
            online_date = datetime.fromisoformat(online_at.replace("Z", "+00:00"))
            online_str = online_date.strftime("%d.%m.%Y %H:%M")
        except:
             online_str = str(online_at)
    else:
        online_str = "Никогда"
    
    # Extract telegram info from note
    display_name = extract_tg_username(user)
    
    # Create clickable title if we have ID
    if tg_id != "N/A":
        title_line = f"👤 <a href='tg://user?id={tg_id}'>{display_name}</a>"
    else:
        title_line = f"👤 <b>{display_name}</b>"
        
    # Translate status
    status_ru_map = {
        "active": "🟢 Активен",
        "disabled": "🔴 Заблокирован",
        "limited": "🟡 Ограничен",
        "expired": "⏰ Истек"
    }
    status_ru = status_ru_map.get(user.get("status"), f"❓ {user.get('status')}")

    # Devices list (from sub_last_user_agent which contains formatted list)
    devices_list = user.get("sub_last_user_agent", "")
    if devices_list:
        devices_str = f"📱 <b>Устройства:</b>\n{devices_list}"
    else:
        devices_str = "📱 <b>Устройства:</b> Нет данных"

    text = f"""
{title_line}

📱 <b>Telegram ID:</b> <code>{tg_id}</code>
🔗 <b>Внутренний ID:</b> <code>{username}</code>
📡 <b>Статус VPN:</b> {status_ru}

📊 <b>Трафик:</b>
{progress} {percent}%
{used_gb} ГБ / {limit_gb} ГБ

{devices_str}

📅 <b>Подписка:</b> {mc_sub_status}
🕐 <b>Последний онлайн:</b> {online_str}

<i>Выберите действие:</i>
"""
    
    # Action buttons
    buttons = []
    
    # Block/Unblock
    if user.get("status") == "active":
        buttons.append([InlineKeyboardButton(text="🔒 Заблокировать", callback_data=f"user:action:block:{username}")])
    else:
        buttons.append([InlineKeyboardButton(text="🔓 Разблокировать", callback_data=f"user:action:unblock:{username}")])
    
    # +1 Device
    buttons.append([InlineKeyboardButton(text="📱 +1 устройство", callback_data=f"user:action:adddevice:{username}")])
    
    # Reset devices (NEW)
    buttons.append([InlineKeyboardButton(text="🔄 Сбросить устройства", callback_data=f"user:action:resetdevices:{username}")])
    
    # Back
    buttons.append([InlineKeyboardButton(text="⬅️ К списку", callback_data="admin:users:0")])
    
    await callback.message.edit_text(
        text, 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), 
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("user:action:"))
async def user_action(callback: CallbackQuery, state: FSMContext):
    """Handle user actions."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    parts = callback.data.split(":")
    action = parts[2]
    username = parts[3]
    
    # Use RemnawaveService instead of legacy MarzbanAdminService
    from app.api.services.remnawave import remnawave_service
    # removed import bot to avoid circular dependency
    
    try:
        if action == "block":
            await remnawave_service.disable_user(username)
            await callback.answer("✅ Пользователь заблокирован", show_alert=True)
            # Refresh user detail
            callback.data = f"user:{username}"
            await user_detail(callback)
            
        elif action == "unblock":
            await remnawave_service.enable_user(username)
            await callback.answer("✅ Пользователь разблокирован", show_alert=True)
            callback.data = f"user:{username}"
            await user_detail(callback)
            
        elif action == "resetdevices":
            # Get user to find telegram_id
            user = await remnawave_service.get_user(username)
            if user and user.get("telegram_id"):
                tg_id = user.get("telegram_id")
                success = await remnawave_service.reset_user_devices(tg_id)
                if success:
                    await callback.answer("✅ Устройства сброшены", show_alert=True)
                    try:
                        await callback.bot.send_message(
                            tg_id, 
                            "🛠 <b>Администратор сбросил привязку ваших устройств.</b>\n\n"
                            "Теперь вы можете подключить новые устройства.",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Failed to send push to {tg_id}: {e}")
                else:
                    await callback.answer("❌ Ошибка сброса (возможно список пуст)", show_alert=True)
            else:
                await callback.answer("❌ Не удалось определить Telegram ID", show_alert=True)
                
            callback.data = f"user:{username}"
            await user_detail(callback)
            
        elif action == "adddevice":
            # Not fully implemented in this refactor step, keeping placeholder or simple logic
            # For now just show alert
             await callback.answer("ℹ️ Используйте кнопку '+1 устройство (100₽)' в боте или измените лимит вручную в БД", show_alert=True)

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
            

@router.callback_query(F.data == "admin:menu")
async def admin_menu(callback: CallbackQuery):
    """Return to admin menu."""
    if not is_admin(callback.from_user.id):
        return
    
    text = """
🔐 <b>Админ-панель MomsVPN</b>

Выберите раздел:
"""
    await callback.message.edit_text(text, reply_markup=admin_menu_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "admin:close")
async def admin_close(callback: CallbackQuery):
    """Close admin panel."""
    await callback.message.delete()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    """Do nothing (for pagination counter)."""
    await callback.answer()


# =====================================================
# NEW: Non-MC Users (Не подписчики Moms Club)
# =====================================================

@router.callback_query(F.data.startswith("admin:nonmc:"))
async def admin_nonmc_users(callback: CallbackQuery):
    """Show non-Moms Club users list."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    page = int(callback.data.split(":")[2])
    per_page = 8
    
    from app.bot.utils.users_db import get_non_momsclub_users, count_non_momsclub_users
    
    total = count_non_momsclub_users()
    total_pages = max(1, (total + per_page - 1) // per_page)
    users = get_non_momsclub_users(limit=per_page, offset=page * per_page)
    
    text = f"📋 <b>Не подписчики Moms Club</b> ({page + 1}/{total_pages})\n\n"
    
    if not users:
        text += "<i>Пока никого нет</i>"
    else:
        text += "Нажмите для управления:"
    
    buttons = []
    for user in users:
        expires = user.get("subscription_expires")
        if expires:
            from datetime import datetime
            try:
                exp_date = datetime.fromisoformat(expires)
                if exp_date.year >= 2100:
                    status = "♾️"
                elif exp_date > datetime.now():
                    status = "✅"
                else:
                    status = "❌"
            except:
                status = "❌"
        else:
            status = "❌"
        
        username = user.get("username")
        first_name = user.get("first_name") or "User"
        display = f"@{username}" if username else first_name
        
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {display} ({user['telegram_id']})",
                callback_data=f"localuser:{user['telegram_id']}"
            )
        ])
    
    # Navigation
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"admin:nonmc:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"admin:nonmc:{page + 1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="admin:menu")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@router.callback_query(F.data.startswith("localuser:"))
async def local_user_detail(callback: CallbackQuery):
    """Show local user details (non-MC)."""
    if not is_admin(callback.from_user.id):
        return
    
    telegram_id = int(callback.data.split(":")[1])
    
    from app.bot.utils.users_db import get_user
    from datetime import datetime
    
    user = get_user(telegram_id)
    if not user:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    # Subscription status
    expires = user.get("subscription_expires")
    if expires:
        try:
            exp_date = datetime.fromisoformat(expires)
            if exp_date.year >= 2100:
                sub_status = "♾️ Безлимит"
            elif exp_date > datetime.now():
                days_left = (exp_date - datetime.now()).days
                sub_status = f"✅ до {exp_date.strftime('%d.%m.%Y')} ({days_left} дн.)"
            else:
                sub_status = "❌ Истекла"
        except:
            sub_status = "❌ Нет"
    else:
        sub_status = "❌ Нет"
    
    devices = user.get("devices_limit", 2)
    username = user.get("username")
    first_name = user.get("first_name") or "User"
    display = f"@{username}" if username else first_name
    
    # Get traffic info from Marzban if user exists there
    traffic_text = "—"
    vpn_status = "⚪ Не создан"
    try:
        from app.api.services.remnawave import remnawave_service as marzban_service
        marzban_user = await marzban_service.get_user(f"user_{telegram_id}")
        if marzban_user:
            used_bytes = marzban_user.get("used_traffic") or 0
            traffic_text = f"{round(used_bytes / (1024**3), 2)} ГБ"
            status_map = {"active": "🟢 Активен", "disabled": "🔴 Отключен", "limited": "🟡 Лимит"}
            vpn_status = status_map.get(marzban_user.get("status"), "🟢 Активен")
    except:
        pass
    
    text = f"""
👤 <b>{display}</b>

📱 <b>Telegram ID:</b> <code>{telegram_id}</code>
📅 <b>Подписка:</b> {sub_status}
📱 <b>Устройств:</b> {devices}
🎀 <b>Moms Club:</b> {"Да" if user.get("is_momsclub_member") else "Нет"}

🛡️ <b>VPN:</b> {vpn_status}
📊 <b>Трафик:</b> {traffic_text}

<i>Выберите действие:</i>
"""
    
    buttons = [
        [InlineKeyboardButton(text="📅 Дать подписку", callback_data=f"localsub:{telegram_id}")],
        [InlineKeyboardButton(text="📱 +1 устройство", callback_data=f"localdevice:{telegram_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:nonmc:0")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@router.callback_query(F.data.startswith("localsub:"))
async def local_subscription_menu(callback: CallbackQuery):
    """Show subscription options for local user."""
    if not is_admin(callback.from_user.id):
        return
    
    telegram_id = int(callback.data.split(":")[1])
    
    text = f"""
📅 <b>Дать подписку</b>

Telegram ID: <code>{telegram_id}</code>

Выберите срок:
"""
    
    buttons = [
        [
            InlineKeyboardButton(text="30 дней", callback_data=f"localsubset:30:{telegram_id}"),
            InlineKeyboardButton(text="90 дней", callback_data=f"localsubset:90:{telegram_id}")
        ],
        [InlineKeyboardButton(text="♾️ Безлимит", callback_data=f"localsubset:0:{telegram_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"localuser:{telegram_id}")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@router.callback_query(F.data.startswith("localsubset:"))
async def set_local_subscription(callback: CallbackQuery):
    """Set local subscription for user."""
    if not is_admin(callback.from_user.id):
        return
    
    parts = callback.data.split(":")
    days = int(parts[1])
    telegram_id = int(parts[2])
    
    from app.bot.utils.users_db import add_subscription, get_user
    from aiogram import Bot
    import os
    
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    
    # Add subscription
    success = add_subscription(telegram_id, days, added_by=callback.from_user.id)
    
    if success:
        user = get_user(telegram_id)
        
        # Format message
        if days == 0:
            period_text = "безлимитная"
        else:
            period_text = f"{days} дней"
        
        # Send push notification to user
        try:
            push_text = (
                "🎁 <b>Отличные новости!</b>\n\n"
                f"Тебе активирована подписка MomsVPN!\n\n"
                f"📅 Срок: <b>{period_text}</b>\n"
                f"📱 Устройств: <b>{user.get('devices_limit', 2)}</b>\n\n"
                "Нажми /start чтобы получить свой ключ ✨"
            )
            await bot.send_message(telegram_id, push_text, parse_mode="HTML")
            await callback.answer(f"✅ Подписка добавлена! Push отправлен", show_alert=True)
        except Exception as e:
            logger.warning(f"Failed to send push to {telegram_id}: {e}")
            await callback.answer(f"✅ Подписка добавлена (push не отправлен)", show_alert=True)
    else:
        await callback.answer("❌ Ошибка добавления подписки", show_alert=True)
    
    # Return to user detail
    callback.data = f"localuser:{telegram_id}"
    await local_user_detail(callback)


@router.callback_query(F.data.startswith("localdevice:"))
async def local_device_confirm(callback: CallbackQuery):
    """Confirm adding device to user."""
    if not is_admin(callback.from_user.id):
        return
    
    telegram_id = int(callback.data.split(":")[1])
    
    from app.bot.utils.users_db import get_user
    user = get_user(telegram_id)
    current_limit = user.get("devices_limit", 2) if user else 2
    
    text = f"""
📱 <b>Добавить устройство?</b>

Telegram ID: <code>{telegram_id}</code>
Текущий лимит: <b>{current_limit}</b>
Новый лимит: <b>{current_limit + 1}</b>
"""
    
    buttons = [
        [
            InlineKeyboardButton(text="✅ Добавить", callback_data=f"localdeviceset:{telegram_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"localuser:{telegram_id}")
        ]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@router.callback_query(F.data.startswith("localdeviceset:"))
async def set_local_device(callback: CallbackQuery):
    """Add device to user and update Marzban."""
    if not is_admin(callback.from_user.id):
        return
    
    telegram_id = int(callback.data.split(":")[1])
    
    from app.bot.utils.users_db import get_user, set_devices_limit
    from aiogram import Bot
    import os
    import httpx
    
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    
    user = get_user(telegram_id)
    current_limit = user.get("devices_limit", 2) if user else 2
    new_limit = current_limit + 1
    
    # Update local DB
    set_devices_limit(telegram_id, new_limit)
    
    # Update Marzban
    try:
        MARZBAN_URL = os.getenv("MARZBAN_URL", "https://instabotwebhook.ru")
        MARZBAN_USER = os.getenv("MARZBAN_USER", "admin")
        MARZBAN_PASS = os.getenv("MARZBAN_PASS", "dmitrenko1996")
        
        async with httpx.AsyncClient(verify=False, timeout=15) as client:
            # Get token
            token_resp = await client.post(
                f"{MARZBAN_URL}/api/admin/token",
                data={"username": MARZBAN_USER, "password": MARZBAN_PASS}
            )
            token = token_resp.json()["access_token"]
            
            # Update user
            username = f"user_{telegram_id}"
            await client.put(
                f"{MARZBAN_URL}/api/user/{username}",
                headers={"Authorization": f"Bearer {token}"},
                json={"ip_limit": new_limit}
            )
    except Exception as e:
        logger.warning(f"Failed to update Marzban ip_limit: {e}")
    
    # Send push notification
    try:
        push_text = (
            "🎁 <b>Отличные новости!</b>\n\n"
            "Тебе добавлено <b>+1 устройство</b> для VPN!\n\n"
            f"📱 Теперь доступно: <b>{new_limit}</b> устройств\n\n"
            "Нажми /start чтобы продолжить ✨"
        )
        await bot.send_message(telegram_id, push_text, parse_mode="HTML")
        await callback.answer(f"✅ Устройство добавлено! Push отправлен", show_alert=True)
    except Exception as e:
        logger.warning(f"Failed to send push to {telegram_id}: {e}")
        await callback.answer(f"✅ Устройство добавлено (push не отправлен)", show_alert=True)
    
    # Return to user detail
    callback.data = f"localuser:{telegram_id}"
    await local_user_detail(callback)


# =====================================================
# NEW: Search User
# =====================================================

@router.callback_query(F.data == "admin:search")
async def admin_search_start(callback: CallbackQuery, state: FSMContext):
    """Start user search."""
    if not is_admin(callback.from_user.id):
        return
    
    await state.set_state(AdminStates.waiting_search)
    
    text = """
🔍 <b>Поиск пользователя</b>

Введите @username или Telegram ID:
"""
    
    buttons = [[InlineKeyboardButton(text="❌ Отмена", callback_data="admin:menu")]]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@router.message(AdminStates.waiting_search)
async def admin_search_process(message: Message, state: FSMContext):
    """Process search query."""
    if not is_admin(message.from_user.id):
        return
    
    query = message.text.strip()
    
    from app.bot.utils.users_db import search_user
    from app.api.services.remnawave import remnawave_service as marzban_service
    
    # Search in local DB
    local_user = search_user(query)
    
    # Search in Marzban
    marzban_user = None
    try:
        username = query.replace("@", "")
        if username.isdigit():
            marzban_username = f"user_{username}"
        else:
            marzban_username = f"user_{username}"
        
        marzban_user = await marzban_service.get_user(marzban_username)
    except:
        pass
    
    await state.clear()
    
    if not local_user and not marzban_user:
        text = f"🔍 По запросу «{query}» ничего не найдено"
        buttons = [[InlineKeyboardButton(text="⬅️ Меню", callback_data="admin:menu")]]
    else:
        text = f"🔍 <b>Результат поиска:</b> {query}\n\n"
        buttons = []
        
        if local_user:
            text += f"📋 <b>Локальная БД:</b> найден\n"
            buttons.append([InlineKeyboardButton(
                text=f"📋 {local_user.get('first_name', 'User')} ({local_user['telegram_id']})",
                callback_data=f"localuser:{local_user['telegram_id']}"
            )])
        
        if marzban_user:
            used_gb = round(marzban_user.get("used_traffic", 0) / (1024**3), 2)
            text += f"🖥️ <b>Marzban:</b> найден ({used_gb} ГБ)\n"
            buttons.append([InlineKeyboardButton(
                text=f"🖥️ {marzban_user.get('username')}",
                callback_data=f"user:{marzban_user.get('username')}"
            )])
        
        buttons.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="admin:menu")])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
