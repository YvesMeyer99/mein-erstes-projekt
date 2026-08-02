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

export type SyncResult =
  | { source_name: string; account_label: string; status: "ok"; new_transactions: number }
  | { source_name: string; account_label: string; status: "error"; error: string };

export interface SyncResponse {
  results: SyncResult[];
}

export interface ConfigField {
  name: string;
  section: string;
  label: string;
  is_secret: boolean;
  hint: string;
  value: string;
}

export interface ConfigResponse {
  fields: ConfigField[];
}

export interface Account {
  source_name: string;
  account_label: string;
  transaction_count: number;
  last_synced_at: string | null;
  last_error: string | null;
  is_configured: boolean;
}

export interface AccountsResponse {
  accounts: Account[];
}

export interface AccountRef {
  source_name: string;
  account_label: string;
}

export interface DeleteAccountsResult {
  source_name: string;
  account_label: string;
  deleted_transactions: number;
  dry_run: boolean;
}

export interface DeleteAccountsResponse {
  results: DeleteAccountsResult[];
}
