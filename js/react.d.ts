import type { ReactNode } from "react";
import type { Osservatore, Valore } from "./index";

export function ProviderOsservatore(props: { osservatore: Osservatore | null; children?: ReactNode }): ReactNode;
export function useOsservatore(): Osservatore | null;
export function useTraccia(): (nome: string, proprieta?: Record<string, Valore>) => void;
