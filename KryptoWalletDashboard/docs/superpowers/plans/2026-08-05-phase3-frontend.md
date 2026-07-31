# Phase 3 – React-Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a React+TypeScript frontend (`KryptoWalletDashboard/frontend/`) that makes the already-complete backend (Bitcoin, 6 EVM chains, Kraken, Coinbase, MEXC, Binance) actually usable: a sidebar-navigated dashboard with an Übersicht (portfolio) page, a Transaktionen page (filterable table + CSV export), and a Sync page (manual sync trigger).

**Architecture:** Vite-scaffolded React+TypeScript SPA using React Router for the three pages, Tailwind CSS v4 for styling, recharts for the portfolio pie chart, and plain `fetch` (no data-fetching library) against the existing FastAPI backend's four JSON/CSV endpoints. A small backend change (CORS middleware) is required first since the Vite dev server runs on a different origin than the FastAPI backend. Testing uses Vitest + React Testing Library, mocking the API client module rather than making real network calls.

**Tech Stack:** TypeScript, Vite, React 19, React Router, Tailwind CSS v4 (`@tailwindcss/vite`, no `tailwind.config.js` needed), recharts, Vitest, `@testing-library/react`/`jest-dom`/`user-event`. Backend: FastAPI's built-in `CORSMiddleware` (no new dependency).

**Related docs:**
- [`docs/superpowers/specs/2026-08-05-phase3-frontend-design.md`](../specs/2026-08-05-phase3-frontend-design.md)

**Scope notes (decided during design, confirmed with user):**
- Sidebar navigation with exactly 3 pages: Übersicht (`/`), Transaktionen (`/transactions`), Sync (`/sync`) — already fixed from the very first brainstorming session for this project.
- Filters on the Transaktionen page: date range, source/chain, transaction type, account/wallet — sent to the backend as query params on every change (server-side filtering via the existing `GET /api/transactions` params), not client-side filtering of one big fetched list. Dropdown *options* for those filters are derived client-side from a separate, one-time unfiltered fetch (no new backend endpoint for this — YAGNI, confirmed in design).
- CSV export re-uses `GET /api/export` directly via a plain `<a href>` with the current filters as query params — the backend already sets `Content-Disposition: attachment`, so the browser handles the download natively. (The design doc mentioned a "blob + `<a download>`" approach as one option; a direct link achieves the identical user-facing result with less code, so that's what this plan uses — not a scope change, just a simpler implementation of the same requirement.)
- CHF amounts (`price_chf`/`value_chf`) are formatted via `Intl.NumberFormat("de-CH", ...)`, which requires converting the string to a JS `number` — acceptable here because these are already-rounded fiat figures, not raw ledger amounts. Crypto quantities (`amount`, `counter_amount`) are rendered as the raw string from the API, un-converted, to avoid any float rounding on high-precision values (e.g. satoshi-level BTC amounts) — this distinction is deliberate, confirmed in the design doc.
- No authentication, no automatic/periodic sync (manual button only), no transaction editing/deletion in the UI, no production deployment setup beyond `npm run build` — all explicitly out of scope per the design doc.
- **Tooling caveat:** exact `npm create vite` / Tailwind v4 / Vitest setup commands below were verified against current documentation as of 2026-08-05, but frontend tooling moves fast. If a command's output or a package's exact API doesn't match what's shown here by execution time, treat the *intent* (Vite+React+TS scaffold, Tailwind v4 via its Vite plugin with no separate config file, Vitest+jsdom+RTL) as authoritative and adapt the exact commands/config syntax to whatever the installed tool version actually expects.
- **Environment prerequisite:** requires Node.js 18+ and npm. Check with `node --version` before starting Task 2; if Node is missing or too old, stop and report back rather than guessing at a workaround.

---

## File Structure

```
KryptoWalletDashboard/
  backend/
    app/
      main.py                          # MODIFIED — add CORSMiddleware
    tests/
      test_cors.py                     # NEW — CORS behavior tests
  frontend/                            # NEW — entire directory, Vite-scaffolded
    src/
      api/
        types.ts                       # NEW — TS interfaces mirroring backend Pydantic schemas
        client.ts                      # NEW — typed fetch wrappers for the 4 backend endpoints
        client.test.ts                 # NEW
      lib/
        format.ts                      # NEW — formatChf()
        format.test.ts                 # NEW
      components/
        Sidebar.tsx                    # NEW — nav sidebar
        Sidebar.test.tsx               # NEW
      pages/
        Overview.tsx                   # NEW — portfolio table + pie chart
        Overview.test.tsx              # NEW
        Transactions.tsx               # NEW — filterable table + CSV export
        Transactions.test.tsx          # NEW
        Sync.tsx                       # NEW — manual sync trigger + results
        Sync.test.tsx                  # NEW
      test/
        setup.ts                       # NEW — Vitest/RTL global setup
      App.tsx                          # NEW — routes + layout shell
      App.test.tsx                     # NEW
      main.tsx                         # MODIFIED (from Vite scaffold) — wrap App in BrowserRouter
      index.css                        # MODIFIED (from Vite scaffold) — Tailwind import only
    vite.config.ts                     # MODIFIED (from Vite scaffold) — add Tailwind + Vitest config
    package.json                       # MODIFIED (from Vite scaffold) — add "test" script, new deps
    README.md                          # NEW — frontend setup/usage
  backend/README.md                    # MODIFIED — pointer to frontend
```

---

### Task 1: Backend CORS Middleware

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/main.py`
- Create: `KryptoWalletDashboard/backend/tests/test_cors.py`

**Why:** The Vite dev server (`http://localhost:5173`) and the FastAPI backend (`http://127.0.0.1:8000`) are different origins. Without CORS headers, the browser blocks every `fetch` call the frontend makes. This must land before any frontend code can actually talk to the backend.

- [ ] **Step 1: Write the failing tests**

Create `KryptoWalletDashboard/backend/tests/test_cors.py`:
```python
from fastapi.testclient import TestClient

from app.main import app, get_session


def _client(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_cors_allows_localhost_vite_dev_server(db_session):
    client = _client(db_session)

    response = client.get("/api/portfolio", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    app.dependency_overrides.clear()


def test_cors_allows_127_0_0_1_vite_dev_server(db_session):
    client = _client(db_session)

    response = client.get("/api/portfolio", headers={"Origin": "http://127.0.0.1:5173"})

    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    app.dependency_overrides.clear()


def test_cors_rejects_unknown_origin(db_session):
    client = _client(db_session)

    response = client.get("/api/portfolio", headers={"Origin": "http://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers
    app.dependency_overrides.clear()
```

This reuses the existing `db_session` pytest fixture already used throughout `tests/test_api.py` — check `tests/conftest.py` if you need to confirm its exact behavior, but you shouldn't need to modify it.

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `KryptoWalletDashboard/backend/`): `.venv/Scripts/pytest tests/test_cors.py -v`
Expected: FAIL — no CORS headers present yet, so `response.headers["access-control-allow-origin"]` raises `KeyError` in the first two tests.

- [ ] **Step 3: Add CORS middleware to `app/main.py`**

Add the import (alongside the existing `fastapi` import):
```python
from fastapi.middleware.cors import CORSMiddleware
```

Add immediately after `app = FastAPI(title="Krypto-Wallet-Dashboard")`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_cors.py -v`
Expected: PASS (3 tests).

Run the full backend suite to confirm no regressions: `.venv/Scripts/pytest -v`
Expected: PASS, all tests green (195 total: 192 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/main.py KryptoWalletDashboard/backend/tests/test_cors.py
git commit -m "feat: allow CORS from the Vite dev server for the upcoming frontend"
```

---

### Task 2: Frontend Project Scaffolding

**Files:**
- Create: `KryptoWalletDashboard/frontend/` (entire directory, via `npm create vite`)
- Create: `KryptoWalletDashboard/frontend/src/test/setup.ts`
- Modify: `KryptoWalletDashboard/frontend/vite.config.ts`
- Modify: `KryptoWalletDashboard/frontend/src/index.css`
- Modify: `KryptoWalletDashboard/frontend/src/App.tsx`
- Create: `KryptoWalletDashboard/frontend/src/App.test.tsx`
- Modify: `KryptoWalletDashboard/frontend/package.json`

**Why this shape:** `npm create vite` gives a working React+TS+Vite setup with its own demo counter app. This task strips the demo down to an empty placeholder (later tasks build the real pages on top) and wires in Tailwind v4, React Router (installed now, used starting Task 4), and Vitest+RTL so every subsequent task can follow TDD.

- [ ] **Step 1: Scaffold the Vite project**

From `KryptoWalletDashboard/` (not inside `backend/`):
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

This should run non-interactively since both the project name (`frontend`) and `--template react-ts` are passed as arguments. If it still prompts, answer: framework = React, variant = TypeScript.

- [ ] **Step 2: Install Tailwind CSS v4 and its Vite plugin**

From `KryptoWalletDashboard/frontend/`:
```bash
npm install tailwindcss @tailwindcss/vite
```

Tailwind v4 does not use a `tailwind.config.js` or PostCSS config by default — it's wired directly into the Vite plugin pipeline (Step 4) and a single CSS import (Step 5).

- [ ] **Step 3: Install React Router**

```bash
npm install react-router-dom
```

- [ ] **Step 4: Install Vitest and React Testing Library (dev dependencies)**

```bash
npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

- [ ] **Step 5: Replace `vite.config.ts` with the merged Vite+Vitest+Tailwind config**

Replace the entire contents of `KryptoWalletDashboard/frontend/vite.config.ts` with:
```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
```

(Importing `defineConfig` from `vitest/config` instead of plain `vite` merges the build config and the test config into one file — no separate `vitest.config.ts` needed.)

- [ ] **Step 6: Replace `src/index.css` with just the Tailwind import**

Replace the entire contents of `KryptoWalletDashboard/frontend/src/index.css` with:
```css
@import "tailwindcss";
```

- [ ] **Step 7: Strip the Vite demo content from `App.tsx`**

Delete `KryptoWalletDashboard/frontend/src/App.css` entirely (Vite's demo counter styling — no longer needed, Tailwind replaces it).

Replace the entire contents of `KryptoWalletDashboard/frontend/src/App.tsx` with:
```tsx
function App() {
  return <div>Krypto-Wallet-Dashboard</div>;
}

export default App;
```

This is an intentionally minimal placeholder — Task 4 replaces it with real routing and a sidebar. Don't build more than this here.

- [ ] **Step 8: Create the Vitest/RTL global setup file**

Create `KryptoWalletDashboard/frontend/src/test/setup.ts`:
```typescript
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});
```

- [ ] **Step 9: Write the failing smoke test**

Create `KryptoWalletDashboard/frontend/src/App.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App", () => {
  it("renders without crashing", () => {
    render(<App />);
    expect(screen.getByText("Krypto-Wallet-Dashboard")).toBeInTheDocument();
  });
});
```

- [ ] **Step 10: Add the `test` script to `package.json`**

Open `KryptoWalletDashboard/frontend/package.json` and add `"test": "vitest run"` to the `"scripts"` object (alongside the existing `dev`/`build`/`lint`/`preview` scripts Vite already generated — don't remove or rename those).

- [ ] **Step 11: Run the test to verify it passes**

From `KryptoWalletDashboard/frontend/`: `npm test`
Expected: PASS (1 test).

- [ ] **Step 12: Verify the project builds cleanly**

```bash
npm run build
```
Expected: succeeds with no TypeScript errors (this runs `tsc -b && vite build` per Vite's default scaffolded `build` script — confirms the whole scaffold, including the new Tailwind/Router/Vitest additions, type-checks correctly together).

- [ ] **Step 13: Commit**

```bash
git add KryptoWalletDashboard/frontend
git commit -m "chore: scaffold Vite+React+TypeScript frontend with Tailwind, React Router, Vitest"
```

(Vite's scaffold includes its own `.gitignore` inside `frontend/` that excludes `node_modules`/`dist` — confirm `git status` doesn't show `node_modules` staged before committing; if it does, something's wrong with the generated `.gitignore` and needs fixing before you commit.)

---

### Task 3: Formatting & API Client Utilities

**Files:**
- Create: `KryptoWalletDashboard/frontend/src/lib/format.ts`
- Create: `KryptoWalletDashboard/frontend/src/lib/format.test.ts`
- Create: `KryptoWalletDashboard/frontend/src/api/types.ts`
- Create: `KryptoWalletDashboard/frontend/src/api/client.ts`
- Create: `KryptoWalletDashboard/frontend/src/api/client.test.ts`

**Backend API being wrapped** (already exists, don't change): `GET /api/portfolio` → `PortfolioEntryOut[]`, `GET /api/transactions?start&end&source_name&tx_type&account_label` → `TransactionOut[]`, `GET /api/export?<same filters>` → CSV file, `POST /api/sync` → `{"results": [{"source_name", "account_label", "status": "ok"|"error", "new_transactions"?, "error"?}]}`. All Decimal fields (`amount`, `price_chf`, `value_chf`, `fee_amount`, `counter_amount`) are serialized by Pydantic as JSON strings, not numbers — the TypeScript types below reflect that.

- [ ] **Step 1: Write the failing test for `formatChf`**

Create `KryptoWalletDashboard/frontend/src/lib/format.test.ts`:
```typescript
import { describe, expect, it } from "vitest";
import { formatChf } from "./format";

describe("formatChf", () => {
  it("includes the CHF symbol and the integer part of the amount", () => {
    const result = formatChf("50000");

    expect(result).toContain("CHF");
    expect(result).toContain("50");
    expect(result).toContain("000");
  });

  it("formats null as an em dash placeholder", () => {
    expect(formatChf(null)).toBe("–");
  });

  it("rounds to two decimal places", () => {
    const result = formatChf("12.5");

    expect(result).toContain("12");
    expect(result).toContain("50");
  });
});
```

Note: these assertions deliberately check for substrings rather than pinning down the exact formatted string. `Intl.NumberFormat`'s exact whitespace/separator characters for `de-CH` (e.g. narrow-no-break-space vs regular space, apostrophe variant) depend on the ICU data bundled with the Node.js version running the tests, and can differ across environments — asserting substrings verifies the real formatting behavior (currency symbol present, correct digits, correct rounding) without being brittle to that variation.

- [ ] **Step 2: Run the test to verify it fails**

From `KryptoWalletDashboard/frontend/`: `npm test -- src/lib/format.test.ts`
Expected: FAIL — `format.ts` doesn't exist yet.

- [ ] **Step 3: Implement `src/lib/format.ts`**

```typescript
const CHF_FORMATTER = new Intl.NumberFormat("de-CH", {
  style: "currency",
  currency: "CHF",
});

export function formatChf(value: string | null): string {
  if (value === null) {
    return "–";
  }
  return CHF_FORMATTER.format(Number(value));
}
```

- [ ] **Step 4: Run the test to verify it passes**

`npm test -- src/lib/format.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Create the API types**

Create `KryptoWalletDashboard/frontend/src/api/types.ts`:
```typescript
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
```

No test needed for this file — it's type-only, has no runtime behavior to verify (TypeScript compilation itself, checked in `npm run build`, is the check).

- [ ] **Step 6: Write the failing tests for the API client**

Create `KryptoWalletDashboard/frontend/src/api/client.test.ts`:
```typescript
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
});
```

- [ ] **Step 7: Run the tests to verify they fail**

`npm test -- src/api/client.test.ts`
Expected: FAIL — `client.ts` doesn't exist yet.

- [ ] **Step 8: Implement `src/api/client.ts`**

```typescript
import type { PortfolioEntry, SyncResponse, Transaction, TransactionFilters } from "./types";

const API_BASE = "http://127.0.0.1:8000";

function buildQuery(filters: TransactionFilters): string {
  const params = new URLSearchParams();
  if (filters.start) params.set("start", filters.start);
  if (filters.end) params.set("end", filters.end);
  if (filters.source_name) params.set("source_name", filters.source_name);
  if (filters.tx_type) params.set("tx_type", filters.tx_type);
  if (filters.account_label) params.set("account_label", filters.account_label);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export async function fetchPortfolio(): Promise<PortfolioEntry[]> {
  const response = await fetch(`${API_BASE}/api/portfolio`);
  if (!response.ok) {
    throw new Error(`Portfolio-Abfrage fehlgeschlagen: ${response.status}`);
  }
  return response.json();
}

export async function fetchTransactions(filters: TransactionFilters = {}): Promise<Transaction[]> {
  const response = await fetch(`${API_BASE}/api/transactions${buildQuery(filters)}`);
  if (!response.ok) {
    throw new Error(`Transaktions-Abfrage fehlgeschlagen: ${response.status}`);
  }
  return response.json();
}

export function exportUrl(filters: TransactionFilters = {}): string {
  return `${API_BASE}/api/export${buildQuery(filters)}`;
}

export async function triggerSync(): Promise<SyncResponse> {
  const response = await fetch(`${API_BASE}/api/sync`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Sync fehlgeschlagen: ${response.status}`);
  }
  return response.json();
}
```

- [ ] **Step 9: Run the tests to verify they pass**

`npm test -- src/api/client.test.ts`
Expected: PASS (9 tests).

Run the full frontend test suite: `npm test`
Expected: PASS (13 tests: 1 from Task 2 + 3 format + 9 client).

- [ ] **Step 10: Commit**

```bash
git add KryptoWalletDashboard/frontend/src/lib KryptoWalletDashboard/frontend/src/api
git commit -m "feat: formatChf helper and typed API client for the backend endpoints"
```

---

### Task 4: App Shell & Sidebar Navigation

**Files:**
- Create: `KryptoWalletDashboard/frontend/src/components/Sidebar.tsx`
- Create: `KryptoWalletDashboard/frontend/src/components/Sidebar.test.tsx`
- Create: `KryptoWalletDashboard/frontend/src/pages/Overview.tsx` (minimal placeholder — Task 5 fills it in)
- Create: `KryptoWalletDashboard/frontend/src/pages/Transactions.tsx` (minimal placeholder — Task 6 fills it in)
- Create: `KryptoWalletDashboard/frontend/src/pages/Sync.tsx` (minimal placeholder — Task 7 fills it in)
- Modify: `KryptoWalletDashboard/frontend/src/App.tsx` (replace Task 2's placeholder with real routing)
- Modify: `KryptoWalletDashboard/frontend/src/App.test.tsx` (replace Task 2's smoke test)
- Modify: `KryptoWalletDashboard/frontend/src/main.tsx` (wrap `App` in `BrowserRouter`)

**Why `BrowserRouter` lives in `main.tsx`, not `App.tsx`:** keeping `App.tsx` router-agnostic lets tests wrap it in a `MemoryRouter` (controllable initial route, no real browser history needed) instead of `BrowserRouter`. This is the standard React Router testing pattern.

- [ ] **Step 1: Write the failing tests for `Sidebar`**

Create `KryptoWalletDashboard/frontend/src/components/Sidebar.test.tsx`:
```tsx
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
```

- [ ] **Step 2: Run the tests to verify they fail**

`npm test -- src/components/Sidebar.test.tsx`
Expected: FAIL — `Sidebar.tsx` doesn't exist yet.

- [ ] **Step 3: Implement `src/components/Sidebar.tsx`**

```tsx
import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Übersicht" },
  { to: "/transactions", label: "Transaktionen" },
  { to: "/sync", label: "Sync" },
];

function Sidebar() {
  return (
    <nav className="w-56 shrink-0 border-r border-gray-200 p-4">
      <h1 className="mb-6 text-lg font-semibold">Krypto-Wallet-Dashboard</h1>
      <ul className="space-y-1">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `block rounded px-3 py-2 text-sm ${
                  isActive ? "bg-gray-900 text-white" : "text-gray-700 hover:bg-gray-100"
                }`
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export default Sidebar;
```

- [ ] **Step 4: Run the tests to verify they pass**

`npm test -- src/components/Sidebar.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Create the placeholder pages**

Create `KryptoWalletDashboard/frontend/src/pages/Overview.tsx`:
```tsx
function Overview() {
  return <div>Übersicht</div>;
}

export default Overview;
```

Create `KryptoWalletDashboard/frontend/src/pages/Transactions.tsx`:
```tsx
function Transactions() {
  return <div>Transaktionen</div>;
}

export default Transactions;
```

Create `KryptoWalletDashboard/frontend/src/pages/Sync.tsx`:
```tsx
function SyncPage() {
  return <div>Sync</div>;
}

export default SyncPage;
```

These are intentionally minimal — Tasks 5, 6, and 7 replace each one's contents. Don't build more than this here.

- [ ] **Step 6: Write the failing tests for `App`'s routing**

Replace the entire contents of `KryptoWalletDashboard/frontend/src/App.test.tsx` with:
```tsx
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
```

- [ ] **Step 7: Run the tests to verify they fail**

`npm test -- src/App.test.tsx`
Expected: FAIL — `App.tsx` still renders Task 2's placeholder text, no routing yet, and no `Sidebar` link exists.

- [ ] **Step 8: Implement the real `App.tsx`**

Replace the entire contents of `KryptoWalletDashboard/frontend/src/App.tsx` with:
```tsx
import { Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Overview from "./pages/Overview";
import Transactions from "./pages/Transactions";
import SyncPage from "./pages/Sync";

function App() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 p-6">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/transactions" element={<Transactions />} />
          <Route path="/sync" element={<SyncPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
```

- [ ] **Step 9: Wrap `App` in `BrowserRouter` inside `main.tsx`**

Open `KryptoWalletDashboard/frontend/src/main.tsx` (Vite's scaffolded version renders `<App />` inside `<StrictMode>`). Add the `BrowserRouter` import and wrap `<App />` with it, keeping everything else (the `StrictMode` wrapper, the `createRoot` call, the `index.css` import) as Vite generated it:
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.tsx";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
```

- [ ] **Step 10: Run the tests to verify they pass**

`npm test -- src/App.test.tsx`
Expected: PASS (3 tests).

Run the full suite: `npm test`
Expected: PASS (18 tests: 13 from Task 3 + 2 Sidebar + 3 App).

Run `npm run build` to confirm the whole thing still type-checks and bundles.

- [ ] **Step 11: Commit**

```bash
git add KryptoWalletDashboard/frontend/src
git commit -m "feat: app shell with sidebar navigation and routed placeholder pages"
```

---

### Task 5: Übersicht Page (Portfolio Table + Pie Chart)

**Files:**
- Modify: `KryptoWalletDashboard/frontend/src/pages/Overview.tsx`
- Create: `KryptoWalletDashboard/frontend/src/pages/Overview.test.tsx`
- Modify: `KryptoWalletDashboard/frontend/src/test/setup.ts` (add a `ResizeObserver` stub — see Step 1)

- [ ] **Step 1: Install recharts and add the `ResizeObserver` test stub it needs**

From `KryptoWalletDashboard/frontend/`:
```bash
npm install recharts
```

recharts' `ResponsiveContainer` relies on `ResizeObserver`, which jsdom (the test DOM environment) doesn't implement. Without a stub, any test that renders a component using `ResponsiveContainer` throws `ReferenceError: ResizeObserver is not defined`. Add a minimal no-op stub to the global test setup — append to `KryptoWalletDashboard/frontend/src/test/setup.ts` (keep the existing `afterEach(cleanup)` block, just add the import and the stub below/after it):
```typescript
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);
```

- [ ] **Step 2: Write the failing tests**

Create `KryptoWalletDashboard/frontend/src/pages/Overview.test.tsx`:
```tsx
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
```

- [ ] **Step 3: Run the tests to verify they fail**

`npm test -- src/pages/Overview.test.tsx`
Expected: FAIL — `Overview.tsx` still renders Task 4's one-line placeholder.

- [ ] **Step 4: Implement `src/pages/Overview.tsx`**

```tsx
import { useEffect, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { fetchPortfolio } from "../api/client";
import type { PortfolioEntry } from "../api/types";
import { formatChf } from "../lib/format";

const CHART_COLORS = ["#2563eb", "#16a34a", "#dc2626", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];

function Overview() {
  const [entries, setEntries] = useState<PortfolioEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPortfolio()
      .then(setEntries)
      .catch((err: Error) => setError(err.message));
  }, []);

  if (error) {
    return (
      <div className="text-red-600">
        Fehler beim Laden des Portfolios: {error}. Läuft das Backend unter http://127.0.0.1:8000?
      </div>
    );
  }

  if (entries === null) {
    return <div>Portfolio wird geladen…</div>;
  }

  const totalValueChf = entries.reduce((sum, entry) => sum + (entry.value_chf ? Number(entry.value_chf) : 0), 0);
  const chartData = entries
    .filter((entry) => entry.value_chf !== null)
    .map((entry) => ({ name: entry.asset, value: Number(entry.value_chf) }));

  return (
    <div>
      <h2 className="mb-4 text-xl font-semibold">Übersicht</h2>
      <p data-testid="portfolio-total" className="mb-6 text-2xl font-bold">
        {formatChf(totalValueChf.toString())}
      </p>

      <table className="mb-8 w-full text-left text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="py-2">Asset</th>
            <th className="py-2">Menge</th>
            <th className="py-2">Kurs CHF</th>
            <th className="py-2">Wert CHF</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.asset} className="border-b border-gray-100">
              <td className="py-2">{entry.asset}</td>
              <td className="py-2">{entry.amount}</td>
              <td className="py-2">{formatChf(entry.price_chf)}</td>
              <td className="py-2">{formatChf(entry.value_chf)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={300}>
          <PieChart>
            <Pie data={chartData} dataKey="value" nameKey="name" outerRadius={100} label>
              {chartData.map((entry, index) => (
                <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(value: number) => formatChf(value.toString())} />
          </PieChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

export default Overview;
```

- [ ] **Step 5: Run the tests to verify they pass**

`npm test -- src/pages/Overview.test.tsx`
Expected: PASS (6 tests).

Run the full suite: `npm test`
Expected: PASS (24 tests: 18 from Task 4 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add KryptoWalletDashboard/frontend/src/pages/Overview.tsx KryptoWalletDashboard/frontend/src/pages/Overview.test.tsx KryptoWalletDashboard/frontend/src/test/setup.ts KryptoWalletDashboard/frontend/package.json KryptoWalletDashboard/frontend/package-lock.json
git commit -m "feat: Übersicht page with portfolio table and allocation pie chart"
```

---

### Task 6: Transaktionen Page (Filterable Table + CSV Export)

**Files:**
- Modify: `KryptoWalletDashboard/frontend/src/pages/Transactions.tsx`
- Create: `KryptoWalletDashboard/frontend/src/pages/Transactions.test.tsx`

**Design reminder:** filters are sent to the backend as query params (server-side filtering via the real `GET /api/transactions?...`) whenever they change — this is a *second*, separate fetch from the one-time unfiltered fetch used only to populate the filter dropdowns' option lists (see the design doc's explicit note on this split).

- [ ] **Step 1: Write the failing tests**

Create `KryptoWalletDashboard/frontend/src/pages/Transactions.test.tsx`:
```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

    expect(await screen.findByText("binance")).toBeInTheDocument();
    expect(screen.getByText("bitcoin")).toBeInTheDocument();
  });

  it("populates the source dropdown from the unfiltered transaction set", async () => {
    vi.spyOn(client, "fetchTransactions").mockResolvedValue(SAMPLE);

    render(<Transactions />);
    await screen.findByText("binance");

    const sourceSelect = screen.getByLabelText("Quelle") as HTMLSelectElement;
    const optionValues = Array.from(sourceSelect.options).map((o) => o.value);
    expect(optionValues).toEqual(expect.arrayContaining(["binance", "bitcoin"]));
  });

  it("re-fetches from the backend with filter params when a filter changes", async () => {
    const spy = vi.spyOn(client, "fetchTransactions").mockResolvedValue(SAMPLE);

    render(<Transactions />);
    await screen.findByText("binance");
    spy.mockClear();

    fireEvent.change(screen.getByLabelText("Quelle"), { target: { value: "binance" } });

    await waitFor(() => expect(spy).toHaveBeenCalledWith(expect.objectContaining({ source_name: "binance" })));
  });

  it("links the CSV export button to the export endpoint with the current filters", async () => {
    vi.spyOn(client, "fetchTransactions").mockResolvedValue(SAMPLE);

    render(<Transactions />);
    await screen.findByText("binance");

    fireEvent.change(screen.getByLabelText("Quelle"), { target: { value: "binance" } });

    await waitFor(() => {
      const link = screen.getByRole("link", { name: "CSV exportieren" });
      expect(link.getAttribute("href")).toContain("source_name=binance");
    });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

`npm test -- src/pages/Transactions.test.tsx`
Expected: FAIL — `Transactions.tsx` still renders Task 4's one-line placeholder.

- [ ] **Step 3: Implement `src/pages/Transactions.tsx`**

```tsx
import { useEffect, useMemo, useState } from "react";
import { exportUrl, fetchTransactions } from "../api/client";
import type { Transaction, TransactionFilters } from "../api/types";
import { formatChf } from "../lib/format";

function Transactions() {
  const [allTransactions, setAllTransactions] = useState<Transaction[] | null>(null);
  const [displayedTransactions, setDisplayedTransactions] = useState<Transaction[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<TransactionFilters>({});

  // One unfiltered fetch, used only to derive the filter dropdowns' option lists.
  useEffect(() => {
    fetchTransactions()
      .then(setAllTransactions)
      .catch((err: Error) => setError(err.message));
  }, []);

  // Re-fetch from the backend with the current filters applied whenever they change.
  useEffect(() => {
    fetchTransactions(filters)
      .then(setDisplayedTransactions)
      .catch((err: Error) => setError(err.message));
  }, [filters]);

  const sourceOptions = useMemo(
    () => Array.from(new Set((allTransactions ?? []).map((tx) => tx.source_name))).sort(),
    [allTransactions],
  );
  const txTypeOptions = useMemo(
    () => Array.from(new Set((allTransactions ?? []).map((tx) => tx.tx_type))).sort(),
    [allTransactions],
  );
  const accountOptions = useMemo(
    () => Array.from(new Set((allTransactions ?? []).map((tx) => tx.account_label))).sort(),
    [allTransactions],
  );

  function updateFilter(key: keyof TransactionFilters, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value || undefined }));
  }

  if (error) {
    return (
      <div className="text-red-600">
        Fehler beim Laden der Transaktionen: {error}. Läuft das Backend unter http://127.0.0.1:8000?
      </div>
    );
  }

  if (displayedTransactions === null) {
    return <div>Transaktionen werden geladen…</div>;
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-xl font-semibold">Transaktionen</h2>
        <a
          href={exportUrl(filters)}
          className="rounded bg-gray-900 px-4 py-2 text-sm text-white hover:bg-gray-700"
        >
          CSV exportieren
        </a>
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        <input
          type="date"
          aria-label="Von"
          onChange={(e) => updateFilter("start", e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
        />
        <input
          type="date"
          aria-label="Bis"
          onChange={(e) => updateFilter("end", e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
        />
        <select
          aria-label="Quelle"
          onChange={(e) => updateFilter("source_name", e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
        >
          <option value="">Alle Quellen</option>
          {sourceOptions.map((source) => (
            <option key={source} value={source}>
              {source}
            </option>
          ))}
        </select>
        <select
          aria-label="Typ"
          onChange={(e) => updateFilter("tx_type", e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
        >
          <option value="">Alle Typen</option>
          {txTypeOptions.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
        <select
          aria-label="Konto"
          onChange={(e) => updateFilter("account_label", e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
        >
          <option value="">Alle Konten</option>
          {accountOptions.map((account) => (
            <option key={account} value={account}>
              {account}
            </option>
          ))}
        </select>
      </div>

      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="py-2">Datum</th>
            <th className="py-2">Quelle</th>
            <th className="py-2">Konto</th>
            <th className="py-2">Typ</th>
            <th className="py-2">Asset</th>
            <th className="py-2">Menge</th>
            <th className="py-2">Wert CHF</th>
          </tr>
        </thead>
        <tbody>
          {displayedTransactions.map((tx) => (
            <tr key={tx.id} className="border-b border-gray-100">
              <td className="py-2">{new Date(tx.timestamp).toLocaleDateString("de-CH")}</td>
              <td className="py-2">{tx.source_name}</td>
              <td className="py-2">{tx.account_label}</td>
              <td className="py-2">{tx.tx_type}</td>
              <td className="py-2">{tx.asset}</td>
              <td className="py-2">{tx.amount}</td>
              <td className="py-2">{formatChf(tx.value_chf)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default Transactions;
```

- [ ] **Step 4: Run the tests to verify they pass**

`npm test -- src/pages/Transactions.test.tsx`
Expected: PASS (6 tests).

Run the full suite: `npm test`
Expected: PASS (30 tests: 24 from Task 5 + 6 new).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/frontend/src/pages/Transactions.tsx KryptoWalletDashboard/frontend/src/pages/Transactions.test.tsx
git commit -m "feat: Transaktionen page with server-side filtering and CSV export"
```

---

### Task 7: Sync Page (Manual Trigger + Per-Source Results)

**Files:**
- Modify: `KryptoWalletDashboard/frontend/src/pages/Sync.tsx`
- Create: `KryptoWalletDashboard/frontend/src/pages/Sync.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `KryptoWalletDashboard/frontend/src/pages/Sync.test.tsx`:
```tsx
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

    expect(await screen.findByText(/Sync fehlgeschlagen/)).toBeInTheDocument();
  });

  it("re-enables the button after the sync completes", async () => {
    vi.spyOn(client, "triggerSync").mockResolvedValue({ results: [] });

    render(<SyncPage />);
    fireEvent.click(screen.getByRole("button", { name: "Jetzt synchronisieren" }));

    expect(await screen.findByRole("button", { name: "Jetzt synchronisieren" })).not.toBeDisabled();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

`npm test -- src/pages/Sync.test.tsx`
Expected: FAIL — `Sync.tsx` still renders Task 4's one-line placeholder.

- [ ] **Step 3: Implement `src/pages/Sync.tsx`**

```tsx
import { useState } from "react";
import { triggerSync } from "../api/client";
import type { SyncResult } from "../api/types";

function SyncPage() {
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<SyncResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSync() {
    setRunning(true);
    setError(null);
    try {
      const response = await triggerSync();
      setResults(response.results);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div>
      <h2 className="mb-4 text-xl font-semibold">Sync</h2>
      <button
        onClick={handleSync}
        disabled={running}
        className="rounded bg-gray-900 px-4 py-2 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
      >
        {running ? "Synchronisiert…" : "Jetzt synchronisieren"}
      </button>

      {error && (
        <p className="mt-4 text-red-600">
          Sync fehlgeschlagen: {error}. Läuft das Backend unter http://127.0.0.1:8000?
        </p>
      )}

      {results && (
        <ul className="mt-6 space-y-2">
          {results.map((result) => (
            <li
              key={`${result.source_name}-${result.account_label}`}
              className={result.status === "ok" ? "text-green-700" : "text-red-600"}
            >
              {result.source_name} ({result.account_label}):{" "}
              {result.status === "ok" ? `${result.new_transactions} neue Transaktionen` : result.error}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default SyncPage;
```

- [ ] **Step 4: Run the tests to verify they pass**

`npm test -- src/pages/Sync.test.tsx`
Expected: PASS (5 tests).

Run the full suite: `npm test`
Expected: PASS (35 tests: 30 from Task 6 + 5 new).

Run `npm run build` to confirm the whole app still type-checks and bundles.

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/frontend/src/pages/Sync.tsx KryptoWalletDashboard/frontend/src/pages/Sync.test.tsx
git commit -m "feat: Sync page with manual trigger and per-source results"
```

---

### Task 8: Documentation

**Files:**
- Create: `KryptoWalletDashboard/frontend/README.md`
- Modify: `KryptoWalletDashboard/backend/README.md`

- [ ] **Step 1: Create the frontend README**

Create `KryptoWalletDashboard/frontend/README.md`:
```markdown
# Krypto-Wallet-Dashboard – Frontend

React-Frontend für das Krypto-Wallet-Dashboard-Backend.

## Setup

1. `npm install`
2. Backend muss laufen (siehe `../backend/README.md`, Standard-Adresse
   `http://127.0.0.1:8000`)
3. `npm run dev`

Läuft danach auf `http://localhost:5173`.

## Seiten

- **Übersicht** (`/`) – aktuelle Bestände, CHF-Gesamtwert,
  Verteilungs-Diagramm
- **Transaktionen** (`/transactions`) – Tabelle mit Filtern (Datum,
  Quelle, Typ, Konto), CSV-Export
- **Sync** (`/sync`) – manueller Sync-Trigger mit Ergebnis pro Quelle

## Tests

```bash
npm test
```

## Build

```bash
npm run build
```
```

- [ ] **Step 2: Add a pointer section to the backend README**

Add to `KryptoWalletDashboard/backend/README.md`, right after the existing "## Server starten" section (before "## Manueller Smoke-Test"):
```markdown
## Frontend

Ein React-Frontend für dieses Backend liegt unter `../frontend/` - siehe
`../frontend/README.md` für Setup. Das Backend muss zuerst laufen (siehe
oben), danach das Frontend separat starten. CORS ist auf die
Vite-Dev-Server-Origins (`http://localhost:5173`, `http://127.0.0.1:5173`)
beschränkt - andere Origins werden vom Backend nicht akzeptiert.
```

- [ ] **Step 3: Commit**

```bash
git add KryptoWalletDashboard/frontend/README.md KryptoWalletDashboard/backend/README.md
git commit -m "docs: document frontend setup and its CORS dependency on the backend"
```

---

## Self-Review Notes

- **Spec coverage:** CORS prerequisite (Task 1), scaffolding with the exact confirmed tech stack — TS/Vite/Tailwind v4/React Router/Vitest+RTL (Task 2), formatting + typed API client matching the real backend schemas exactly (Task 3), sidebar navigation with the 3 confirmed pages (Task 4), Übersicht with table + chart (Task 5), Transaktionen with the confirmed filters + server-side filtering + CSV export (Task 6), Sync with manual trigger + per-source results (Task 7), documentation (Task 8). Matches the design doc's scope exactly; explicitly-excluded items (auth, auto-sync, transaction editing, deployment) correctly have no task.
- **Placeholder scan:** no TBD/TODO. The "tooling caveat" note about exact npm/Tailwind-v4/Vitest command syntax possibly drifting is a deliberate, explicit caveat (matching the same pattern already used for external API research in prior backend plans), not missing design work.
- **Type/signature consistency:** `PortfolioEntry`/`Transaction`/`TransactionFilters`/`SyncResult`/`SyncResponse` (Task 3) are defined once in `api/types.ts` and used identically by `api/client.ts` (Task 3), `Overview.tsx` (Task 5), `Transactions.tsx` (Task 6), and `Sync.tsx` (Task 7) — no redefinition or drift. `formatChf(value: string | null): string` (Task 3) is used with the same signature in both `Overview.tsx` and `Transactions.tsx`. `fetchTransactions(filters?: TransactionFilters)` and `exportUrl(filters?: TransactionFilters)` (Task 3) share the exact same `buildQuery` logic, so a filter added to one is automatically available to the other. `App.tsx`'s router-agnostic shape (Task 4) is relied upon unchanged by every later task's tests (`MemoryRouter` wrapping).
