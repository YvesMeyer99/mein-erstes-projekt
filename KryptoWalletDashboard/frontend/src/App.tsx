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
