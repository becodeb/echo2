export interface UserOut {
  id: string;
  email: string;
  name: string;
  avatar_color: string;
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
}

export interface OrgOut {
  id: string;
  name: string;
  slug: string;
  role: string;
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
}

export interface SpeakerOut {
  id: string;
  label: string;
  display_name: string | null;
  color: string;
  identity_suggestion: { profile_id?: string; person_name?: string; confidence?: number } | null;
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
    timeline?: { at_ms: number; label: string }[];
    next_steps?: string[];
    mentions?: Record<string, unknown>;
  };
  participants: ParticipantOut[];
  speakers: SpeakerOut[];
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
  due_text: string | null;
  due_date: string | null;
  status: "pending" | "in_progress" | "done" | "cancelled";
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
    verification: { claim: string; status: string; evidence_ms: number | null; note: string }[] | null;
    note: string | null;
    model_used: string | null;
    created_at: string;
    created_by: string | null;
  } | null;
  versions: { version: number; note: string | null; created_at: string; model_used: string | null }[];
  generation_status: "idle" | "generating" | "ok" | "failed";
  generation_error: string | null;
}

export interface FamilyMemberOut {
  id: string;
  name: string;
  relationship_type: "madre" | "padre" | "tutor" | "estudiante" | "otro";
  /** Solo los responsables cuentan para "¿estuvieron todos?". */
  is_guardian: boolean;
  email: string | null;
  phone: string | null;
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
  | { type: "segment"; id: string; seq: number; start_ms: number; end_ms: number; text: string; confidence: number | null; speaker_hint: string | null }
  | { type: "partial"; text: string; start_ms: number; speaker_hint?: string | null }
  | { type: "status"; status: string }
  | { type: "processing"; stage: string; progress: number }
  | { type: "insights"; totals: { decisions: number; tasks: number; questions: number }; new: Record<string, number> }
  | { type: "warning"; code: string; message: string }
  | { type: "error"; code: string; message: string }
  | { type: "pong" };
