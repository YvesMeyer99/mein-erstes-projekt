import { useEffect, useState } from "react";
import { fetchConfig, saveConfig } from "../api/client";
import type { ConfigField } from "../api/types";

function groupBySection(fields: ConfigField[]): Map<string, ConfigField[]> {
  const groups = new Map<string, ConfigField[]>();
  for (const field of fields) {
    const existing = groups.get(field.section) ?? [];
    existing.push(field);
    groups.set(field.section, existing);
  }
  return groups;
}

function Konfiguration() {
  const [fields, setFields] = useState<ConfigField[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [sections, setSections] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchConfig()
      .then((response) => {
        setFields(response.fields);
        const initialValues: Record<string, string> = {};
        for (const field of response.fields) {
          initialValues[field.name] = field.value;
        }
        setValues(initialValues);

        const initialSections: Record<string, boolean> = {};
        for (const section of response.sections) {
          initialSections[section.name] = section.enabled;
        }
        setSections(initialSections);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await saveConfig(values, sections);
      setSaved(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (error && fields === null) {
    return (
      <div className="text-red-600">
        {error}. Läuft das Backend unter http://127.0.0.1:8000?
      </div>
    );
  }

  if (fields === null) {
    return <div>Konfiguration wird geladen…</div>;
  }

  const groupedSections = groupBySection(fields);

  return (
    <div>
      <h2 className="mb-4 text-xl font-semibold">Konfiguration</h2>
      <p className="mb-6 text-sm text-gray-500">
        Änderungen werden sofort in der .env-Datei gespeichert und beim nächsten Sync verwendet - kein
        Neustart nötig. Secret-Felder zeigen nie den gespeicherten Wert - leer lassen, um ihn unverändert
        zu behalten. Eine abgewählte Schnittstelle wird beim Sync übersprungen, ihre Werte bleiben aber
        erhalten.
      </p>

      {Array.from(groupedSections.entries()).map(([section, sectionFields]) => (
        <fieldset key={section} className="mb-6 rounded border border-gray-200 p-4">
          <legend className="flex items-center gap-2 px-1 text-sm font-semibold">
            <input
              type="checkbox"
              role="checkbox"
              aria-label={section}
              checked={sections[section] ?? true}
              onChange={(e) =>
                setSections((prev) => ({ ...prev, [section]: e.target.checked }))
              }
            />
            {section}
          </legend>
          <div className={sections[section] === false ? "space-y-3 opacity-50" : "space-y-3"}>
            {sectionFields.map((field) => (
              <div key={field.name}>
                <label htmlFor={field.name} className="mb-1 block text-sm text-gray-700">
                  {field.label}
                </label>
                <input
                  id={field.name}
                  type={field.is_secret ? "password" : "text"}
                  autoComplete={field.is_secret ? "new-password" : "off"}
                  value={values[field.name] ?? ""}
                  placeholder={field.is_secret ? "•••• (unverändert lassen, um bestehenden Wert zu behalten)" : field.hint}
                  onChange={(e) => setValues((prev) => ({ ...prev, [field.name]: e.target.value }))}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
                {!field.is_secret && field.hint && (
                  <p className="mt-1 text-xs text-gray-400">{field.hint}</p>
                )}
              </div>
            ))}
          </div>
        </fieldset>
      ))}

      <button
        onClick={handleSave}
        disabled={saving}
        className="rounded bg-gray-900 px-4 py-2 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
      >
        {saving ? "Speichert…" : "Speichern"}
      </button>

      {saved && <p className="mt-4 text-green-700">Gespeichert.</p>}
      {error && fields !== null && <p className="mt-4 text-red-600">{error}</p>}
    </div>
  );
}

export default Konfiguration;
