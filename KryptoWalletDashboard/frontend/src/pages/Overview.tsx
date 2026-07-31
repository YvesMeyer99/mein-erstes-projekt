import { useEffect, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { fetchPortfolio } from "../api/client";
import type { PortfolioEntry } from "../api/types";
import { formatChf } from "../lib/format";

const CHART_COLORS = ["#2563eb", "#16a34a", "#dc2626", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];

function Overview() {
  const [entries, setEntries] = useState<PortfolioEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPortfolio()
      .then(setEntries)
      .catch((err: Error) => setError(err.message));
  }, []);

  if (error) {
    return (
      <div className="text-red-600">
        Fehler beim Laden des Portfolios: {error}. Läuft das Backend unter http://127.0.0.1:8000?
      </div>
    );
  }

  if (entries === null) {
    return <div>Portfolio wird geladen…</div>;
  }

  const totalValueChf = entries.reduce((sum, entry) => sum + (entry.value_chf ? Number(entry.value_chf) : 0), 0);
  const chartData = entries
    .filter((entry) => entry.value_chf !== null)
    .map((entry) => ({ name: entry.asset, value: Number(entry.value_chf) }));

  return (
    <div>
      <h2 className="mb-4 text-xl font-semibold">Übersicht</h2>
      <p data-testid="portfolio-total" className="mb-6 text-2xl font-bold">
        {formatChf(totalValueChf.toString())}
      </p>

      <table className="mb-8 w-full text-left text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="py-2">Asset</th>
            <th className="py-2">Menge</th>
            <th className="py-2">Kurs CHF</th>
            <th className="py-2">Wert CHF</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.asset} className="border-b border-gray-100">
              <td className="py-2">{entry.asset}</td>
              <td className="py-2">{entry.amount}</td>
              <td className="py-2">{entry.price_chf === null ? "" : formatChf(entry.price_chf)}</td>
              <td className="py-2">{formatChf(entry.value_chf)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={300}>
          <PieChart>
            <Pie data={chartData} dataKey="value" nameKey="name" outerRadius={100} label>
              {chartData.map((entry, index) => (
                <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(value) => formatChf(String(value))} />
          </PieChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

export default Overview;
