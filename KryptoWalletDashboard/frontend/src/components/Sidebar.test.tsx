import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Sidebar from "./Sidebar";

describe("Sidebar", () => {
  it("renders links to all three pages", () => {
    render(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "Übersicht" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Transaktionen" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sync" })).toBeInTheDocument();
  });

  it("marks the current page's link as active", () => {
    render(
      <MemoryRouter initialEntries={["/transactions"]}>
        <Sidebar />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "Transaktionen" })).toHaveClass("bg-gray-900");
    expect(screen.getByRole("link", { name: "Übersicht" })).not.toHaveClass("bg-gray-900");
  });
});
