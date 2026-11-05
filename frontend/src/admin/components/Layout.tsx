import {
  ActionIcon,
  AppShell,
  Burger,
  Group,
  Menu,
  NavLink,
  ScrollArea,
  Select,
  Text,
  ThemeIcon,
  Tooltip,
  useMantineColorScheme,
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
  IconDeviceDesktop,
  IconLogout,
  IconMoon,
  IconMessages,
  IconMicrophone,
  IconPlugConnected,
  IconRobot,
  IconSettingsAutomation,
  IconStethoscope,
  IconTool,
  IconSun,
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

function ThemeToggle() {
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const { t } = useI18n();
  const Icon =
    colorScheme === "dark"
      ? IconMoon
      : colorScheme === "light"
        ? IconSun
        : IconDeviceDesktop;
  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <ActionIcon variant="default" size="lg" aria-label={t("shell.theme")}>
          <Icon size={18} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item
          leftSection={<IconSun size={16} />}
          onClick={() => setColorScheme("light")}
        >
          {t("shell.themeLight")}
        </Menu.Item>
        <Menu.Item
          leftSection={<IconMoon size={16} />}
          onClick={() => setColorScheme("dark")}
        >
          {t("shell.themeDark")}
        </Menu.Item>
        <Menu.Item
          leftSection={<IconDeviceDesktop size={16} />}
          onClick={() => setColorScheme("auto")}
        >
          {t("shell.themeAuto")}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}

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
      header={{ height: 72 }}
      navbar={{ width: 230, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header className="g-header">
        <Group className="g-header-inner g-glass" justify="space-between">
          <Group gap="xs">
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
            />
            <ThemeIcon className="g-logo" size="lg" radius="xl">
              <IconRobot size={20} />
            </ThemeIcon>
            <Text className="g-brand">JuStAI</Text>
          </Group>
          <Group gap="md">
            <PrivacyIndicator />
            <ThemeToggle />
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
      <AppShell.Navbar className="g-navbar">
        <ScrollArea className="g-navbar-inner g-glass">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              className="g-nav-link"
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
