import asyncio
import logging
import os
from typing import Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
from dotenv import load_dotenv

from websocket_server import get_server_instance

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# Глобальные переменные для серверов
websocket_server_task = None
websocket_server_instance = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    global websocket_server_task, websocket_server_instance

    # Startup
    logger.info("Запуск Voice AI Server...")

    # Проверяем наличие API ключа
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        logger.error("GEMINI_API_KEY не найден в переменных окружения!")
        raise RuntimeError("GEMINI_API_KEY обязателен для работы")

    # Запускаем WebSocket сервер
    try:
        websocket_server_instance = get_server_instance(gemini_api_key)

        ws_host = os.getenv("HOST", "0.0.0.0")
        ws_port = int(os.getenv("WS_PORT", "8001"))

        websocket_server = await websocket_server_instance.start_server(ws_host, ws_port)
        websocket_server_task = asyncio.create_task(websocket_server.wait_closed())

        logger.info(f"WebSocket сервер запущен на ws://{ws_host}:{ws_port}")

    except Exception as e:
        logger.error(f"Ошибка запуска WebSocket сервера: {e}")
        raise

    yield

    # Shutdown
    logger.info("Остановка Voice AI Server...")

    if websocket_server_task:
        websocket_server_task.cancel()
        try:
            await websocket_server_task
        except asyncio.CancelledError:
            pass

# Создаем FastAPI приложение
app = FastAPI(
    title="Voice AI Server",
    description="Сервер для обработки голосовых сообщений через Gemini Live API",
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
        "message": "Voice AI Server запущен",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    """Проверка здоровья сервера"""
    global websocket_server_instance

    status = {
        "status": "healthy",
        "websocket_server": "running" if websocket_server_instance else "stopped",
        "active_connections": 0
    }

    if websocket_server_instance:
        status["active_connections"] = len(websocket_server_instance.active_connections)

    return status

@app.get("/stats")
async def get_stats():
    """Получение статистики сервера"""
    global websocket_server_instance

    if not websocket_server_instance:
        raise HTTPException(status_code=503, detail="WebSocket сервер не запущен")

    stats = {
        "active_connections": len(websocket_server_instance.active_connections),
        "total_clients": len(websocket_server_instance.clients),
        "server_status": "running"
    }

    return stats

@app.post("/broadcast")
async def broadcast_message(message: Dict[str, Any]):
    """Отправка сообщения всем подключенным клиентам"""
    global websocket_server_instance

    if not websocket_server_instance:
        raise HTTPException(status_code=503, detail="WebSocket сервер не запущен")

    sent_count = 0
    for websocket in websocket_server_instance.active_connections:
        try:
            await websocket_server_instance.send_to_client(websocket, message)
            sent_count += 1
        except Exception as e:
            logger.error(f"Ошибка отправки broadcast сообщения: {e}")

    return {
        "message": "Сообщение отправлено",
        "sent_to": sent_count,
        "total_connections": len(websocket_server_instance.active_connections)
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
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    logger.info(f"Запуск FastAPI сервера на http://{host}:{port}")

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,  # В production должно быть False
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )

if __name__ == "__main__":
    main()
