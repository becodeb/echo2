//! Echo Bridge — servicio local de transcripción.
//!
//! Corre en la máquina del usuario, escucha SOLO en 127.0.0.1 y conecta el
//! navegador con el motor STT local (Murmur / whisper.cpp / servidor HTTP
//! compatible). El audio entra por WebSocket, se transcribe localmente y solo
//! el TEXTO vuelve al navegador. Nada de audio sale de la máquina ni se
//! persiste: los WAV temporales que exige un motor CLI viven milisegundos y
//! se borran automáticamente.

mod engine;
mod stt;

use std::{
    collections::HashMap,
    net::SocketAddr,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use axum::{
    extract::{ws::WebSocketUpgrade, Query, State},
    http::{header, HeaderMap, HeaderValue, Method, StatusCode},
    response::{IntoResponse, Json},
    routing::{get, post},
    Router,
};
use rand::{distributions::Alphanumeric, Rng};
use serde::{Deserialize, Serialize};
use tower_http::cors::CorsLayer;

const VERSION: &str = env!("CARGO_PKG_VERSION");
const TOKEN_TTL: Duration = Duration::from_secs(12 * 3600);

#[derive(Clone, Serialize, Deserialize)]
pub struct Config {
    #[serde(default = "default_port")]
    pub port: u16,
    /// Orígenes web autorizados a emparejarse con el bridge.
    #[serde(default = "default_origins")]
    pub allowed_origins: Vec<String>,
    /// Forzar un comando de motor (ej: "murmur transcribe {input}").
    #[serde(default)]
    pub engine_command: Option<String>,
    /// Ruta a un modelo whisper.cpp (ggml/gguf).
    #[serde(default)]
    pub model_path: Option<String>,
    /// URL de un servidor STT local compatible con whisper.cpp server.
    #[serde(default)]
    pub server_url: Option<String>,
    /// Idioma por defecto.
    #[serde(default)]
    pub language: Option<String>,
}

fn default_port() -> u16 {
    8974
}

fn default_origins() -> Vec<String> {
    vec![
        "http://localhost:5173".into(),
        "http://127.0.0.1:5173".into(),
        "http://localhost:4173".into(),
    ]
}

impl Default for Config {
    fn default() -> Self {
        Self {
            port: default_port(),
            allowed_origins: default_origins(),
            engine_command: None,
            model_path: None,
            server_url: None,
            language: None,
        }
    }
}

fn config_path() -> std::path::PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| ".".into())
        .join("echo-bridge")
        .join("config.json")
}

fn load_config() -> Config {
    let path = config_path();
    match std::fs::read_to_string(&path) {
        Ok(raw) => serde_json::from_str(&raw).unwrap_or_default(),
        Err(_) => {
            let config = Config::default();
            if let Some(parent) = path.parent() {
                let _ = std::fs::create_dir_all(parent);
            }
            let _ = std::fs::write(&path, serde_json::to_string_pretty(&config).unwrap());
            config
        }
    }
}

pub struct AppState {
    pub config: Config,
    pub engine: engine::Engine,
    /// tokens de sesión emitidos -> expiración
    pub tokens: Mutex<HashMap<String, Instant>>,
    /// rate limit simple de /session
    pub session_hits: Mutex<Vec<Instant>>,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "echo_bridge=info,info".into()),
        )
        .init();

    let config = load_config();
    let engine = engine::detect(&config).await;

    match &engine.kind {
        engine::EngineKind::Unavailable(reason) => {
            tracing::warn!("Sin motor STT local: {reason}");
            tracing::warn!("Echo seguirá funcionando en modo cloud. Ver README para configurar Murmur/whisper.");
        }
        other => tracing::info!("Motor STT: {} ({:?})", engine.name, other),
    }

    let port = config.port;
    let allowed = config.allowed_origins.clone();
    let state = Arc::new(AppState {
        config,
        engine,
        tokens: Mutex::new(HashMap::new()),
        session_hits: Mutex::new(Vec::new()),
    });

    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::POST])
        .allow_headers([header::CONTENT_TYPE])
        .allow_origin(
            allowed
                .iter()
                .filter_map(|origin| origin.parse::<HeaderValue>().ok())
                .collect::<Vec<_>>(),
        );

    let app = Router::new()
        .route("/health", get(health))
        .route("/session", post(create_session))
        .route("/stt", get(stt_ws))
        .layer(cors)
        .with_state(state);

    // SOLO loopback: nunca exponer el bridge a la red
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    tracing::info!("Echo Bridge escuchando en http://{addr}");
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("no se pudo abrir el puerto local");
    axum::serve(listener, app).await.expect("server error");
}

#[derive(Serialize)]
struct HealthOut {
    status: &'static str,
    version: &'static str,
    engine: EngineOut,
    models: Vec<String>,
}

#[derive(Serialize)]
struct EngineOut {
    kind: String,
    name: String,
    available: bool,
    detail: Option<String>,
}

async fn health(State(state): State<Arc<AppState>>) -> Json<HealthOut> {
    let (kind, available, detail) = match &state.engine.kind {
        engine::EngineKind::Cli { .. } => ("cli".to_string(), true, None),
        engine::EngineKind::HttpServer { url } => ("http".to_string(), true, Some(url.clone())),
        engine::EngineKind::Unavailable(reason) => {
            ("none".to_string(), false, Some(reason.clone()))
        }
    };
    Json(HealthOut {
        status: "ok",
        version: VERSION,
        engine: EngineOut {
            kind,
            name: state.engine.name.clone(),
            available,
            detail,
        },
        models: state.engine.models.clone(),
    })
}

#[derive(Serialize)]
struct SessionOut {
    token: String,
    expires_in_seconds: u64,
}

async fn create_session(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<SessionOut>, (StatusCode, String)> {
    // Validación de Origin: solo la web de Echo puede emparejarse.
    let origin = headers
        .get(header::ORIGIN)
        .and_then(|value| value.to_str().ok())
        .unwrap_or("");
    if !state.config.allowed_origins.iter().any(|o| o == origin) {
        return Err((
            StatusCode::FORBIDDEN,
            "Origin no autorizado para Echo Bridge".into(),
        ));
    }

    // rate limit: máx 20 sesiones por minuto
    {
        let mut hits = state.session_hits.lock().unwrap();
        let now = Instant::now();
        hits.retain(|t| now.duration_since(*t) < Duration::from_secs(60));
        if hits.len() >= 20 {
            return Err((StatusCode::TOO_MANY_REQUESTS, "Demasiadas sesiones".into()));
        }
        hits.push(now);
    }

    let token: String = rand::thread_rng()
        .sample_iter(&Alphanumeric)
        .take(40)
        .map(char::from)
        .collect();
    let mut tokens = state.tokens.lock().unwrap();
    let now = Instant::now();
    tokens.retain(|_, expiry| *expiry > now);
    tokens.insert(token.clone(), now + TOKEN_TTL);
    Ok(Json(SessionOut {
        token,
        expires_in_seconds: TOKEN_TTL.as_secs(),
    }))
}

#[derive(Deserialize)]
struct SttQuery {
    token: String,
    #[serde(default)]
    lang: Option<String>,
}

async fn stt_ws(
    State(state): State<Arc<AppState>>,
    Query(query): Query<SttQuery>,
    ws: WebSocketUpgrade,
) -> impl IntoResponse {
    // token de sesión obligatorio (protege el WS de páginas arbitrarias)
    let valid = {
        let tokens = state.tokens.lock().unwrap();
        tokens
            .get(&query.token)
            .map(|expiry| *expiry > Instant::now())
            .unwrap_or(false)
    };
    if !valid {
        return (StatusCode::UNAUTHORIZED, "token inválido").into_response();
    }
    let language = query
        .lang
        .or_else(|| state.config.language.clone())
        .unwrap_or_else(|| "es".into());
    ws.on_upgrade(move |socket| stt::handle_session(socket, state, language))
}
