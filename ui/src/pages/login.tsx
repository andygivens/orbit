import { useEffect, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { LogIn, Sparkles } from "lucide-react";

import { useApi } from "../lib/api-context";
import { Button } from "../components/ui/button";
import { cn } from "../lib/utils";

export function LoginPage() {
  const { auth, login } = useApi();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string })?.from ?? "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (auth.status === "authenticated") {
      navigate(from, { replace: true });
    }
  }, [auth.status, from, navigate]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Login failed";
      setError(message);
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg)] px-4">
      <div className="w-full max-w-sm space-y-6 rounded-2xl border border-border-subtle bg-[var(--color-surface)] p-8 shadow-elev-2">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex items-center gap-2 text-2xl font-semibold text-[var(--color-text-strong)]">
            <Sparkles className="h-6 w-6 text-[var(--accent-600)]" />
            Orbit
          </div>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <label className="text-xs font-medium text-[var(--color-text-soft)]" htmlFor="username">
              Username
            </label>
            <input
              id="username"
              name="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="w-full rounded-md border border-border-strong bg-[var(--color-bg)] px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-600)]"
              autoComplete="username"
              disabled={isSubmitting}
              required
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium text-[var(--color-text-soft)]" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-md border border-border-strong bg-[var(--color-bg)] px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-600)]"
              autoComplete="current-password"
              disabled={isSubmitting}
              required
            />
          </div>

          {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}

          <Button
            type="submit"
            variant="primary"
            size="sm"
            className={cn("w-full gap-2", isSubmitting && "opacity-80")}
            disabled={isSubmitting}
          >
            <LogIn className="h-4 w-4" />
            {isSubmitting ? "Signing in" : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}

export default LoginPage;
