import { SSEParser } from "./sse";
import type {
  ApiError,
  AppConfig,
  ChatEvent,
  ChunkOut,
  DocumentOut,
  MetadataSuggestion,
} from "./types";

export class RequestError extends Error {
  constructor(
    public status: number,
    public detail: ApiError,
  ) {
    super(detail.message);
  }
}

async function json<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  const body = await response.json().catch(() => ({}));
  const detail = body.detail;
  // 422 de FastAPI trae una lista de errores; el resto, {code, message}
  const message = Array.isArray(detail)
    ? detail.map((d: { loc: string[]; msg: string }) => `${d.loc.at(-1)}: ${d.msg}`).join(" · ")
    : (detail?.message ?? `Error ${response.status}`);
  throw new RequestError(response.status, { code: detail?.code ?? "error", message });
}

export const api = {
  config: () => fetch("/api/config").then((r) => json<AppConfig>(r)),
  documents: () => fetch("/api/documents").then((r) => json<DocumentOut[]>(r)),
  chunk: (id: string) => fetch(`/api/chunks/${id}`).then((r) => json<ChunkOut>(r)),
  reindex: () =>
    fetch("/api/documents/reindex", { method: "POST" }).then((r) => json<{ requeued: number }>(r)),
  suggest: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch("/api/documents/suggest", { method: "POST", body: form }).then((r) =>
      json<MetadataSuggestion>(r),
    );
  },
  upload: (form: FormData) =>
    fetch("/api/documents", { method: "POST", body: form }).then((r) => json<DocumentOut>(r)),
};

export interface ChatParams {
  question: string;
  carrier: string | null;
  only_current: boolean;
}

/** Envía la pregunta y llama a onEvent por cada evento SSE según llega. */
export async function streamChat(
  params: ChatParams,
  onEvent: (event: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
    signal, // abortar cierra la conexión: el servidor deja de llamar al LLM [F7]
  });
  if (!response.ok || !response.body) await json(response);

  const reader = response.body!.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SSEParser();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    parser.feed(value).forEach(onEvent);
  }
}
