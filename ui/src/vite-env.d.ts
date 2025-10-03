/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_UI2_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
