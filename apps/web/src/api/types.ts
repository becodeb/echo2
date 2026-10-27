export interface UserOut {
  id: string;
  email: string;
  name: string;
  avatar_color: string;
  avatar_url?: string | null;
  job_title: string | null;
  locale: string;
  /** Superadmin de la instalación: ve todas las organizaciones, no solo las suyas. */
  is_superadmin: boolean;
}

export interface AdminOrgOut {
  id: string;
  name: string;
  slug: string;
  members: number;
  meetings: number;
  llm_provider: string | null;
  llm_model: string | null;
  llm_api_key_masked: string | null;
  /** false = está viviendo del default del servidor, no tiene key propia. */
  uses_own_key: boolean;
  /** Dominios o emails que se unen sin invitación. */
  join_rules: string[];
  /** Plan (base | institucion | cortesia) y topes propios. */
  plan: string;
  is_personal: boolean;
  limits: Record<string, number>;
}

export interface OrgOut {
  id: string;
  name: string;
  slug: string;
  role: string;
  /** Cuenta individual: organización de una sola persona. */
  is_personal?: boolean;
}

export interface SessionOut {
  access_token: string;
  user: UserOut;
  organizations: OrgOut[];
}

export interface ParticipantOut {
  id: string;
  name: string;
  email: string | null;
  role_label: string | null;
  /** Persona de la sede que estuvo: con eso ve la reunión. */
  user_id: string | null;
}

export interface SpeakerOut {
  id: string;
  label: string;
  display_name: string | null;
  color: string;
  identity_suggestion: {
    person_name?: string;
    confidence?: number;
    user_id?: string | null;
    /** voz | dijo | ia */
    source?: string;
    /** Dijo un nombre pero la voz parece de otra persona: para revisar. */
    voice_says?: string;
  } | null;
  user_id?: string | null;
  /** Cómo se supo el nombre: voz | dijo | ia | manual. */
  name_source?: string | null;
}

export interface MeetingOut {
  id: string;
  title: string;
  status: "draft" | "live" | "paused" | "processing" | "completed" | "failed";
  language: string;
  audio_source: string;
  stt_engine: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number;
  created_at: string;
  created_by: string;
  processing_state: Record<string, unknown>;
  meta: {
    visibility?: string;
    /** Se pidió separar quién habló / hablan menores (NewMeetingModal). */
    people?: boolean;
    minors?: boolean;
    /** Entre las dos sedes: el acta sale sin el formato de ninguna. */
    intersede?: boolean;
    /** pending: ElevenLabs falló y se reintenta solo (services/diarization.py). */
    people_status?: "pending" | "done" | "failed" | "skipped";
    /** pending: Groq no respondió en la pasada final y se reintenta solo. */
    text_status?: "pending" | "done" | "failed" | "skipped";
    timeline?: { at_ms: number; label: string }[];
    next_steps?: string[];
    mentions?: Record<string, unknown>;
  };
  /** inicial | primaria | secundaria; null = sin nivel (solo admins y quien la creó). */
  level: string | null;
  /** familia: con alumno, acta y nivel. interna: de un grupo (directivos, coordinadores). */
  kind: MeetingKind;
  group_id: string | null;
  group_name: string | null;
  /** null = no se graba el audio completo. */
  recording: RecordingState | null;
  participants: ParticipantOut[];
  speakers: SpeakerOut[];
}

export type MeetingKind = "familia" | "interna";

/** Grabación del audio completo (services/recording.py en el API). */
export interface RecordingState {
  enabled: boolean;
  status:
    | "pending"
    | "recording"
    | "processing"
    | "uploaded"
    | "download"
    | "expired"
    | "discarded"
    | "empty"
    | "failed";
  user_id: string | null;
  drive_url: string | null;
  /** Hasta cuándo se puede descargar del servidor (después se borra). */
  expires_at: string | null;
  size_bytes: number | null;
  duration_seconds: number | null;
  error: string | null;
}

export interface InternalGroupOut {
  id: string;
  name: string;
  is_member: boolean;
  meetings: number;
  members: { user_id: string; name: string; email: string }[];
}

export interface InternalGroupsOut {
  can_manage: boolean;
  groups: InternalGroupOut[];
}

export interface MyDriveOut {
  enabled: boolean;
  connected: boolean;
  connected_email: string | null;
  folder_url: string | null;
  last_error: string | null;
}

export interface MeetingListItem {
  id: string;
  title: string;
  status: string;
  started_at: string | null;
  duration_seconds: number;
  created_at: string;
  participant_count: number;
  project_name: string | null;
  level: string | null;
  kind: MeetingKind;
  group_id: string | null;
  group_name: string | null;
  recorded: boolean;
}

export interface SegmentOut {
  id: string;
  seq: number;
  start_ms: number;
  end_ms: number;
  text: string;
  confidence: number | null;
  speaker_id: string | null;
  edited: boolean;
}

export interface DecisionOut {
  id: string;
  text: string;
  context: string | null;
  evidence_start_ms: number | null;
  evidence_end_ms: number | null;
  status: string;
  source: string;
}

export interface TaskOut {
  id: string;
  text: string;
  assignee_name: string | null;
  assignee_user_id: string | null;
  /** Responsable de afuera de Echo: le llegó por mail con un link. */
  assignee_email?: string | null;
  /** Quién dijo en la reunión que se encargaba (las que detecta Echo). */
  suggested_assignee?: string | null;
  due_text: string | null;
  due_date: string | null;
  /** suggested: la detectó Echo y nadie la confirmó; dismissed: descartada. */
  status: "suggested" | "pending" | "in_progress" | "done" | "cancelled" | "dismissed";
  source: string;
  meeting_id: string | null;
  meeting_title: string | null;
  evidence_start_ms: number | null;
  overdue: boolean;
  created_at: string;
}

export interface QuestionOut {
  id: string;
  text: string;
  resolved: boolean;
  evidence_start_ms: number | null;
  evidence_end_ms: number | null;
}

export interface InsightsOut {
  decisions: DecisionOut[];
  action_items: TaskOut[];
  questions: QuestionOut[];
}

export interface ChatSource {
  meeting_id: string;
  meeting_title: string;
  segment_id: string;
  start_ms: number;
  end_ms: number;
  text: string;
  speaker: string | null;
}

export interface ChatOut {
  answer: string;
  sources: ChatSource[];
}

export interface MinutesOut {
  id: string;
  status: "draft" | "in_review" | "approved";
  current_version: number;
  approved_at: string | null;
  version: {
    version: number;
    body_markdown: string;
    /** Formulario del acta de entrevista; null en actas de texto libre. */
    blocks: { kind: "entrevista"; fields: InterviewFields } | null;
    verification: { claim: string; status: string; evidence_ms: number | null; note: string }[] | null;
    note: string | null;
    model_used: string | null;
    created_at: string;
    created_by: string | null;
  } | null;
  versions: { version: number; note: string | null; created_at: string; model_used: string | null }[];
  /** Número de acta, correlativo por organización. null hasta que se genera o se imprime. */
  number: number | null;
  // "verifying": el acta ya se puede leer e imprimir; falta la verificación.
  generation_status: "idle" | "generating" | "verifying" | "ok" | "failed";
  generation_error: string | null;
  generation_started_at: string | null;
  /** Quien grabó la reunión (o un admin) puede confirmar el acta. */
  can_confirm: boolean;
}

/** Campos del formulario del acta del colegio (de entrevista o de reunión). */
export interface InterviewFields {
  alumno: string;
  curso: string;
  solicitada_por: "familia" | "colegio" | "";
  motivo: string;
  /** ISO yyyy-mm-dd; de acá salen el día, el mes y el año del párrafo. */
  fecha: string;
  reunen: string;
  con: string;
  desarrollo: string;
  /** "reunion": el acta de reunión en prosa (Nordelta); sin dato, la de entrevista. */
  formato?: "entrevista" | "reunion";
  /** HH:MM, solo en el acta de reunión ("siendo las 11:30 hs"). */
  hora?: string;
}

/** Membrete del acta impresa (Ajustes → Membrete). */
export interface LetterheadOut {
  institution: string;
  lines: string[];
  address: string;
  phone: string;
  email: string;
  title: string;
  signatures: string[];
  logo_data_url: string | null;
  interview_place: string;
  /** Fuente del acta impresa, en Word y en PDF. */
  font: "arial" | "calibri" | "times" | "trebuchet";
  /** Cómo se ve el acta (Ajustes → Formato de acta): impresa, en la reunión, Word y PDF. */
  font_size: ActaFontSize;
  line_spacing: ActaLineSpacing;
  margins: ActaMargins;
}

export type ActaFontSize = "normal" | "grande" | "muy_grande";
export type ActaLineSpacing = "simple" | "1.5";
export type ActaMargins = "normal" | "angosto";

export interface FamilyMemberOut {
  id: string;
  name: string;
  relationship_type: "madre" | "padre" | "tutor" | "estudiante" | "otro";
  /** Solo los responsables cuentan para "¿estuvieron todos?". */
  is_guardian: boolean;
  email: string | null;
  phone: string | null;
  /** Estudiantes: curso ("3N EP") y nivel. */
  curso?: string | null;
  level?: "inicial" | "primaria" | "secundaria" | null;
}

export interface ProfessionalOut {
  id: string;
  name: string;
  role_label: string | null;
  affiliation: string | null;
  email: string | null;
  phone: string | null;
  is_active: boolean;
}

export interface FamilyOut {
  id: string;
  name: string;
  reference: string | null;
  notes: string | null;
  /** Carpeta de Drive de la familia. Echo solo guarda el enlace. */
  drive_url: string | null;
  members: FamilyMemberOut[];
  professionals: ProfessionalOut[];
  meetings: number;
  /** Personas de la sede asignadas: ven todas las reuniones de la familia. */
  assignees: { user_id: string; name: string }[];
}

export interface AttachmentOut {
  id: string;
  url: string;
  title: string | null;
}

export type Audience = "familia" | "profesionales" | "mixta" | "docentes" | "interna";

export interface ProfessionalAttendanceRow {
  professional_id: string;
  name: string;
  role_label: string | null;
  attended: boolean;
  /** true = acompaña a esta familia; false = participó de forma puntual. */
  linked: boolean;
}

export interface ReasonOut {
  id: string;
  name: string;
  is_active: boolean;
  position: number;
}

export type Severity = "verde" | "amarillo" | "rojo";

/** Una reunión en el panel de la familia (GET /api/families/{id}/meetings). */
export interface FamilyMeetingOut {
  id: string;
  title: string;
  status: string;
  started_at: string | null;
  created_at: string;
  duration_seconds: number;
  level: string | null;
  reason_id: string | null;
  reason_name: string | null;
  severity: Severity | null;
  audience: Audience | null;
  minutes_status: "draft" | "in_review" | "approved" | null;
  minutes_number: number | null;
  /** null = no se registró asistencia, que no es lo mismo que "faltaron". */
  all_guardians_present: boolean | null;
  attended: string[];
  professionals: string[];
  /** Primeros puntos del resumen ejecutivo. */
  summary: string[];
  /** De qué hijo(s) de la familia es. */
  student_ids: string[];
}

/** Tarea sin cerrar de una reunión de la familia. */
export interface FamilyTaskOut {
  id: string;
  text: string;
  /** suggested = la detectó Echo y falta confirmarla. */
  status: "suggested" | "pending" | "in_progress";
  assignee: string | null;
  due_date: string | null;
  due_text: string | null;
  overdue: boolean;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
}

/** La ficha de una familia (GET /api/families/{id}). */
export interface FamilyDetailOut extends FamilyOut {
  created_at: string;
  open_tasks: FamilyTaskOut[];
  /** Cambios en la ficha, del más nuevo al más viejo. */
  history: { at: string; action: string; actor: string | null; detail: Record<string, unknown> | null }[];
}

export interface FamilySummaryContent {
  overview: string;
  working_on: string[];
  agreements: string[];
  pending: string[];
  alerts: string[];
}

/** Resumen de IA de la familia, armado con las reuniones que ve quien mira. */
export interface FamilySummaryOut {
  /** empty: nada para resumir · none: no se generó · stale: reuniones nuevas · outdated: cambió un acta o una tarea. */
  status: "empty" | "none" | "stale" | "outdated" | "fresh";
  summary: FamilySummaryContent | null;
  generated_at: string | null;
  meetings_used: number;
  meetings_available: number;
  new_meetings: number;
  ai_configured: boolean;
}

export interface AttendanceRow {
  member_id: string;
  name: string;
  relationship_type: string;
  is_guardian: boolean;
  attended: boolean;
  /** false = nunca se registró asistencia para esta persona en esta reunión. */
  recorded: boolean;
}

export interface ClassificationOut {
  family_id: string | null;
  family_name: string | null;
  family_drive_url: string | null;
  audience: Audience | null;
  professionals: ProfessionalAttendanceRow[];
  reason_id: string | null;
  reason_name: string | null;
  severity: Severity | null;
  attendance: AttendanceRow[];
  /** null = no hay registro de asistencia, que no es lo mismo que "faltaron". */
  all_guardians_present: boolean | null;
  /** De qué hijo(s) de la familia es la reunión. */
  student_ids: string[];
}

export interface ReportOut {
  range_from: string;
  range_to: string;
  totals: {
    meetings: number;
    families_with_meetings: number;
    classified: number;
    unclassified: number;
  };
  by_family: {
    family_id: string;
    name: string;
    reference: string | null;
    meetings: number;
    last_meeting_at: string | null;
    verde: number;
    amarillo: number;
    rojo: number;
  }[];
  by_reason: { reason_id: string | null; name: string; meetings: number }[];
  by_severity: { verde: number; amarillo: number; rojo: number; sin_clasificar: number };
  attendance: {
    complete: number;
    incomplete: number;
    unknown: number;
    absentees: { member_id: string; name: string; family: string | null; missed: number }[];
  };
  timeline: { month: string; meetings: number; verde: number; amarillo: number; rojo: number }[];
}

export interface ServerAIOut {
  llm_provider: string | null;
  llm_model: string | null;
  llm_api_key_masked: string | null;
  llm_base_url: string | null;
  /** "panel" = cargado acá · "entorno" = variables del servidor · "sin_configurar" */
  source: "panel" | "entorno" | "sin_configurar";
}

export interface ServerAITestOut {
  ok: boolean;
  provider: string | null;
  model: string | null;
  message: string;
}

export interface DriveStatusOut {
  /** false = el servidor no tiene credenciales de Google configuradas. */
  enabled: boolean;
  connected: boolean;
  connected_email: string | null;
  root_folder_url: string | null;
  last_error: string | null;
}

export type LiveEvent =
  | { type: "hello_ack"; role: string; meeting_status: string }
  | { type: "flushed" }
  | { type: "segment"; id: string; seq: number; start_ms: number; end_ms: number; text: string; confidence: number | null; speaker_hint: string | null }
  | { type: "partial"; text: string; start_ms: number; speaker_hint?: string | null }
  | { type: "status"; status: string }
  | { type: "processing"; stage: string; progress: number }
  | { type: "ready"; what: "minutes" | "summary" }
  | { type: "insights"; totals: { decisions: number; tasks: number; questions: number }; new: Record<string, number> }
  | { type: "warning"; code: string; message: string }
  | { type: "limit"; code: string; message: string }
  | { type: "error"; code: string; message: string }
  | { type: "pong" };
