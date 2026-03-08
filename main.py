"""
Точка входа VPN Telegram бота.

Инициализирует бота, диспетчер, применяет миграции и запускает polling.
"""
import asyncio
import logging
import os
import signal
import sys
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage

from config import (
    BOT_TOKEN,
    SUBSCRIPTION_AGGREGATOR_HOST,
    SUBSCRIPTION_AGGREGATOR_PORT,
)
from database.migrations import run_migrations

from bot.services.vpn_api import close_all_clients
from bot.services.scheduler import run_daily_tasks, run_update_check_scheduler
from bot.services.sub_aggregator import create_sub_aggregator_app

# Импорт роутеров
from bot.handlers.user.main import router as user_router
from bot.handlers.user.payments import router as payments_router
# Импортируем общий роутер админки, который уже включает в себя все подроутеры
from bot.handlers.admin import admin_router


# Создаём папку для логов если её нет (важно сделать до basicConfig)
os.makedirs("logs", exist_ok=True)


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bot.log", encoding="utf-8")
    ]
)

# Уменьшаем шум от aiohttp
logging.getLogger("aiohttp").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)





async def on_startup(bot: Bot):
    """Действия при запуске бота."""
    logger.info("🚀 Бот запускается...")
    
    # Применяем миграции БД
    run_migrations()
    
    # Информация о боте
    bot_info = await bot.get_me()
    bot.my_username = bot_info.username

    await bot.set_my_commands([
        BotCommand(command="connect", description="Подключиться"),
        BotCommand(command="cabinet", description="Личный кабинет"),
        BotCommand(command="faq", description="FAQ"),
        BotCommand(command="referrals", description="Реферальная система"),
        BotCommand(command="support", description="Поддержка"),
        BotCommand(command="start", description="Главное меню"),
    ])
    logger.info(f"✅ Бот запущен: @{bot_info.username}")


async def on_shutdown(bot: Bot):
    """Действия при остановке бота."""
    logger.info("🛑 Бот останавливается...")
    
    # Закрываем все VPN API сессии
    await close_all_clients()
    
    logger.info("✅ Бот остановлен")


async def start_sub_aggregator_server() -> web.AppRunner:
    """Запускает HTTP endpoint агрегатора подписок /sub/{token}."""
    app = create_sub_aggregator_app()
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, host=SUBSCRIPTION_AGGREGATOR_HOST, port=SUBSCRIPTION_AGGREGATOR_PORT)
        await site.start()
        logger.info(
            "✅ Subscription aggregator started on %s:%s",
            SUBSCRIPTION_AGGREGATOR_HOST,
            SUBSCRIPTION_AGGREGATOR_PORT
        )
    except OSError as e:
        if SUBSCRIPTION_AGGREGATOR_PORT != 8088:
            logger.warning(
                "Порт %s занят для агрегатора (%s). Пробуем fallback порт 8088.",
                SUBSCRIPTION_AGGREGATOR_PORT,
                e
            )
            site = web.TCPSite(runner, host=SUBSCRIPTION_AGGREGATOR_HOST, port=8088)
            await site.start()
            logger.info(
                "✅ Subscription aggregator started on %s:%s (fallback)",
                SUBSCRIPTION_AGGREGATOR_HOST,
                8088
            )
        else:
            raise
    return runner


async def main():
    """Главная функция запуска бота."""
    # Импортируем кастомную сессию с fallback для ошибок Markdown
    from bot.middlewares.parse_mode_fallback import SafeParseSession
    
    # Создаём бота с кастомной сессией и диспетчер
    session = SafeParseSession()
    bot = Bot(token=BOT_TOKEN, session=session)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Регистрируем роутеры
    # Порядок важен: сначала более специфичные, потом общие
    dp.include_router(admin_router)           # Админ-панель (общая)
    dp.include_router(payments_router)        # Платежи (ДО user, чтобы /start bill1 работал)
    dp.include_router(user_router)            # Пользователь
    
    # Регистрируем startup/shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Запускаем HTTP агрегатор подписок
    sub_aggregator_runner = await start_sub_aggregator_server()

    # Удаляем старые обновления и запускаем polling
    await bot.delete_webhook(drop_pending_updates=True)
    

    
    # Запускаем планировщик ежедневных задач (статистика + бэкапы)
    daily_tasks = asyncio.create_task(run_daily_tasks(bot))
    # Запускаем планировщик проверки обновлений
    update_tasks = asyncio.create_task(run_update_check_scheduler(bot))
    
    try:
        await dp.start_polling(bot)
    finally:
        daily_tasks.cancel()
        update_tasks.cancel()
        await sub_aggregator_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    # Запускаем бота
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Получен сигнал остановки")
