import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App", () => {
  it("renders the Sidebar alongside the routed page content", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "Übersicht" })).toBeInTheDocument();
    expect(screen.getAllByText("Übersicht").length).toBeGreaterThan(0);
  });

  it("renders the Transaktionen page at /transactions", () => {
    render(
      <MemoryRouter initialEntries={["/transactions"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getAllByText("Transaktionen").length).toBeGreaterThan(0);
  });

  it("renders the Sync page at /sync", () => {
    render(
      <MemoryRouter initialEntries={["/sync"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getAllByText("Sync").length).toBeGreaterThan(0);
  });
});
