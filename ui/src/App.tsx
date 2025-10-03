import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AppLayout } from "./components/layout/app-layout";
import { SyncsPage } from "./pages/syncs";
import { DashboardPlaceholderPage } from "./pages/dashboard-home";
import { ProvidersPage } from "./pages/providers";
import { ProviderCardPreviewPage } from "./pages/provider-card-preview";
import { AdminPage } from "./pages/admin";
import { ApiProvider } from "./lib/api-context";
import { ErrorPage } from "./components/layout/error-page";
import { LoginPage } from "./pages/login";
import { Ui2WorkspacePage } from "./pages/ui2";

const ui2Enabled = import.meta.env.VITE_UI2_ENABLED === "true";

const legacyChildren = [
  { path: "legacy-dashboard", element: <DashboardPlaceholderPage /> },
  { path: "syncs", element: <SyncsPage /> },
  { path: "providers", element: <ProvidersPage /> },
  { path: "providers/card-preview", element: <ProviderCardPreviewPage /> },
  { path: "admin", element: <AdminPage /> }
];

const router = createBrowserRouter(
  ui2Enabled
    ? [
        { path: "/", element: <Ui2WorkspacePage /> },
        {
          path: "/",
          element: <AppLayout />,
          errorElement: <ErrorPage />,
          children: legacyChildren
        },
        {
          path: "/login",
          element: <LoginPage />,
          errorElement: <ErrorPage />
        }
      ]
    : [
        {
          path: "/",
          element: <AppLayout />,
          errorElement: <ErrorPage />,
          children: [{ index: true, element: <DashboardPlaceholderPage /> }, ...legacyChildren]
        },
        {
          path: "/login",
          element: <LoginPage />,
          errorElement: <ErrorPage />
        }
      ],
  { basename: "/ui" }
);

export function App() {
  return (
    <ApiProvider>
      <RouterProvider router={router} />
    </ApiProvider>
  );
}

export default App;
