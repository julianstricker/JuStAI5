// Renders a form for a (flat) JSON schema: string/number/integer/boolean/enum
// fields; arrays and objects are edited as JSON. Secret fields are password inputs
// that stay empty unless the user types a new value.
import {
  Checkbox,
  JsonInput,
  NumberInput,
  PasswordInput,
  Select,
  Stack,
  TextInput,
} from "@mantine/core";

import type { JsonSchema } from "@/shared/types";

import { useI18n } from "@/shared/i18n";

interface Props {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  secretFields?: string[];
  secretsSet?: string[];
}

export function JsonSchemaForm({
  schema,
  value,
  onChange,
  secretFields = [],
  secretsSet = [],
}: Props) {
  const { lang, t } = useI18n();
  const props = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const set = (key: string, v: unknown) => onChange({ ...value, [key]: v });

  return (
    <Stack gap="sm">
      {Object.entries(props).map(([key, field]) => {
        const loc = field["x-i18n"]?.[lang];
        const label = loc?.title ?? field.title ?? key;
        const description = loc?.description ?? field.description;
        const current = value[key] ?? field.default;
        const type = Array.isArray(field.type) ? field.type[0] : field.type;
        if (secretFields.includes(key)) {
          return (
            <PasswordInput
              key={key}
              label={label}
              description={
                secretsSet.includes(key)
                  ? t("form.secretStored", { desc: description ?? "" })
                  : description
              }
              value={(value[key] as string) ?? ""}
              onChange={(e) => set(key, e.currentTarget.value)}
              autoComplete="new-password"
            />
          );
        }
        if (field.enum) {
          return (
            <Select
              key={key}
              label={label}
              description={description}
              data={field.enum.map((o) => String(o))}
              value={current === undefined ? null : String(current)}
              onChange={(v) => set(key, v)}
              required={required.has(key)}
            />
          );
        }
        if (type === "boolean") {
          return (
            <Checkbox
              key={key}
              label={label}
              description={description}
              checked={Boolean(current)}
              onChange={(e) => set(key, e.currentTarget.checked)}
            />
          );
        }
        if (type === "number" || type === "integer") {
          return (
            <NumberInput
              key={key}
              label={label}
              description={description}
              value={(current as number) ?? ""}
              min={field.minimum}
              max={field.maximum}
              allowDecimal={type === "number"}
              onChange={(v) => set(key, typeof v === "number" ? v : undefined)}
              required={required.has(key)}
            />
          );
        }
        if (type === "array" || type === "object") {
          return (
            <JsonInput
              key={key}
              label={label}
              description={description}
              autosize
              minRows={3}
              formatOnBlur
              defaultValue={JSON.stringify(
                current ?? (type === "array" ? [] : {}),
                null,
                2,
              )}
              onChange={(text) => {
                try {
                  set(key, JSON.parse(text));
                } catch {
                  /* keep editing */
                }
              }}
            />
          );
        }
        return (
          <TextInput
            key={key}
            label={label}
            description={description}
            value={(current as string) ?? ""}
            onChange={(e) => set(key, e.currentTarget.value)}
            required={required.has(key)}
          />
        );
      })}
    </Stack>
  );
}
