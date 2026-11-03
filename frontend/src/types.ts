// Espejo de los modelos Pydantic de la API (SPEC §4)

export type DocumentStatus = "PENDING" | "PROCESSING" | "READY" | "FAILED";

export interface DocumentOut {
  id: string;
  filename: string;
  carrier: string;
  contract_code: string;
  version: number;
  effective_from: string;
  is_current: boolean;
  status: DocumentStatus;
  error_code: string | null;
  attempts: number;
  chunk_count: number;
  duplicate: boolean;
  created_at: string;
  updated_at: string;
}

export interface ChunkOut {
  id: string;
  document_id: string;
  kind: "text" | "table";
  section: string | null;
  page_start: number;
  page_end: number;
  content: string;
}

export interface Citation {
  label: string;
  chunk_id: string;
  document_id: string;
  filename: string;
  carrier: string;
  version: number;
  page_start: number;
  page_end: number;
  snippet: string;
}

export interface AppConfig {
  demo_mode: boolean;
  llm_model: string;
  carriers: string[];
}

export interface ApiError {
  code: string;
  message: string;
}

// Eventos SSE del chat (SPEC §4)
export type ChatEvent =
  | { event: "clarification"; data: { suggestions: string[] } }
  | { event: "retrieval"; data: { k: number; top_score: number; carrier_filter: string | null } }
  | { event: "token"; data: { text: string } }
  | {
      event: "citations";
      data: { citations: Citation[]; confidence: "high" | "medium" | "low"; evidence: boolean };
    }
  | { event: "done"; data: { answer: string } }
  | { event: "error"; data: ApiError };
