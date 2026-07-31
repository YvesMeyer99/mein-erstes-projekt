import { useEffect, useMemo, useState } from "react";
import { exportUrl, fetchTransactions } from "../api/client";
import type { Transaction, TransactionFilters } from "../api/types";
import { formatChf } from "../lib/format";

function Transactions() {
  const [allTransactions, setAllTransactions] = useState<Transaction[] | null>(null);
  const [displayedTransactions, setDisplayedTransactions] = useState<Transaction[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<TransactionFilters>({});

  // One unfiltered fetch, used only to derive the filter dropdowns' option lists.
  useEffect(() => {
    fetchTransactions()
      .then(setAllTransactions)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  // Re-fetch from the backend with the current filters applied whenever they change.
  useEffect(() => {
    fetchTransactions(filters)
      .then(setDisplayedTransactions)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [filters]);

  const sourceOptions = useMemo(
    () => Array.from(new Set((allTransactions ?? []).map((tx) => tx.source_name))).sort(),
    [allTransactions],
  );
  const txTypeOptions = useMemo(
    () => Array.from(new Set((allTransactions ?? []).map((tx) => tx.tx_type))).sort(),
    [allTransactions],
  );
  const accountOptions = useMemo(
    () => Array.from(new Set((allTransactions ?? []).map((tx) => tx.account_label))).sort(),
    [allTransactions],
  );

  function updateFilter(key: keyof TransactionFilters, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value || undefined }));
  }

  if (error) {
    return (
      <div className="text-red-600">
        {error}. Läuft das Backend unter http://127.0.0.1:8000?
      </div>
    );
  }

  if (displayedTransactions === null) {
    return <div>Transaktionen werden geladen…</div>;
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-xl font-semibold">Transaktionen</h2>
        <a
          href={exportUrl(filters)}
          className="rounded bg-gray-900 px-4 py-2 text-sm text-white hover:bg-gray-700"
        >
          CSV exportieren
        </a>
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        <input
          type="date"
          aria-label="Von"
          onChange={(e) => updateFilter("start", e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
        />
        <input
          type="date"
          aria-label="Bis"
          onChange={(e) => updateFilter("end", e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
        />
        <select
          aria-label="Quelle"
          onChange={(e) => updateFilter("source_name", e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
        >
          <option value="">Alle Quellen</option>
          {sourceOptions.map((source) => (
            <option key={source} value={source}>
              {source}
            </option>
          ))}
        </select>
        <select
          aria-label="Typ"
          onChange={(e) => updateFilter("tx_type", e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
        >
          <option value="">Alle Typen</option>
          {txTypeOptions.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
        <select
          aria-label="Konto"
          onChange={(e) => updateFilter("account_label", e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
        >
          <option value="">Alle Konten</option>
          {accountOptions.map((account) => (
            <option key={account} value={account}>
              {account}
            </option>
          ))}
        </select>
      </div>

      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="py-2">Datum</th>
            <th className="py-2">Quelle</th>
            <th className="py-2">Konto</th>
            <th className="py-2">Typ</th>
            <th className="py-2">Asset</th>
            <th className="py-2">Menge</th>
            <th className="py-2">Wert CHF</th>
          </tr>
        </thead>
        <tbody>
          {displayedTransactions.map((tx) => (
            <tr key={tx.id} className="border-b border-gray-100">
              <td className="py-2">{new Date(tx.timestamp).toLocaleDateString("de-CH")}</td>
              <td className="py-2">{tx.source_name}</td>
              <td className="py-2">{tx.account_label}</td>
              <td className="py-2">{tx.tx_type}</td>
              <td className="py-2">{tx.asset}</td>
              <td className="py-2">{tx.amount}</td>
              <td className="py-2">{formatChf(tx.value_chf)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default Transactions;
