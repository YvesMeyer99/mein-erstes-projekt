import { afterEach, describe, expect, it, vi } from "vitest";
import { exportUrl, fetchPortfolio, fetchTransactions, triggerSync } from "./client";

function mockFetchOnce(body: unknown, ok = true, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok,
      status,
      json: () => Promise.resolve(body),
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchPortfolio", () => {
  it("returns the parsed JSON body on success", async () => {
    mockFetchOnce([{ asset: "BTC", amount: "1", price_chf: "50000", value_chf: "50000" }]);

    const result = await fetchPortfolio();

    expect(result).toEqual([{ asset: "BTC", amount: "1", price_chf: "50000", value_chf: "50000" }]);
  });

  it("throws when the response is not ok", async () => {
    mockFetchOnce(null, false, 500);

    await expect(fetchPortfolio()).rejects.toThrow();
  });

  it("includes the backend's error detail in the thrown message", async () => {
    mockFetchOnce({ detail: "Ungültiger Datumsbereich" }, false, 422);

    await expect(fetchPortfolio()).rejects.toThrow(/Ungültiger Datumsbereich/);
  });
});

describe("fetchTransactions", () => {
  it("builds a query string from the given filters", async () => {
    mockFetchOnce([]);

    await fetchTransactions({ source_name: "binance", tx_type: "swap" });

    const calledUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(calledUrl).toContain("source_name=binance");
    expect(calledUrl).toContain("tx_type=swap");
  });

  it("omits the query string entirely when no filters are given", async () => {
    mockFetchOnce([]);

    await fetchTransactions();

    const calledUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(calledUrl).not.toContain("?");
  });

  it("omits filter keys whose value is undefined", async () => {
    mockFetchOnce([]);

    await fetchTransactions({ source_name: "binance", tx_type: undefined });

    const calledUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(calledUrl).toContain("source_name=binance");
    expect(calledUrl).not.toContain("tx_type");
  });

  it("includes the backend's error detail in the thrown message", async () => {
    mockFetchOnce({ detail: "Ungültiger Datumsbereich" }, false, 422);

    await expect(fetchTransactions()).rejects.toThrow(/Ungültiger Datumsbereich/);
  });
});

describe("exportUrl", () => {
  it("includes given filters in the URL", () => {
    const url = exportUrl({ start: "2024-01-01", account_label: "main" });

    expect(url).toContain("/api/export?");
    expect(url).toContain("start=2024-01-01");
    expect(url).toContain("account_label=main");
  });

  it("has no query string when no filters are given", () => {
    const url = exportUrl();

    expect(url).toBe("http://127.0.0.1:8000/api/export");
  });
});

describe("triggerSync", () => {
  it("POSTs to /api/sync and returns the parsed results", async () => {
    mockFetchOnce({
      results: [{ source_name: "bitcoin", account_label: "main", status: "ok", new_transactions: 3 }],
    });

    const result = await triggerSync();

    expect(result.results[0].status).toBe("ok");
    const [url, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/api/sync");
    expect(options.method).toBe("POST");
  });

  it("throws when the response is not ok", async () => {
    mockFetchOnce(null, false, 500);

    await expect(triggerSync()).rejects.toThrow();
  });

  it("includes the backend's error detail in the thrown message", async () => {
    mockFetchOnce({ detail: "Ungültiger Datumsbereich" }, false, 422);

    await expect(triggerSync()).rejects.toThrow(/Ungültiger Datumsbereich/);
  });
});

import { deleteAccounts, fetchAccounts, fetchConfig, saveConfig } from "./client";

describe("fetchConfig", () => {
  it("returns the parsed fields array", async () => {
    mockFetchOnce({
      fields: [
        { name: "SOLANA_ADDRESSES", section: "Solana", label: "Adressen", is_secret: false, hint: "", value: "main:abc" },
      ],
    });

    const result = await fetchConfig();

    expect(result.fields[0].name).toBe("SOLANA_ADDRESSES");
  });

  it("throws when the response is not ok", async () => {
    mockFetchOnce(null, false, 500);

    await expect(fetchConfig()).rejects.toThrow();
  });
});

describe("saveConfig", () => {
  it("POSTs the given field values as JSON", async () => {
    mockFetchOnce({ status: "ok" });

    await saveConfig({ SOLANA_ADDRESSES: "main:new" });

    const [url, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/api/config");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ SOLANA_ADDRESSES: "main:new" });
  });

  it("throws when the response is not ok", async () => {
    mockFetchOnce(null, false, 500);

    await expect(saveConfig({})).rejects.toThrow();
  });
});

describe("fetchAccounts", () => {
  it("returns the parsed accounts array", async () => {
    mockFetchOnce({
      accounts: [
        {
          source_name: "bitcoin",
          account_label: "ledger",
          transaction_count: 3,
          last_synced_at: null,
          last_error: null,
          is_configured: true,
        },
      ],
    });

    const result = await fetchAccounts();

    expect(result.accounts[0].source_name).toBe("bitcoin");
  });

  it("throws when the response is not ok", async () => {
    mockFetchOnce(null, false, 500);

    await expect(fetchAccounts()).rejects.toThrow();
  });
});

describe("deleteAccounts", () => {
  it("POSTs the given account refs and returns the results", async () => {
    mockFetchOnce({
      results: [{ source_name: "bitcoin", account_label: "ledger", deleted_transactions: 3, dry_run: false }],
    });

    const result = await deleteAccounts([{ source_name: "bitcoin", account_label: "ledger" }]);

    expect(result.results[0].deleted_transactions).toBe(3);
    const [url, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/api/accounts/delete");
    expect(JSON.parse(options.body)).toEqual({ accounts: [{ source_name: "bitcoin", account_label: "ledger" }] });
  });

  it("throws when the response is not ok", async () => {
    mockFetchOnce(null, false, 500);

    await expect(deleteAccounts([])).rejects.toThrow();
  });
});
