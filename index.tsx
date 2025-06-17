/* tslint:disable */
/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import {GoogleGenAI, LiveServerMessage, Modality, Session} from '@google/genai';
import {LitElement, css, html} from 'lit';
import {customElement, state} from 'lit/decorators.js';
import {createBlob, decode, decodeAudioData} from './utils';

// Telegram WebApp API types
declare global {
  interface Window {
    Telegram: {
      WebApp: {
        ready(): void;
        close(): void;
        expand(): void;
        MainButton: {
          text: string;
          show(): void;
          hide(): void;
          onClick(callback: () => void): void;
        };
        HapticFeedback: {
          impactOccurred(style: 'light' | 'medium' | 'heavy'): void;
          notificationOccurred(type: 'error' | 'success' | 'warning'): void;
        };
        themeParams: {
          bg_color?: string;
          text_color?: string;
          hint_color?: string;
          button_color?: string;
          button_text_color?: string;
        };
        initData: string;
        initDataUnsafe: any;
      };
    };
  }
}

@customElement('tma-live-audio')
export class TmaLiveAudio extends LitElement {
  @state() isRecording = false;
  @state() status = 'Готов к разговору';
  @state() error = '';
  @state() isConnected = false;

  private client: GoogleGenAI;
  private session: Session;
  private inputAudioContext = new (window.AudioContext ||
    window.webkitAudioContext)({sampleRate: 16000});
  private outputAudioContext = new (window.AudioContext ||
    window.webkitAudioContext)({sampleRate: 24000});
  private inputNode = this.inputAudioContext.createGain();
  private outputNode = this.outputAudioContext.createGain();
  private nextStartTime = 0;
  private mediaStream: MediaStream;
  private sourceNode: AudioBufferSourceNode;
  private scriptProcessorNode: ScriptProcessorNode;
  private sources = new Set<AudioBufferSourceNode>();

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      height: 100vh;
      width: 100vw;
      background: var(--tg-theme-bg-color, #ffffff);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }

    .container {
      display: flex;
      flex-direction: column;
      height: 100%;
      padding: var(--spacing, 16px);
      gap: var(--spacing, 16px);
    }

    .header {
      text-align: center;
      padding: 20px 0;
    }

    .title {
      font-size: 24px;
      font-weight: 600;
      color: var(--tg-theme-text-color, #000000);
      margin-bottom: 8px;
    }

    .subtitle {
      font-size: 16px;
      color: var(--tg-theme-hint-color, #999999);
    }

    .main-content {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 32px;
    }

    .voice-visualizer {
      width: 200px;
      height: 200px;
      border-radius: 50%;
      background: var(--tg-theme-secondary-bg-color, #f1f1f1);
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
      transition: all 0.3s ease;
    }

    .voice-visualizer.recording {
      background: linear-gradient(45deg, var(--tg-primary, #007aff), #00d4ff);
      animation: pulse 2s infinite;
    }

    .voice-icon {
      width: 80px;
      height: 80px;
      fill: var(--tg-theme-hint-color, #999999);
      transition: all 0.3s ease;
    }

    .voice-visualizer.recording .voice-icon {
      fill: white;
    }

    @keyframes pulse {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.05); }
    }

    .controls {
      display: flex;
      justify-content: center;
      gap: 16px;
      padding: 20px 0;
    }

    .control-button {
      width: 64px;
      height: 64px;
      border-radius: 50%;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.2s ease;
      outline: none;
      position: relative;
    }

    .control-button:active {
      transform: scale(0.95);
    }

    .record-button {
      background: var(--tg-destructive, #ff3b30);
      box-shadow: 0 4px 16px rgba(255, 59, 48, 0.3);
    }

    .record-button.recording {
      background: #333333;
    }

    .stop-button {
      background: var(--tg-theme-secondary-bg-color, #f1f1f1);
    }

    .reset-button {
      background: var(--tg-primary, #007aff);
      box-shadow: 0 4px 16px rgba(0, 122, 255, 0.3);
    }

    .button-icon {
      width: 32px;
      height: 32px;
      fill: white;
    }

    .stop-button .button-icon {
      fill: var(--tg-theme-text-color, #000000);
    }

    .status {
      text-align: center;
      padding: 16px;
      background: var(--tg-theme-secondary-bg-color, #f1f1f1);
      border-radius: var(--border-radius, 12px);
      margin-top: auto;
    }

    .status-text {
      font-size: 14px;
      color: var(--tg-theme-text-color, #000000);
      margin-bottom: 4px;
    }

    .error-text {
      font-size: 12px;
      color: var(--tg-destructive, #ff3b30);
    }

    .connection-indicator {
      position: absolute;
      top: 16px;
      right: 16px;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: var(--tg-destructive, #ff3b30);
      transition: all 0.3s ease;
    }

    .connection-indicator.connected {
      background: #34c759;
    }

    @media (max-width: 480px) {
      .voice-visualizer {
        width: 160px;
        height: 160px;
      }

      .voice-icon {
        width: 60px;
        height: 60px;
      }

      .control-button {
        width: 56px;
        height: 56px;
      }

      .button-icon {
        width: 28px;
        height: 28px;
      }
    }
  `;

  constructor() {
    super();
    this.initTelegram();
    this.initClient();
  }

  private initTelegram() {
    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();
    }
  }

  private initAudio() {
    this.nextStartTime = this.outputAudioContext.currentTime;
  }

  private async initClient() {
    this.initAudio();

    this.client = new GoogleGenAI({
      apiKey: process.env.GEMINI_API_KEY,
    });

    this.outputNode.connect(this.outputAudioContext.destination);

    // Don't connect automatically - wait for user action
    this.updateStatus('Нажмите кнопку для начала разговора');
  }

  private async initSession() {
    const model = 'gemini-2.5-flash-preview-native-audio-dialog';

    try {
      this.session = await this.client.live.connect({
        model: model,
        callbacks: {
          onopen: () => {
            this.updateStatus('Соединение установлено');
            this.isConnected = true;
            this.hapticFeedback('success');
          },
          onmessage: async (message: LiveServerMessage) => {
            const audio =
              message.serverContent?.modelTurn?.parts[0]?.inlineData;

            if (audio) {
              this.nextStartTime = Math.max(
                this.nextStartTime,
                this.outputAudioContext.currentTime,
              );

              const audioBuffer = await decodeAudioData(
                decode(audio.data),
                this.outputAudioContext,
                24000,
                1,
              );
              const source = this.outputAudioContext.createBufferSource();
              source.buffer = audioBuffer;
              source.connect(this.outputNode);
              source.addEventListener('ended', () => {
                this.sources.delete(source);
              });

              source.start(this.nextStartTime);
              this.nextStartTime = this.nextStartTime + audioBuffer.duration;
              this.sources.add(source);
            }

            const interrupted = message.serverContent?.interrupted;
            if (interrupted) {
              for (const source of this.sources.values()) {
                source.stop();
                this.sources.delete(source);
              }
              this.nextStartTime = 0;
            }
          },
          onerror: (e: ErrorEvent) => {
            this.updateError(e.message);
            this.isConnected = false;
            this.hapticFeedback('error');
          },
          onclose: (e: CloseEvent) => {
            this.updateStatus('Close: ' + e.code + ' ' + e.reason);
            this.isConnected = false;
          },
        },
        config: {
          responseModalities: [Modality.AUDIO],
          speechConfig: {
            voiceConfig: {prebuiltVoiceConfig: {voiceName: 'Orus'}},
            // languageCode: 'en-GB'
          },
        },
      });
    } catch (e) {
      console.error(e);
      this.updateError('Ошибка подключения к AI: ' + e.message);
      this.isConnected = false;
    }
  }

  private hapticFeedback(type: 'light' | 'medium' | 'heavy' | 'success' | 'error' | 'warning') {
    if (window.Telegram?.WebApp?.HapticFeedback) {
      if (type === 'success' || type === 'error' || type === 'warning') {
        window.Telegram.WebApp.HapticFeedback.notificationOccurred(type);
      } else {
        window.Telegram.WebApp.HapticFeedback.impactOccurred(type);
      }
    }
  }

  private updateStatus(msg: string) {
    this.status = msg;
  }

  private updateError(msg: string) {
    this.error = msg;
  }

  private async startRecording() {
    if (this.isRecording) return;

    // Clear previous errors
    this.error = '';

    // If not connected to AI, connect first
    if (!this.isConnected || !this.session) {
      this.updateStatus('Подключение к AI...');
      await this.initSession();

      // Wait for connection to establish
      let attempts = 0;
      while (!this.isConnected && attempts < 50) { // 5 seconds max
        await new Promise(resolve => setTimeout(resolve, 100));
        attempts++;
      }

      if (!this.isConnected) {
        this.updateError('Не удалось подключиться к AI. Попробуйте еще раз.');
        return;
      }
    }

    // Resume audio context on user interaction
    if (this.inputAudioContext.state === 'suspended') {
      await this.inputAudioContext.resume();
    }
    if (this.outputAudioContext.state === 'suspended') {
      await this.outputAudioContext.resume();
    }

    this.hapticFeedback('medium');
    this.updateStatus('Запрашиваем доступ к микрофону...');

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: 16000
        },
        video: false,
      });

      this.updateStatus('🔴 Записываю... Говорите!');

      this.sourceNode = this.inputAudioContext.createMediaStreamSource(
        this.mediaStream,
      );
      this.sourceNode.connect(this.inputNode);

      const bufferSize = 256;
      this.scriptProcessorNode = this.inputAudioContext.createScriptProcessor(
        bufferSize,
        1,
        1,
      );

      this.scriptProcessorNode.onaudioprocess = (audioProcessingEvent) => {
        if (!this.isRecording || !this.session || !this.isConnected) return;

        const inputBuffer = audioProcessingEvent.inputBuffer;
        const pcmData = inputBuffer.getChannelData(0);

        try {
          this.session.sendRealtimeInput({media: createBlob(pcmData)});
        } catch (e) {
          console.error('Failed to send audio data:', e);
          this.stopRecording();
          this.updateError('Потеряно соединение с AI');
        }
      };

      this.sourceNode.connect(this.scriptProcessorNode);
      this.scriptProcessorNode.connect(this.inputAudioContext.destination);

      this.isRecording = true;
    } catch (err) {
      console.error('Error starting recording:', err);

      // Better error messages for different scenarios
      if (err.name === 'NotAllowedError') {
        this.updateError('Доступ к микрофону запрещен. Разрешите доступ для работы голосового чата.');
      } else if (err.name === 'NotFoundError') {
        this.updateError('Микрофон не найден. Проверьте подключение устройства.');
      } else if (err.name === 'NotSupportedError') {
        this.updateError('Ваш браузер не поддерживает запись аудио.');
      } else {
        this.updateError(`Ошибка: ${err.message}`);
      }

      this.hapticFeedback('error');
      this.stopRecording();
    }
  }

  private stopRecording() {
    if (!this.isRecording && !this.mediaStream && !this.inputAudioContext)
      return;

    this.hapticFeedback('light');
    this.updateStatus('Остановка записи...');

    this.isRecording = false;

    if (this.scriptProcessorNode && this.sourceNode && this.inputAudioContext) {
      this.scriptProcessorNode.disconnect();
      this.sourceNode.disconnect();
    }

    this.scriptProcessorNode = null;
    this.sourceNode = null;

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
    }

    this.updateStatus('Готов к разговору');
  }

  private async reset() {
    this.hapticFeedback('medium');
    this.session?.close();
    this.initSession();
    this.updateStatus('Сессия сброшена');
  }

  render() {
    return html`
      <div class="container">
        <div class="connection-indicator ${this.isConnected ? 'connected' : ''}"></div>

        <div class="header">
          <div class="title">Live Audio Chat</div>
          <div class="subtitle">Голосовой чат с AI</div>
        </div>

        <div class="main-content">
          <div class="voice-visualizer ${this.isRecording ? 'recording' : ''}">
            <svg class="voice-icon" viewBox="0 0 24 24">
              <path d="M12 2c1.1 0 2 .9 2 2v6c0 1.1-.9 2-2 2s-2-.9-2-2V4c0-1.1.9-2 2-2zm5.3 6c0 3-2.54 5.1-5.3 5.1S6.7 11 6.7 8H5c0 3.41 2.72 6.23 6 6.72V17h-2v2h6v-2h-2v-2.28c3.28-.49 6-3.31 6-6.72h-1.7z"/>
            </svg>
          </div>

          <div class="controls">
            <button
              class="control-button reset-button"
              @click=${this.reset}
              ?disabled=${this.isRecording}
              title="Переподключиться">
              <svg class="button-icon" viewBox="0 0 24 24">
                <path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
              </svg>
            </button>

            <button
              class="control-button record-button ${this.isRecording ? 'recording' : ''}"
              @click=${this.isRecording ? this.stopRecording : this.startRecording}
              title="${this.isRecording ? 'Остановить запись' : (this.isConnected ? 'Начать запись' : 'Подключиться и записать')}">
              <svg class="button-icon" viewBox="0 0 24 24">
                ${this.isRecording
                  ? html`<rect x="6" y="6" width="12" height="12" rx="2"/>`
                  : html`<circle cx="12" cy="12" r="10"/>`
                }
              </svg>
            </button>
          </div>
        </div>

        <div class="status">
          <div class="status-text">${this.status}</div>
          ${this.error ? html`<div class="error-text">${this.error}</div>` : ''}
        </div>
      </div>
    `;
  }
}
