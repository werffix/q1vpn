"""
Утилита для отправки VPN-подписки пользователю.
"""
import logging
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup

from bot.services.vpn_api import get_client
from bot.utils.key_generator import generate_qr_code
from config import SUBSCRIPTION_AGGREGATOR_URL

logger = logging.getLogger(__name__)
SUBSCRIPTION_PUBLIC_PORT = 2096


def build_subscription_link(sub_id: str, protocol: str, host: str) -> str:
    """
    Строит URL подписки.
    Приоритет: URL агрегатора -> прямой URL панели (fallback).
    """
    if SUBSCRIPTION_AGGREGATOR_URL:
        return f"{SUBSCRIPTION_AGGREGATOR_URL}/sub/{sub_id}"
    return f"{protocol}://{host}:{SUBSCRIPTION_PUBLIC_PORT}/sub/{sub_id}"


async def send_key_with_qr(
    messageable,
    key_data: dict,
    key_manage_markup: InlineKeyboardMarkup = None,
    is_new: bool = False
):
    """
    Отправляет пользователю subscription URL с QR-кодом.
    """
    try:
        if not key_data.get('server_id') or not key_data.get('client_uuid') or not key_data.get('panel_inbound_id'):
            await _send_error(messageable, "Неполные данные ключа", key_manage_markup)
            return

        from database.requests import get_server_by_id
        server = get_server_by_id(key_data['server_id'])
        if not server:
            await _send_error(messageable, "Сервер ключа не найден", key_manage_markup)
            return

        client = await get_client(key_data['server_id'])
        sub_id = await client.get_client_sub_id(key_data['panel_inbound_id'], key_data['client_uuid'])
        if not sub_id:
            await _send_error(messageable, "Не найден subId для подписки", key_manage_markup)
            return

        protocol = server.get("protocol", "https")
        host = str(server.get("host") or "").strip()
        link = build_subscription_link(sub_id, protocol, host)

        qr_bytes = generate_qr_code(link)

        title = "✅ *Ваш новый VPN-профиль!*" if is_new else "📋 *Ваш VPN-профиль*"
        caption = (
            f"{title}\n\n"
            f"```\n{link}\n```\n"
            "☝️ Нажмите на ссылку, чтобы скопировать.\n\n"
            "📱 *Инструкция:*\n"
            "1. Скопируйте ссылку или отсканируйте QR-код.\n"
            "2. Импортируйте в Happ / Shadowrocket / v2rayNG.\n"
            "3. Нажмите подключиться!"
        )

        photo = BufferedInputFile(qr_bytes, filename="subscription_qr.png")
        send_func = messageable.answer_photo if hasattr(messageable, 'answer_photo') else messageable.message.answer_photo
        await send_func(photo=photo, caption=caption, parse_mode="Markdown")

        answer_func = messageable.message.answer if hasattr(messageable, 'message') else messageable.answer
        await answer_func("🔑 Подписка готова.", reply_markup=key_manage_markup)

    except Exception as e:
        logger.error(f"Error sending subscription: {e}")
        await _send_error(messageable, f"Ошибка отправки подписки: {e}", key_manage_markup)


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
