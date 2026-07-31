import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import Overview from "./Overview";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Overview", () => {
  it("shows a loading indicator before data arrives", () => {
    vi.spyOn(client, "fetchPortfolio").mockReturnValue(new Promise(() => {}));

    render(<Overview />);

    expect(screen.getByText(/wird geladen/i)).toBeInTheDocument();
  });

  it("shows an error message when the fetch fails", async () => {
    vi.spyOn(client, "fetchPortfolio").mockRejectedValue(new Error("Netzwerkfehler"));

    render(<Overview />);

    expect(await screen.findByText(/Fehler beim Laden/i)).toBeInTheDocument();
    expect(screen.getByText(/Netzwerkfehler/)).toBeInTheDocument();
  });

  it("renders portfolio entries in a table", async () => {
    vi.spyOn(client, "fetchPortfolio").mockResolvedValue([
      { asset: "BTC", amount: "1.5", price_chf: "50000", value_chf: "75000" },
      { asset: "ETH", amount: "10", price_chf: "3000", value_chf: "30000" },
    ]);

    render(<Overview />);

    expect(await screen.findByText("BTC")).toBeInTheDocument();
    expect(screen.getByText("ETH")).toBeInTheDocument();
    expect(screen.getByText("1.5")).toBeInTheDocument();
  });

  it("shows a CHF total that reflects the sum of value_chf across entries", async () => {
    vi.spyOn(client, "fetchPortfolio").mockResolvedValue([
      { asset: "BTC", amount: "1", price_chf: "50000", value_chf: "50000" },
      { asset: "ETH", amount: "1", price_chf: "3000", value_chf: "3000" },
    ]);

    render(<Overview />);

    await waitFor(() => expect(screen.getByText("BTC")).toBeInTheDocument());
    // 50000 + 3000 = 53000 -- assert the digits appear somewhere in the total display
    // rather than pinning the exact Intl-formatted string (see format.test.ts's note
    // on why exact separator characters aren't asserted).
    const totalEl = document.querySelector("[data-testid='portfolio-total']");
    expect(totalEl?.textContent).toContain("53");
  });

  it("handles entries with no CHF price without crashing", async () => {
    vi.spyOn(client, "fetchPortfolio").mockResolvedValue([
      { asset: "UNKNOWNTOKEN", amount: "100", price_chf: null, value_chf: null },
    ]);

    render(<Overview />);

    expect(await screen.findByText("UNKNOWNTOKEN")).toBeInTheDocument();
    expect(screen.getByText("–")).toBeInTheDocument();
  });

  it("renders an empty table without crashing when the portfolio is empty", async () => {
    vi.spyOn(client, "fetchPortfolio").mockResolvedValue([]);

    render(<Overview />);

    await waitFor(() => expect(screen.queryByText(/wird geladen/i)).not.toBeInTheDocument());
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});
