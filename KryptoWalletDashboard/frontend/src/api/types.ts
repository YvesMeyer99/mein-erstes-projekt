export interface PortfolioEntry {
  asset: string;
  amount: string;
  price_chf: string | null;
  value_chf: string | null;
}

export interface Transaction {
  id: number;
  timestamp: string;
  source_type: string;
  source_name: string;
  account_label: string;
  tx_type: string;
  asset: string;
  amount: string;
  counter_asset: string | null;
  counter_amount: string | null;
  price_chf: string | null;
  value_chf: string | null;
  fee_amount: string | null;
  fee_asset: string | null;
  external_id: string;
}

export interface TransactionFilters {
  start?: string;
  end?: string;
  source_name?: string;
  tx_type?: string;
  account_label?: string;
}

export interface SyncResult {
  source_name: string;
  account_label: string;
  status: "ok" | "error";
  new_transactions?: number;
  error?: string;
}

export interface SyncResponse {
  results: SyncResult[];
}
