import asyncio
import json
import base64
import logging
from typing import Dict, Set
import websockets
from websockets.server import WebSocketServerProtocol
from gemini_live_client import GeminiLiveClient

logger = logging.getLogger(__name__)

class VoiceAIWebSocketServer:
    """WebSocket сервер для обработки подключений от Android приложения"""

    def __init__(self, gemini_api_key: str):
        self.gemini_api_key = gemini_api_key
        self.clients: Dict[WebSocketServerProtocol, GeminiLiveClient] = {}
        self.active_connections: Set[WebSocketServerProtocol] = set()

    async def register_client(self, websocket: WebSocketServerProtocol):
        """Регистрация нового клиента"""
        self.active_connections.add(websocket)
        logger.info(f"Новый клиент подключился: {websocket.remote_address}")

        # Создаем отдельный Gemini клиент для каждого подключения
        gemini_client = GeminiLiveClient(self.gemini_api_key)
        self.clients[websocket] = gemini_client

        # Подключаемся к Gemini Live API
        success = await gemini_client.connect(
            message_callback=lambda msg: self.send_to_client(websocket, msg)
        )

        if success:
            await self.send_to_client(websocket, {
                "type": "connection_established",
                "message": "Успешно подключились к Gemini Live API"
            })
        else:
            await self.send_to_client(websocket, {
                "type": "error",
                "message": "Ошибка подключения к Gemini Live API"
            })

    async def unregister_client(self, websocket: WebSocketServerProtocol):
        """Отключение клиента"""
        self.active_connections.discard(websocket)

        if websocket in self.clients:
            gemini_client = self.clients[websocket]
            await gemini_client.disconnect()
            del self.clients[websocket]

        logger.info(f"Клиент отключился: {websocket.remote_address}")

    async def send_to_client(self, websocket: WebSocketServerProtocol, message: dict):
        """Отправка сообщения конкретному клиенту"""
        try:
            if websocket in self.active_connections:
                await websocket.send(json.dumps(message))
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Попытка отправки в закрытое соединение")
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения клиенту: {e}")

    async def handle_client_message(self, websocket: WebSocketServerProtocol, message: str):
        """Обработка сообщений от клиента"""
        try:
            data = json.loads(message)
            message_type = data.get("type")

            if websocket not in self.clients:
                await self.send_to_client(websocket, {
                    "type": "error",
                    "message": "Сессия не установлена"
                })
                return

            gemini_client = self.clients[websocket]

            if message_type == "audio_data":
                # Обработка аудио данных от клиента
                audio_data_b64 = data.get("data")
                mime_type = data.get("mime_type", "audio/pcm;rate=16000")

                if audio_data_b64:
                    try:
                        audio_data = base64.b64decode(audio_data_b64)
                        success = await gemini_client.send_audio(audio_data, mime_type)

                        if not success:
                            await self.send_to_client(websocket, {
                                "type": "error",
                                "message": "Ошибка отправки аудио в Gemini"
                            })
                    except Exception as e:
                        logger.error(f"Ошибка декодирования аудио: {e}")
                        await self.send_to_client(websocket, {
                            "type": "error",
                            "message": "Ошибка декодирования аудио данных"
                        })

            elif message_type == "text_message":
                # Обработка текстовых сообщений
                text = data.get("text")
                if text:
                    success = await gemini_client.send_text(text)
                    if not success:
                        await self.send_to_client(websocket, {
                            "type": "error",
                            "message": "Ошибка отправки текста в Gemini"
                        })

            elif message_type == "user_speaking_started":
                # Уведомление о начале речи пользователя
                await self.send_to_client(websocket, {
                    "type": "user_speaking_acknowledged"
                })

            elif message_type == "user_speaking_stopped":
                # Уведомление об окончании речи пользователя
                await self.send_to_client(websocket, {
                    "type": "user_speaking_ended_acknowledged"
                })

            elif message_type == "ping":
                # Простой ping для проверки соединения
                await self.send_to_client(websocket, {
                    "type": "pong"
                })

            else:
                logger.warning(f"Неизвестный тип сообщения: {message_type}")
                await self.send_to_client(websocket, {
                    "type": "error",
                    "message": f"Неизвестный тип сообщения: {message_type}"
                })

        except json.JSONDecodeError:
            logger.error("Ошибка парсинга JSON сообщения")
            await self.send_to_client(websocket, {
                "type": "error",
                "message": "Неверный формат JSON"
            })
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения от клиента: {e}")
            await self.send_to_client(websocket, {
                "type": "error",
                "message": f"Ошибка обработки сообщения: {str(e)}"
            })

    async def handle_client(self, websocket: WebSocketServerProtocol, path: str):
        """Основной обработчик клиентских подключений"""
        await self.register_client(websocket)

        try:
            async for message in websocket:
                await self.handle_client_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Клиент закрыл соединение")
        except Exception as e:
            logger.error(f"Ошибка в обработчике клиента: {e}")
        finally:
            await self.unregister_client(websocket)

    async def start_server(self, host: str = "0.0.0.0", port: int = 8001):
        """Запуск WebSocket сервера"""
        logger.info(f"Запуск WebSocket сервера на {host}:{port}")

        return await websockets.serve(
            self.handle_client,
            host,
            port,
            ping_interval=20,
            ping_timeout=10,
            max_size=10 * 1024 * 1024,  # 10MB для аудио данных
        )

# Глобальный экземпляр сервера
_server_instance = None

def get_server_instance(gemini_api_key: str) -> VoiceAIWebSocketServer:
    """Получить глобальный экземпляр сервера"""
    global _server_instance
    if _server_instance is None:
        _server_instance = VoiceAIWebSocketServer(gemini_api_key)
    return _server_instance
