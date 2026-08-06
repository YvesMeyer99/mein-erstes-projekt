import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import Konfiguration from "./Konfiguration";

const FIELDS = [
  { name: "SOLANA_ADDRESSES", section: "Solana", label: "Adressen", is_secret: false, hint: "label:adresse", value: "main:abc" },
  { name: "KRAKEN_API_KEY", section: "Kraken", label: "API-Key", is_secret: false, hint: "", value: "existing-key" },
  { name: "KRAKEN_API_SECRET", section: "Kraken", label: "API-Secret", is_secret: true, hint: "", value: "" },
];

const SECTIONS = [
  { name: "Solana", enabled: true },
  { name: "Kraken", enabled: true },
];

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Konfiguration", () => {
  it("renders a labeled input pre-filled with the current value for each field", async () => {
    vi.spyOn(client, "fetchConfig").mockResolvedValue({ sections: SECTIONS, fields: FIELDS });

    render(<Konfiguration />);

    expect(await screen.findByDisplayValue("main:abc")).toBeInTheDocument();
    expect(screen.getByDisplayValue("existing-key")).toBeInTheDocument();
  });

  it("groups fields by section with a heading per section", async () => {
    vi.spyOn(client, "fetchConfig").mockResolvedValue({ sections: SECTIONS, fields: FIELDS });

    render(<Konfiguration />);

    expect(await screen.findByText("Solana")).toBeInTheDocument();
    expect(screen.getByText("Kraken")).toBeInTheDocument();
  });

  it("renders secret fields as empty password inputs regardless of any stored value", async () => {
    vi.spyOn(client, "fetchConfig").mockResolvedValue({ sections: SECTIONS, fields: FIELDS });

    render(<Konfiguration />);

    const secretInput = (await screen.findByLabelText("API-Secret")) as HTMLInputElement;
    expect(secretInput.type).toBe("password");
    expect(secretInput.value).toBe("");
  });

  it("marks secret inputs with autoComplete=new-password to prevent browser credential autofill", async () => {
    vi.spyOn(client, "fetchConfig").mockResolvedValue({ sections: SECTIONS, fields: FIELDS });

    render(<Konfiguration />);

    const secretInput = (await screen.findByLabelText("API-Secret")) as HTMLInputElement;
    expect(secretInput.autocomplete).toBe("new-password");
  });

  it("saves the current form values when the save button is clicked", async () => {
    vi.spyOn(client, "fetchConfig").mockResolvedValue({ sections: SECTIONS, fields: FIELDS });
    const saveSpy = vi.spyOn(client, "saveConfig").mockResolvedValue(undefined);

    render(<Konfiguration />);
    const addressInput = await screen.findByDisplayValue("main:abc");
    fireEvent.change(addressInput, { target: { value: "main:new" } });
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));

    await waitFor(() =>
      expect(saveSpy).toHaveBeenCalledWith(
        expect.objectContaining({ SOLANA_ADDRESSES: "main:new" }),
        expect.anything(),
      ),
    );
  });

  it("shows a confirmation message after a successful save", async () => {
    vi.spyOn(client, "fetchConfig").mockResolvedValue({ sections: SECTIONS, fields: FIELDS });
    vi.spyOn(client, "saveConfig").mockResolvedValue(undefined);

    render(<Konfiguration />);
    fireEvent.click(await screen.findByRole("button", { name: "Speichern" }));

    expect(await screen.findByText(/gespeichert/i)).toBeInTheDocument();
  });

  it("shows an error message if saving fails", async () => {
    vi.spyOn(client, "fetchConfig").mockResolvedValue({ sections: SECTIONS, fields: FIELDS });
    vi.spyOn(client, "saveConfig").mockRejectedValue(new Error("Serverfehler"));

    render(<Konfiguration />);
    fireEvent.click(await screen.findByRole("button", { name: "Speichern" }));

    expect(await screen.findByText(/Serverfehler/)).toBeInTheDocument();
  });

  it("renders a checkbox per section reflecting its enabled state", async () => {
    vi.spyOn(client, "fetchConfig").mockResolvedValue({
      sections: [
        { name: "Solana", enabled: true },
        { name: "Kraken", enabled: false },
      ],
      fields: FIELDS,
    });

    render(<Konfiguration />);

    const solanaCheckbox = (await screen.findByRole("checkbox", { name: /Solana/ })) as HTMLInputElement;
    const krakenCheckbox = screen.getByRole("checkbox", { name: /Kraken/ }) as HTMLInputElement;
    expect(solanaCheckbox.checked).toBe(true);
    expect(krakenCheckbox.checked).toBe(false);
  });

  it("includes the current section toggle state when saving", async () => {
    vi.spyOn(client, "fetchConfig").mockResolvedValue({
      sections: [{ name: "Solana", enabled: true }],
      fields: FIELDS,
    });
    const saveSpy = vi.spyOn(client, "saveConfig").mockResolvedValue(undefined);

    render(<Konfiguration />);
    const solanaCheckbox = await screen.findByRole("checkbox", { name: /Solana/ });
    fireEvent.click(solanaCheckbox);
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));

    await waitFor(() =>
      expect(saveSpy).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ Solana: false }),
      ),
    );
  });
});
