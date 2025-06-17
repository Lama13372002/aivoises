import asyncio
import json
import base64
import logging
from typing import Optional, Callable, Dict, Any
import websockets
import google.generativeai as genai
from google.generativeai import types

logger = logging.getLogger(__name__)

class GeminiLiveClient:
    """Клиент для работы с Gemini Live API через Python SDK"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = genai.Client(api_key=api_key)
        self.session = None
        self.model = "gemini-2.5-flash-preview-native-audio-dialog"
        self.is_connected = False
        self.message_callback: Optional[Callable] = None

    async def connect(self, message_callback: Callable):
        """Подключение к Gemini Live API"""
        try:
            self.message_callback = message_callback

            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Aoede"
                        )
                    )
                ),
                system_instruction=types.Content(
                    parts=[types.Part(
                        text="Ты дружелюбный голосовой помощник. Отвечай кратко и естественно, как в живом разговоре. Говори на русском языке."
                    )]
                ),
                realtime_input_config=types.RealtimeInputConfig(
                    automatic_activity_detection=types.AutomaticActivityDetection(
                        disabled=False,
                        start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                        end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                        prefix_padding_ms=20,
                        silence_duration_ms=100
                    )
                )
            )

            self.session = self.client.aio.live.connect(model=self.model, config=config)
            await self.session.__aenter__()

            self.is_connected = True
            logger.info("Успешно подключились к Gemini Live API")

            # Запускаем задачу для прослушивания сообщений
            asyncio.create_task(self._listen_for_messages())

            return True

        except Exception as e:
            logger.error(f"Ошибка подключения к Gemini Live API: {e}")
            return False

    async def _listen_for_messages(self):
        """Прослушивание сообщений от Gemini Live API"""
        try:
            if not self.session:
                return

            async for response in self.session.receive():
                await self._handle_gemini_response(response)

        except Exception as e:
            logger.error(f"Ошибка при прослушивании сообщений: {e}")
            self.is_connected = False

    async def _handle_gemini_response(self, response):
        """Обработка ответов от Gemini"""
        try:
            # Обработка аудио данных
            if response.data is not None:
                await self._send_to_client({
                    "type": "audio_data",
                    "data": base64.b64encode(response.data).decode('utf-8'),
                    "mime_type": "audio/pcm;rate=24000"
                })

            # Обработка завершения генерации
            if response.server_content and response.server_content.turn_complete:
                await self._send_to_client({
                    "type": "ai_stopped_speaking"
                })

            # Обработка прерываний
            if response.server_content and response.server_content.interrupted:
                await self._send_to_client({
                    "type": "generation_interrupted"
                })

            # Обработка метаданных использования
            if response.usage_metadata:
                await self._send_to_client({
                    "type": "usage_metadata",
                    "total_tokens": response.usage_metadata.total_token_count
                })

        except Exception as e:
            logger.error(f"Ошибка обработки ответа Gemini: {e}")

    async def _send_to_client(self, message: Dict[str, Any]):
        """Отправка сообщения клиенту через callback"""
        if self.message_callback:
            await self.message_callback(message)

    async def send_audio(self, audio_data: bytes, mime_type: str = "audio/pcm;rate=16000"):
        """Отправка аудио данных в Gemini"""
        try:
            if not self.session or not self.is_connected:
                logger.warning("Сессия не активна")
                return False

            blob = types.Blob(data=audio_data, mime_type=mime_type)
            await self.session.send_realtime_input(audio=blob)

            return True

        except Exception as e:
            logger.error(f"Ошибка отправки аудио: {e}")
            return False

    async def send_text(self, text: str):
        """Отправка текстового сообщения в Gemini"""
        try:
            if not self.session or not self.is_connected:
                logger.warning("Сессия не активна")
                return False

            content = types.Content(
                role="user",
                parts=[types.Part(text=text)]
            )

            await self.session.send_client_content(turns=content, turn_complete=True)
            return True

        except Exception as e:
            logger.error(f"Ошибка отправки текста: {e}")
            return False

    async def disconnect(self):
        """Отключение от Gemini Live API"""
        try:
            self.is_connected = False
            if self.session:
                await self.session.__aexit__(None, None, None)
                self.session = None
            logger.info("Отключились от Gemini Live API")

        except Exception as e:
            logger.error(f"Ошибка отключения: {e}")
