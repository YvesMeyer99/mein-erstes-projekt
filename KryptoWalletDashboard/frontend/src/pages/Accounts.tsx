import { useEffect, useState } from "react";
import { deleteAccounts, fetchAccounts } from "../api/client";
import type { Account } from "../api/types";

function accountKey(account: { source_name: string; account_label: string }): string {
  return `${account.source_name}::${account.account_label}`;
}

function Accounts() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  function load() {
    fetchAccounts()
      .then((response) => setAccounts(response.accounts))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }

  useEffect(load, []);

  function toggle(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  async function handleDelete() {
    if (!accounts) return;
    const toDelete = accounts.filter((a) => selected.has(accountKey(a)));
    if (toDelete.length === 0) return;
    const confirmed = window.confirm(
      `${toDelete.length} Account(s) inkl. aller zugehörigen Transaktionen unwiderruflich löschen?`,
    );
    if (!confirmed) return;

    setDeleting(true);
    setError(null);
    try {
      await deleteAccounts(toDelete.map((a) => ({ source_name: a.source_name, account_label: a.account_label })));
      setSelected(new Set());
      load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(false);
    }
  }

  if (error && accounts === null) {
    return (
      <div className="text-red-600">
        {error}. Läuft das Backend unter http://127.0.0.1:8000?
      </div>
    );
  }

  if (accounts === null) {
    return <div>Accounts werden geladen…</div>;
  }

  return (
    <div>
      <h2 className="mb-4 text-xl font-semibold">Accounts</h2>
      <p className="mb-6 text-sm text-gray-500">
        Löscht Transaktionen und Sync-Status für ausgewählte Accounts unwiderruflich - unabhängig davon,
        ob sie noch in der .env konfiguriert sind.
      </p>

      <table className="mb-4 w-full text-left text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="py-2"></th>
            <th className="py-2">Quelle</th>
            <th className="py-2">Account</th>
            <th className="py-2">Transaktionen</th>
            <th className="py-2">Konfiguriert</th>
            <th className="py-2">Letzter Fehler</th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((account) => {
            const key = accountKey(account);
            return (
              <tr key={key} className="border-b border-gray-100">
                <td className="py-2">
                  <input type="checkbox" checked={selected.has(key)} onChange={() => toggle(key)} />
                </td>
                <td className="py-2">{account.source_name}</td>
                <td className="py-2">{account.account_label}</td>
                <td className="py-2">{account.transaction_count}</td>
                <td className="py-2">{account.is_configured ? "ja" : "nein"}</td>
                <td className="py-2 text-red-600">{account.last_error ?? ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <button
        onClick={handleDelete}
        disabled={selected.size === 0 || deleting}
        className="rounded bg-red-700 px-4 py-2 text-sm text-white hover:bg-red-800 disabled:opacity-50"
      >
        {deleting ? "Löscht…" : "Ausgewählte löschen"}
      </button>

      {error && accounts !== null && <p className="mt-4 text-red-600">{error}</p>}
    </div>
  );
}

export default Accounts;
