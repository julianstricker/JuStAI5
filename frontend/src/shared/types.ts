// Types mirroring the backend API responses (kept intentionally small).

export interface Me {
  id: string;
  username: string;
  role: "admin" | "resident" | "guest";
  permissions: string[];
  person_id: string | null;
}

export interface Room {
  id: string;
  name: string;
  slug: string;
  description: string;
  floor: string | null;
  icon: string | null;
  layout: Record<string, unknown>;
  policy: RoomPolicy;
  devices: string[];
  endpoints: string[];
}

export interface RoomPolicy {
  shared_space?: boolean;
  vision_allowed?: boolean;
  face_recognition_allowed?: boolean;
  cloud_media_allowed?: boolean;
  announcements_allowed?: boolean;
}

export interface Device {
  id: string;
  name: string;
  driver_id: string;
  room_id: string | null;
  enabled: boolean;
  config: Record<string, unknown>;
  settings: Record<string, unknown>;
  secret_fields_set: string[];
  capabilities: string[];
  info: Record<string, unknown>;
  status: string;
  status_detail: string | null;
  last_seen_at: string | null;
  stream: string | null;
  audio: { input: boolean; output: boolean };
}

export interface Driver {
  id: string;
  name: string;
  plugin_id: string;
  config_schema: JsonSchema;
  secret_fields: string[];
}

export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  enum?: unknown[];
  default?: unknown;
  items?: JsonSchema;
  minimum?: number;
  maximum?: number;
  pattern?: string;
}

export type DeviceRole = "mic" | "camera" | "speaker" | "display";

export interface EndpointDeviceRef {
  device_id: string;
  role: DeviceRole;
  priority: number;
}

export interface EndpointConfig {
  wakeword: {
    enabled: boolean;
    models: string[];
    threshold: number;
    threshold_during_playback: number;
  };
  audio: {
    duplex: "auto" | "full" | "half";
    aec: boolean;
    noise_suppression: boolean;
    output_latency_ms: number | null;
    echo_tail_ms: number;
    input_gain_db: number;
    vad_threshold: number;
    barge_in: boolean;
    barge_in_min_speech_ms: number;
  };
  conversation: {
    mode: "default" | "realtime" | "pipeline";
    inactivity_timeout_s: number;
    end_of_utterance_silence_ms: number;
    max_utterance_s: number;
    voice: string | null;
    default_role: string;
    follow_up_listening: boolean;
    send_video: boolean;
  };
}

export interface Endpoint {
  id: string;
  name: string;
  room_id: string;
  enabled: boolean;
  priority: number;
  arbitration_group: string;
  language: string | null;
  config: EndpointConfig;
  devices: EndpointDeviceRef[];
  runtime: EndpointRuntime | null;
  session: { id: string; state: string } | null;
}

export interface EndpointRuntime {
  level_db: number;
  noise_floor_db: number;
  vad: number;
  speech: boolean;
  gated: boolean;
  echo_window: boolean;
  wake_score: number;
  delay_estimate_s: number | null;
  delay_confidence: number;
  erle_db: number | null;
  effective_duplex: string;
  duplex_reason: string;
  frames: number;
  gated_frames: number;
  suppressed_wakes: number;
  processing_ms: number;
  latency_s: number;
  mic: string | null;
  duplex: string;
}

export interface PluginInfo {
  id: string;
  version: string;
  source: string;
  enabled: boolean;
  status: string;
  error: string | null;
  manifest: {
    name: string;
    description: string;
    types: string[];
    permissions: string[];
    config_schema: JsonSchema;
    secret_fields: string[];
    trust: string;
    network_allowlist: string[];
    author?: string;
  };
  config: Record<string, unknown>;
  granted_permissions: string[];
  running: boolean;
  health: { state: string; detail: string | null } | null;
  provides: { tools: string[]; providers: string[] };
}

export interface JEvent {
  id: string;
  type: string;
  timestamp: string;
  source: Record<string, string | null>;
  payload: Record<string, unknown>;
  correlation_id: string | null;
  hop: number;
}

export interface ActiveSession {
  id: string;
  endpoint_id: string | null;
  room_id: string | null;
  room: string | null;
  state: string;
  mode: string;
  person: string | null;
  language: string | null;
  trigger: string;
  user_turns: number;
  transcript: { role: string; text: string; t: number }[];
}

export interface ToolInfo {
  name: string;
  description: string;
  category: string;
  owner: string;
  permissions: string[];
  side_effect: string;
  requires_confirmation: boolean;
  parameters: JsonSchema;
}
