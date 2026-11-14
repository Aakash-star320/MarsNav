import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Demo } from "./Demo";
const root = document.getElementById("root");
if (!root) throw new Error("Preview root is missing");
createRoot(root).render(<StrictMode><Demo /></StrictMode>);
