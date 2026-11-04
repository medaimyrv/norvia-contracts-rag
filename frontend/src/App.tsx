import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Chat } from "./components/Chat";
import { DocumentList } from "./components/DocumentList";
import { UploadForm } from "./components/UploadForm";
import { usePolling } from "./hooks/usePolling";
import type { AppConfig, DocumentOut } from "./types";

const busy = (docs: DocumentOut[] | null) =>
  docs?.some((d) => d.status === "PENDING" || d.status === "PROCESSING") ?? false;

/**
 * Layout de aplicación: la raíz mide exactamente la ventana (app-viewport) y solo se desplazan
 * por dentro la lista de documentos y el historial. Así el campo de mensaje siempre está visible.
 */
export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [docsOpen, setDocsOpen] = useState(false); // panel de documentos en móvil
  const [reindexing, setReindexing] = useState(false);
  const loadConfig = useCallback(() => api.config().then(setConfig, () => setConfig(null)), []);

  // Polling: cada 2 s mientras algo se procesa, cada 10 s cuando todo está quieto
  const documents = usePolling(api.documents, (docs) => (busy(docs) ? 2000 : 10000));
  const docs = documents.data ?? [];
  const readyCount = docs.filter((d) => d.status === "READY").length;
  const failedCount = docs.filter((d) => d.status === "FAILED").length;

  // Los transportistas del desplegable cambian cuando un documento pasa a READY
  useEffect(() => {
    loadConfig();
  }, [loadConfig, readyCount]);

  // Reprocesa los documentos vectorizados con otro modelo [D6]
  async function reindex() {
    setReindexing(true);
    try {
      await api.reindex();
      await documents.refresh();
      await loadConfig();
    } finally {
      setReindexing(false);
    }
  }

  useEffect(() => {
    if (!docsOpen) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setDocsOpen(false);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [docsOpen]);

  return (
    <div className="app-viewport flex flex-col overflow-hidden">
      <header className="flex shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-3 py-2">
        <button
          onClick={() => setDocsOpen(true)}
          className="rounded-md border border-slate-300 px-2 py-1 text-sm md:hidden"
          aria-label="Abrir documentos"
        >
          ☰ Documentos ({docs.length})
        </button>
        <span
          aria-hidden
          className="hidden size-7 shrink-0 items-center justify-center rounded-lg bg-brand-700 text-sm font-bold text-white sm:flex"
        >
          N
        </span>
        <h1 className="min-w-0 truncate font-semibold text-slate-900">
          Norvia <span className="font-normal text-slate-500">· Asistente de contratos</span>
        </h1>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {config?.demo_mode && (
            <details className="relative">
              <summary className="cursor-pointer list-none rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900">
                ● Modo demo
              </summary>
              <p className="absolute right-0 z-20 mt-2 w-72 rounded-md border border-amber-200 bg-white p-3 text-xs text-slate-700 shadow-lg">
                Sin modelo de IA real: las respuestas son frases copiadas de los documentos y la
                búsqueda compara palabras, no significados. Añade <code>GEMINI_API_KEY</code> y{" "}
                <code>MODEL_PROVIDER=gemini</code> en <code>.env</code> para respuestas generativas.
              </p>
            </details>
          )}
          {!!config?.stale_documents && (
            <details className="relative">
              <summary className="cursor-pointer list-none rounded-full bg-red-100 px-2.5 py-1 text-xs font-medium text-red-900">
                ⚠ {config.stale_documents} documento{config.stale_documents > 1 ? "s" : ""} por
                actualizar ▾
              </summary>
              <div className="absolute right-0 z-20 mt-2 w-80 space-y-2 rounded-md border border-red-200 bg-white p-3 text-xs text-slate-700 shadow-lg">
                <p>
                  <strong>
                    {config.stale_documents} documento{config.stale_documents > 1 ? "s" : ""}
                  </strong>{" "}
                  se procesaron con otro modelo de IA (por ejemplo, en modo demo) y{" "}
                  <strong>no se usan en las búsquedas</strong>: sus datos no son compatibles con
                  el modelo actual (<code>{config.embedding_model}</code>).
                </p>
                <p>
                  Al actualizarlos se vuelven a procesar con el modelo actual. Tarda alrededor de
                  un minuto.
                </p>
                <button
                  onClick={reindex}
                  disabled={reindexing}
                  className="ml-auto block rounded-md bg-red-800 px-3 py-1.5 font-medium text-white hover:bg-red-900 disabled:opacity-50"
                >
                  {reindexing ? "Actualizando…" : "Actualizar ahora"}
                </button>
              </div>
            </details>
          )}
        </div>
      </header>

      <main className="grid min-h-0 flex-1 md:grid-cols-[300px_1fr]">
        {docsOpen && (
          <div
            className="fixed inset-0 z-20 bg-black/30 md:hidden"
            onClick={() => setDocsOpen(false)}
          />
        )}
        {/* En móvil es un panel lateral superpuesto; en escritorio, una columna con scroll propio */}
        <aside
          className={`${docsOpen ? "flex" : "hidden"} fixed inset-y-0 left-0 z-30 w-80 max-w-[85vw] flex-col gap-3 overflow-y-auto border-r border-slate-200 bg-slate-50 p-3 shadow-xl md:static md:z-auto md:flex md:min-h-0 md:w-auto md:max-w-none md:shadow-none`}
          aria-label="Documentos"
        >
          <button
            onClick={() => setDocsOpen(false)}
            className="self-end text-sm text-slate-500 md:hidden"
            aria-label="Cerrar documentos"
          >
            ✕
          </button>
          <UploadForm carriers={config?.carriers ?? []} onUploaded={documents.refresh} />
          <h2 className="text-sm font-semibold text-slate-800">
            Documentos ({docs.length})
            {failedCount > 0 && <span className="ml-1 text-red-700">· {failedCount} con error</span>}
          </h2>
          {documents.error && <p className="text-sm text-red-700">{documents.error}</p>}
          <DocumentList documents={docs} />
        </aside>
        <div className="flex min-h-0 min-w-0 flex-col">
          <Chat carriers={config?.carriers ?? []} />
        </div>
      </main>
    </div>
  );
}
