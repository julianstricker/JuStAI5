import { Alert, Button, Center, Paper, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { useState } from "react";

import { api } from "@/shared/api";

import { errorMessage } from "../components/common";

export function LoginPage({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/auth/login", { username, password });
      onLoggedIn();
    } catch (err) {
      setError(errorMessage(err));
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
              Turn ordinary cameras into intelligent AI assistants.
            </Text>
            {error && <Alert color="red">{error}</Alert>}
            <TextInput label="Benutzer" value={username} onChange={(e) => setUsername(e.currentTarget.value)} autoFocus />
            <PasswordInput label="Passwort" value={password} onChange={(e) => setPassword(e.currentTarget.value)} />
            <Button type="submit" loading={busy}>
              Anmelden
            </Button>
            <Text size="xs" c="dimmed">
              Das initiale Admin-Passwort steht beim ersten Start in data/initial_admin_password.txt bzw. im Log.
            </Text>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
