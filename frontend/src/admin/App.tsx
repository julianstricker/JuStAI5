import { Center, Loader } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router";

import { ApiError, api } from "@/shared/api";
import type { Me } from "@/shared/types";

import { AuthContext } from "./auth";
import { Layout } from "./components/Layout";
import { AIPage } from "./pages/AIPage";
import { AudioPage } from "./pages/AudioPage";
import { AutomationsPage } from "./pages/AutomationsPage";
import { ConversationsPage } from "./pages/ConversationsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DevicesPage } from "./pages/DevicesPage";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { DisplaysPage } from "./pages/DisplaysPage";
import { LoginPage } from "./pages/LoginPage";
import { MemoryPage } from "./pages/MemoryPage";
import { PeoplePage } from "./pages/PeoplePage";
import { PluginsPage } from "./pages/PluginsPage";
import { RoomsPage } from "./pages/RoomsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ToolsPage } from "./pages/ToolsPage";
import { VisionPage } from "./pages/VisionPage";

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "rooms", element: <RoomsPage /> },
      { path: "devices", element: <DevicesPage /> },
      { path: "audio", element: <AudioPage /> },
      { path: "conversations", element: <ConversationsPage /> },
      { path: "ai", element: <AIPage /> },
      { path: "people", element: <PeoplePage /> },
      { path: "memory", element: <MemoryPage /> },
      { path: "automations", element: <AutomationsPage /> },
      { path: "vision", element: <VisionPage /> },
      { path: "displays", element: <DisplaysPage /> },
      { path: "plugins", element: <PluginsPage /> },
      { path: "tools", element: <ToolsPage /> },
      { path: "diagnostics", element: <DiagnosticsPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);

export function App() {
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<Me>("/api/auth/me"),
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 2,
  });
  if (me.isLoading)
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  if (!me.data) return <LoginPage onLoggedIn={() => me.refetch()} />;
  return (
    <AuthContext.Provider value={me.data}>
      <RouterProvider router={router} />
    </AuthContext.Provider>
  );
}
