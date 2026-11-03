import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { api, RequestError } from "../api";

interface Props {
  carriers: string[];
  onUploaded: () => void;
}

// Color de texto explícito: un campo dentro de un <label> heredaría el gris claro de la etiqueta
const input = "w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm text-slate-900";

/** Subida de PDF con los metadatos que exige D3 (transportista, código, versión, vigencia). */
export function UploadForm({ carriers, onUploaded }: Props) {
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [sending, setSending] = useState(false);
  const [hint, setHint] = useState<{ ok: boolean; text: string } | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  /** Al elegir el PDF, la API lee la portada y propone los datos; el usuario los revisa [D19]. */
  async function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    setMessage(null);
    if (!file) return setHint(null);
    setHint({ ok: true, text: "Leyendo la portada del PDF…" });
    try {
      const s = await api.suggest(file);
      const fields = formRef.current!.elements;
      // Lo no detectado se vacía: no deben quedar datos de un archivo elegido antes
      const set = (name: string, value: string | number | null) => {
        (fields.namedItem(name) as HTMLInputElement).value = value === null ? "" : String(value);
      };
      set("carrier", s.carrier);
      set("contract_code", s.contract_code);
      set("version", s.version);
      set("effective_from", s.effective_from);
      if (s.warning) setHint({ ok: false, text: s.warning });
      else
        setHint({
          ok: true,
          text: `Datos detectados en la portada${s.known_carrier ? " (transportista ya registrado)" : ""}: revísalos antes de subir.`,
        });
    } catch (e) {
      setHint({ ok: false, text: e instanceof RequestError ? e.message : "No se pudo leer el PDF." });
    }
  }

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
      setHint(null);
      onUploaded();
    } catch (e) {
      const text = e instanceof RequestError ? e.message : "No se pudo subir el archivo.";
      setMessage({ ok: false, text });
    } finally {
      setSending(false);
    }
  }

  // Plegable (<details> nativo: accesible con teclado) para que la lista de documentos se vea.
  // shrink-0: en la columna flex de altura fija, overflow-hidden permitiría aplastar la tarjeta
  // hasta ocultar el formulario; así nunca se encoge y, si falta sitio, se desplaza la columna
  return (
    <details className="group shrink-0 overflow-hidden rounded-lg border border-brand-600/30 bg-white">
      {/* Cabecera bien visible: icono verde (+/−) y flecha que gira, para que se note que se despliega */}
      <summary className="flex cursor-pointer list-none items-center gap-2 bg-brand-50 px-3 py-2 text-sm font-semibold text-brand-800 hover:bg-brand-100">
        <span
          aria-hidden
          className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand-700 text-base leading-none text-white"
        >
          <span className="group-open:hidden">+</span>
          <span className="hidden group-open:inline">−</span>
        </span>
        Subir contrato
        <svg
          aria-hidden
          viewBox="0 0 24 24"
          className="ml-auto size-4 transition-transform group-open:rotate-180"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </summary>
    <form ref={formRef} onSubmit={submit} className="space-y-2 px-3 pt-2 pb-3">
      {/* w-full: el control nativo (botón + nombre) no debe salirse de la columna en ningún navegador */}
      <input
        name="file"
        type="file"
        accept="application/pdf,.pdf"
        required
        onChange={onFileChange}
        className="block w-full min-w-0 text-sm text-slate-600 file:mr-2 file:rounded-md file:border-0 file:bg-slate-200 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-slate-800 hover:file:bg-slate-300"
      />
      {hint && (
        <p className={`text-xs ${hint.ok ? "text-slate-500" : "text-amber-700"}`}>{hint.text}</p>
      )}
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
      <label className="block">
        <span className="text-xs text-slate-500">Vigente desde</span>
        <input name="effective_from" type="date" required className={input} />
      </label>
      <button
        disabled={sending}
        className="w-full rounded-md bg-brand-700 py-1.5 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-50"
      >
        {sending ? "Subiendo…" : "Subir"}
      </button>
      {message && (
        <p className={`text-sm ${message.ok ? "text-emerald-700" : "text-red-700"}`}>
          {message.text}
        </p>
      )}
    </form>
    </details>
  );
}
