import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import type { Transaction } from "../api/types";
import Transactions from "./Transactions";

const SAMPLE: Transaction[] = [
  {
    id: 1,
    timestamp: "2024-01-15T00:00:00Z",
    source_type: "exchange",
    source_name: "binance",
    account_label: "binance-main",
    tx_type: "swap",
    asset: "BTC",
    amount: "0.5",
    counter_asset: "USDT",
    counter_amount: "25000",
    price_chf: "50000",
    value_chf: "25000",
    fee_amount: null,
    fee_asset: null,
    external_id: "trade-1",
  },
  {
    id: 2,
    timestamp: "2024-02-01T00:00:00Z",
    source_type: "chain",
    source_name: "bitcoin",
    account_label: "main",
    tx_type: "transfer_in",
    asset: "BTC",
    amount: "1",
    counter_asset: null,
    counter_amount: null,
    price_chf: "52000",
    value_chf: "52000",
    fee_amount: null,
    fee_asset: null,
    external_id: "deposit-1",
  },
];

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Transactions", () => {
  it("shows a loading indicator before data arrives", () => {
    vi.spyOn(client, "fetchTransactions").mockReturnValue(new Promise(() => {}));

    render(<Transactions />);

    expect(screen.getByText(/werden geladen/i)).toBeInTheDocument();
  });

  it("shows an error message when the fetch fails", async () => {
    vi.spyOn(client, "fetchTransactions").mockRejectedValue(new Error("Netzwerkfehler"));

    render(<Transactions />);

    expect(await screen.findByText(/Fehler beim Laden/i)).toBeInTheDocument();
  });

  it("renders fetched transactions in a table", async () => {
    vi.spyOn(client, "fetchTransactions").mockResolvedValue(SAMPLE);

    render(<Transactions />);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("binance")).toBeInTheDocument();
    expect(within(table).getByText("bitcoin")).toBeInTheDocument();
  });

  it("populates the source dropdown from the unfiltered transaction set", async () => {
    vi.spyOn(client, "fetchTransactions").mockResolvedValue(SAMPLE);

    render(<Transactions />);
    const table = await screen.findByRole("table");
    within(table).getByText("binance");

    const sourceSelect = screen.getByLabelText("Quelle") as HTMLSelectElement;
    const optionValues = Array.from(sourceSelect.options).map((o) => o.value);
    expect(optionValues).toEqual(expect.arrayContaining(["binance", "bitcoin"]));
  });

  it("re-fetches from the backend with filter params when a filter changes", async () => {
    const spy = vi.spyOn(client, "fetchTransactions").mockResolvedValue(SAMPLE);

    render(<Transactions />);
    const table = await screen.findByRole("table");
    within(table).getByText("binance");
    spy.mockClear();

    fireEvent.change(screen.getByLabelText("Quelle"), { target: { value: "binance" } });

    await waitFor(() => expect(spy).toHaveBeenCalledWith(expect.objectContaining({ source_name: "binance" })));
  });

  it("links the CSV export button to the export endpoint with the current filters", async () => {
    vi.spyOn(client, "fetchTransactions").mockResolvedValue(SAMPLE);

    render(<Transactions />);
    const table = await screen.findByRole("table");
    within(table).getByText("binance");

    fireEvent.change(screen.getByLabelText("Quelle"), { target: { value: "binance" } });

    await waitFor(() => {
      const link = screen.getByRole("link", { name: "CSV exportieren" });
      expect(link.getAttribute("href")).toContain("source_name=binance");
    });
  });
});
