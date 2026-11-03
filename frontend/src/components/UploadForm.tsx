import { useState, type FormEvent } from "react";
import { api, RequestError } from "../api";

interface Props {
  carriers: string[];
  onUploaded: () => void;
}

const input = "w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm";

/** Subida de PDF con los metadatos que exige D3 (transportista, código, versión, vigencia). */
export function UploadForm({ carriers, onUploaded }: Props) {
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setSending(true);
    setMessage(null);
    try {
      const doc = await api.upload(new FormData(form));
      setMessage({
        ok: true,
        text: doc.duplicate ? "Ese archivo ya estaba registrado." : "Recibido: procesando…",
      });
      form.reset();
      onUploaded();
    } catch (e) {
      const text = e instanceof RequestError ? e.message : "No se pudo subir el archivo.";
      setMessage({ ok: false, text });
    } finally {
      setSending(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
      <h2 className="font-semibold text-slate-800">Subir contrato</h2>
      <input name="file" type="file" accept="application/pdf,.pdf" required className="text-sm" />
      <input name="carrier" list="carriers" placeholder="Transportista" required className={input} />
      <datalist id="carriers">
        {carriers.map((c) => (
          <option key={c} value={c} />
        ))}
      </datalist>
      <div className="grid grid-cols-2 gap-2">
        <input name="contract_code" placeholder="Código (CA-2025)" required className={input} />
        <input name="version" type="number" min={1} placeholder="Versión" required className={input} />
      </div>
      <label className="block text-xs text-slate-500">
        Vigente desde
        <input name="effective_from" type="date" required className={input} />
      </label>
      <button
        disabled={sending}
        className="w-full rounded-md bg-slate-800 py-1.5 text-sm font-medium text-white disabled:opacity-50"
      >
        {sending ? "Subiendo…" : "Subir"}
      </button>
      {message && (
        <p className={`text-sm ${message.ok ? "text-emerald-700" : "text-red-700"}`}>
          {message.text}
        </p>
      )}
    </form>
  );
}
