import { useState } from "react";
import { triggerSync } from "../api/client";
import type { SyncResult } from "../api/types";

function SyncPage() {
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<SyncResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSync() {
    setRunning(true);
    setError(null);
    try {
      const response = await triggerSync();
      setResults(response.results);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div>
      <h2 className="mb-4 text-xl font-semibold">Sync</h2>
      <button
        onClick={handleSync}
        disabled={running}
        className="rounded bg-gray-900 px-4 py-2 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
      >
        {running ? "Synchronisiert…" : "Jetzt synchronisieren"}
      </button>

      {error && (
        <p className="mt-4 text-red-600">
          {error}. Läuft das Backend unter http://127.0.0.1:8000?
        </p>
      )}

      {results && (
        <ul className="mt-6 space-y-2">
          {results.map((result) => (
            <li
              key={`${result.source_name}-${result.account_label}`}
              className={result.status === "ok" ? "text-green-700" : "text-red-600"}
            >
              {result.source_name} ({result.account_label}):{" "}
              {result.status === "ok" ? `${result.new_transactions} neue Transaktionen` : result.error}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default SyncPage;
