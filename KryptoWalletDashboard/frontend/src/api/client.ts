import type { PortfolioEntry, SyncResponse, Transaction, TransactionFilters } from "./types";

const API_BASE = "http://127.0.0.1:8000";

function buildQuery(filters: TransactionFilters): string {
  const params = new URLSearchParams();
  if (filters.start) params.set("start", filters.start);
  if (filters.end) params.set("end", filters.end);
  if (filters.source_name) params.set("source_name", filters.source_name);
  if (filters.tx_type) params.set("tx_type", filters.tx_type);
  if (filters.account_label) params.set("account_label", filters.account_label);
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function errorDetail(response: Response): Promise<string> {
  const body = await response.json().catch(() => null);
  if (body && typeof body === "object" && "detail" in body) {
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  }
  return String(response.status);
}

export async function fetchPortfolio(): Promise<PortfolioEntry[]> {
  const response = await fetch(`${API_BASE}/api/portfolio`);
  if (!response.ok) {
    throw new Error(`Portfolio-Abfrage fehlgeschlagen: ${await errorDetail(response)}`);
  }
  return response.json();
}

export async function fetchTransactions(filters: TransactionFilters = {}): Promise<Transaction[]> {
  const response = await fetch(`${API_BASE}/api/transactions${buildQuery(filters)}`);
  if (!response.ok) {
    throw new Error(`Transaktions-Abfrage fehlgeschlagen: ${await errorDetail(response)}`);
  }
  return response.json();
}

export function exportUrl(filters: TransactionFilters = {}): string {
  return `${API_BASE}/api/export${buildQuery(filters)}`;
}

export async function triggerSync(): Promise<SyncResponse> {
  const response = await fetch(`${API_BASE}/api/sync`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Sync fehlgeschlagen: ${await errorDetail(response)}`);
  }
  return response.json();
}
