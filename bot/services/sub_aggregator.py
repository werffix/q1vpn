"""
HTTP агрегатор подписок: /sub/{token}

Собирает subscription с нескольких панелей 3x-ui, объединяет конфиги и
возвращает единый base64-ответ для VPN-клиентов.
"""

import base64
import binascii
import logging
from typing import Dict, List, Optional

import aiohttp
from aiohttp import web

from database.requests import get_all_servers
from bot.services.vpn_api import get_client

logger = logging.getLogger(__name__)

SUBSCRIPTION_PUBLIC_PORT = 2096


def _build_panel_sub_url(server: dict, token: str) -> Optional[str]:
    protocol = (server.get("protocol") or "https").strip()
    host = str(server.get("host") or "").strip()
    if not host:
        return None
    return f"{protocol}://{host}:{SUBSCRIPTION_PUBLIC_PORT}/sub/{token}"


def _try_decode_base64(payload: str) -> Optional[str]:
    text = (payload or "").strip()
    if not text:
        return None
    padded = text + ("=" * (-len(text) % 4))
    try:
        decoded = base64.b64decode(padded, validate=False)
        result = decoded.decode("utf-8", errors="ignore")
        return result if result else None
    except (binascii.Error, ValueError):
        return None


def _extract_config_lines(raw_payload: str) -> List[str]:
    """
    Превращает payload панели в список ссылок-конфигов.
    Поддерживает как base64, так и plain-text ответы.
    """
    text = (raw_payload or "").strip()
    if not text:
        return []

    decoded = _try_decode_base64(text)
    source = decoded if decoded and "://" in decoded else text

    lines: List[str] = []
    for line in source.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("vless://", "vmess://", "trojan://", "ss://")):
            lines.append(line)
    return lines


def _parse_userinfo(header_value: str) -> Dict[str, int]:
    """
    Парсит header вида:
    upload=...; download=...; total=...; expire=...
    """
    result = {"upload": 0, "download": 0, "total": 0, "expire": 0}
    if not header_value:
        return result

    for chunk in header_value.split(";"):
        part = chunk.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in result and value.isdigit():
            result[key] = int(value)
    return result


def _format_userinfo(upload: int, download: int, total: int, expire: int) -> str:
    return f"upload={upload}; download={download}; total={total}; expire={expire}"


async def aggregate_subscription(token: str) -> web.Response:
    token = (token or "").strip()
    if not token:
        return web.Response(status=400, text="Token is required", content_type="text/plain")

    servers = get_all_servers()
    if not servers:
        return web.Response(status=503, text="No active panels", content_type="text/plain")

    merged_lines: List[str] = []
    seen = set()
    passthrough_headers: Dict[str, str] = {}
    userinfo_acc = {"upload": 0, "download": 0, "total": 0, "expire": 0}
    userinfo_seen = False

    timeout = aiohttp.ClientTimeout(total=10)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        for server in servers:
            try:
                # Сначала получаем реально рабочий URL подписки для конкретной панели
                # (учитывает base_path/варианты /sub и /subscribe).
                panel_client = await get_client(server["id"])
                url = await panel_client.get_subscription_link(token)
                if not url:
                    # fallback на прямой URL (старый путь)
                    url = _build_panel_sub_url(server, token)
                if not url:
                    continue

                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "Панель вернула не-200 при агрегации: server_id=%s status=%s",
                            server.get("id"),
                            resp.status
                        )
                        continue

                    payload = await resp.text()
                    lines = _extract_config_lines(payload)
                    for line in lines:
                        if line in seen:
                            continue
                        seen.add(line)
                        merged_lines.append(line)

                    # Пробрасываем мета-заголовки, если есть
                    for header_name in ("profile-title", "profile-web-page-url", "support-url", "announcement"):
                        if header_name in resp.headers and header_name not in passthrough_headers:
                            passthrough_headers[header_name] = resp.headers[header_name]

                    raw_userinfo = resp.headers.get("subscription-userinfo", "")
                    if raw_userinfo:
                        parsed = _parse_userinfo(raw_userinfo)
                        userinfo_acc["upload"] += parsed["upload"]
                        userinfo_acc["download"] += parsed["download"]
                        userinfo_acc["total"] += parsed["total"]
                        # Для срока берём минимальный ненулевой expire (самый ранний)
                        cur_expire = parsed["expire"]
                        if cur_expire > 0:
                            if userinfo_acc["expire"] == 0:
                                userinfo_acc["expire"] = cur_expire
                            else:
                                userinfo_acc["expire"] = min(userinfo_acc["expire"], cur_expire)
                        userinfo_seen = True
            except Exception as e:
                logger.error("Ошибка доступа к панели server_id=%s: %s", server.get("id"), e)
                continue

    if not merged_lines:
        return web.Response(status=404, text="No subscription configs found", content_type="text/plain")

    if userinfo_seen:
        passthrough_headers["subscription-userinfo"] = _format_userinfo(
            userinfo_acc["upload"],
            userinfo_acc["download"],
            userinfo_acc["total"],
            userinfo_acc["expire"],
        )

    final_payload = "\n".join(merged_lines)
    encoded_payload = base64.b64encode(final_payload.encode("utf-8")).decode("utf-8")

    return web.Response(
        text=encoded_payload,
        content_type="text/plain",
        headers=passthrough_headers,
    )


async def sub_handler(request: web.Request) -> web.Response:
    token = request.match_info.get("token", "")
    return await aggregate_subscription(token)


def create_sub_aggregator_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/sub/{token}", sub_handler)
    return app
