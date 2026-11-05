import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "./glass.css";

import { MantineProvider, createTheme } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { I18nProvider } from "@/shared/i18n";

import { App } from "./App";

const theme = createTheme({
  primaryColor: "indigo",
  defaultRadius: "lg",
  fontFamily:
    "Inter, -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, Segoe UI, Roboto, sans-serif",
  headings: { fontWeight: "700" },
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>
        <I18nProvider>
          <App />
        </I18nProvider>
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
