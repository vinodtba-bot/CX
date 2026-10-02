import { useCallback, useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { ApiError, adminFetch } from "@/lib/api";

export function useAdminQuery<T>(path: string) {
  const { onAuthError } = useOutletContext<{ onAuthError: () => void }>();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await adminFetch<T>(path));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onAuthError();
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [path, onAuthError]);

  useEffect(() => { load(); }, [load]);
  return { data, error, loading, reload: load };
}
