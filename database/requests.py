"""
Модуль запросов к базе данных.

Единственная точка доступа к БД для всех хендлеров.
Прямой SQL в хендлерах запрещён — используйте функции из этого модуля.
"""
import sqlite3
import logging
from typing import Optional, List, Dict, Any
from .connection import get_db

logger = logging.getLogger(__name__)


# ============================================================================
# СЕРВЕРЫ (servers)
# ============================================================================

def get_all_servers() -> List[Dict[str, Any]]:
    """
    Получает список всех VPN-серверов.
    
    Returns:
        Список словарей с данными серверов
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, name, host, port, web_base_path, login, password, is_active, protocol
            FROM servers
            ORDER BY id
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_server_by_id(server_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает сервер по ID.
    
    Args:
        server_id: ID сервера
        
    Returns:
        Словарь с данными сервера или None
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, name, host, port, web_base_path, login, password, is_active, protocol
            FROM servers
            WHERE id = ?
        """, (server_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_active_servers() -> List[Dict[str, Any]]:
    """
    Получает список активных VPN-серверов.
    
    Returns:
        Список словарей с данными активных серверов
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, name, host, port, web_base_path, login, password, is_active, protocol
            FROM servers
            WHERE is_active = 1
            ORDER BY id
        """)
        return [dict(row) for row in cursor.fetchall()]


def add_server(
    name: str,
    host: str,
    port: int,
    web_base_path: str,
    login: str,
    password: str,
    protocol: str = 'https'
) -> int:
    """
    Добавляет новый VPN-сервер.
    
    Args:
        name: Название сервера
        host: IP-адрес или домен
        port: Порт панели 3X-UI
        web_base_path: Секретный путь API
        login: Логин для панели
        password: Пароль для панели
        protocol: Протокол подключения (http/https)
        
    Returns:
        ID созданного сервера
    """
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO servers (name, host, port, web_base_path, login, password, is_active, protocol)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """, (name, host, port, web_base_path, login, password, protocol))
        server_id = cursor.lastrowid
        logger.info(f"Добавлен сервер: {name} (ID: {server_id})")
        return server_id


def update_server(server_id: int, **fields) -> bool:
    """
    Обновляет поля сервера.
    
    Args:
        server_id: ID сервера
        **fields: Поля для обновления (name, host, port, web_base_path, login, password, protocol)
        
    Returns:
        True если обновление успешно
    """
    allowed_fields = {'name', 'host', 'port', 'web_base_path', 'login', 'password', 'is_active', 'protocol'}
    fields = {k: v for k, v in fields.items() if k in allowed_fields}
    
    if not fields:
        return False
    
    set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
    values = list(fields.values()) + [server_id]
    
    with get_db() as conn:
        cursor = conn.execute(f"""
            UPDATE servers
            SET {set_clause}
            WHERE id = ?
        """, values)
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Обновлён сервер ID {server_id}: {list(fields.keys())}")
        return success


def update_server_field(server_id: int, field: str, value: Any) -> bool:
    """
    Обновляет одно поле сервера.
    
    Args:
        server_id: ID сервера
        field: Название поля
        value: Новое значение
        
    Returns:
        True если обновление успешно
    """
    return update_server(server_id, **{field: value})


def delete_server(server_id: int) -> bool:
    """
    Удаляет сервер.
    
    Args:
        server_id: ID сервера
        
    Returns:
        True если удаление успешно
    """
    with get_db() as conn:
        # Сначала отвязываем ключи от этого сервера, чтобы не нарушить Foreign Key
        conn.execute("UPDATE vpn_keys SET server_id = NULL WHERE server_id = ?", (server_id,))
        
        cursor = conn.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Удалён сервер ID {server_id}")
        return success


def toggle_server_active(server_id: int) -> Optional[bool]:
    """
    Переключает активность сервера.
    
    Args:
        server_id: ID сервера
        
    Returns:
        Новый статус (True = активен) или None если сервер не найден
    """
    server = get_server_by_id(server_id)
    if not server:
        return None
    
    new_status = 0 if server['is_active'] else 1
    
    with get_db() as conn:
        conn.execute("""
            UPDATE servers
            SET is_active = ?
            WHERE id = ?
        """, (new_status, server_id))
        logger.info(f"Сервер ID {server_id}: is_active = {new_status}")
        return bool(new_status)


# ============================================================================
# ПОЛЬЗОВАТЕЛИ (users)
# ============================================================================

def get_or_create_user(telegram_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    """
    Получает или создаёт пользователя.
    
    Args:
        telegram_id: Telegram ID пользователя
        username: @username (опционально)
        
    Returns:
        Словарь с данными пользователя
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()
        
        if row:
            # Обновляем username если изменился
            if username and row['username'] != username:
                conn.execute(
                    "UPDATE users SET username = ? WHERE telegram_id = ?",
                    (username, telegram_id)
                )
            return dict(row)
        
        # Создаём нового пользователя
        cursor = conn.execute(
            "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
            (telegram_id, username)
        )
        logger.info(f"Новый пользователь: {telegram_id} (@{username})")
        
        return {
            'id': cursor.lastrowid,
            'telegram_id': telegram_id,
            'username': username,
            'is_banned': 0
        }


def is_user_banned(telegram_id: int) -> bool:
    """
    Проверяет, забанен ли пользователь.
    
    Args:
        telegram_id: Telegram ID пользователя
        
    Returns:
        True если пользователь забанен
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT is_banned FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()
        return bool(row['is_banned']) if row else False


# ============================================================================
# НАСТРОЙКИ (settings)
# ============================================================================

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Получает значение настройки.
    
    Args:
        key: Ключ настройки
        default: Значение по умолчанию
        
    Returns:
        Значение настройки или default
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()
        return row['value'] if row else default


def set_setting(key: str, value: str) -> None:
    """
    Устанавливает значение настройки.
    
    Args:
        key: Ключ настройки
        value: Значение настройки
    """
    with get_db() as conn:
        conn.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        logger.info(f"Настройка обновлена: {key}")


def delete_setting(key: str) -> bool:
    """
    Удаляет настройку.
    
    Args:
        key: Ключ настройки
        
    Returns:
        True если настройка была удалена
    """
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        return cursor.rowcount > 0


def is_crypto_enabled() -> bool:
    """Проверяет, включены ли крипто-платежи."""
    return get_setting('crypto_enabled', '0') == '1'


def is_stars_enabled() -> bool:
    """Проверяет, включены ли Telegram Stars."""
    return get_setting('stars_enabled', '0') == '1'


def is_crypto_configured() -> bool:
    """
    Проверяет, настроены ли крипто-платежи полностью.
    
    Returns:
        True если крипто включены И есть ссылка на товар
    """
    if not is_crypto_enabled():
        return False
    crypto_item_url = get_setting('crypto_item_url')
    return bool(crypto_item_url and crypto_item_url.strip())


def is_cards_enabled() -> bool:
    """Проверяет, включена ли оплата картами (ЮКасса)."""
    return get_setting('cards_enabled', '0') == '1'


def is_cards_configured() -> bool:
    """
    Проверяет, настроена ли оплата картами.
    
    Returns:
        True если оплата картами включена И есть provider_token
    """
    if not is_cards_enabled():
        return False
    token = get_setting('cards_provider_token')
    return bool(token and token.strip())


def is_yookassa_qr_enabled() -> bool:
    """Проверяет, включена ли QR-оплата через ЮКассу."""
    return get_setting('yookassa_qr_enabled', '0') == '1'


def is_yookassa_qr_configured() -> bool:
    """
    Проверяет, настроена ли QR-оплата через ЮКассу полностью.

    Returns:
        True если QR включена И есть shop_id и secret_key
    """
    if not is_yookassa_qr_enabled():
        return False
    shop_id = get_setting('yookassa_shop_id', '')
    secret_key = get_setting('yookassa_secret_key', '')
    return bool(shop_id and shop_id.strip() and secret_key and secret_key.strip())


def get_yookassa_credentials() -> tuple[str, str]:
    """
    Возвращает учётные данные ЮКасса для прямого API.

    Returns:
        Кортеж (shop_id, secret_key)
    """
    shop_id = get_setting('yookassa_shop_id', '')
    secret_key = get_setting('yookassa_secret_key', '')
    return shop_id, secret_key


def save_yookassa_payment_id(order_id: str, yookassa_payment_id: str) -> bool:
    """
    Сохраняет ID платежа ЮКасса в запись ордера.

    Args:
        order_id: Наш внутренний order_id
        yookassa_payment_id: ID платежа в системе ЮКассы

    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE payments SET yookassa_payment_id = ? WHERE order_id = ?",
            (yookassa_payment_id, order_id)
        )
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Сохранён yookassa_payment_id={yookassa_payment_id} для order_id={order_id}")
        return success


def find_order_by_yookassa_id(yookassa_payment_id: str) -> Optional[Dict[str, Any]]:
    """
    Находит ордер по ID платежа ЮКасса.

    Args:
        yookassa_payment_id: ID платежа в системе ЮКассы

    Returns:
        Словарь с данными ордера или None
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM payments WHERE yookassa_payment_id = ?",
            (yookassa_payment_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def is_trial_enabled() -> bool:
    """Включена ли функция пробной подписки."""
    return get_setting('trial_enabled', '0') == '1'


def get_trial_tariff_id() -> Optional[int]:
    """
    Возвращает ID тарифа для пробной подписки.
    
    Returns:
        ID тарифа или None если тариф не задан
    """
    val = get_setting('trial_tariff_id', '')
    return int(val) if val and val.isdigit() else None


def has_used_trial(telegram_id: int) -> bool:
    """
    Проверяет, использовал ли пользователь пробную подписку.
    
    Args:
        telegram_id: Telegram ID пользователя
        
    Returns:
        True если пользователь уже использовал пробный период
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT used_trial FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()
        return bool(row['used_trial']) if row else False


def mark_trial_used(user_id: int) -> None:
    """
    Помечает, что пользователь использовал пробную подписку.
    
    Args:
        user_id: Внутренний ID пользователя (не Telegram ID)
    """
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET used_trial = 1 WHERE id = ?",
            (user_id,)
        )
        logger.info(f"Пользователь ID {user_id} использовал пробный период")


def set_referrer_if_possible(telegram_id: int, referrer_telegram_id: int) -> bool:
    """
    Привязывает реферера пользователю один раз (если еще не привязан).
    """
    if telegram_id == referrer_telegram_id:
        return False

    with get_db() as conn:
        user_row = conn.execute(
            "SELECT id, referred_by FROM users WHERE telegram_id = ?",
            (telegram_id,)
        ).fetchone()
        if not user_row or user_row['referred_by'] is not None:
            return False

        ref_row = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?",
            (referrer_telegram_id,)
        ).fetchone()
        if not ref_row:
            return False

        if user_row['id'] == ref_row['id']:
            return False

        cursor = conn.execute(
            "UPDATE users SET referred_by = ? WHERE id = ? AND referred_by IS NULL",
            (ref_row['id'], user_row['id'])
        )
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Реферер привязан: user={telegram_id}, referrer={referrer_telegram_id}")
        return success


def apply_referral_reward_for_trial(referred_user_id: int, reward_days: int = 7) -> bool:
    """
    Начисляет награду рефереру после активации trial приглашенным пользователем.
    Награда начисляется только один раз на приглашенного.
    """
    with get_db() as conn:
        referred = conn.execute("""
            SELECT id, referred_by, referred_reward_granted
            FROM users
            WHERE id = ?
        """, (referred_user_id,)).fetchone()

        if not referred or not referred['referred_by'] or referred['referred_reward_granted']:
            return False

        referrer_id = referred['referred_by']

        conn.execute(
            "UPDATE users SET referred_reward_granted = 1 WHERE id = ?",
            (referred_user_id,)
        )
        conn.execute("""
            UPDATE users
            SET referral_days_earned = COALESCE(referral_days_earned, 0) + ?
            WHERE id = ?
        """, (reward_days, referrer_id))

        key_row = conn.execute("""
            SELECT id
            FROM vpn_keys
            WHERE user_id = ?
            ORDER BY
                CASE WHEN expires_at > datetime('now') THEN 0 ELSE 1 END,
                expires_at DESC
            LIMIT 1
        """, (referrer_id,)).fetchone()

        if key_row:
            conn.execute("""
                UPDATE vpn_keys
                SET expires_at = datetime(
                    CASE
                        WHEN expires_at > datetime('now') THEN expires_at
                        ELSE datetime('now')
                    END,
                    '+' || ? || ' days'
                )
                WHERE id = ?
            """, (reward_days, key_row['id']))

        logger.info(
            f"Реферальная награда начислена: referred_user={referred_user_id}, "
            f"referrer_user={referrer_id}, days={reward_days}"
        )
        return True


def apply_referral_reward_on_join(referred_telegram_id: int, reward_days: int = 7) -> Dict[str, Any]:
    """
    Начисляет реферальную награду сразу при первом переходе друга по ссылке.
    """
    with get_db() as conn:
        referred = conn.execute("""
            SELECT id, referred_by, referred_reward_granted
            FROM users
            WHERE telegram_id = ?
        """, (referred_telegram_id,)).fetchone()
        if not referred or not referred['referred_by'] or referred['referred_reward_granted']:
            return {'granted': False}

        referrer = conn.execute("""
            SELECT id, telegram_id
            FROM users
            WHERE id = ?
        """, (referred['referred_by'],)).fetchone()
        if not referrer:
            return {'granted': False}

        conn.execute("UPDATE users SET referred_reward_granted = 1 WHERE id = ?", (referred['id'],))
        conn.execute("""
            UPDATE users
            SET referral_days_earned = COALESCE(referral_days_earned, 0) + ?
            WHERE id = ?
        """, (reward_days, referrer['id']))

        key_row = conn.execute("""
            SELECT id
            FROM vpn_keys
            WHERE user_id = ?
            ORDER BY
                CASE WHEN expires_at > datetime('now') THEN 0 ELSE 1 END,
                expires_at DESC
            LIMIT 1
        """, (referrer['id'],)).fetchone()
        if key_row:
            conn.execute("""
                UPDATE vpn_keys
                SET expires_at = datetime(
                    CASE
                        WHEN expires_at > datetime('now') THEN expires_at
                        ELSE datetime('now')
                    END,
                    '+' || ? || ' days'
                )
                WHERE id = ?
            """, (reward_days, key_row['id']))

        logger.info(
            f"Реферальная награда при входе: referred_tg={referred_telegram_id}, "
            f"referrer_tg={referrer['telegram_id']}, days={reward_days}"
        )
        return {'granted': True, 'referrer_telegram_id': referrer['telegram_id']}


def is_user_referred(user_id: int) -> bool:
    """Проверяет, что пользователь пришел по реферальной ссылке."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT referred_by FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        return bool(row and row['referred_by'])


def get_referral_stats(telegram_id: int) -> Dict[str, Any]:
    """Статистика реферальной системы пользователя."""
    with get_db() as conn:
        user = conn.execute("""
            SELECT id, COALESCE(referral_days_earned, 0) AS referral_days_earned
            FROM users
            WHERE telegram_id = ?
        """, (telegram_id,)).fetchone()

        if not user:
            return {'invited_total': 0, 'trial_activated_total': 0, 'earned_days': 0}

        invited_total = conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE referred_by = ?",
            (user['id'],)
        ).fetchone()['cnt']

        trial_activated_total = conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE referred_by = ? AND used_trial = 1",
            (user['id'],)
        ).fetchone()['cnt']

        return {
            'invited_total': invited_total,
            'trial_activated_total': trial_activated_total,
            'earned_days': user['referral_days_earned'],
        }


def get_user_primary_key_for_profile(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Основной ключ пользователя для экрана личного кабинета."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                vk.id, vk.user_id, vk.server_id, vk.panel_inbound_id, vk.panel_email, vk.client_uuid,
                vk.created_at, vk.expires_at,
                t.name AS tariff_name,
                CASE
                    WHEN vk.expires_at > datetime('now') THEN 1
                    ELSE 0
                END AS is_active
            FROM vpn_keys vk
            JOIN users u ON u.id = vk.user_id
            LEFT JOIN tariffs t ON t.id = vk.tariff_id
            WHERE u.telegram_id = ?
            ORDER BY
                CASE WHEN vk.expires_at > datetime('now') THEN 0 ELSE 1 END,
                vk.expires_at DESC
            LIMIT 1
        """, (telegram_id,)).fetchone()
        return dict(row) if row else None


def get_user_keys_for_subscription(telegram_id: int) -> List[Dict[str, Any]]:
    """
    Возвращает ключи пользователя с данными серверов для формирования подписки.
    """
    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                vk.id,
                vk.panel_email,
                vk.expires_at,
                vk.server_id,
                s.name AS server_name,
                s.host,
                s.port,
                s.web_base_path,
                s.protocol
            FROM vpn_keys vk
            JOIN users u ON u.id = vk.user_id
            LEFT JOIN servers s ON s.id = vk.server_id
            WHERE u.telegram_id = ?
            ORDER BY vk.expires_at DESC
        """, (telegram_id,)).fetchall()
        return [dict(row) for row in rows]


# ============================================================================
# ТАРИФЫ (tariffs)
# ============================================================================

def get_all_tariffs(include_hidden: bool = False) -> List[Dict[str, Any]]:
    """
    Получает список всех тарифов.
    
    Args:
        include_hidden: Включать скрытые тарифы (is_active = 0)
        
    Returns:
        Список словарей с данными тарифов
    """
    with get_db() as conn:
        if include_hidden:
            cursor = conn.execute("""
                SELECT id, name, duration_days, price_cents, price_stars, price_rub, 
                       external_id, display_order, is_active
                FROM tariffs
                ORDER BY display_order, id
            """)
        else:
            cursor = conn.execute("""
                SELECT id, name, duration_days, price_cents, price_stars, price_rub, 
                       external_id, display_order, is_active
                FROM tariffs
                WHERE is_active = 1
                ORDER BY display_order, id
            """)
        return [dict(row) for row in cursor.fetchall()]


def get_tariff_by_id(tariff_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает тариф по ID.
    
    Args:
        tariff_id: ID тарифа
        
    Returns:
        Словарь с данными тарифа или None
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, name, duration_days, price_cents, price_stars, price_rub, 
                   external_id, display_order, is_active
            FROM tariffs
            WHERE id = ?
        """, (tariff_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_tariff_by_external_id(external_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает тариф по external_id (ID в Ya.Seller).
    
    Args:
        external_id: Номер тарифа в Ya.Seller (1-9)
        
    Returns:
        Словарь с данными тарифа или None
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, name, duration_days, price_cents, price_stars, price_rub, 
                   external_id, display_order, is_active
            FROM tariffs
            WHERE external_id = ? AND is_active = 1
        """, (external_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def add_tariff(
    name: str,
    duration_days: int,
    price_cents: int,
    price_stars: int,
    price_rub: int = 0,
    external_id: Optional[int] = None,
    display_order: int = 0
) -> int:
    """
    Добавляет новый тариф.
    
    Args:
        name: Название тарифа
        duration_days: Длительность в днях
        price_cents: Цена в центах (USDT * 100)
        price_stars: Цена в Telegram Stars
        price_rub: Цена в рублях
        external_id: Номер тарифа в Ya.Seller (1-9), опционально
        display_order: Порядок отображения
        
    Returns:
        ID созданного тарифа
    """
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO tariffs (name, duration_days, price_cents, price_stars, price_rub, 
                                external_id, display_order, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """, (name, duration_days, price_cents, price_stars, price_rub, external_id, display_order))
        tariff_id = cursor.lastrowid
        logger.info(f"Добавлен тариф: {name} (ID: {tariff_id})")
        return tariff_id


def update_tariff(tariff_id: int, **fields) -> bool:
    """
    Обновляет поля тарифа.
    
    Args:
        tariff_id: ID тарифа
        **fields: Поля для обновления
        
    Returns:
        True если обновление успешно
    """
    allowed_fields = {'name', 'duration_days', 'price_cents', 'price_stars', 'price_rub',
                      'external_id', 'display_order', 'is_active'}
    fields = {k: v for k, v in fields.items() if k in allowed_fields}
    
    if not fields:
        return False
    
    set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
    values = list(fields.values()) + [tariff_id]
    
    with get_db() as conn:
        cursor = conn.execute(f"""
            UPDATE tariffs
            SET {set_clause}
            WHERE id = ?
        """, values)
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Обновлён тариф ID {tariff_id}: {list(fields.keys())}")
        return success


def update_tariff_field(tariff_id: int, field: str, value: Any) -> bool:
    """
    Обновляет одно поле тарифа.
    
    Args:
        tariff_id: ID тарифа
        field: Название поля
        value: Новое значение
        
    Returns:
        True если обновление успешно
    """
    return update_tariff(tariff_id, **{field: value})


def toggle_tariff_active(tariff_id: int) -> Optional[bool]:
    """
    Переключает активность тарифа (скрыть/показать).
    
    Args:
        tariff_id: ID тарифа
        
    Returns:
        Новый статус (True = активен) или None если тариф не найден
    """
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        return None
    
    new_status = 0 if tariff['is_active'] else 1
    
    with get_db() as conn:
        conn.execute("""
            UPDATE tariffs
            SET is_active = ?
            WHERE id = ?
        """, (new_status, tariff_id))
        status_text = "активирован" if new_status else "скрыт"
        logger.info(f"Тариф ID {tariff_id}: {status_text}")
        return bool(new_status)


def get_tariffs_count() -> int:
    """
    Возвращает количество активных тарифов.
    
    Returns:
        Количество активных тарифов
    """
    with get_db() as conn:
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM tariffs WHERE is_active = 1")
        row = cursor.fetchone()
        return row['cnt'] if row else 0


def get_admin_tariff() -> Optional[Dict[str, Any]]:
    """
    Получает скрытый Admin Tariff для админского добавления ключей.
    
    Если тариф не существует, создаёт его автоматически.
    
    Returns:
        Словарь с данными тарифа
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, name, duration_days, price_cents, price_stars, price_rub, 
                   external_id, display_order, is_active
            FROM tariffs
            WHERE name = 'Admin Tariff'
            LIMIT 1
        """)
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        
        # Если тариф не найден, создаём его
        cursor = conn.execute("""
            INSERT INTO tariffs (name, duration_days, price_cents, price_stars, price_rub, display_order, is_active)
            VALUES ('Admin Tariff', 30, 0, 0, 0, 999, 0)
        """)
        logger.info("Создан Admin Tariff")
        
        return {
            'id': cursor.lastrowid,
            'name': 'Admin Tariff',
            'duration_days': 30,
            'price_cents': 0,
            'price_stars': 0,
            'price_rub': 0,
            'external_id': None,
            'display_order': 999,
            'is_active': 0
        }


# ============================================================================
# РАССЫЛКА И УВЕДОМЛЕНИЯ
# ============================================================================

def get_users_for_broadcast(filter_type: str) -> List[int]:
    """
    Получает список telegram_id пользователей для рассылки.
    
    Args:
        filter_type: Тип фильтра:
            - 'all': все не забаненные пользователи
            - 'active': с активными (непросроченными) ключами
            - 'inactive': без активных ключей
            - 'never_paid': никогда не покупали VPN
            - 'expired': был ключ, но он истёк
    
    Returns:
        Список telegram_id пользователей
    """
    with get_db() as conn:
        if filter_type == 'all':
            # Все не забаненные
            cursor = conn.execute("""
                SELECT telegram_id FROM users WHERE is_banned = 0
            """)
        elif filter_type == 'active':
            # Есть хотя бы один непросроченный ключ
            cursor = conn.execute("""
                SELECT DISTINCT u.telegram_id 
                FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE u.is_banned = 0 
                AND vk.expires_at > datetime('now')
            """)
        elif filter_type == 'inactive':
            # Нет активных ключей (либо все истекли, либо никогда не было)
            cursor = conn.execute("""
                SELECT u.telegram_id 
                FROM users u
                WHERE u.is_banned = 0 
                AND u.id NOT IN (
                    SELECT DISTINCT user_id FROM vpn_keys 
                    WHERE expires_at > datetime('now')
                )
            """)
        elif filter_type == 'never_paid':
            # Никогда не покупали VPN (нет ключей вообще)
            cursor = conn.execute("""
                SELECT u.telegram_id 
                FROM users u
                WHERE u.is_banned = 0 
                AND u.id NOT IN (SELECT DISTINCT user_id FROM vpn_keys)
            """)
        elif filter_type == 'expired':
            # Был ключ, но он уже истёк (и нет активных)
            cursor = conn.execute("""
                SELECT DISTINCT u.telegram_id 
                FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE u.is_banned = 0 
                AND vk.expires_at <= datetime('now')
                AND u.id NOT IN (
                    SELECT DISTINCT user_id FROM vpn_keys 
                    WHERE expires_at > datetime('now')
                )
            """)
        else:
            return []
        
        return [row['telegram_id'] for row in cursor.fetchall()]


def count_users_for_broadcast(filter_type: str) -> int:
    """
    Считает количество пользователей для рассылки.
    
    Args:
        filter_type: Тип фильтра (см. get_users_for_broadcast)
    
    Returns:
        Количество пользователей
    """
    return len(get_users_for_broadcast(filter_type))


def get_expiring_keys(days: int) -> List[Dict[str, Any]]:
    """
    Получает ключи, истекающие в ближайшие N дней (но ещё не истёкшие).
    
    Args:
        days: Количество дней до истечения
    
    Returns:
        Список словарей: vpn_key_id, user_telegram_id, expires_at, days_left
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT 
                vk.id as vpn_key_id,
                u.telegram_id as user_telegram_id,
                vk.expires_at,
                CAST((julianday(vk.expires_at) - julianday('now')) AS INTEGER) as days_left
            FROM vpn_keys vk
            JOIN users u ON vk.user_id = u.id
            WHERE u.is_banned = 0
            AND vk.expires_at > datetime('now')
            AND vk.expires_at <= datetime('now', '+' || ? || ' days')
        """, (days,))
        return [dict(row) for row in cursor.fetchall()]


def is_notification_sent_today(vpn_key_id: int) -> bool:
    """
    Проверяет, было ли сегодня отправлено уведомление для этого ключа.
    
    Args:
        vpn_key_id: ID VPN-ключа
    
    Returns:
        True если уведомление уже отправлено сегодня
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT 1 FROM notification_log
            WHERE vpn_key_id = ? AND sent_at = date('now')
        """, (vpn_key_id,))
        return cursor.fetchone() is not None


def log_notification_sent(vpn_key_id: int) -> None:
    """
    Записывает факт отправки уведомления.
    
    Args:
        vpn_key_id: ID VPN-ключа
    """
    with get_db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO notification_log (vpn_key_id, sent_at)
            VALUES (?, date('now'))
        """, (vpn_key_id,))
        logger.debug(f"Записано уведомление для ключа {vpn_key_id}")


def get_all_users_count() -> int:
    """
    Возвращает общее количество пользователей (не забаненных).
    
    Returns:
        Количество пользователей
    """
    with get_db() as conn:
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE is_banned = 0")
        row = cursor.fetchone()
        return row['cnt'] if row else 0


# ============================================================================
# ПОЛЬЗОВАТЕЛИ - АДМИНИСТРАТИВНЫЕ ФУНКЦИИ
# ============================================================================

def get_users_stats() -> Dict[str, int]:
    """
    Возвращает статистику пользователей по фильтрам (как в рассылке).
    
    Returns:
        Словарь с количеством пользователей по категориям:
        - total: все не забаненные
        - active: с активными ключами
        - inactive: без активных ключей
        - never_paid: никогда не покупали
        - expired: был ключ, но истёк
    """
    return {
        'total': count_users_for_broadcast('all'),
        'active': count_users_for_broadcast('active'),
        'inactive': count_users_for_broadcast('inactive'),
        'never_paid': count_users_for_broadcast('never_paid'),
        'expired': count_users_for_broadcast('expired'),
    }


def get_all_users_paginated(offset: int = 0, limit: int = 20, 
                             filter_type: str = 'all') -> tuple[List[Dict[str, Any]], int]:
    """
    Получает список пользователей с пагинацией и фильтрацией.
    
    Args:
        offset: Смещение для пагинации
        limit: Количество на странице (по умолчанию 20)
        filter_type: Тип фильтра (all, active, inactive, never_paid, expired)
    
    Returns:
        Кортеж (список пользователей, общее количество)
    """
    with get_db() as conn:
        # Базовый запрос с данными о ключах
        if filter_type == 'all':
            base_query = "SELECT * FROM users WHERE is_banned = 0"
            count_query = "SELECT COUNT(*) as cnt FROM users WHERE is_banned = 0"
        elif filter_type == 'active':
            base_query = """
                SELECT DISTINCT u.* FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE u.is_banned = 0 AND vk.expires_at > datetime('now')
            """
            count_query = """
                SELECT COUNT(DISTINCT u.id) as cnt FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE u.is_banned = 0 AND vk.expires_at > datetime('now')
            """
        elif filter_type == 'inactive':
            base_query = """
                SELECT u.* FROM users u
                WHERE u.is_banned = 0 
                AND u.id NOT IN (
                    SELECT DISTINCT user_id FROM vpn_keys 
                    WHERE expires_at > datetime('now')
                )
            """
            count_query = """
                SELECT COUNT(*) as cnt FROM users u
                WHERE u.is_banned = 0 
                AND u.id NOT IN (
                    SELECT DISTINCT user_id FROM vpn_keys 
                    WHERE expires_at > datetime('now')
                )
            """
        elif filter_type == 'never_paid':
            base_query = """
                SELECT u.* FROM users u
                WHERE u.is_banned = 0 
                AND u.id NOT IN (SELECT DISTINCT user_id FROM vpn_keys)
            """
            count_query = """
                SELECT COUNT(*) as cnt FROM users u
                WHERE u.is_banned = 0 
                AND u.id NOT IN (SELECT DISTINCT user_id FROM vpn_keys)
            """
        elif filter_type == 'expired':
            base_query = """
                SELECT DISTINCT u.* FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE u.is_banned = 0 
                AND vk.expires_at <= datetime('now')
                AND u.id NOT IN (
                    SELECT DISTINCT user_id FROM vpn_keys 
                    WHERE expires_at > datetime('now')
                )
            """
            count_query = """
                SELECT COUNT(DISTINCT u.id) as cnt FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE u.is_banned = 0 
                AND vk.expires_at <= datetime('now')
                AND u.id NOT IN (
                    SELECT DISTINCT user_id FROM vpn_keys 
                    WHERE expires_at > datetime('now')
                )
            """
        else:
            return [], 0
        
        # Получаем общее количество
        cursor = conn.execute(count_query)
        total = cursor.fetchone()['cnt']
        
        # Получаем страницу
        cursor = conn.execute(f"{base_query} ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        users = [dict(row) for row in cursor.fetchall()]
        
        return users, total


def get_user_by_telegram_id(telegram_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает пользователя по Telegram ID.
    
    Args:
        telegram_id: Telegram ID пользователя
    
    Returns:
        Словарь с данными пользователя или None
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """
    Получает пользователя по @username.
    
    Args:
        username: Username без @
    
    Returns:
        Словарь с данными пользователя или None
    """
    # Убираем @ если передали с ним
    username = username.lstrip('@')
    
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)",
            (username,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def toggle_user_ban(telegram_id: int) -> Optional[bool]:
    """
    Переключает бан пользователя.
    
    Args:
        telegram_id: Telegram ID пользователя
    
    Returns:
        Новый статус (True = забанен) или None если не найден
    """
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        return None
    
    new_status = 0 if user['is_banned'] else 1
    
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET is_banned = ? WHERE telegram_id = ?",
            (new_status, telegram_id)
        )
        status_text = "забанен" if new_status else "разбанен"
        logger.info(f"Пользователь {telegram_id}: {status_text}")
        return bool(new_status)


def get_user_vpn_keys(user_id: int) -> List[Dict[str, Any]]:
    """
    Получает все VPN-ключи пользователя с данными о тарифе и сервере.
    
    Args:
        user_id: Внутренний ID пользователя (users.id)
    
    Returns:
        Список ключей с полной информацией
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT 
                vk.id, vk.client_uuid, vk.custom_name, vk.expires_at, 
                vk.created_at, vk.panel_inbound_id, vk.panel_email,
                t.name as tariff_name, t.duration_days,
                s.name as server_name, s.id as server_id
            FROM vpn_keys vk
            LEFT JOIN tariffs t ON vk.tariff_id = t.id
            LEFT JOIN servers s ON vk.server_id = s.id
            WHERE vk.user_id = ?
            ORDER BY vk.expires_at DESC
        """, (user_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_user_payments_stats(user_id: int) -> Dict[str, Any]:
    """
    Получает статистику оплат пользователя.
    
    Args:
        user_id: Внутренний ID пользователя
    
    Returns:
        Словарь со статистикой:
        - total_payments: количество платежей
        - total_amount_cents: общая сумма в центах
        - total_amount_stars: общая сумма в звёздах
        - last_payment_at: дата последней оплаты
        - tariffs: список уникальных тарифов
    """
    with get_db() as conn:
        # Общая статистика
        cursor = conn.execute("""
            SELECT 
                COUNT(*) as total_payments,
                COALESCE(SUM(CASE WHEN payment_type = 'crypto' THEN amount_cents ELSE 0 END), 0) as total_amount_cents,
                COALESCE(SUM(CASE WHEN payment_type = 'stars' THEN amount_stars ELSE 0 END), 0) as total_amount_stars,
                COALESCE(SUM(CASE WHEN payment_type = 'cards' THEN t.price_rub ELSE 0 END), 0) as total_amount_rub,
                MAX(paid_at) as last_payment_at
            FROM payments p
            LEFT JOIN tariffs t ON p.tariff_id = t.id
            WHERE p.user_id = ? AND p.status = 'paid'
        """, (user_id,))
        stats = dict(cursor.fetchone())
        
        # Уникальные тарифы
        cursor = conn.execute("""
            SELECT DISTINCT t.name 
            FROM payments p
            JOIN tariffs t ON p.tariff_id = t.id
            WHERE p.user_id = ?
        """, (user_id,))
        stats['tariffs'] = [row['name'] for row in cursor.fetchall()]
        
        return stats


def get_vpn_key_by_id(key_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает VPN-ключ по ID с полной информацией.
    
    Args:
        key_id: ID ключа
    
    Returns:
        Словарь с данными ключа или None
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT 
                vk.*,
                t.name as tariff_name, t.duration_days, t.price_cents,
                s.name as server_name, s.host, s.port, s.web_base_path, 
                s.login, s.password, s.is_active as server_active,
                u.telegram_id, u.username
            FROM vpn_keys vk
            LEFT JOIN tariffs t ON vk.tariff_id = t.id
            LEFT JOIN servers s ON vk.server_id = s.id
            LEFT JOIN users u ON vk.user_id = u.id
            WHERE vk.id = ?
        """, (key_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def extend_vpn_key(key_id: int, days: int) -> bool:
    """
    Продлевает VPN-ключ на указанное количество дней.
    
    Args:
        key_id: ID ключа
        days: Количество дней для продления
    
    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE vpn_keys 
            SET expires_at = datetime(
                CASE 
                    WHEN expires_at > datetime('now') THEN expires_at
                    ELSE datetime('now')
                END, 
                '+' || ? || ' days'
            )
            WHERE id = ?
        """, (days, key_id))
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Ключ ID {key_id} продлён на {days} дней")
        return success


def create_vpn_key_admin(
    user_id: int, 
    server_id: int, 
    tariff_id: int,
    panel_inbound_id: int,
    panel_email: str,
    client_uuid: str,
    days: int
) -> int:
    """
    Создаёт VPN-ключ администратором (без оплаты).
    
    Args:
        user_id: Внутренний ID пользователя
        server_id: ID сервера
        tariff_id: ID тарифа
        panel_inbound_id: ID inbound в панели
        panel_email: Email (идентификатор) клиента в панели
        client_uuid: UUID клиента
        days: Срок действия в днях
    
    Returns:
        ID созданного ключа
    """
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO vpn_keys 
            (user_id, server_id, tariff_id, panel_inbound_id, panel_email, client_uuid, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now', '+' || ? || ' days'))
        """, (user_id, server_id, tariff_id, panel_inbound_id, panel_email, client_uuid, days))
        key_id = cursor.lastrowid
        logger.info(f"Администратор создал ключ ID {key_id} для user_id {user_id}")
        return key_id



def update_vpn_key_connection(
    key_id: int,
    server_id: int,
    panel_inbound_id: int,
    panel_email: str,
    client_uuid: str
) -> bool:
    """
    Обновляет технические данные ключа (сервер, UUID, inbound).
    Используется при замене ключа.
    
    Args:
        key_id: ID ключа
        server_id: ID нового сервера
        panel_inbound_id: ID inbound в панели
        panel_email: Email (идентификатор) клиента в панели
        client_uuid: Новый UUID клиента
        
    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE vpn_keys 
            SET server_id = ?, 
                panel_inbound_id = ?, 
                panel_email = ?, 
                client_uuid = ?
            WHERE id = ?
        """, (server_id, panel_inbound_id, panel_email, client_uuid, key_id))
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Ключ ID {key_id} перенесён на сервер {server_id} (новый UUID: {client_uuid[:4]}...)")
        return success


# ============================================================================
# СТАТИСТИКА ДЛЯ ЕЖЕДНЕВНЫХ ОТЧЁТОВ
# ============================================================================

def get_daily_payments_stats() -> Dict[str, Any]:
    """
    Получает статистику платежей за последние 24 часа.
    
    Returns:
        Словарь со статистикой:
        - paid_count: количество успешных платежей
        - paid_cents: сумма успешных в центах
        - paid_stars: сумма успешных в звёздах
        - pending_count: количество ожидающих (неоплаченных)
    """
    with get_db() as conn:
        # 1. Считаем USDT (crypto)
        cursor = conn.execute("""
            SELECT 
                COUNT(*) as count,
                COALESCE(SUM(amount_cents), 0) as total_cents
            FROM payments
            WHERE status = 'paid' 
            AND payment_type = 'crypto'
            AND paid_at >= datetime('now', '-1 day')
        """)
        crypto_row = cursor.fetchone()
        
        # 2. Считаем Stars
        cursor = conn.execute("""
            SELECT 
                COUNT(*) as count,
                COALESCE(SUM(amount_stars), 0) as total_stars
            FROM payments
            WHERE status = 'paid' 
            AND payment_type = 'stars'
            AND paid_at >= datetime('now', '-1 day')
        """)
        stars_row = cursor.fetchone()
        
        # 3. Считаем Карты (Cards - Рубли)
        cursor = conn.execute("""
            SELECT 
                COUNT(*) as count,
                COALESCE(SUM(t.price_rub), 0) as total_rub
            FROM payments p
            LEFT JOIN tariffs t ON p.tariff_id = t.id
            WHERE p.status = 'paid' 
            AND p.payment_type = 'cards'
            AND p.paid_at >= datetime('now', '-1 day')
        """)
        cards_row = cursor.fetchone()
        
        paid_count = (crypto_row['count'] if crypto_row else 0) + \
                     (stars_row['count'] if stars_row else 0) + \
                     (cards_row['count'] if cards_row else 0)
        total_cents = crypto_row['total_cents'] if crypto_row else 0
        total_stars = stars_row['total_stars'] if stars_row else 0
        total_rub = cards_row['total_rub'] if cards_row else 0
        
        return {
            'paid_count': paid_count,
            'paid_cents': total_cents,
            'paid_stars': total_stars,
            'paid_rub': total_rub,
            'pending_count': 0 
        }

def get_key_payments_history(key_id: int) -> List[Dict[str, Any]]:
    """
    Получает историю платежей по конкретному ключу.
    
    Args:
        key_id: ID ключа
    
    Returns:
        Список платежей, отсортированный по дате (по убыванию).
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT 
                p.id, p.paid_at, p.payment_type, p.amount_cents, p.amount_stars,
                t.name as tariff_name, t.price_rub
            FROM payments p
            LEFT JOIN tariffs t ON p.tariff_id = t.id
            WHERE p.vpn_key_id = ? AND p.status = 'paid'
            ORDER BY p.paid_at DESC
        """, (key_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_keys_stats() -> Dict[str, int]:
    """
    Получает статистику VPN-ключей.
    
    Returns:
        Словарь со статистикой:
        - total: всего ключей
        - active: активных (не истёкших)
        - expired: истёкших
        - created_today: созданных за последние 24 часа
    """
    with get_db() as conn:
        # Всего ключей
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM vpn_keys")
        total = cursor.fetchone()['cnt']
        
        # Активных (не истёкших)
        cursor = conn.execute("""
            SELECT COUNT(*) as cnt FROM vpn_keys 
            WHERE expires_at > datetime('now')
        """)
        active = cursor.fetchone()['cnt']
        
        # Созданных за сутки
        cursor = conn.execute("""
            SELECT COUNT(*) as cnt FROM vpn_keys 
            WHERE created_at >= datetime('now', '-1 day')
        """)
        created_today = cursor.fetchone()['cnt']
        
        return {
            'total': total,
            'active': active,
            'expired': total - active,
            'created_today': created_today
        }





def get_new_users_count_today() -> int:
    """
    Получает количество новых пользователей за последние 24 часа.
    
    Returns:
        Количество новых пользователей
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT COUNT(*) as cnt FROM users 
            WHERE created_at >= datetime('now', '-1 day')
        """)
        row = cursor.fetchone()
        return row['cnt'] if row else 0


# ============================================================================
# ПЛАТЕЖИ И PENDING ORDERS
# ============================================================================

# Base62 алфавит для генерации коротких уникальных ID
BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _int_to_base62(num: int) -> str:
    """
    Конвертирует число в base62 строку.
    
    Args:
        num: Положительное целое число
        
    Returns:
        Base62 строка (0-9, A-Z, a-z)
    """
    if num == 0:
        return BASE62_ALPHABET[0]
    
    result = []
    while num > 0:
        result.append(BASE62_ALPHABET[num % 62])
        num //= 62
    
    return ''.join(reversed(result))


def create_pending_order(
    user_id: int,
    tariff_id: Optional[int],
    payment_type: Optional[str],
    vpn_key_id: Optional[int] = None
) -> tuple[int, str]:
    """
    Создаёт pending order и генерирует уникальный order_id.
    
    Order_id генерируется из внутреннего ID записи в base62 формате,
    что гарантирует уникальность и соответствие формату криптопроцессинга
    (макс 8 символов A-Za-z0-9).
    
    Args:
        user_id: Внутренний ID пользователя
        tariff_id: ID тарифа (может быть None для крипты)
        payment_type: 'crypto', 'stars' или None (если выбирается при оплате)
        vpn_key_id: ID ключа для продления (None для нового ключа)
    
    Returns:
        Кортеж (payment_id, order_id)
    """
    tariff = get_tariff_by_id(tariff_id) if tariff_id else None
    
    with get_db() as conn:
        # Шаг 1: создаём запись с временным order_id
        cursor = conn.execute("""
            INSERT INTO payments 
            (user_id, tariff_id, order_id, payment_type, vpn_key_id, 
             amount_cents, amount_stars, period_days, status, paid_at)
            VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, 'pending', NULL)
        """, (
            user_id, tariff_id, payment_type, vpn_key_id,
            tariff['price_cents'] if tariff else 0,
            tariff['price_stars'] if tariff else 0,
            tariff['duration_days'] if tariff else None
        ))
        payment_id = cursor.lastrowid
        
        # Шаг 2: генерируем order_id из ID записи (base62)
        # Добавляем префикс '00' для исключения конфликтов с внешними ID
        order_id = "00" + _int_to_base62(payment_id)
        
        # Шаг 3: обновляем order_id
        conn.execute("""
            UPDATE payments SET order_id = ? WHERE id = ?
        """, (order_id, payment_id))
        
        logger.info(f"Создан pending order: {order_id} (id={payment_id}, user={user_id}, type={payment_type})")
        return payment_id, order_id


def create_paid_order_external(
    order_id: str,
    user_id: int,
    tariff_id: int,
    payment_type: str,
    amount_cents: int,
    amount_stars: int,
    period_days: int
) -> bool:
    """
    Создаёт сразу оплаченный ордер (для внешних платежей).
    
    Используется когда оплата пришла извне (без предварительного pending order).
    
    Args:
        order_id: Внешний ID ордера
        user_id: ID пользователя
        tariff_id: ID тарифа
        payment_type: Тип оплаты ('crypto', 'stars')
        amount_cents: Сумма в центах
        amount_stars: Сумма в звёздах
        period_days: Срок действия
        
    Returns:
        True если успешно
    """
    try:
        with get_db() as conn:
            conn.execute("""
                INSERT INTO payments 
                (user_id, tariff_id, order_id, payment_type, vpn_key_id, 
                 amount_cents, amount_stars, period_days, status, paid_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, 'pending', NULL)
            """, (
                user_id, tariff_id, order_id, payment_type,
                amount_cents, amount_stars, period_days
            ))
            logger.info(f"Создан external pending order: {order_id} (user={user_id})")
            return True
    except Exception as e:
        logger.error(f"Ошибка создания external order {order_id}: {e}")
        return False


def find_order_by_order_id(order_id: str) -> Optional[Dict[str, Any]]:
    """
    Находит платёж по order_id.
    
    Args:
        order_id: Уникальный ID ордера
    
    Returns:
        Словарь с данными платежа или None
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT p.*, t.duration_days, t.name as tariff_name
            FROM payments p
            LEFT JOIN tariffs t ON p.tariff_id = t.id
            WHERE p.order_id = ?
        """, (order_id,))
        row = cursor.fetchone()
        return dict(row) if row else None



def complete_order(order_id: str) -> bool:
    """
    Завершает платёж: меняет статус на 'paid'.
    
    Args:
        order_id: ID ордера
    
    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE payments 
            SET status = 'paid', paid_at = CURRENT_TIMESTAMP
            WHERE order_id = ? AND status = 'pending'
        """, (order_id,))
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Order {order_id} завершён (paid)")
        return success


def update_order_tariff(order_id: str, tariff_id: int, payment_type: Optional[str] = None) -> bool:
    """
    Обновляет тариф и суммы в ордере.
    
    Args:
        order_id: ID ордера
        tariff_id: ID нового тарифа
        payment_type: Тип оплаты (опционально)
    
    Returns:
        True если успешно
    """
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        return False
        
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE payments 
            SET tariff_id = ?, 
                amount_cents = ?, 
                amount_stars = ?, 
                period_days = ?,
                payment_type = COALESCE(?, payment_type)
            WHERE order_id = ?
        """, (
            tariff_id, 
            tariff['price_cents'], 
            tariff['price_stars'], 
            tariff['duration_days'], 
            payment_type,
            order_id
        ))
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Order {order_id} обновлен на тариф {tariff_id} (тип: {payment_type})")
        return success


def update_payment_type(order_id: str, payment_type: str) -> bool:
    """
    Обновляет тип оплаты в ордере.
    
    Args:
        order_id: ID ордера
        payment_type: Новый тип оплаты ('crypto', 'stars')
        
    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE payments 
            SET payment_type = ?
            WHERE order_id = ?
        """, (payment_type, order_id))
        success = cursor.rowcount > 0
        if success:
             logger.info(f"Order {order_id} тип оплаты обновлен на {payment_type}")
        return success


def update_payment_key_id(order_id: str, vpn_key_id: int) -> bool:
    """
    Привязывает созданный VPN-ключ к платежу.
    
    Args:
        order_id: ID ордера
        vpn_key_id: ID ключа
    
    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE payments 
            SET vpn_key_id = ?
            WHERE order_id = ?
        """, (vpn_key_id, order_id))
        return cursor.rowcount > 0


def create_vpn_key(
    user_id: int, 
    server_id: int, 
    tariff_id: int,
    panel_inbound_id: int,
    panel_email: str,
    client_uuid: str,
    days: int
) -> int:
    """
    Создаёт полностью настроенный VPN-ключ (обертка над create_vpn_key_admin).
    Для создания черновика используйте create_initial_vpn_key.
    """
    return create_vpn_key_admin(
        user_id, server_id, tariff_id, panel_inbound_id, 
        panel_email, client_uuid, days
    )


def create_initial_vpn_key(
    user_id: int,
    tariff_id: int,
    days: int
) -> int:
    """
    Создаёт начальный (черновой) VPN-ключ без привязки к серверу.
    Ключ создается сразу после оплаты.
    
    Args:
        user_id: ID пользователя
        tariff_id: ID тарифа
        days: Срок действия (дней)
        
    Returns:
        ID созданного ключа
    """
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO vpn_keys 
            (user_id, tariff_id, expires_at, created_at)
            VALUES (?, ?, datetime('now', '+' || ? || ' days'), CURRENT_TIMESTAMP)
        """, (user_id, tariff_id, days))
        return cursor.lastrowid


def update_vpn_key_config(
    key_id: int,
    server_id: int,
    panel_inbound_id: int,
    panel_email: str,
    client_uuid: str
) -> bool:
    """
    Обновляет конфигурацию ключа (привязывает к серверу).
    Используется для завершения настройки ключа.
    
    Args:
        key_id: ID ключа
        server_id: ID сервера
        panel_inbound_id: ID inbound на панели
        panel_email: Email на панели
        client_uuid: UUID клиента
        
    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE vpn_keys 
            SET server_id = ?,
                panel_inbound_id = ?,
                panel_email = ?,
                client_uuid = ?
            WHERE id = ?
        """, (server_id, panel_inbound_id, panel_email, client_uuid, key_id))
        return cursor.rowcount > 0



def is_order_already_paid(order_id: str) -> bool:
    """
    Проверяет, был ли ордер уже оплачен.
    
    Args:
        order_id: ID ордера
    
    Returns:
        True если статус = 'paid'
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT status FROM payments WHERE order_id = ?",
            (order_id,)
        )
        row = cursor.fetchone()
        return row and row['status'] == 'paid'


def get_user_keys_for_display(telegram_id: int) -> List[Dict[str, Any]]:
    """
    Получает ключи пользователя для отображения в разделе «Мои ключи».
    
    Args:
        telegram_id: Telegram ID пользователя
    
    Returns:
        Список ключей с полями: id, display_name, server_name, protocol,
        expires_at, is_active (не истёк), is_enabled, traffic_info
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT 
                vk.id, vk.client_uuid, vk.custom_name, vk.expires_at, 
                s.name as server_name, s.id as server_id, vk.panel_email,
                CASE 
                    WHEN vk.expires_at > datetime('now') THEN 1 
                    ELSE 0 
                END as is_active
            FROM vpn_keys vk
            LEFT JOIN servers s ON vk.server_id = s.id
            JOIN users u ON vk.user_id = u.id
            WHERE u.telegram_id = ?
            ORDER BY vk.expires_at DESC
        """, (telegram_id,))
        
        keys = []
        for row in cursor.fetchall():
            key = dict(row)
            # Формируем display_name
            if key['custom_name']:
                key['display_name'] = key['custom_name']
            elif key['client_uuid']:
                uuid = key['client_uuid']
                key['display_name'] = f"{uuid[:4]}...{uuid[-4:]}"
            else:
                if not key['server_id']:
                     key['display_name'] = f"Ключ #{key['id']} (Не настроен)"
                else:
                     key['display_name'] = f"Ключ #{key['id']}"
            keys.append(key)
        
        return keys


def get_key_details_for_user(key_id: int, telegram_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает детальную информацию о ключе с проверкой принадлежности.
    
    Args:
        key_id: ID ключа
        telegram_id: Telegram ID пользователя
    
    Returns:
        Словарь с данными ключа или None если не найден или не принадлежит
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT 
                vk.*, 
                s.name as server_name, s.id as server_id,
                t.name as tariff_name, t.duration_days, t.price_cents, t.price_stars,
                u.telegram_id, u.username,
                s.is_active as server_active,
                CASE 
                    WHEN vk.expires_at > datetime('now') THEN 1 
                    ELSE 0 
                END as is_active
            FROM vpn_keys vk
            LEFT JOIN servers s ON vk.server_id = s.id
            LEFT JOIN tariffs t ON vk.tariff_id = t.id
            JOIN users u ON vk.user_id = u.id
            WHERE vk.id = ? AND u.telegram_id = ?
        """, (key_id, telegram_id))
        row = cursor.fetchone()
        if not row:
            return None
        
        key = dict(row)
        # Формируем display_name
        if key['custom_name']:
            key['display_name'] = key['custom_name']
        elif key['client_uuid']:
            uuid = key['client_uuid']
            key['display_name'] = f"{uuid[:4]}...{uuid[-4:]}"
        else:
            if not key['server_id']:
                 key['display_name'] = f"Ключ #{key['id']} (Не настроен)"
            else:
                 key['display_name'] = f"Ключ #{key['id']}"
        
        return key


def get_key_payments_history(key_id: int) -> List[Dict[str, Any]]:
    """
    Получает историю платежей по ключу.
    
    Args:
        key_id: ID ключа
    
    Returns:
        Список платежей с названиями тарифов
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT p.*, t.name as tariff_name
            FROM payments p
            LEFT JOIN tariffs t ON p.tariff_id = t.id
            WHERE p.vpn_key_id = ? AND p.status = 'paid'
            ORDER BY p.paid_at DESC
        """, (key_id,))
        return [dict(row) for row in cursor.fetchall()]


def update_key_custom_name(key_id: int, telegram_id: int, new_name: str) -> bool:
    """
    Обновляет пользовательское имя ключа.
    
    Args:
        key_id: ID ключа
        telegram_id: Telegram ID владельца
        new_name: Новое имя (или пустая строка для сброса)
    
    Returns:
        True если успешно
    """
    if new_name and len(new_name) > 30:
        logger.warning(f"Попытка установить слишком длинное имя ключа {key_id}: {new_name}")
        return False

    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        return False
    
    with get_db() as conn:
        conn.execute("""
            UPDATE vpn_keys SET custom_name = ? WHERE id = ?
        """, (new_name or None, key_id))
        logger.info(f"Ключ {key_id}: переименован в '{new_name}'")
        return True


def get_user_internal_id(telegram_id: int) -> Optional[int]:
    """
    Получает внутренний ID пользователя по Telegram ID.
    
    Args:
        telegram_id: Telegram ID
    
    Returns:
        Внутренний ID (users.id) или None
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()
        return row['id'] if row else None
