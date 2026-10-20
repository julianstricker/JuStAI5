import {
  Alert,
  Button,
  Center,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useState } from "react";

import { api, ApiError } from "@/shared/api";
import { useT } from "@/shared/i18n";

import { errorMessage } from "../components/common";

export function LoginPage({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const t = useT();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/auth/login", { username, password });
      onLoggedIn();
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        const wait = (err.details as { retry_after_s?: number } | undefined)
          ?.retry_after_s;
        setError(
          t("login.tooMany", {
            when: wait ? t("login.inSeconds", { s: wait }) : t("login.later"),
          }),
        );
      } else if (err instanceof ApiError && err.status === 401) {
        setError(t("login.wrong"));
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Center h="100vh">
      <Paper withBorder shadow="md" p="xl" w={360}>
        <form onSubmit={submit}>
          <Stack>
            <Title order={2}>JuStAI5</Title>
            <Text c="dimmed" size="sm">
              {t("login.tagline")}
            </Text>
            {error && <Alert color="red">{error}</Alert>}
            <TextInput
              label={t("login.user")}
              value={username}
              onChange={(e) => setUsername(e.currentTarget.value)}
              autoFocus
            />
            <PasswordInput
              label={t("login.password")}
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
            />
            <Button type="submit" loading={busy}>
              {t("login.submit")}
            </Button>
            <Text size="xs" c="dimmed">
              {t("login.initialHint")}
            </Text>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
