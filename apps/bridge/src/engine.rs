//! Detección e invocación del motor STT local.
//!
//! Prioridad de detección (sin asumir cómo está instalado nada):
//!   1. `engine_command` de la config (override manual — sirve para Murmur
//!      o cualquier CLI: usar {input}, {lang} como placeholders).
//!   2. `murmur` en PATH (con subcomando de transcripción detectado).
//!   3. whisper.cpp CLI en PATH (`whisper-cli`, `whisper-cpp`, `whisper`,
//!      `main`) + modelo ggml/gguf.
//!   4. Servidor HTTP local compatible con whisper.cpp server (config
//!      `server_url`, o autodetección en http://127.0.0.1:8080).
//!
//! Si nada aparece, el bridge queda en modo "sin motor" y lo reporta en
//! /health para que la web ofrezca el modo cloud.

use std::{path::PathBuf, process::Stdio, time::Duration};

use serde::Deserialize;
use tokio::process::Command;

#[derive(Debug, Clone)]
pub enum EngineKind {
    Cli {
        /// plantilla de argv; {input} => wav, {lang} => idioma, {model} => modelo
        argv: Vec<String>,
        /// el motor emite JSON de whisper.cpp (-oj)
        json_output: bool,
    },
    HttpServer {
        url: String,
    },
    Unavailable(String),
}

#[derive(Clone)]
pub struct Engine {
    pub kind: EngineKind,
    pub name: String,
    pub models: Vec<String>,
}

pub async fn detect(config: &super::Config) -> Engine {
    // 1. Override manual
    if let Some(command) = &config.engine_command {
        let argv: Vec<String> = shell_words(command);
        if !argv.is_empty() {
            return Engine {
                name: argv[0].clone(),
                kind: EngineKind::Cli {
                    argv,
                    json_output: command.contains("-oj") || command.contains("--output-json"),
                },
                models: vec![],
            };
        }
    }

    // 2. Murmur en PATH
    if let Ok(path) = which::which("murmur") {
        if let Some(engine) = probe_murmur(&path).await {
            return engine;
        }
    }

    // 3. whisper.cpp CLI + modelo
    let model = find_model(config);
    for binary in ["whisper-cli", "whisper-cpp", "whisper", "main"] {
        if let Ok(path) = which::which(binary) {
            if binary == "main" && !path.to_string_lossy().to_lowercase().contains("whisper") {
                continue; // "main" genérico que no es whisper.cpp
            }
            if let Some(model_path) = &model {
                return Engine {
                    name: format!("{binary} ({})", short_name(model_path)),
                    kind: EngineKind::Cli {
                        argv: vec![
                            path.to_string_lossy().to_string(),
                            "-m".into(),
                            model_path.to_string_lossy().to_string(),
                            "-l".into(),
                            "{lang}".into(),
                            "-oj".into(),
                            "-of".into(),
                            "{output}".into(),
                            "-np".into(),
                            "{input}".into(),
                        ],
                        json_output: true,
                    },
                    models: vec![short_name(model_path)],
                };
            }
            return Engine {
                name: binary.to_string(),
                kind: EngineKind::Unavailable(format!(
                    "Se encontró {binary} pero ningún modelo ggml/gguf. Configurá model_path en {}",
                    super::config_path().display()
                )),
                models: vec![],
            };
        }
    }

    // 4. Servidor HTTP local
    let candidates: Vec<String> = config
        .server_url
        .clone()
        .map(|url| vec![url])
        .unwrap_or_else(|| vec!["http://127.0.0.1:8080".into()]);
    for url in candidates {
        if probe_http_server(&url).await {
            return Engine {
                name: format!("servidor local {url}"),
                kind: EngineKind::HttpServer { url },
                models: vec![],
            };
        }
    }

    Engine {
        name: "ninguno".into(),
        kind: EngineKind::Unavailable(
            "No se encontró murmur, whisper.cpp ni un servidor STT local. \
             Configurá engine_command/model_path/server_url en la config del bridge."
                .into(),
        ),
        models: vec![],
    }
}

/// Prueba si `murmur` expone un subcomando de transcripción utilizable.
async fn probe_murmur(path: &std::path::Path) -> Option<Engine> {
    let output = Command::new(path)
        .arg("--help")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .await
        .ok()?;
    let help = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    )
    .to_lowercase();

    // buscar un subcomando que reciba un archivo de audio
    for sub in ["transcribe", "stt", "recognize", "run"] {
        if help.contains(sub) {
            return Some(Engine {
                name: "murmur".into(),
                kind: EngineKind::Cli {
                    argv: vec![
                        path.to_string_lossy().to_string(),
                        sub.into(),
                        "{input}".into(),
                    ],
                    json_output: false,
                },
                models: vec![],
            });
        }
    }
    // sin subcomando conocido: probar pasarle el archivo directo
    if help.contains("audio") || help.contains("wav") || help.contains("file") {
        return Some(Engine {
            name: "murmur".into(),
            kind: EngineKind::Cli {
                argv: vec![path.to_string_lossy().to_string(), "{input}".into()],
                json_output: false,
            },
            models: vec![],
        });
    }
    None
}

async fn probe_http_server(url: &str) -> bool {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_millis(800))
        .build()
        .unwrap();
    // whisper.cpp server responde en / y en /inference (POST)
    matches!(client.get(url).send().await, Ok(response) if response.status().as_u16() < 500)
}

fn find_model(config: &super::Config) -> Option<PathBuf> {
    if let Some(model) = &config.model_path {
        let path = PathBuf::from(model);
        if path.exists() {
            return Some(path);
        }
    }
    let mut roots: Vec<PathBuf> = vec![];
    if let Some(home) = dirs::home_dir() {
        roots.push(home.join("whisper.cpp").join("models"));
        roots.push(home.join(".cache").join("whisper"));
        roots.push(home.join("models"));
    }
    if let Some(data) = dirs::data_dir() {
        roots.push(data.join("whisper").join("models"));
        roots.push(data.join("echo-bridge").join("models"));
    }
    for root in roots {
        if let Ok(entries) = std::fs::read_dir(&root) {
            let mut candidates: Vec<PathBuf> = entries
                .flatten()
                .map(|entry| entry.path())
                .filter(|path| {
                    let name = path.file_name().unwrap_or_default().to_string_lossy();
                    (name.ends_with(".bin") && name.starts_with("ggml"))
                        || name.ends_with(".gguf")
                })
                .collect();
            candidates.sort();
            if let Some(best) = candidates.pop() {
                return Some(best);
            }
        }
    }
    None
}

fn short_name(path: &std::path::Path) -> String {
    path.file_name()
        .map(|name| name.to_string_lossy().to_string())
        .unwrap_or_default()
}

fn shell_words(input: &str) -> Vec<String> {
    // separador simple con soporte de comillas dobles
    let mut words = vec![];
    let mut current = String::new();
    let mut quoted = false;
    for ch in input.chars() {
        match ch {
            '"' => quoted = !quoted,
            ' ' if !quoted => {
                if !current.is_empty() {
                    words.push(std::mem::take(&mut current));
                }
            }
            _ => current.push(ch),
        }
    }
    if !current.is_empty() {
        words.push(current);
    }
    words
}

// ── Transcripción ────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct Segment {
    pub text: String,
    pub start_ms: u64,
    pub end_ms: u64,
    pub confidence: Option<f32>,
    pub speaker: Option<String>,
}

#[derive(Deserialize)]
struct WhisperJson {
    transcription: Option<Vec<WhisperSegment>>,
}

#[derive(Deserialize)]
struct WhisperSegment {
    text: String,
    offsets: Option<WhisperOffsets>,
}

#[derive(Deserialize)]
struct WhisperOffsets {
    from: u64,
    to: u64,
}

impl Engine {
    /// Transcribe PCM16 mono. El WAV temporal se crea, se procesa y se borra
    /// inmediatamente (privacy first).
    pub async fn transcribe(
        &self,
        pcm16: &[i16],
        sample_rate: u32,
        language: &str,
        offset_ms: u64,
    ) -> Result<Vec<Segment>, String> {
        match &self.kind {
            EngineKind::Unavailable(reason) => Err(reason.clone()),
            EngineKind::HttpServer { url } => {
                self.transcribe_http(url, pcm16, sample_rate, language, offset_ms)
                    .await
            }
            EngineKind::Cli { argv, json_output } => {
                self.transcribe_cli(argv, *json_output, pcm16, sample_rate, language, offset_ms)
                    .await
            }
        }
    }

    async fn transcribe_cli(
        &self,
        argv: &[String],
        json_output: bool,
        pcm16: &[i16],
        sample_rate: u32,
        language: &str,
        offset_ms: u64,
    ) -> Result<Vec<Segment>, String> {
        // WAV temporal de vida mínima (NamedTempFile se borra al hacer drop)
        let wav_file = tempfile::Builder::new()
            .prefix("echo-")
            .suffix(".wav")
            .tempfile()
            .map_err(|error| error.to_string())?;
        write_wav(wav_file.path(), pcm16, sample_rate)?;
        let output_base = wav_file.path().with_extension("out");

        let mut command_args: Vec<String> = vec![];
        for arg in argv.iter().skip(1) {
            command_args.push(
                arg.replace("{input}", &wav_file.path().to_string_lossy())
                    .replace("{lang}", language)
                    .replace("{output}", &output_base.to_string_lossy()),
            );
        }
        let result = Command::new(&argv[0])
            .args(&command_args)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .output()
            .await
            .map_err(|error| format!("no se pudo ejecutar el motor: {error}"))?;

        // el WAV se borra acá pase lo que pase (drop del NamedTempFile)
        drop(wav_file);

        let stdout = String::from_utf8_lossy(&result.stdout).to_string();

        if json_output {
            let json_path = output_base.with_extension("out.json");
            let json_raw = tokio::fs::read_to_string(&json_path).await;
            let _ = tokio::fs::remove_file(&json_path).await;
            if let Ok(raw) = json_raw {
                if let Ok(parsed) = serde_json::from_str::<WhisperJson>(&raw) {
                    return Ok(parse_whisper_segments(parsed, offset_ms));
                }
            }
        }

        if !result.status.success() && stdout.trim().is_empty() {
            return Err(format!(
                "el motor terminó con error: {}",
                String::from_utf8_lossy(&result.stderr)
                    .chars()
                    .take(300)
                    .collect::<String>()
            ));
        }

        // salida de texto plano (murmur u otros): todo como un segmento
        let text = clean_plain_output(&stdout);
        if text.is_empty() {
            return Ok(vec![]);
        }
        let duration_ms = (pcm16.len() as u64 * 1000) / sample_rate as u64;
        Ok(vec![Segment {
            text,
            start_ms: offset_ms,
            end_ms: offset_ms + duration_ms,
            confidence: None,
            speaker: None,
        }])
    }

    async fn transcribe_http(
        &self,
        url: &str,
        pcm16: &[i16],
        sample_rate: u32,
        language: &str,
        offset_ms: u64,
    ) -> Result<Vec<Segment>, String> {
        let wav_bytes = wav_in_memory(pcm16, sample_rate);
        let duration_ms = (pcm16.len() as u64 * 1000) / sample_rate as u64;
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(60))
            .build()
            .unwrap();
        let part = reqwest::multipart::Part::bytes(wav_bytes)
            .file_name("chunk.wav")
            .mime_str("audio/wav")
            .unwrap();
        let form = reqwest::multipart::Form::new()
            .part("file", part)
            .text("language", language.to_string())
            .text("response_format", "json");
        let response = client
            .post(format!("{}/inference", url.trim_end_matches('/')))
            .multipart(form)
            .send()
            .await
            .map_err(|error| format!("servidor STT local: {error}"))?;
        if !response.status().is_success() {
            return Err(format!("servidor STT local devolvió {}", response.status()));
        }
        let body: serde_json::Value = response
            .json()
            .await
            .map_err(|error| error.to_string())?;
        let text = body
            .get("text")
            .and_then(|value| value.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        if text.is_empty() {
            return Ok(vec![]);
        }
        Ok(vec![Segment {
            text,
            start_ms: offset_ms,
            end_ms: offset_ms + duration_ms,
            confidence: None,
            speaker: None,
        }])
    }
}

fn parse_whisper_segments(parsed: WhisperJson, offset_ms: u64) -> Vec<Segment> {
    let mut segments = vec![];
    let mut speaker_index = 1u32;
    for raw in parsed.transcription.unwrap_or_default() {
        let mut text = raw.text.trim().to_string();
        // tinydiarize marca cambios de hablante con [SPEAKER_TURN]
        let had_turn = text.contains("[SPEAKER_TURN]");
        text = text.replace("[SPEAKER_TURN]", "").trim().to_string();
        if text.is_empty() {
            if had_turn {
                speaker_index += 1;
            }
            continue;
        }
        let (start, end) = raw
            .offsets
            .map(|offsets| (offsets.from, offsets.to))
            .unwrap_or((0, 0));
        segments.push(Segment {
            text,
            start_ms: offset_ms + start,
            end_ms: offset_ms + end,
            confidence: None,
            speaker: Some(format!("speaker_{speaker_index}")),
        });
        if had_turn {
            speaker_index += 1;
        }
    }
    // si nunca hubo cambio de hablante, no afirmar diarización
    if speaker_index == 1 {
        for segment in &mut segments {
            segment.speaker = None;
        }
    }
    segments
}

fn clean_plain_output(stdout: &str) -> String {
    stdout
        .lines()
        .map(str::trim)
        .filter(|line| {
            !line.is_empty()
                && !line.starts_with('[')
                && !line.to_lowercase().starts_with("whisper")
                && !line.to_lowercase().contains("processing")
        })
        .collect::<Vec<_>>()
        .join(" ")
        .trim()
        .to_string()
}

fn write_wav(path: &std::path::Path, pcm16: &[i16], sample_rate: u32) -> Result<(), String> {
    let spec = hound::WavSpec {
        channels: 1,
        sample_rate,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let mut writer = hound::WavWriter::create(path, spec).map_err(|error| error.to_string())?;
    for sample in pcm16 {
        writer.write_sample(*sample).map_err(|error| error.to_string())?;
    }
    writer.finalize().map_err(|error| error.to_string())
}

fn wav_in_memory(pcm16: &[i16], sample_rate: u32) -> Vec<u8> {
    let mut buffer = std::io::Cursor::new(Vec::new());
    {
        let spec = hound::WavSpec {
            channels: 1,
            sample_rate,
            bits_per_sample: 16,
            sample_format: hound::SampleFormat::Int,
        };
        let mut writer = hound::WavWriter::new(&mut buffer, spec).unwrap();
        for sample in pcm16 {
            writer.write_sample(*sample).unwrap();
        }
        writer.finalize().unwrap();
    }
    buffer.into_inner()
}
