export type Valore = string | number | boolean | null;

export interface Opzioni {
  /** Dove si mandano i lotti. Predefinito `/api/e`. */
  endpoint?: string;
  /** Ogni quanto si svuota la coda. Predefinito 5000 ms. */
  intervalloMs?: number;
  /** Con quanti eventi in coda si invia subito. Predefinito 10. */
  maxInCoda?: number;
  /** Prefissi di percorso mai misurati. Predefinito `["/admin"]`. */
  esclusi?: string[];
  /** La lingua dell'interfaccia (es. `it`). */
  lingua?: () => string | null | undefined;
  /** L'identificativo del browser, **solo col consenso**: altrimenti `null`. */
  idBrowser?: () => string | null | undefined;
  /** Il token di accesso, se l'utente è autenticato (sincrono: serve anche alla chiusura). */
  token?: () => string | null | undefined;
  /** Misura anche i browser automatizzati (`navigator.webdriver`): solo per i test. */
  ancheAutomatizzati?: boolean;
  /** Proprietà aggiunte a ogni evento, pagine viste comprese: fisse o calcolate dal percorso. Quelle dell'evento
   *  vincono a parità di nome. Es. `(p) => ({ piattaforma: "web" })`. */
  proprieta?: Record<string, Valore> | ((percorso: string) => Record<string, Valore> | undefined);
}

export interface Osservatore {
  /** Una pagina vista: da chiamare a ogni cambio di percorso. */
  pagina(percorso?: string): void;
  /** Un evento dell'applicazione (nome: minuscole, cifre, `_`). */
  traccia(nome: string, proprieta?: Record<string, Valore>): void;
  /** Invia subito quanto è in coda. */
  svuota(): void;
  /** Smette di osservare e invia ciò che resta. */
  ferma(): void;
}

export function avvia(opzioni: Opzioni): Osservatore;
export function dimentica(idBrowser: string, endpoint?: string): void;
