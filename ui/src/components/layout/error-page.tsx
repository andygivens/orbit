import { isRouteErrorResponse, useRouteError } from "react-router-dom";
import { Button } from "../ui/button";

export function ErrorPage() {
  const error = useRouteError();

  let title = "Something went wrong";
  let message = "An unexpected error occurred. Try refreshing or head back to the Syncs page.";

  if (isRouteErrorResponse(error)) {
    title = error.status === 404 ? "Page not found" : `Error ${error.status}`;
    message = error.statusText || message;
  } else if (error instanceof Error) {
    message = error.message;
  }

  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-4 bg-[var(--color-bg)] px-4 text-center">
      <div className="space-y-2">
        <h1 className="orbit-type-display font-bold text-[var(--color-text-strong)]">{title}</h1>
        <p className="orbit-text-subtle max-w-md">{message}</p>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-3">
  <Button onClick={() => window.location.assign("/ui/syncs")}>Go to Syncs</Button>
        <Button variant="outline" onClick={() => window.location.reload()}>Reload</Button>
      </div>
    </div>
  );
}

export default ErrorPage;
