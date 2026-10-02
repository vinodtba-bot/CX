import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import AdminLayout from "./pages/admin/AdminLayout";
import Overview from "./pages/admin/Overview";
import Calls from "./pages/admin/Calls";
import CallDetailPage from "./pages/admin/CallDetail";
import AgentSettings from "./pages/admin/AgentSettings";
import AuditLog from "./pages/admin/AuditLog";
import PortalDemo from "./pages/PortalDemo";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/admin" replace />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<Overview />} />
          <Route path="calls" element={<Calls />} />
          <Route path="calls/:callId" element={<CallDetailPage />} />
          <Route path="agent" element={<AgentSettings />} />
          <Route path="audit" element={<AuditLog />} />
        </Route>
        <Route path="/portal" element={<PortalDemo />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
