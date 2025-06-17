import asyncio
import logging
import os
import json
import base64
from typing import Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
from dotenv import load_dotenv

from gemini_live_client import GeminiLiveClient

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# Глобальные переменные для управления соединениями
active_connections: Dict[WebSocket, GeminiLiveClient] = {}

class ConnectionManager:
    """Менеджер WebSocket соединений"""

    def __init__(self):
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY обязателен для работы")

    async def connect(self, websocket: WebSocket):
        """Принятие нового WebSocket соединения"""
        await websocket.accept()

        # Создаем отдельный Gemini клиент для каждого подключения
        gemini_client = GeminiLiveClient(self.gemini_api_key)
        active_connections[websocket] = gemini_client

        logger.info(f"Новый клиент подключился: {websocket.client}")

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

    async def disconnect(self, websocket: WebSocket):
        """Отключение WebSocket соединения"""
        if websocket in active_connections:
            gemini_client = active_connections[websocket]
            await gemini_client.disconnect()
            del active_connections[websocket]

        logger.info(f"Клиент отключился: {websocket.client}")

    async def send_to_client(self, websocket: WebSocket, message: dict):
        """Отправка сообщения конкретному клиенту"""
        try:
            if websocket in active_connections:
                await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения клиенту: {e}")

    async def handle_message(self, websocket: WebSocket, message: str):
        """Обработка сообщений от клиента"""
        try:
            data = json.loads(message)
            message_type = data.get("type")

            if websocket not in active_connections:
                await self.send_to_client(websocket, {
                    "type": "error",
                    "message": "Сессия не установлена"
                })
                return

            gemini_client = active_connections[websocket]

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
                await self.send_to_client(websocket, {
                    "type": "user_speaking_acknowledged"
                })

            elif message_type == "user_speaking_stopped":
                await self.send_to_client(websocket, {
                    "type": "user_speaking_ended_acknowledged"
                })

            elif message_type == "ping":
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

# Создаем менеджер соединений
manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    # Startup
    logger.info("Запуск Voice AI Server (Integrated)...")

    yield

    # Shutdown
    logger.info("Остановка Voice AI Server...")

    # Закрываем все активные соединения
    for websocket, gemini_client in active_connections.items():
        try:
            await gemini_client.disconnect()
        except Exception as e:
            logger.error(f"Ошибка закрытия соединения: {e}")

# Создаем FastAPI приложение
app = FastAPI(
    title="Voice AI Server (Integrated)",
    description="Сервер для обработки голосовых сообщений через Gemini Live API с интегрированным WebSocket",
    version="1.0.0",
    lifespan=lifespan
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В production следует ограничить
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Главная страница API"""
    return {
        "message": "Voice AI Server (Integrated) запущен",
        "version": "1.0.0",
        "status": "running",
        "websocket_endpoint": "/ws"
    }

@app.get("/health")
async def health_check():
    """Проверка здоровья сервера"""
    status = {
        "status": "healthy",
        "active_connections": len(active_connections),
        "websocket_integrated": True
    }
    return status

@app.get("/stats")
async def get_stats():
    """Получение статистики сервера"""
    stats = {
        "active_connections": len(active_connections),
        "server_status": "running",
        "websocket_integrated": True
    }
    return stats

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint для голосового общения"""
    await manager.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            await manager.handle_message(websocket, message)
    except WebSocketDisconnect:
        logger.info("WebSocket соединение закрыто клиентом")
    except Exception as e:
        logger.error(f"Ошибка в WebSocket соединении: {e}")
    finally:
        await manager.disconnect(websocket)

@app.post("/broadcast")
async def broadcast_message(message: Dict[str, Any]):
    """Отправка сообщения всем подключенным клиентам"""
    sent_count = 0
    for websocket in active_connections.keys():
        try:
            await manager.send_to_client(websocket, message)
            sent_count += 1
        except Exception as e:
            logger.error(f"Ошибка отправки broadcast сообщения: {e}")

    return {
        "message": "Сообщение отправлено",
        "sent_to": sent_count,
        "total_connections": len(active_connections)
    }

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Глобальный обработчик исключений"""
    logger.error(f"Необработанная ошибка: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Внутренняя ошибка сервера"}
    )

def main():
    """Главная функция для запуска сервера"""
    # Render передает PORT через переменную окружения
    port = int(os.getenv("PORT", "10000"))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Запуск интегрированного сервера на http://{host}:{port}")
    logger.info(f"WebSocket доступен на ws://{host}:{port}/ws")

    uvicorn.run(
        "main_integrated:app",
        host=host,
        port=port,
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )

if __name__ == "__main__":
    main()
