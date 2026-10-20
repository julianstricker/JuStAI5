import {
  AppShell,
  Burger,
  Group,
  NavLink,
  ScrollArea,
  Select,
  Text,
  ThemeIcon,
  Tooltip,
} from "@mantine/core";
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
import { type Key, type Lang, LANGS, useI18n } from "@/shared/i18n";

import { useMe } from "../auth";
import { PrivacyIndicator } from "./PrivacyIndicator";

const NAV: { to: string; label: Key; icon: typeof IconDashboard }[] = [
  { to: "/", label: "nav.dashboard", icon: IconDashboard },
  { to: "/rooms", label: "nav.rooms", icon: IconDoor },
  { to: "/devices", label: "nav.devices", icon: IconCamera },
  { to: "/audio", label: "nav.audio", icon: IconMicrophone },
  { to: "/conversations", label: "nav.conversations", icon: IconMessages },
  { to: "/ai", label: "nav.ai", icon: IconRobot },
  { to: "/people", label: "nav.people", icon: IconUsers },
  { to: "/memory", label: "nav.memory", icon: IconBrain },
  {
    to: "/automations",
    label: "nav.automations",
    icon: IconSettingsAutomation,
  },
  { to: "/vision", label: "nav.vision", icon: IconEye },
  { to: "/displays", label: "nav.displays", icon: IconDeviceTv },
  { to: "/plugins", label: "nav.plugins", icon: IconPlugConnected },
  { to: "/tools", label: "nav.tools", icon: IconTool },
  { to: "/diagnostics", label: "nav.diagnostics", icon: IconStethoscope },
  { to: "/settings", label: "nav.settings", icon: IconAdjustments },
];

export function Layout() {
  const [opened, { toggle, close }] = useDisclosure();
  const location = useLocation();
  const me = useMe();
  const qc = useQueryClient();
  const { lang, setLang, t } = useI18n();

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
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
            />
            <ThemeIcon variant="gradient" size="lg" radius="xl">
              <IconRobot size={20} />
            </ThemeIcon>
            <Text fw={700}>JuStAI5</Text>
          </Group>
          <Group gap="md">
            <PrivacyIndicator />
            <Select
              aria-label={t("shell.language")}
              size="xs"
              w={110}
              data={LANGS.map((l) => ({ value: l.code, label: l.label }))}
              value={lang}
              onChange={(v) => v && setLang(v as Lang)}
              allowDeselect={false}
            />
            <Text size="sm" c="dimmed">
              {me.username} ({me.role})
            </Text>
            <Tooltip label={t("shell.logout")}>
              <IconLogout
                style={{ cursor: "pointer" }}
                size={20}
                onClick={logout}
              />
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
              label={t(item.label)}
              leftSection={<item.icon size={18} />}
              active={
                item.to === "/"
                  ? location.pathname === "/"
                  : location.pathname.startsWith(item.to)
              }
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
