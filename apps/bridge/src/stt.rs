//! Sesión de transcripción por WebSocket.
//!
//! Recibe frames PCM16 (16 kHz mono), corta el stream en utterances por
//! detección de silencio (VAD por energía con histéresis) y manda cada
//! utterance al motor local. Devuelve JSON:
//!   {type:"partial"|"final", text, start_ms, end_ms, confidence?, speaker?}
//!
//! El buffer vive SOLO en RAM y se vacía apenas se transcribe.

use std::sync::Arc;

use axum::extract::ws::{Message, WebSocket};
use serde_json::json;

use crate::AppState;

const SAMPLE_RATE: u32 = 16_000;
/// silencio que cierra una utterance (ms)
const SILENCE_CLOSE_MS: u64 = 700;
/// máximo de audio por utterance antes de forzar procesamiento (ms)
const MAX_UTTERANCE_MS: u64 = 10_000;
/// mínimo para molestarse en transcribir (ms)
const MIN_UTTERANCE_MS: u64 = 400;
/// umbral RMS de voz (sobre i16 normalizado)
const VOICE_RMS: f32 = 0.010;

pub async fn handle_session(mut socket: WebSocket, state: Arc<AppState>, language: String) {
    let _ = socket
        .send(Message::Text(
            json!({"type": "ready", "message": "Echo Bridge listo"}).to_string(),
        ))
        .await;

    let mut buffer: Vec<i16> = Vec::with_capacity(SAMPLE_RATE as usize * 12);
    let mut stream_ms: u64 = 0; // posición absoluta del stream
    let mut utterance_start_ms: u64 = 0;
    let mut silence_ms: u64 = 0;
    let mut in_voice = false;

    while let Some(Ok(message)) = socket.recv().await {
        match message {
            Message::Binary(bytes) => {
                let samples: Vec<i16> = bytes
                    .chunks_exact(2)
                    .map(|pair| i16::from_le_bytes([pair[0], pair[1]]))
                    .collect();
                let frame_ms = (samples.len() as u64 * 1000) / SAMPLE_RATE as u64;

                // energía del frame
                let rms = {
                    let sum: f64 = samples
                        .iter()
                        .map(|sample| {
                            let value = *sample as f64 / 32768.0;
                            value * value
                        })
                        .sum();
                    ((sum / samples.len().max(1) as f64).sqrt()) as f32
                };

                let is_voice = rms >= VOICE_RMS;
                if is_voice {
                    if !in_voice && buffer.is_empty() {
                        utterance_start_ms = stream_ms;
                    }
                    in_voice = true;
                    silence_ms = 0;
                } else if in_voice {
                    silence_ms += frame_ms;
                }

                // acumular solo si hay una utterance abierta (con algo de cola de silencio)
                if in_voice {
                    buffer.extend_from_slice(&samples);
                }
                stream_ms += frame_ms;

                let utterance_ms = (buffer.len() as u64 * 1000) / SAMPLE_RATE as u64;
                let should_close = in_voice
                    && ((silence_ms >= SILENCE_CLOSE_MS && utterance_ms >= MIN_UTTERANCE_MS)
                        || utterance_ms >= MAX_UTTERANCE_MS);

                if should_close {
                    let is_final = silence_ms >= SILENCE_CLOSE_MS;
                    flush_buffer(
                        &mut socket,
                        &state,
                        &mut buffer,
                        utterance_start_ms,
                        &language,
                        is_final,
                    )
                    .await;
                    if is_final {
                        in_voice = false;
                        silence_ms = 0;
                    } else {
                        // ventana forzada: seguimos en la misma locución
                        utterance_start_ms = stream_ms;
                    }
                }
            }
            Message::Text(text) => {
                if let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) {
                    match value.get("type").and_then(|t| t.as_str()) {
                        Some("flush") => {
                            flush_buffer(
                                &mut socket,
                                &state,
                                &mut buffer,
                                utterance_start_ms,
                                &language,
                                true,
                            )
                            .await;
                            in_voice = false;
                            silence_ms = 0;
                        }
                        Some("ping") => {
                            let _ = socket
                                .send(Message::Text(json!({"type": "pong"}).to_string()))
                                .await;
                        }
                        _ => {}
                    }
                }
            }
            Message::Close(_) => break,
            _ => {}
        }
    }

    // descartar lo que quede: el audio nunca se persiste
    buffer.clear();
}

async fn flush_buffer(
    socket: &mut WebSocket,
    state: &Arc<AppState>,
    buffer: &mut Vec<i16>,
    utterance_start_ms: u64,
    language: &str,
    is_final: bool,
) {
    if buffer.len() < (SAMPLE_RATE as usize * MIN_UTTERANCE_MS as usize) / 1000 {
        buffer.clear();
        return;
    }
    // mover el audio fuera del buffer (queda vacío de inmediato)
    let audio: Vec<i16> = std::mem::take(buffer);

    match state
        .engine
        .transcribe(&audio, SAMPLE_RATE, language, utterance_start_ms)
        .await
    {
        Ok(segments) => {
            for segment in segments {
                let event = json!({
                    "type": if is_final { "final" } else { "partial" },
                    "text": segment.text,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "confidence": segment.confidence,
                    "speaker": segment.speaker,
                });
                if socket.send(Message::Text(event.to_string())).await.is_err() {
                    return;
                }
            }
        }
        Err(error) => {
            tracing::warn!("motor STT falló: {error}");
            let _ = socket
                .send(Message::Text(
                    json!({"type": "error", "message": error}).to_string(),
                ))
                .await;
        }
    }
    // `audio` se libera acá: nada persiste
}
