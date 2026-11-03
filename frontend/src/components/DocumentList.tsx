import type { DocumentOut, DocumentStatus } from "../types";

const STATUS: Record<DocumentStatus, { label: string; style: string }> = {
  PENDING: { label: "En cola", style: "bg-slate-200 text-slate-700" },
  PROCESSING: { label: "Procesando", style: "bg-amber-100 text-amber-800" },
  READY: { label: "Listo", style: "bg-emerald-100 text-emerald-800" },
  FAILED: { label: "Error", style: "bg-red-100 text-red-800" },
};

// Códigos de error de ingesta (domain/errors.py) en lenguaje de operaciones
const ERRORS: Record<string, string> = {
  invalid_pdf: "El PDF está dañado o no es válido.",
  no_text_layer: "PDF escaneado sin texto (OCR no disponible).",
  file_missing: "No se encontró el archivo subido.",
  embedding_provider_error: "El servicio de IA no respondió tras varios intentos.",
  embedding_misconfigured: "El servicio de IA está mal configurado.",
  database_unavailable: "La base de datos no estaba disponible.",
};

export function DocumentList({ documents }: { documents: DocumentOut[] }) {
  if (documents.length === 0) {
    return <p className="text-sm text-slate-500">Aún no hay documentos.</p>;
  }
  return (
    <ul className="space-y-2">
      {documents.map((doc) => {
        const status = STATUS[doc.status];
        return (
          <li key={doc.id} className="rounded-lg border border-slate-200 bg-white p-2 text-sm">
            <div className="flex items-start justify-between gap-2">
              <span className="font-medium break-all text-slate-800">{doc.filename}</span>
              <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs ${status.style}`}>
                {status.label}
                {doc.status === "PROCESSING" && doc.attempts > 1 && ` · intento ${doc.attempts}`}
              </span>
            </div>
            <p className="text-xs text-slate-500">
              {doc.carrier} · {doc.contract_code} v{doc.version} ·{" "}
              {doc.status === "READY" && (doc.is_current ? "vigente" : "histórica")}
              {doc.status === "READY" && ` · ${doc.chunk_count} fragmentos`}
            </p>
            {doc.status === "FAILED" && (
              <p className="text-xs text-red-700">{ERRORS[doc.error_code ?? ""] ?? doc.error_code}</p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
