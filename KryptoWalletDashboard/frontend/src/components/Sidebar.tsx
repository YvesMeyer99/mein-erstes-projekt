import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Übersicht" },
  { to: "/transactions", label: "Transaktionen" },
  { to: "/sync", label: "Sync" },
  { to: "/konfiguration", label: "Konfiguration" },
  { to: "/accounts", label: "Accounts" },
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
