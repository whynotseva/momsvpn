from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile, URLInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
import logging
from app.bot.utils.api_client import api
from app.bot.services.subscription_sync import subscription_sync_service
from app.bot.utils.users_db import create_or_update_user, has_local_subscription, get_user as get_local_user
from app.bot.utils.oferta_db import is_oferta_accepted, accept_oferta
from app.bot.utils.momsclub_api import check_momsclub_subscription

logger = logging.getLogger(__name__)
import os

router = Router()

# === ТЕКСТЫ ===

def get_oferta_text(name: str) -> str:
    return f"""Привет, <b>красотка {name}</b> 🤎

Добро пожаловать в <b>MomsVPN</b> — твой безопасный интернет от Moms Club.

🔐 <b>Что такое MomsVPN?</b>

— Безопасный доступ к Instagram, TikTok, YouTube
— Защита твоих данных от посторонних глаз
— Стабильное соединение без тормозов
— Без рекламы и ограничений

📜 <b>Условия использования:</b>
• VPN только для личного использования
• Мы не храним логи твоей активности
• Запрещено использовать для противоправных действий

<i>Принимая условия, ты соглашаешься с правилами сервиса.</i>"""

def get_no_sub_text(name: str) -> str:
    return f"""Привет, <b>красотка {name}</b> 🤎

<b>MomsVPN</b> — эксклюзивный сервис для участниц закрытого клуба <b>Moms Club</b>.

💎 <b>Подписка в клубе открывает доступ к:</b>
— Безлимитному VPN (Instagram, TikTok, YouTube)
— Базе знаний и урокам по блогингу
— Комьюнити мам-блогеров
— Поддержке и разборам контента

<i>Чтобы пользоваться VPN, вступи в клуб</i> 🤎"""

def get_expired_text(name: str) -> str:
    return f"""Привет, <b>красотка {name}</b> 🤎

Твоя подписка в <b>Moms Club</b> закончилась 😔

<i>Пока подписка неактивна, VPN приостановлен.</i>
Продли подписку, чтобы снова пользоваться свободным интернетом!"""

def get_active_text(name: str, end_date: str = None) -> str:
    # Форматируем дату подписки из API Moms Club
    sub_info = ""
    if end_date:
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            if dt.year >= 2100:
                sub_info = " — безлимитную"
            else:
                sub_info = f" до {dt.strftime('%d.%m.%Y')}"
        except:
            pass
    
    return f"""Привет, <b>{name}</b> 🤎

Вижу твою подписку в <b>Moms Club</b>{sub_info} ✨

Добро пожаловать в семью <b>MomsVPN</b>!
Теперь у тебя есть свободный и безопасный доступ к интернету — без ограничений.

🔐 Твой ключ — личный. Не передавай его другим пользователям.

<i>Нажми кнопку «Мой VPN» — сгенерируем твой ключ за пару секунд</i> 🛡️"""

def get_menu_text(name: str) -> str:
    return f"""Привет, <b>красотка {name}</b> 🤎

Чем могу помочь?"""

# === КЛАВИАТУРЫ ===

def oferta_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять условия", callback_data="accept_terms")],
        [InlineKeyboardButton(text="📜 Читать полные правила", url="https://telegra.ph/Terms-of-Service-MomsVPN")]
    ])

def no_sub_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Вступить в Moms Club", url="https://t.me/momsclubsubscribe_bot")],
        [InlineKeyboardButton(text="🔄 Уже оплатила? Проверить", callback_data="check_subscription")]
    ])

def expired_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Продлить подписку", url="https://t.me/momsclubsubscribe_bot")],
        [InlineKeyboardButton(text="🔄 Уже оплатила? Проверить", callback_data="check_subscription")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_home")]
    ])

def active_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡️ Мой VPN", callback_data="my_keys")],
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="💬 Поддержка", url="https://t.me/momsclubsupport")]
    ])

def main_menu_kb():
    return active_kb()

# === HANDLERS ===

@router.message(Command("start"))
async def command_start(message: types.Message):
    user_name = message.from_user.first_name or "красотка"
    telegram_id = message.from_user.id
    username = message.from_user.username
    
    # Записываем пользователя в локальную БД
    create_or_update_user(telegram_id, username, user_name, is_momsclub=False)
    
    # Проверяем оферту
    if not is_oferta_accepted(telegram_id):
        await message.answer(
            get_oferta_text(user_name),
            reply_markup=oferta_kb(),
            parse_mode="HTML"
        )
        return
    
    # Оферта принята - проверяем подписку
    await show_subscription_status(message, user_name, telegram_id)


@router.message(Command("profile"))
async def command_profile(message: types.Message):
    """Открыть личный кабинет через команду /profile"""
    telegram_id = message.from_user.id
    first_name = message.from_user.first_name or "друг"
    username = message.from_user.username
    
    # Проверяем оферту
    if not is_oferta_accepted(telegram_id):
        await message.answer(
            get_oferta_text(first_name),
            reply_markup=oferta_kb(),
            parse_mode="HTML"
        )
        return
    
    # Получаем инфо из Marzban
    sub_info = await api.get_subscription(telegram_id)
    
    # Получаем роль и лимит из Moms Club
    from app.bot.utils.momsclub_api import get_user_ip_limit, is_admin
    import httpx
    
    # Получаем роль
    role_text = "🎀 Участница Mom's Club"
    role_group = None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # Use MARZBAN_URL from env or default to https endpoint
            base_url = os.getenv("MARZBAN_URL", "https://instabotwebhook.ru") 
            resp = await client.get(f"{base_url}/api/vpn/is_admin/{telegram_id}")
            if resp.status_code == 200:
                data = resp.json()
                role_group = data.get("group")
                if role_group == "admin" or role_group == "developer":
                    role_text = "💻 Разработчик"
                elif role_group == "creator":
                    role_text = "👑 Создательница"
                elif role_group == "curator":
                    role_text = "🎯 Куратор"
    except:
        pass
    
    # Статус VPN
    vpn_status = "❌ Не активен"
    traffic_text = "—"
    if sub_info:
        status_map = {"active": "🟢 Активен", "disabled": "🔴 Отключен", "limited": "🟡 Лимит"}
        vpn_status = status_map.get(sub_info.get("status"), "🟢 Активен")
        used_bytes = sub_info.get("traffic_used") or 0
        traffic_text = f"{round(used_bytes / (1024**3), 2)} ГБ"
    
    # Лимит устройств
    ip_limit = await get_user_ip_limit(telegram_id)
    is_vip = await is_admin(telegram_id)
    if is_vip or ip_limit is None:
        limit_text = "∞ Безлимит"
    else:
        limit_text = f"до {ip_limit}"
    
    # Подписка
    sub_data = await check_momsclub_subscription(telegram_id)
    if sub_data.get("end_date"):
        from datetime import datetime
        try:
            end_date = datetime.fromisoformat(sub_data["end_date"])
            if end_date.year > 2100:
                sub_until = "безлимитная"
            else:
                sub_until = end_date.strftime("%d.%m.%Y")
        except:
            sub_until = "активна"
    else:
        sub_until = "не активна"
    
    # Формируем username строку
    username_str = f"@{username}" if username else ""
    
    text = (
        f"🎀 <b>Добро пожаловать в личный кабинет Moms VPN!</b>\n\n"
        f"👋 Привет, <b>{first_name}</b>!\n"
        f"{username_str}\n\n"
        f"{role_text}\n\n"
        f"━━━ <b>VPN</b> ━━━\n"
        f"🔐 Статус: <b>{vpn_status}</b>\n"
        f"📱 Устройств: <b>{limit_text}</b>\n"
        f"📊 Трафик: <b>{traffic_text}</b>\n"
        f"📅 Подписка: <b>{sub_until}</b>"
    )
    
    # Кнопки — скрываем +1 устройство для VIP
    buttons = [[InlineKeyboardButton(text="🛡️ Мой VPN", callback_data="my_keys")]]
    if not is_vip:
        buttons.append([InlineKeyboardButton(text="📱 +1 устройство (100₽)", callback_data="add_device")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_home")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("help"))
async def command_help(message: types.Message):
    """Обработчик команды /help — перенаправление на поддержку"""
    text = (
        "🆘 <b>Нужна помощь?</b>\n\n"
        "Если у тебя возникли вопросы или проблемы с VPN, "
        "напиши нашей службе поддержки:\n\n"
        "👇 Нажми кнопку ниже"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать в поддержку", url="https://t.me/momsclubsupport")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_home")]
    ])
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


async def show_subscription_status(message_or_callback, user_name: str, telegram_id: int):
    """Показать статус подписки - сначала локальная БД, потом Moms Club"""
    
    # 1. Проверяем локальную подписку (для друзей без MC)
    if has_local_subscription(telegram_id):
        local_user = get_local_user(telegram_id)
        status = "active"
        sub_data = {
            "status": "active",
            "end_date": local_user.get("subscription_expires") if local_user else None,
            "source": "local"
        }
    else:
        # 2. Проверяем Moms Club
        sub_data = await check_momsclub_subscription(telegram_id)
        status = sub_data.get("status", "none")
        
        # Обновляем is_momsclub_member если активна подписка MC
        if status == "active":
            create_or_update_user(telegram_id, is_momsclub=True)
    
    if status == "active":
        text = get_active_text(user_name, sub_data.get("end_date"))
        kb = active_kb()
    elif status == "expired":
        text = get_expired_text(user_name)
        kb = expired_kb()
    else:  # none or error
        text = get_no_sub_text(user_name)
        kb = no_sub_kb()
    
    # Путь к изображению (абсолютный)
    import pathlib
    current_dir = pathlib.Path(__file__).parent.resolve()
    image_path = current_dir.parent / "images" / "welcome.png"
    
    # print(f"DEBUG: Checking image at {image_path}, exists: {image_path.exists()}")
    
    if isinstance(message_or_callback, types.Message):
        if status == "active" and image_path.exists():
            from aiogram.types import FSInputFile
            photo = FSInputFile(str(image_path))
            await message_or_callback.answer_photo(photo, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await message_or_callback.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        # Для callback (обновление)
        try:
            # Если уже есть фото и мы обновляем текст
            if message_or_callback.message.photo:
                if status == "active":
                    await message_or_callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
                else:
                    await message_or_callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
            else:
                # Было текстовое сообщение
                if status == "active" and image_path.exists():
                    # Удаляем старое текстовое и шлём фото
                    await message_or_callback.message.delete()
                    from aiogram.types import FSInputFile
                    photo = FSInputFile(str(image_path))
                    await message_or_callback.message.answer_photo(photo, caption=text, reply_markup=kb, parse_mode="HTML")
                else:
                    await message_or_callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            # Fallback
            # print(f"DEBUG Error sending photo: {e}")
            await message_or_callback.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "accept_terms")
async def terms_accept(callback: CallbackQuery):
    telegram_id = callback.from_user.id
    user_name = callback.from_user.first_name or "красотка"
    
    # Сохраняем принятие оферты
    accept_oferta(telegram_id)
    
    await callback.message.delete()
    await show_subscription_status(callback.message, user_name, telegram_id)

@router.callback_query(F.data == "check_subscription")
async def check_subscription_handler(callback: CallbackQuery):
    user_name = callback.from_user.first_name or "красотка"
    telegram_id = callback.from_user.id
    
    await callback.answer("⏳ Проверяю подписку...")
    await show_subscription_status(callback, user_name, telegram_id)

@router.callback_query(F.data == "back_home")
async def back_home_handler(callback: CallbackQuery):
    user_name = callback.from_user.first_name or "красотка"
    telegram_id = callback.from_user.id
    # Возвращаемся на информативный экран с проверкой подписки
    await show_subscription_status(callback, user_name, telegram_id)

@router.callback_query(F.data == "profile")
async def profile_handler(callback: CallbackQuery):
    telegram_id = callback.from_user.id
    first_name = callback.from_user.first_name or "друг"
    username = callback.from_user.username
    
    # Получаем инфо из Marzban
    sub_info = await api.get_subscription(telegram_id)
    
    # Получаем роль и лимит из Moms Club
    from app.bot.utils.momsclub_api import get_user_ip_limit, is_admin
    import httpx
    
    # Получаем роль
    role_text = "🎀 Участница Mom's Club"
    role_group = None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            base_url = os.getenv("MARZBAN_URL", "https://instabotwebhook.ru")
            resp = await client.get(f"{base_url}/api/vpn/is_admin/{telegram_id}")
            if resp.status_code == 200:
                data = resp.json()
                role_group = data.get("group")
                if role_group == "admin" or role_group == "developer":
                    role_text = "💻 Разработчик"
                elif role_group == "creator":
                    role_text = "👑 Создательница"
                elif role_group == "curator":
                    role_text = "🎯 Куратор"
    except:
        pass
    
    # Статус VPN
    vpn_status = "❌ Не активен"
    traffic_text = "—"
    if sub_info:
        status_map = {"active": "🟢 Активен", "disabled": "🔴 Отключен", "limited": "🟡 Лимит"}
        vpn_status = status_map.get(sub_info.get("status"), "🟢 Активен")
        used_bytes = sub_info.get("traffic_used") or 0
        traffic_text = f"{round(used_bytes / (1024**3), 2)} ГБ"
    
    # Лимит устройств
    ip_limit = await get_user_ip_limit(telegram_id)
    is_vip = await is_admin(telegram_id)
    if is_vip or ip_limit is None:
        limit_text = "∞ Безлимит"
    else:
        limit_text = f"до {ip_limit}"
    
    # Подписка
    sub_data = await check_momsclub_subscription(telegram_id)
    if sub_data.get("end_date"):
        from datetime import datetime
        try:
            end_date = datetime.fromisoformat(sub_data["end_date"])
            if end_date.year > 2100:
                sub_until = "безлимитная"
            else:
                sub_until = end_date.strftime("%d.%m.%Y")
        except:
            sub_until = "активна"
    else:
        sub_until = "не активна"
    
    # Формируем username строку
    username_str = f"@{username}" if username else ""
    
    text = (
        f"🎀 <b>Добро пожаловать в личный кабинет Moms VPN!</b>\n\n"
        f"👋 Привет, <b>{first_name}</b>!\n"
        f"{username_str}\n\n"
        f"{role_text}\n\n"
        f"━━━ <b>VPN</b> ━━━\n"
        f"🔐 Статус: <b>{vpn_status}</b>\n"
        f"📱 Устройств: <b>{limit_text}</b>\n"
        f"📊 Трафик: <b>{traffic_text}</b>\n"
        f"📅 Подписка: <b>{sub_until}</b>"
    )
    
    # Кнопки — скрываем +1 устройство для VIP
    buttons = [[InlineKeyboardButton(text="🛡️ Мой VPN", callback_data="my_keys")]]
    if not is_vip:
        buttons.append([InlineKeyboardButton(text="📱 +1 устройство (100₽)", callback_data="add_device")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_home")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "my_keys")
async def my_keys(callback: CallbackQuery):
    from app.bot.utils.crypto import encrypt_vless_link
    
    user_name = callback.from_user.first_name or "красотка"
    telegram_id = callback.from_user.id
    
    # Сначала проверяем локальную подписку (для друзей без MC)
    has_access = False
    if has_local_subscription(telegram_id):
        has_access = True
    else:
        # Проверяем подписку в Moms Club
        sub_data = await check_momsclub_subscription(telegram_id)
        if sub_data.get("status") == "active":
            has_access = True
    
    if not has_access:
        await callback.answer("❌ Нет активной подписки", show_alert=True)
        await show_subscription_status(callback, user_name, telegram_id)
        return
    
    await callback.answer("⏳ Загружаю ключ...")
    
    # Instant sync: ensure VPN key is enabled if user has access
    try:
        from app.bot.services.subscription_sync import subscription_sync_service
        from app.api.services.remnawave import remnawave_service as marzban_service
        
        marzban_user = await marzban_service.get_user(f"user_{telegram_id}")
        if marzban_user and marzban_user.get("status") == "disabled":
            # User has access but key is disabled - enable it
            await subscription_sync_service.sync_user(telegram_id, "disabled")
    except Exception as e:
        logger.warning(f"Failed to sync VPN status for {telegram_id}: {e}")
    
    # Получаем ключ из Marzban (с запросом устройств)
    sub_info = await api.get_subscription(telegram_id, fetch_devices=True)
    
    # Если пользователь не найден, создаём (с учётом лимита)
    if not sub_info:
        username = callback.from_user.username or "User"
        
        # Получаем лимиты
        from app.bot.utils.momsclub_api import is_admin, get_user_ip_limit
        is_vip = await is_admin(telegram_id)
        ip_limit = await get_user_ip_limit(telegram_id)
        
        # Для админов лимит 0 (безлимит), для остальных берем из БД или дефолт 2
        limit_to_pass = 0 if is_vip else (ip_limit if ip_limit else 2)
        await api.create_user(telegram_id, username, user_name, ip_limit=limit_to_pass)
        sub_info = await api.get_subscription(telegram_id)
    
    if not sub_info or not sub_info.get("subscription_url"):
        await callback.answer("❌ Ошибка получения ключа", show_alert=True)
        return
    
    subscription_url = sub_info.get("subscription_url")
    encrypted_key = await encrypt_vless_link(subscription_url)
    
    # Получаем лимит устройств
    from app.bot.utils.momsclub_api import get_user_ip_limit, is_admin
    ip_limit = await get_user_ip_limit(telegram_id)
    is_vip = await is_admin(telegram_id)
    
    # Текст про лимит устройств
    if is_vip or ip_limit is None:
        limit_text = "∞ Безлимит"
    else:
        limit_text = f"до {ip_limit} устройств"
    
    # Динамический статус из Marzban
    status_raw = sub_info.get("status", "active")
    status_map = {"active": "🟢 Активен", "disabled": "🔴 Отключен", "limited": "🟡 Лимит"}
    status_text = status_map.get(status_raw, "🟢 Активен")
    
    # Трафик
    used_bytes = sub_info.get("traffic_used") or 0
    used_gb = round(used_bytes / (1024**3), 2)
    

    
    # Информация об устройстве
    last_device = sub_info.get("sub_last_user_agent")
    if last_device:
        device_info = f"<blockquote>{last_device}</blockquote>"
    else:
        device_info = "<blockquote>Устройства не обнаружены</blockquote>"

    text = (
        f"<b>🔑 Твой VPN ключ</b>\n\n"
        f"Статус: <b>{status_text}</b>\n"
        f"Устройств: <b>{limit_text}</b>\n"
        f"Трафик: <b>{used_gb} ГБ</b>\n\n"
        f"👉 <b>Текущие устройства к которым привязан ваш VPN:</b>\n"
        f"{device_info}\n\n"
        f"<b>━━━ КЛЮЧ ━━━</b>\n"
        f"<blockquote><code>{encrypted_key}</code></blockquote>\n"
        f"<b>━━━ КАК ПОДКЛЮЧИТЬ ━━━</b>\n"
        f"1️⃣ Скачай <b>Happ</b> (кнопки ниже)\n"
        f"2️⃣ Скопируй ключ (нажми на него)\n"
        f"3️⃣ В Happ: <b>＋</b> → вставь ключ\n"
        f"4️⃣ Нажми <b>Connect</b> ✨\n\n"
        f"💡 <b>Anti-RKN</b>: Самый надежный профиль для обхода блокировок.\n"
        f"Если основной не работает — включай его."
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Перевыпустить ключ", callback_data="regenerate_key")],
        [InlineKeyboardButton(text="📱 Сбросить устройства", callback_data="reset_devices")],
        [InlineKeyboardButton(text="📱 +1 устройство (100₽)", callback_data="add_device")],
        [InlineKeyboardButton(text="📱 iPhone", url="https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973"),
         InlineKeyboardButton(text="🤖 Android", url="https://play.google.com/store/apps/details?id=com.happproxy")],
        [InlineKeyboardButton(text="💻 Windows", url="https://happ.su/download/windows"),
         InlineKeyboardButton(text="🍎 Mac", url="https://happ.su/download/mac")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_home")]
    ])
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)

@router.callback_query(F.data == "regenerate_key")
async def regenerate_key_handler(callback: CallbackQuery):
    telegram_id = callback.from_user.id
    user_name = callback.from_user.first_name or "красотка"
    username = callback.from_user.username or "User"
    
    await callback.answer("🔄 Перевыпускаю ключ...")
    
    try:
        # Перевыпуск ключа через Marzban (сброс UUID, трафик НЕ сбрасывается)
        await api.reset_user_subscription(telegram_id)
        await callback.answer("✅ Ключ перевыпущен!", show_alert=True)
        
        # Показываем обновлённый ключ
        from app.bot.handlers.start import my_keys
        await my_keys(callback)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)[:50]}", show_alert=True)


@router.callback_query(F.data == "reset_devices")
async def reset_devices_handler(callback: CallbackQuery):
    """Сбросить привязку устройств"""
    telegram_id = callback.from_user.id
    
    # Не отвечаем сразу, чтобы крутился спиннер и потом появился Alert
    
    try:
        success = await api.reset_devices(telegram_id)
        if success:
            await callback.answer("✅ Вы отвязали все устройства от своего VPN ключа.\nМожете снова выбрать, где он будет работать 🚀", show_alert=True)
            # Обновляем инфо о ключе
            from app.bot.handlers.start import my_keys
            await my_keys(callback)
        else:
            await callback.answer("❌ Не удалось сбросить устройства.\nВозможно, список и так пуст.", show_alert=True)
    except Exception as e:
        logger.error(f"Reset devices error: {e}")
        await callback.answer("❌ Произошла ошибка при сбросе.", show_alert=True)


@router.callback_query(F.data == "add_device")
async def add_device_handler(callback: CallbackQuery):
    """Обработчик покупки дополнительного устройства"""
    telegram_id = callback.from_user.id
    
    from app.bot.utils.momsclub_api import is_admin, buy_device
    
    # Проверяем — может уже VIP?
    if await is_admin(telegram_id):
        await callback.answer("👑 У тебя уже безлимит!", show_alert=True)
        return
    
    # Создаём платёж
    payment_url = await buy_device(telegram_id)
    
    if payment_url:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить 100₽", url=payment_url)],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="my_keys")]
        ])
        
        msg_text = (
            "📱 <b>Добавить устройство</b>\n\n"
            "Сейчас ты можешь подключить VPN на 2 устройствах.\n\n"
            "За 100₽ ты получишь <b>+1 устройство навсегда</b>.\n\n"
            "После оплаты лимит увеличится автоматически."
        )
        
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(msg_text, reply_markup=kb, parse_mode="HTML")
        else:
            await callback.message.edit_text(msg_text, reply_markup=kb, parse_mode="HTML")
    else:
        await callback.answer("❌ Ошибка, попробуй позже", show_alert=True)

