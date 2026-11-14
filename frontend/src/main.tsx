import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
const App = () => <main><h1>MarsNav</h1><p>Integration scaffold. See the shared contracts and member tasks before implementing features.</p></main>;
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
