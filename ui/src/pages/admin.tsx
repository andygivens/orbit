import { useEffect, useState } from "react";
import { format, parseISO } from "date-fns";
import { KeyRound, Users, RefreshCcw, Loader2, TriangleAlert, Eye, EyeOff } from "lucide-react";

import { useApi } from "../lib/api-context";
import type { OAuthClient } from "../types/api";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";

type FetchState<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
};

const initialState = <T,>(): FetchState<T> => ({ data: null, loading: true, error: null });

export function AdminPage() {
  const { auth, client } = useApi();
  const [oauthClients, setOauthClients] = useState<FetchState<OAuthClient[]>>(initialState);
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [isApiKeyVisible, setIsApiKeyVisible] = useState(false);

  const loadData = async () => {
    if (auth.status !== "authenticated") {
      return;
    }

    setOauthClients(initialState);

    try {
      const clientsRes = await client.listOAuthClients();
      setOauthClients({ data: clientsRes, loading: false, error: null });

      const apiKeyRes = await client.getApiKey();
      setApiKey(apiKeyRes.key);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load admin data";
      setOauthClients((prev) => ({ ...prev, loading: false, error: message }));
    }
  };

  const generateApiKey = async () => {
    try {
      const newKey = await client.generateApiKey();
      setApiKey(newKey.key);
    } catch (error) {
      console.error("Failed to generate API key", error);
    }
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.status, client]);

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-2">
          <h1 className="orbit-heading-lg">Admin controls</h1>
          <p className="orbit-text-subtle">
            Inspect service configuration, credentials, and OAuth clients provisioned for Orbit.
          </p>
        </div>
        <Button onClick={loadData} disabled={auth.status !== "authenticated"} variant="ghost">
          <RefreshCcw className="mr-2 h-4 w-4" />
          Refresh data
        </Button>
      </section>

      <section className="grid gap-4 lg:grid-cols-1">
        <Card>
          <CardHeader className="items-start justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Users className="h-5 w-5 text-[var(--accent-600)]" />
                OAuth clients
              </CardTitle>
              <p className="orbit-text-subtle">
                Machine or delegated access configured via Orbit’s OAuth provider.
              </p>
            </div>
            <Badge variant="outline">{oauthClients.data?.length ?? 0} clients</Badge>
          </CardHeader>
          <CardContent>
            {oauthClients.loading ? (
              <LoadingState label="Loading OAuth clients" />
            ) : oauthClients.error ? (
              <ErrorState message={oauthClients.error} />
            ) : oauthClients.data && oauthClients.data.length ? (
              <div className="space-y-3">
                {oauthClients.data.map((client) => (
                  <div
                    key={client.client_id}
                    className="rounded-md border border-border-subtle bg-[var(--color-bg)] p-4 text-sm shadow-elev-1"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-semibold">{client.name}</span>
                      <Badge variant={client.is_active ? "success" : "danger"}>
                        {client.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </div>
                    <div className="mt-2 grid gap-1 text-xs text-[var(--color-text-soft)]">
                      <span>ID: {client.client_id}</span>
                      <span>Scopes: {client.scopes}</span>
                      <span>Created: {format(parseISO(client.created_at), "MMM d, yyyy HH:mm")}</span>
                      {client.description && <span>Description: {client.description}</span>}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState message="No OAuth clients registered yet." />
            )}
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader className="items-start justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <KeyRound className="h-5 w-5 text-[var(--accent-600)]" />
                API Key Management
              </CardTitle>
              <p className="orbit-text-subtle">
                Generate, view, and manage the Orbit API key.
              </p>
            </div>
          </CardHeader>
          <CardContent>
            {apiKey ? (
              <div className="flex items-center gap-4">
                <input
                  type={isApiKeyVisible ? "text" : "password"}
                  value={apiKey}
                  readOnly
                  className="orbit-input"
                />
                <Button
                  variant="ghost"
                  onClick={() => setIsApiKeyVisible((prev) => !prev)}
                >
                  {isApiKeyVisible ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                </Button>
              </div>
            ) : (
              <Button onClick={generateApiKey} variant="primary">
                Generate API Key
              </Button>
            )}
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader className="items-start justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <KeyRound className="h-5 w-5 text-[var(--accent-600)]" />
                API key guidance
              </CardTitle>
              <p className="orbit-text-subtle">
                Remind operators how to supply or rotate the Orbit API key securely.
              </p>
            </div>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-2 pl-5 text-sm text-[var(--color-text-soft)]">
              <li>The UI keeps the key in memory only; reload the page to clear it.</li>
              <li>For deployments, expose the key via environment variable `ORBIT_API_KEY`.</li>
              <li>Rotate the key and recycle the container if an operator leaves.</li>
            </ul>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-[var(--color-text-soft)]">
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 px-3 py-2 text-sm text-[var(--color-danger)]">
      <TriangleAlert className="h-4 w-4" />
      {message}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-dashed border-border-subtle bg-[var(--color-hover)]/40 px-3 py-6 text-center text-sm text-[var(--color-text-soft)]">
      {message}
    </div>
  );
}
