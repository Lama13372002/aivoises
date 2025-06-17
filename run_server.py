#!/usr/bin/env python3
"""
Скрипт для запуска Voice AI Server
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

# Добавляем текущую директорию в путь Python
sys.path.insert(0, str(Path(__file__).parent))

from main import main

def setup_environment():
    """Настройка окружения перед запуском"""

    # Проверяем наличие .env файла
    env_file = Path(".env")
    if not env_file.exists():
        env_example = Path(".env.example")
        if env_example.exists():
            print("⚠️  Файл .env не найден!")
            print("📋 Скопируйте .env.example в .env и заполните необходимые поля:")
            print(f"   cp {env_example} {env_file}")
            return False

    # Проверяем API ключ
    from dotenv import load_dotenv
    load_dotenv()

    if not os.getenv("GEMINI_API_KEY"):
        print("❌ GEMINI_API_KEY не найден в .env файле!")
        print("🔑 Добавьте ваш API ключ от Google AI Studio в файл .env:")
        print("   GEMINI_API_KEY=your_actual_api_key_here")
        return False

    return True

def print_startup_info():
    """Выводит информацию о запуске"""
    print("🚀 Запуск Voice AI Server...")
    print("📡 Сервер будет доступен по адресам:")
    print(f"   FastAPI (HTTP): http://localhost:8000")
    print(f"   WebSocket:      ws://localhost:8001")
    print("📊 Проверка здоровья: http://localhost:8000/health")
    print("📈 Статистика:       http://localhost:8000/stats")
    print("📖 API документация: http://localhost:8000/docs")
    print("\n🔧 Для остановки сервера нажмите Ctrl+C\n")

if __name__ == "__main__":
    print("🎙️  Voice AI Server - Сервер для голосового общения с AI")
    print("=" * 60)

    # Настраиваем окружение
    if not setup_environment():
        sys.exit(1)

    # Выводим информацию о запуске
    print_startup_info()

    try:
        # Запускаем сервер
        main()
    except KeyboardInterrupt:
        print("\n🛑 Сервер остановлен пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка запуска сервера: {e}")
        sys.exit(1)
