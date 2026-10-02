// Standalone embed bundle. On the payer's portal page:
//   <script src="https://<middleware-host>/widget/payer-assistant.js"></script>
//   <script>
//     PayerAssistant.mount({
//       apiBase: "https://<middleware-host>",
//       getPortalToken: () => fetch("/my-portal/ai-token").then(r => r.text()),
//     });
//   </script>
import { createRoot } from "react-dom/client";
import PayerAssistant, { type PayerAssistantProps } from "./PayerAssistant";
import css from "./widget.css?inline";

export function mount(props: PayerAssistantProps & { target?: HTMLElement }) {
  const host = document.createElement("div");
  host.id = "payer-assistant-root";
  (props.target ?? document.body).appendChild(host);
  const shadow = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = css;
  shadow.appendChild(style);
  const mountPoint = document.createElement("div");
  shadow.appendChild(mountPoint);
  const root = createRoot(mountPoint);
  root.render(<PayerAssistant {...props} />);
  return { unmount: () => { root.unmount(); host.remove(); } };
}
