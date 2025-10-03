import { createContext, useContext } from "react";

import type { Provider } from "../../types/api";

export type ProviderData = Provider;

export type ProvidersContextValue = {
  providers: Provider[];
  onRefresh: () => void;
};

export const ProvidersContext = createContext<ProvidersContextValue | null>(null);

export function useProvidersContext(): ProvidersContextValue {
  const context = useContext(ProvidersContext);
  if (!context) {
    throw new Error("useProvidersContext must be used within ProvidersContext.Provider");
  }
  return context;
}
