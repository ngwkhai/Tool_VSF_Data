import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import "./styles.css";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { Batches } from "./pages/Batches";
import { BatchDetail } from "./pages/BatchDetail";
import { JobDetail } from "./pages/JobDetail";
import { Triage } from "./pages/Triage";
import { Doctor } from "./pages/Doctor";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="batches" element={<Batches />} />
          <Route path="batches/:id" element={<BatchDetail />} />
          <Route path="jobs/:id" element={<JobDetail />} />
          <Route path="triage" element={<Triage />} />
          <Route path="doctor" element={<Doctor />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
