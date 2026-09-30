/* Il ponte con React: un contesto con l'osservatore e un hook per gli eventi dell'applicazione.
 *
 *   <ProviderOsservatore osservatore={o}>…</ProviderOsservatore>
 *   const traccia = useTraccia();  traccia("lettura_fase", { fase: "responso" });
 *
 * Senza provider l'hook restituisce una funzione che non fa nulla: un componente riusato fuori dal
 * sito (anteprime, test) non deve rompersi. */
import { createContext, createElement, useCallback, useContext } from "react";

const Contesto = createContext(null);

export function ProviderOsservatore({ osservatore, children }) {
  return createElement(Contesto.Provider, { value: osservatore }, children);
}

export function useOsservatore() {
  return useContext(Contesto);
}

export function useTraccia() {
  const o = useContext(Contesto);
  return useCallback((nome, proprieta) => o?.traccia(nome, proprieta), [o]);
}
