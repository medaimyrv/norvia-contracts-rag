import {
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
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

const CONFIDENCE: Record<string, { label: string; style: string }> = {
  high: { label: "Confianza alta", style: "bg-emerald-50 text-emerald-800" },
  medium: { label: "Confianza media", style: "bg-amber-50 text-amber-800" },
  low: { label: "Confianza baja", style: "bg-slate-100 text-slate-600" },
};
const EXAMPLES = [
  "¿Cuál es el plazo de reclamación por mercancía dañada con Cóndor Andino?",
  "¿Cuánto cuesta un envío de 5000 kg de Sevilla a Málaga con Vientos del Sur?",
  "¿Qué cobertura de seguro tiene Mareas del Pacífico?",
];
const NEAR_BOTTOM_PX = 80; // a menos de esto del final se considera «estoy abajo»
const MAX_INPUT_PX = 140; // el campo crece hasta ~5 líneas

export function Chat({ carriers }: { carriers: string[] }) {
  const [messages, setMessages] = useState<Message[]>([]);
  // Transportista escrito con sugerencias: solo filtra si coincide con uno existente
  const [carrierText, setCarrierText] = useState("");
  const carrier = matchCarrier(carrierText, carriers);
  const [typingCarrier, setTypingCarrier] = useState(false);
  // El aviso no sale mientras se escribe («Mar…» aún no es un nombre), sino al salir del campo
  const unknownCarrier = !typingCarrier && carrierText.trim() !== "" && carrier === null;
  const [onlyCurrent, setOnlyCurrent] = useState(true);
  const [draft, setDraft] = useState(""); // controlado: abrir una cita no borra el borrador
  const [open, setOpen] = useState<Citation | null>(null);
  const abort = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
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
      all.map((m, i) =>
        i === index ? { ...m, ...(typeof patch === "function" ? patch(m) : patch) } : m,
      ),
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
      await streamChat(
        { question, carrier: chosenCarrier, only_current: current },
        onEvent,
        abort.current.signal,
      );
      update(index, (m) => (m.status === "streaming" ? { status: "done" } : {}));
    } catch (e) {
      if ((e as Error).name === "AbortError") return update(index, { status: "done" });
      const text = e instanceof RequestError ? e.message : "No se pudo contactar con el servidor.";
      update(index, { error: text, status: "error" });
    }
  }

  function resize() {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_INPUT_PX)}px`;
  }

  function send() {
    const question = draft.trim();
    if (question.length < 3 || busy) return;
    ask(question, carrier, onlyCurrent);
    setDraft("");
    requestAnimationFrame(resize);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    send();
  }

  // Enter envía; Mayús+Enter salta de línea (convención de los asistentes conversacionales)
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  }

  // El historial vive en el navegador: empezar de nuevo es vaciarlo (y cortar si hay streaming)
  function newConversation() {
    abort.current?.abort();
    setMessages([]);
    setShowJump(false);
    stickRef.current = true;
  }

  function fillExample(text: string) {
    setDraft(text);
    requestAnimationFrame(() => {
      resize();
      inputRef.current?.focus();
    });
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col bg-white">
      <div className="shrink-0 bg-brand-700 px-4 py-3 text-white">
        <div className="mx-auto flex max-w-3xl items-center gap-3">
          <Avatar size="lg" inverted />
          <div className="min-w-0 flex-1">
            <h2 className="font-semibold leading-tight">Asistente de contratos</h2>
            {/* Contexto activo: en qué contratos se va a buscar */}
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-brand-100">
              <label
                className="flex items-center gap-1.5"
                title="Vacío: automático (si la pregunta nombra a un transportista, se busca solo en sus contratos). Escribe parte de un nombre y elige uno para fijarlo sin nombrarlo en cada pregunta."
              >
                Buscando en
                <span className="relative flex items-center">
                  <input
                    value={carrierText}
                    onChange={(e) => setCarrierText(e.target.value)}
                    onFocus={() => setTypingCarrier(true)}
                    onBlur={() => setTypingCarrier(false)}
                    list="chat-carriers"
                    placeholder="Automático · escribe un transportista"
                    aria-label="Transportista"
                    aria-invalid={unknownCarrier}
                    className="w-60 rounded-full border-0 bg-white/15 py-0.5 pr-6 pl-2.5 text-xs text-white placeholder:text-brand-100/80"
                  />
                  {carrierText && (
                    <button
                      type="button"
                      onClick={() => setCarrierText("")}
                      className="absolute right-1.5 text-brand-100 hover:text-white"
                      aria-label="Volver a automático"
                      title="Volver a automático"
                    >
                      ✕
                    </button>
                  )}
                </span>
                <datalist id="chat-carriers">
                  {carriers.map((c) => (
                    <option key={c} value={c} />
                  ))}
                </datalist>
              </label>
              <label
                className="flex items-center gap-1.5"
                title="Por defecto solo se busca en la versión vigente de cada contrato. Márcalo para consultar también versiones anteriores (p. ej. una reclamación de un envío antiguo); si se contradicen, la respuesta lo indica."
              >
                <input
                  type="checkbox"
                  checked={!onlyCurrent}
                  onChange={(e) => setOnlyCurrent(!e.target.checked)}
                  className="accent-white"
                />
                También versiones anteriores del contrato
              </label>
            </div>
            {unknownCarrier && (
              <p className="mt-1 text-xs text-amber-200" role="status">
                No hay contratos de «{carrierText.trim()}»: se buscará en automático.
              </p>
            )}
          </div>
          {messages.length > 0 && (
            <button
              onClick={newConversation}
              className="shrink-0 rounded-full border border-white/40 px-3 py-1 text-xs font-medium hover:bg-white/10"
            >
              Nueva conversación
            </button>
          )}
        </div>
      </div>

      {/* min-h-0: sin él, un hijo flex crece con su contenido y su scroll nunca se activa */}
      <div className="relative min-h-0 flex-1">
        <div
          ref={listRef}
          onScroll={onScroll}
          className="h-full overflow-y-auto bg-slate-50/60 px-4 py-5"
          aria-live="polite"
        >
          <div className="mx-auto max-w-3xl space-y-6">
            <Welcome examples={messages.length === 0} onExample={fillExample} />
            {messages.map((m, i) => (
              <article key={i} className="space-y-3">
                <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-brand-700 px-4 py-2.5 text-sm break-words whitespace-pre-wrap text-white">
                  {m.question}
                </p>
                <div className="flex gap-3">
                  <Avatar />
                  <div className="min-w-0 flex-1 space-y-2">
                    {m.carrierFilter && (
                      <span className="inline-block rounded-full bg-brand-50 px-2 py-0.5 text-xs text-brand-800">
                        Filtrando por: {m.carrierFilter}
                      </span>
                    )}
                    <AssistantMessage
                      message={m}
                      busy={busy}
                      onCite={setOpen}
                      onSuggestion={(s) => ask(m.question, s, m.onlyCurrent)}
                    />
                  </div>
                </div>
              </article>
            ))}
          </div>
        </div>
        {showJump && (
          <button
            onClick={() => {
              stickRef.current = true;
              setShowJump(false);
              scrollToBottom();
            }}
            className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-md"
          >
            ↓ Ir al último
          </button>
        )}
      </div>

      <form onSubmit={submit} className="shrink-0 border-t border-slate-200 bg-white px-4 py-3">
        <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-full border border-slate-300 bg-white py-1.5 pr-1.5 pl-3 focus-within:border-brand-600">
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              resize();
            }}
            onKeyDown={onKeyDown}
            rows={1}
            maxLength={1000}
            placeholder="Pregunta sobre plazos, tarifas, seguros…"
            aria-label="Pregunta"
            className="max-h-36 min-h-8 flex-1 resize-none bg-transparent py-1.5 text-sm text-slate-900 outline-none placeholder:text-slate-400"
          />
          {busy ? (
            <button
              type="button"
              onClick={() => abort.current?.abort()}
              className="flex size-9 shrink-0 items-center justify-center rounded-full border border-slate-300 text-slate-700 hover:bg-slate-50"
              aria-label="Detener la respuesta"
              title="Detener"
            >
              <span className="size-3 rounded-sm bg-current" />
            </button>
          ) : (
            <button
              disabled={draft.trim().length < 3}
              className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-700 text-white hover:bg-brand-800 disabled:opacity-30"
              aria-label="Enviar pregunta"
              title="Enviar"
            >
              <SendIcon />
            </button>
          )}
        </div>
        <p className="mx-auto mt-1 max-w-3xl px-1 text-[11px] text-slate-400">
          Enter para enviar · Mayús+Enter para salto de línea · Las respuestas citan su fuente
        </p>
      </form>
      {open && <CitationPanel citation={open} onClose={() => setOpen(null)} />}
    </section>
  );
}

const plain = (text: string) =>
  text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().trim();

/** El texto escrito corresponde a un transportista existente (sin mayúsculas ni tildes)? */
function matchCarrier(text: string, carriers: string[]): string | null {
  const wanted = plain(text);
  return wanted ? (carriers.find((c) => plain(c) === wanted) ?? null) : null;
}

/** Avatar del asistente: documento con marca de verificación (SVG propio, sin dependencias). */
function Avatar({ size = "md", inverted = false }: { size?: "md" | "lg"; inverted?: boolean }) {
  return (
    <span
      aria-hidden
      className={`flex shrink-0 items-center justify-center rounded-full ${
        size === "lg" ? "size-10" : "size-8"
      } ${inverted ? "bg-white text-brand-700" : "bg-brand-100 text-brand-800"}`}
    >
      <svg viewBox="0 0 24 24" className="size-1/2" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
        <path d="M14 3v5h5M9 14l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2.2">
      <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** El asistente habla primero: qué hace y cómo. Las preguntas de ejemplo solo al empezar. */
function Welcome({ examples, onExample }: { examples: boolean; onExample: (t: string) => void }) {
  return (
    <div className="flex gap-3">
      <Avatar />
      <div className="min-w-0 flex-1 space-y-3">
        <div className="w-fit max-w-[90%] rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-4 py-3 text-sm leading-relaxed text-slate-800">
          ¡Hola! Soy el asistente de contratos de Norvia. Pregúntame por plazos, tarifas, seguros
          o cualquier cláusula: responderé citando el documento, la versión y la página. Si los
          contratos no lo dicen, te lo diré.
        </div>
        {examples && (
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                onClick={() => onExample(example)}
                className="rounded-full border border-brand-600/40 bg-white px-3 py-1.5 text-left text-xs text-brand-800 hover:bg-brand-50"
              >
                {example}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

interface AssistantProps {
  message: Message;
  busy: boolean;
  onCite: (c: Citation) => void;
  onSuggestion: (carrier: string) => void;
}

/** Cada estado tiene su forma: buscando, respuesta, sin evidencia, aclaración y error. */
function AssistantMessage({ message: m, busy, onCite, onSuggestion }: AssistantProps) {
  if (m.suggestions) {
    return (
      <div className="rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-4 py-3 text-sm">
        <p className="font-medium text-slate-800">¿Quisiste decir…?</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {m.suggestions.map((s) => (
            <button
              key={s}
              disabled={busy}
              onClick={() => onSuggestion(s)}
              className="rounded-full border border-brand-600 px-3 py-1 text-brand-800 hover:bg-brand-50 disabled:opacity-40"
            >
              {s}
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (m.status === "error") {
    return (
      <div className="rounded-2xl rounded-tl-sm border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
        <p className="font-medium">No se pudo responder</p>
        <p className="mt-0.5">{m.error}</p>
      </div>
    );
  }

  if (m.status === "streaming" && !m.answer) {
    return (
      <p className="flex items-center gap-2 px-1 py-2 text-sm text-slate-500">
        <span className="size-2 animate-pulse rounded-full bg-brand-600" />
        Buscando en los contratos…
      </p>
    );
  }

  const noEvidence = m.status === "done" && m.evidence === false;
  return (
    <div
      className={`rounded-2xl rounded-tl-sm border px-4 py-3 text-sm leading-relaxed break-words ${
        noEvidence
          ? "border-amber-200 bg-amber-50 text-amber-950"
          : "border-slate-200 bg-white text-slate-800"
      }`}
    >
      {noEvidence && <p className="mb-1 font-medium">⚠ Sin evidencia en los contratos</p>}
      {renderAnswer(m.answer, m.citations ?? [], onCite)}
      {m.status === "streaming" && <span className="ml-0.5 animate-pulse text-brand-700">▍</span>}

      {!!m.citations?.length && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
          {m.citations.map((c) => (
            <button
              key={c.label}
              onClick={() => onCite(c)}
              className="max-w-full truncate rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-left text-xs text-slate-700 hover:border-brand-600 hover:bg-brand-50"
              title="Ver el fragmento original"
            >
              <span className="font-semibold text-brand-800">{c.label}</span> · {c.filename} · v
              {c.version} · pág.{" "}
              {c.page_start === c.page_end ? c.page_start : `${c.page_start}–${c.page_end}`}
            </button>
          ))}
        </div>
      )}
      {m.confidence && m.evidence && (
        <span
          className={`mt-2 inline-block rounded-full px-2 py-0.5 text-xs ${CONFIDENCE[m.confidence].style}`}
        >
          {CONFIDENCE[m.confidence].label}
        </span>
      )}
    </div>
  );
}

/** Convierte los marcadores [c1] del texto en botones que abren la cita. */
function renderAnswer(
  text: string,
  citations: Citation[],
  open: (c: Citation) => void,
): ReactNode[] {
  return text.split(/(\[c\d+\])/g).map((part, i) => {
    const citation = citations.find((c) => `[${c.label}]` === part);
    return citation ? (
      <button
        key={i}
        onClick={() => open(citation)}
        className="mx-0.5 rounded bg-brand-50 px-1 align-super text-[10px] font-semibold text-brand-800 hover:bg-brand-100"
        aria-label={`Ver fuente ${citation.label}`}
      >
        {citation.label}
      </button>
    ) : (
      <span key={i} className="whitespace-pre-wrap">
        {part}
      </span>
    );
  });
}
