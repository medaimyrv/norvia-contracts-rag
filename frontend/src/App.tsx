import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Chat } from "./components/Chat";
import { DocumentList } from "./components/DocumentList";
import { UploadForm } from "./components/UploadForm";
import { usePolling } from "./hooks/usePolling";
import type { AppConfig, DocumentOut } from "./types";

const busy = (docs: DocumentOut[] | null) =>
  docs?.some((d) => d.status === "PENDING" || d.status === "PROCESSING") ?? false;

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const loadConfig = useCallback(() => api.config().then(setConfig, () => setConfig(null)), []);

  // Polling: cada 2 s mientras algo se procesa, cada 10 s cuando todo está quieto
  const documents = usePolling(api.documents, (docs) => (busy(docs) ? 2000 : 10000));
  const readyCount = documents.data?.filter((d) => d.status === "READY").length ?? 0;

  // Los transportistas del desplegable cambian cuando un documento pasa a READY
  useEffect(() => {
    loadConfig();
  }, [loadConfig, readyCount]);

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-3 p-4">
      <header>
        <h1 className="text-xl font-bold text-slate-900">Norvia Freight · Asistente de contratos</h1>
        {config?.demo_mode && (
          <p className="mt-2 rounded-md bg-amber-100 px-3 py-2 text-sm text-amber-900">
            <strong>Modo demostración:</strong> sin modelo de IA real. Las respuestas son frases
            copiadas de los documentos y la búsqueda compara palabras, no significados. Añade{" "}
            <code>GEMINI_API_KEY</code> y <code>MODEL_PROVIDER=gemini</code> en <code>.env</code>{" "}
            para respuestas generativas.
          </p>
        )}
      </header>

      <main className="grid flex-1 gap-3 md:grid-cols-[320px_1fr]">
        <aside className="space-y-3">
          <UploadForm carriers={config?.carriers ?? []} onUploaded={documents.refresh} />
          <h2 className="font-semibold text-slate-800">Documentos</h2>
          {documents.error && <p className="text-sm text-red-700">{documents.error}</p>}
          <DocumentList documents={documents.data ?? []} />
        </aside>
        <div className="min-h-[60vh]">
          <Chat carriers={config?.carriers ?? []} />
        </div>
      </main>
    </div>
  );
}
