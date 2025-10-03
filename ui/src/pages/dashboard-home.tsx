import { useNavigate } from "react-router-dom";

import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";

export function DashboardPlaceholderPage() {
  const navigate = useNavigate();

  return (
    <div className="mx-auto flex max-w-3xl flex-1 flex-col items-center justify-center gap-6 px-6 py-12 text-center">
      <Card className="w-full max-w-xl shadow-elev-2">
        <CardContent className="space-y-4 px-6 py-8">
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold text-[var(--color-text-strong)]">
              Dashboard coming soon
            </h1>
            <p className="text-sm text-[var(--color-text-soft)]">
              We&apos;re building a new monitoring dashboard that will roll out shortly. In the meantime, head over to the
              Syncs page to manage your connections and trigger runs.
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Button onClick={() => navigate("/syncs")}>Go to Syncs</Button>
            <Button variant="ghost" onClick={() => navigate("/providers")}>
              Manage providers
            </Button>
          </div>
        </CardContent>
      </Card>
      <p className="text-xs text-[var(--color-text-muted)]">
        Need deeper insights? Check the Provider or Admin sections while we finish the dashboard experience.
      </p>
    </div>
  );
}

export default DashboardPlaceholderPage;
