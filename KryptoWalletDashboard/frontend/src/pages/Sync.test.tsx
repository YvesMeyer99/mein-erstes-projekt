import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import SyncPage from "./Sync";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SyncPage", () => {
  it("shows a button that triggers a sync when clicked", () => {
    vi.spyOn(client, "triggerSync").mockReturnValue(new Promise(() => {}));

    render(<SyncPage />);

    expect(screen.getByRole("button", { name: "Jetzt synchronisieren" })).toBeInTheDocument();
  });

  it("disables the button and shows a loading state while syncing", async () => {
    vi.spyOn(client, "triggerSync").mockReturnValue(new Promise(() => {}));

    render(<SyncPage />);
    fireEvent.click(screen.getByRole("button", { name: "Jetzt synchronisieren" }));

    expect(await screen.findByRole("button", { name: "Synchronisiert…" })).toBeDisabled();
  });

  it("renders per-source results after a successful sync", async () => {
    vi.spyOn(client, "triggerSync").mockResolvedValue({
      results: [
        { source_name: "bitcoin", account_label: "main", status: "ok", new_transactions: 3 },
        { source_name: "binance", account_label: "binance-main", status: "error", error: "401 Unauthorized" },
      ],
    });

    render(<SyncPage />);
    fireEvent.click(screen.getByRole("button", { name: "Jetzt synchronisieren" }));

    expect(await screen.findByText(/bitcoin.*3 neue Transaktionen/)).toBeInTheDocument();
    expect(screen.getByText(/binance.*401 Unauthorized/)).toBeInTheDocument();
  });

  it("shows an error message if the sync request itself fails", async () => {
    vi.spyOn(client, "triggerSync").mockRejectedValue(new Error("Netzwerkfehler"));

    render(<SyncPage />);
    fireEvent.click(screen.getByRole("button", { name: "Jetzt synchronisieren" }));

    expect(await screen.findByText(/Netzwerkfehler/)).toBeInTheDocument();
    expect(screen.getByText(/Läuft das Backend/i)).toBeInTheDocument();
  });

  it("re-enables the button after the sync completes", async () => {
    vi.spyOn(client, "triggerSync").mockResolvedValue({ results: [] });

    render(<SyncPage />);
    fireEvent.click(screen.getByRole("button", { name: "Jetzt synchronisieren" }));

    expect(await screen.findByRole("button", { name: "Jetzt synchronisieren" })).not.toBeDisabled();
  });
});
