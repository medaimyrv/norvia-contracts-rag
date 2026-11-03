import { useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { RequestError, streamChat } from "../api";
import type { ChatEvent, Citation } from "../types";
import { CitationPanel } from "./CitationPanel";

interface Message {
  question: string;
  answer: string;
  status: "streaming" | "done" | "error";
  carrierFilter?: string | null;
  citations?: Citation[];
  confidence?: string;
  evidence?: boolean;
  suggestions?: string[];
  error?: string;
  carrier: string | null;
  onlyCurrent: boolean;
}

const CONFIDENCE: Record<string, string> = { high: "alta", medium: "media", low: "baja" };
const NEAR_BOTTOM_PX = 80; // a menos de esto del final se considera «estoy abajo»

export function Chat({ carriers }: { carriers: string[] }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [carrier, setCarrier] = useState<string>("");
  const [onlyCurrent, setOnlyCurrent] = useState(true);
  const [open, setOpen] = useState<Citation | null>(null);
  const abort = useRef<AbortController | null>(null);
  const busy = messages.at(-1)?.status === "streaming";

  // Seguir el final solo si el usuario ya estaba abajo: si subió a leer, no se le mueve
  const listRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const [showJump, setShowJump] = useState(false);

  function onScroll() {
    const el = listRef.current!;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
    stickRef.current = near;
    setShowJump(!near);
  }

  function scrollToBottom() {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }

  // Tras cada cambio (token nuevo, cita, mensaje), antes de pintar: sin saltos visibles
  useLayoutEffect(() => {
    if (stickRef.current) scrollToBottom();
  }, [messages]);

  function update(index: number, patch: Partial<Message> | ((m: Message) => Partial<Message>)) {
    setMessages((all) =>
      all.map((m, i) => (i === index ? { ...m, ...(typeof patch === "function" ? patch(m) : patch) } : m)),
    );
  }

  async function ask(question: string, chosenCarrier: string | null, current: boolean) {
    const index = messages.length;
    stickRef.current = true; // al preguntar, siempre se baja al final
    setShowJump(false);
    const base = { question, answer: "", carrier: chosenCarrier, onlyCurrent: current };
    setMessages((all) => [...all, { ...base, status: "streaming" }]);
    abort.current = new AbortController();

    const onEvent = (event: ChatEvent) => {
      switch (event.event) {
        case "retrieval":
          return update(index, { carrierFilter: event.data.carrier_filter });
        case "token":
          return update(index, (m) => ({ answer: m.answer + event.data.text }));
        case "citations":
          return update(index, {
            citations: event.data.citations,
            confidence: event.data.confidence,
            evidence: event.data.evidence,
          });
        case "done":
          // La respuesta final sustituye a lo emitido (p. ej. si se degradó a «sin evidencia»)
          return update(index, { answer: event.data.answer, status: "done" });
        case "clarification":
          return update(index, { suggestions: event.data.suggestions, status: "done" });
        case "error":
          return update(index, { error: event.data.message, status: "error" });
      }
    };
    try {
      await streamChat({ question, carrier: chosenCarrier, only_current: current }, onEvent, abort.current.signal);
      update(index, (m) => (m.status === "streaming" ? { status: "done" } : {}));
    } catch (e) {
      if ((e as Error).name === "AbortError") return update(index, { status: "done" });
      const text = e instanceof RequestError ? e.message : "No se pudo contactar con el servidor.";
      update(index, { error: text, status: "error" });
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const field = event.currentTarget.elements.namedItem("question") as HTMLInputElement;
    if (field.value.trim().length < 3) return;
    ask(field.value.trim(), carrier || null, onlyCurrent);
    field.value = "";
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col bg-white">
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-slate-200 px-3 py-2 text-sm">
        <label className="flex items-center gap-1">
          Transportista
          <select
            value={carrier}
            onChange={(e) => setCarrier(e.target.value)}
            className="rounded-md border border-slate-300 px-1 py-1"
          >
            <option value="">Detectar en la pregunta</option>
            {carriers.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={!onlyCurrent} onChange={(e) => setOnlyCurrent(!e.target.checked)} />
          Incluir versiones históricas
        </label>
      </div>

      {/* min-h-0: sin él, un hijo flex crece con su contenido y su scroll nunca se activa */}
      <div className="relative min-h-0 flex-1">
      <div
        ref={listRef}
        onScroll={onScroll}
        className="h-full space-y-4 overflow-y-auto p-3"
        aria-live="polite"
      >
        {messages.length === 0 && (
          <p className="text-sm text-slate-500">
            Pregunta por plazos, tarifas, seguros… Por ejemplo: «¿Cuál es el plazo de reclamación por
            mercancía dañada con Cóndor Andino?»
          </p>
        )}
        {messages.map((m, i) => (
          <article key={i} className="space-y-1">
            <p className="ml-auto w-fit max-w-[85%] rounded-lg bg-slate-800 px-3 py-2 text-sm break-words text-white">
              {m.question}
            </p>
            {m.carrierFilter && (
              <p className="text-xs text-slate-500">Filtrando por: {m.carrierFilter}</p>
            )}
            {m.suggestions ? (
              <div className="text-sm">
                <p className="text-slate-700">¿Quisiste decir…?</p>
                <div className="mt-1 flex flex-wrap gap-2">
                  {m.suggestions.map((s) => (
                    <button
                      key={s}
                      disabled={busy}
                      onClick={() => ask(m.question, s, m.onlyCurrent)}
                      className="rounded-full border border-slate-300 px-3 py-1 hover:bg-slate-100"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="max-w-[90%] rounded-lg bg-slate-100 px-3 py-2 text-sm break-words text-slate-800">
                {renderAnswer(m.answer, m.citations ?? [], setOpen)}
                {m.status === "streaming" && <span className="animate-pulse">▍</span>}
                {m.error && <p className="text-red-700">{m.error}</p>}
                {m.citations && m.citations.length > 0 && (
                  <ul className="mt-2 space-y-1 border-t border-slate-200 pt-2">
                    {m.citations.map((c) => (
                      <li key={c.label}>
                        <button onClick={() => setOpen(c)} className="text-left text-xs text-sky-800 hover:underline">
                          [{c.label}] {c.filename} · v{c.version} · pág.{" "}
                          {c.page_start === c.page_end ? c.page_start : `${c.page_start}–${c.page_end}`}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {m.confidence && m.evidence && (
                  <p className="mt-1 text-xs text-slate-500">Confianza: {CONFIDENCE[m.confidence]}</p>
                )}
              </div>
            )}
          </article>
        ))}
      </div>
      {showJump && (
        <button
          onClick={() => {
            stickRef.current = true;
            setShowJump(false);
            scrollToBottom();
          }}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-slate-800 px-3 py-1 text-xs text-white shadow"
        >
          ↓ Ir al último
        </button>
      )}
      </div>

      <form onSubmit={submit} className="flex shrink-0 gap-2 border-t border-slate-200 p-3">
        <input
          name="question"
          placeholder="Escribe tu pregunta…"
          maxLength={1000}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        {busy ? (
          <button type="button" onClick={() => abort.current?.abort()} className="rounded-md border px-3 text-sm">
            Detener
          </button>
        ) : (
          <button className="rounded-md bg-slate-800 px-4 text-sm font-medium text-white">Preguntar</button>
        )}
      </form>
      {open && <CitationPanel citation={open} onClose={() => setOpen(null)} />}
    </section>
  );
}

/** Convierte los marcadores [c1] del texto en botones que abren la cita. */
function renderAnswer(text: string, citations: Citation[], open: (c: Citation) => void): ReactNode[] {
  return text.split(/(\[c\d+\])/g).map((part, i) => {
    const citation = citations.find((c) => `[${c.label}]` === part);
    return citation ? (
      <button key={i} onClick={() => open(citation)} className="mx-0.5 align-super text-xs text-sky-800 hover:underline">
        {part}
      </button>
    ) : (
      <span key={i} className="whitespace-pre-wrap">
        {part}
      </span>
    );
  });
}
