"""
Утилита для отправки VPN-ключей пользователю.
"""
import logging
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup

from bot.services.vpn_api import get_client
from bot.utils.key_generator import generate_qr_code

logger = logging.getLogger(__name__)

async def send_key_with_qr(
    messageable, 
    key_data: dict, 
    key_manage_markup: InlineKeyboardMarkup = None,
    is_new: bool = False
):
    """
    Отправляет пользователю ключ с QR-кодом и файлом конфигурации.
    
    Args:
        messageable: Объект Message или CallbackQuery, куда отвечать
        key_data: Данные ключа из БД (должны содержать server_id, panel_email, client_uuid)
        key_manage_markup: Клавиатура управления ключом
        is_new: Является ли ключ только что созданным
    """
    try:
        # Проверяем наличие необходимых данных
        if not key_data.get('server_id') or not key_data.get('panel_email'):
             await _send_error(messageable, "Неполные данные ключа", key_manage_markup)
             return

        # 1. Получаем конфигурацию с сервера
        try:
            client = await get_client(key_data['server_id'])
            config = await client.get_client_config(key_data['panel_email'])
        except Exception as e:
            logger.error(f"Failed to get client config: {e}")
            config = None
            
        if not config:
            # Если не удалось получить конфиг (например, сервер недоступен),
            # отправляем просто UUID (как раньше)
            uuid = key_data.get('client_uuid', 'Unknown')
            text = (
                f"📋 *Ваш VPN-ключ*\n\n"
                f"```\n{uuid}\n```\n\n"
                "☝️ Нажмите на ключ, чтобы скопировать.\n"
                "⚠️ Не удалось получить полную конфигурацию (сервер недоступен).\n"
                "Попробуйте позже."
            )
            await _send_text(messageable, text, key_manage_markup)
            return

<<<<<<< HEAD
        # 2. Формируем именно subscription URL (/sub/...),
        # чтобы клиент сам получил заголовки 3x-ui (usage/total/expire/title/announcement)
        sub_id = config.get("sub_id")
        if not sub_id:
            await _send_error(messageable, "Не найден sub_id для подписки", key_manage_markup)
            return

        from database.requests import get_server_by_id
        server = get_server_by_id(key_data['server_id'])
        if not server:
            await _send_error(messageable, "Сервер ключа не найден", key_manage_markup)
            return

        protocol = server.get("protocol", "https")
        host = server.get("host")
        port = server.get("port")
        base_path = (server.get("web_base_path") or "").strip("/")
        path_prefix = f"/{base_path}" if base_path else ""
        link = f"{protocol}://{host}:{port}{path_prefix}/sub/{sub_id}"

        logger.info(f"Generating subscription URL for {key_data.get('panel_email')}: {link}")
=======
        # 2. Генерируем данные
        logger.info(f"Generating key for {key_data.get('panel_email')} (protocol: {config.get('protocol', 'vless')})")
        # Единое отображаемое имя в клиентах
        config_for_client = dict(config)
        config_for_client['inbound_name'] = "q1 vpn"

        link = generate_link(config_for_client)
        json_config = generate_json(config_for_client)
>>>>>>> fc82ba592b8b8e4410b23b3b6326e53153beb9a8
        qr_bytes = generate_qr_code(link)
        
        # 3. Формируем сообщение
        title = "✅ *Ваш новый VPN-ключ!*" if is_new else "📋 *Ваш VPN-ключ*"
        caption = (
            f"{title}\n\n"
            f"```\n{link}\n```\n"
            "☝️ Нажмите на ссылку, чтобы скопировать.\n\n"
            "📱 *Инструкция:*\n"
            "1. Скопируйте ссылку или отсканируйте QR-код.\n"
            "2. Импортируйте в Happ / Shadowrocket / v2rayNG.\n"
            "3. Нажмите подключиться!"
        )
        
        # Если caption слишком длинный (Telegram limit 1024), сокращаем
        if len(caption) > 1024:
             caption = (
                f"{title}\n\n"
                "👇 *Ваша ссылка доступа (нажмите для копирования):*\n"
                f"`{link}`\n\n"
                "📸 Отсканируйте QR-код для быстрого подключения."
             )

        # 4. Отправляем фото с QR и ссылкой
        photo = BufferedInputFile(qr_bytes, filename="qrcode.png")
        
        # Определяем функцию отправки
        send_func = messageable.answer_photo if hasattr(messageable, 'answer_photo') else messageable.message.answer_photo
        
        await send_func(
            photo=photo,
            caption=caption,
            parse_mode="Markdown"
        )
        
        # Отправляем файл и клавиатуру отдельным сообщением, если это callback
        # Или тем же, если позволяет контекст. 
        # Но answer_photo не поддерживает редактирование предыдущего текстового сообщения в фото.
        # Поэтому если мы пришли из callback (кнопка "Показать"), старое сообщение лучше удалить или изменить.
        
        # Кнопки управления отправляем отдельным сообщением
        answer_func = messageable.message.answer if hasattr(messageable, 'message') else messageable.answer
        await answer_func("🔑 Подписка готова.", reply_markup=key_manage_markup)

    except Exception as e:
        logger.error(f"Error sending key: {e}")
        await _send_error(messageable, f"Ошибка отправки ключа: {e}", key_manage_markup)


async def _send_error(messageable, text, markup):
    """Отправляет сообщение об ошибке."""
    msg_text = f"❌ {text}"
    if hasattr(messageable, 'edit_text'):
        await messageable.edit_text(msg_text, reply_markup=markup)
    elif hasattr(messageable, 'message') and hasattr(messageable.message, 'edit_text'):
         await messageable.message.edit_text(msg_text, reply_markup=markup)
    else:
        func = messageable.answer if hasattr(messageable, 'answer') else messageable.message.answer
        await func(msg_text, reply_markup=markup)


async def _send_text(messageable, text, markup):
    """Отправляет текстовое сообщение (fallback при отсутствии фото)."""
    if hasattr(messageable, 'edit_text'):
        await messageable.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    elif hasattr(messageable, 'message') and hasattr(messageable.message, 'edit_text'):
         await messageable.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        func = messageable.answer if hasattr(messageable, 'answer') else messageable.message.answer
        await func(text, reply_markup=markup, parse_mode="Markdown")
