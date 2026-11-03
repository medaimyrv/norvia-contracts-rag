import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Ejecuta `load` cada `intervalMs(data)` milisegundos. El intervalo depende de los datos:
 * rápido mientras hay documentos procesándose, lento cuando todo está quieto [R12].
 */
export function usePolling<T>(load: () => Promise<T>, intervalMs: (data: T | null) => number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Refs con la última versión de las funciones: el bucle de polling no se reinicia cada render
  const loadRef = useRef(load);
  const intervalRef = useRef(intervalMs);
  useEffect(() => {
    loadRef.current = load;
    intervalRef.current = intervalMs;
  });

  const refresh = useCallback(async () => {
    try {
      const next = await loadRef.current();
      setData(next);
      setError(null);
      return next;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error de red");
      return null;
    }
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let cancelled = false;
    const tick = async () => {
      const next = await refresh();
      if (!cancelled) timer = setTimeout(tick, intervalRef.current(next));
    };
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [refresh]);

  return { data, error, refresh };
}
