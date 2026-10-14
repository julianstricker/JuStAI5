import { AppShell, Burger, Group, NavLink, ScrollArea, Text, ThemeIcon, Tooltip } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconAdjustments,
  IconBrain,
  IconCamera,
  IconDashboard,
  IconDeviceTv,
  IconDoor,
  IconEye,
  IconLogout,
  IconMessages,
  IconMicrophone,
  IconPlugConnected,
  IconRobot,
  IconSettingsAutomation,
  IconStethoscope,
  IconTool,
  IconUsers,
} from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useLocation } from "react-router";

import { api } from "@/shared/api";

import { useMe } from "../auth";
import { PrivacyIndicator } from "./PrivacyIndicator";

const NAV = [
  { to: "/", label: "Dashboard", icon: IconDashboard },
  { to: "/rooms", label: "Räume", icon: IconDoor },
  { to: "/devices", label: "Geräte", icon: IconCamera },
  { to: "/audio", label: "Audio", icon: IconMicrophone },
  { to: "/conversations", label: "Gespräche", icon: IconMessages },
  { to: "/ai", label: "KI-Provider", icon: IconRobot },
  { to: "/people", label: "Personen", icon: IconUsers },
  { to: "/memory", label: "Gedächtnis", icon: IconBrain },
  { to: "/automations", label: "Automationen", icon: IconSettingsAutomation },
  { to: "/vision", label: "Vision", icon: IconEye },
  { to: "/displays", label: "Displays", icon: IconDeviceTv },
  { to: "/plugins", label: "Plugins", icon: IconPlugConnected },
  { to: "/tools", label: "Tools", icon: IconTool },
  { to: "/diagnostics", label: "Diagnose", icon: IconStethoscope },
  { to: "/settings", label: "Einstellungen", icon: IconAdjustments },
];

export function Layout() {
  const [opened, { toggle, close }] = useDisclosure();
  const location = useLocation();
  const me = useMe();
  const qc = useQueryClient();

  const logout = async () => {
    await api.post("/api/auth/logout");
    qc.setQueryData(["me"], null);
    window.location.assign("/");
  };

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 230, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <ThemeIcon variant="gradient" size="lg" radius="xl">
              <IconRobot size={20} />
            </ThemeIcon>
            <Text fw={700}>JuStAI5</Text>
          </Group>
          <Group gap="md">
            <PrivacyIndicator />
            <Text size="sm" c="dimmed">
              {me.username} ({me.role})
            </Text>
            <Tooltip label="Abmelden">
              <IconLogout style={{ cursor: "pointer" }} size={20} onClick={logout} />
            </Tooltip>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        <ScrollArea>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              component={Link}
              to={item.to}
              label={item.label}
              leftSection={<item.icon size={18} />}
              active={item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to)}
              onClick={close}
            />
          ))}
        </ScrollArea>
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
