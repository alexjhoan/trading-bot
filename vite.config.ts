import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    host: "0.0.0.0",
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("error", (_err, _req, res) => {
            if (res && "writeHead" in res && !res.headersSent) {
              res.writeHead(502, { "Content-Type": "application/json" });
              res.end(
                JSON.stringify({
                  error: "Backend Python aún no iniciado en puerto 8000",
                }),
              );
            }
          });
        },
      },
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("error", (_err, _req, socket) => {
            try {
              if (
                socket &&
                !socket.destroyed &&
                typeof socket.destroy === "function"
              ) {
                socket.destroy();
              }
            } catch {
              // ignore
            }
          });
          proxy.on("proxyReqWs", (_proxyReq, _req, socket) => {
            socket.on("error", () => {});
          });
          proxy.on("open", (proxySocket) => {
            proxySocket.on("error", () => {});
          });
          proxy.on("close", () => {});
        },
      },
    },
  },
});
