import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import Accounts from "./Accounts";

const ACCOUNTS = [
  {
    source_name: "bitcoin",
    account_label: "ledger",
    transaction_count: 12,
    last_synced_at: "2026-08-01T10:00:00Z",
    last_error: null,
    is_configured: true,
  },
  {
    source_name: "solana",
    account_label: "old-test",
    transaction_count: 3,
    last_synced_at: null,
    last_error: "401 Unauthorized",
    is_configured: false,
  },
];

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Accounts", () => {
  it("renders one row per account with its transaction count", async () => {
    vi.spyOn(client, "fetchAccounts").mockResolvedValue({ accounts: ACCOUNTS });

    render(<Accounts />);

    expect(await screen.findByText("bitcoin")).toBeInTheDocument();
    expect(screen.getByText("ledger")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("solana")).toBeInTheDocument();
  });

  it("disables the delete button until at least one account is selected", async () => {
    vi.spyOn(client, "fetchAccounts").mockResolvedValue({ accounts: ACCOUNTS });

    render(<Accounts />);
    await screen.findByText("bitcoin");

    expect(screen.getByRole("button", { name: /löschen/i })).toBeDisabled();
  });

  it("enables the delete button once an account is checked", async () => {
    vi.spyOn(client, "fetchAccounts").mockResolvedValue({ accounts: ACCOUNTS });

    render(<Accounts />);
    await screen.findByText("bitcoin");
    fireEvent.click(screen.getAllByRole("checkbox")[0]);

    expect(screen.getByRole("button", { name: /löschen/i })).not.toBeDisabled();
  });

  it("asks for confirmation and deletes only the checked accounts", async () => {
    vi.spyOn(client, "fetchAccounts").mockResolvedValue({ accounts: ACCOUNTS });
    const deleteSpy = vi.spyOn(client, "deleteAccounts").mockResolvedValue({
      results: [{ source_name: "solana", account_label: "old-test", deleted_transactions: 3, dry_run: false }],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<Accounts />);
    await screen.findByText("bitcoin");
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.click(screen.getByRole("button", { name: /löschen/i }));

    await waitFor(() =>
      expect(deleteSpy).toHaveBeenCalledWith([{ source_name: "solana", account_label: "old-test" }]),
    );
  });

  it("does not delete anything if the confirmation is declined", async () => {
    vi.spyOn(client, "fetchAccounts").mockResolvedValue({ accounts: ACCOUNTS });
    const deleteSpy = vi.spyOn(client, "deleteAccounts").mockResolvedValue({ results: [] });
    vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<Accounts />);
    await screen.findByText("bitcoin");
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByRole("button", { name: /löschen/i }));

    expect(deleteSpy).not.toHaveBeenCalled();
  });

  it("shows an error message if loading accounts fails", async () => {
    vi.spyOn(client, "fetchAccounts").mockRejectedValue(new Error("Netzwerkfehler"));

    render(<Accounts />);

    expect(await screen.findByText(/Netzwerkfehler/)).toBeInTheDocument();
  });
});
