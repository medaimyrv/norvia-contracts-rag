import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ChunkOut, Citation } from "../types";

/** Muestra el fragmento original citado: documento, versión y páginas [R12]. */
export function CitationPanel({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const [chunk, setChunk] = useState<ChunkOut | null>(null);
  const [error, setError] = useState(false);

  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    api.chunk(citation.chunk_id).then(setChunk, () => setError(true));
  }, [citation.chunk_id]);

  // onClose cambia en cada render del chat (cada token): se guarda en un ref para que el efecto
  // de foco se ejecute una sola vez al abrir y no le robe el foco al usuario durante el streaming
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  // Teclado: el foco entra en el diálogo, Escape lo cierra y el foco vuelve a la cita pulsada
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCloseRef.current();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, []);

  const pages =
    citation.page_start === citation.page_end
      ? `página ${citation.page_start}`
      : `páginas ${citation.page_start}–${citation.page_end}`;

  return (
    <div
      className="fixed inset-0 z-10 flex items-end justify-center bg-black/30 p-4 sm:items-center"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-full max-w-2xl overflow-auto rounded-lg bg-white p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Fragmento citado ${citation.label}`}
      >
        <div className="mb-2 flex items-start justify-between gap-2">
          <div>
            <p className="font-semibold text-slate-800">
              [{citation.label}] {citation.filename}
            </p>
            <p className="text-xs text-slate-500">
              {citation.carrier} · versión {citation.version} · {pages}
              {chunk?.section && ` · ${chunk.section}`}
            </p>
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            className="text-slate-500 hover:text-slate-800"
            aria-label="Cerrar"
          >
            ✕
          </button>
        </div>
        {error && <p className="text-sm text-red-700">No se pudo cargar el fragmento.</p>}
        {!chunk && !error && <p className="text-sm text-slate-500">Cargando…</p>}
        {chunk && (
          <pre className="text-sm break-words whitespace-pre-wrap text-slate-700">{chunk.content}</pre>
        )}
      </div>
    </div>
  );
}
