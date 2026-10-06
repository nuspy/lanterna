/* lanterna-osservatore — il lato browser di lanterna.
 *
 * Cosa misura, senza cookie e senza salvare nulla nel browser:
 * - `page_view` a ogni cambio di pagina (l'applicazione chiama `pagina()`: in una SPA solo lei sa
 *   quando il percorso è cambiato); alla prima pagina anche referrer e parametri UTM;
 * - `engagement`: il tempo **attivo** sulla pagina (scheda visibile e un'interazione negli ultimi 30
 *   secondi) e la profondità di scorrimento, mandato quando si cambia pagina o si nasconde la scheda;
 * - click sugli elementi con `data-an="nome"` (le proprietà da `data-an-*`), e i link esterni;
 * - viste degli elementi con `data-an-vista="nome"` (una volta per pagina, a metà dentro lo schermo);
 * - eventi dell'applicazione con `traccia(nome, proprieta)`.
 *
 * Il percorso si manda senza query string: può contenere dati personali. L'identificativo del
 * browser (`idBrowser`) si manda solo se l'applicazione lo restituisce, cioè col consenso.
 *
 * Invio a lotti, con `fetch(..., {keepalive: true})`: sopravvive alla chiusura della pagina e
 * permette l'intestazione `Authorization` (stessa origine). Nessun errore esce mai di qui.
 */

const INATTIVITA_MS = 30_000;
const NOME_VALIDO = /^[a-z][a-z0-9_]{0,63}$/;

function adesso() {
  return Date.now();
}

function percorsoAttuale() {
  return typeof location === "undefined" ? "/" : location.pathname || "/";
}

function utmDallaPagina() {
  const utm = {};
  try {
    new URLSearchParams(location.search).forEach((valore, chiave) => {
      if (chiave.startsWith("utm_") && valore) utm[chiave] = valore.slice(0, 200);
    });
  } catch {
    /* niente UTM */
  }
  return utm;
}

function proprietaDaDataset(el) {
  const x = {};
  for (const [chiave, valore] of Object.entries(el.dataset || {})) {
    if (chiave.startsWith("an") && chiave.length > 2 && chiave !== "anVista") {
      const nome = chiave.slice(2, 3).toLowerCase() + chiave.slice(3);
      x[nome] = String(valore).slice(0, 200);
    }
  }
  return x;
}

function automatizzato() {
  try {
    return typeof navigator !== "undefined" && navigator.webdriver === true;
  } catch {
    return false;
  }
}

/**
 * @param {import("./index").Opzioni} opzioni
 * @returns {import("./index").Osservatore}
 */
export function avvia(opzioni) {
  const o = {
    endpoint: "/api/e",
    intervalloMs: 5_000,
    maxInCoda: 10,
    esclusi: ["/admin"],
    ...opzioni,
  };
  const spento =
    typeof window === "undefined" || (automatizzato() && !o.ancheAutomatizzati);
  if (spento) {
    const nulla = () => {};
    return { pagina: nulla, traccia: nulla, svuota: nulla, ferma: nulla };
  }

  let coda = [];
  let primaPagina = true;
  let paginaCorrente = null;
  let attivoMs = 0;
  let ultimoTic = adesso();
  let ultimaInterazione = adesso();
  let scrollMax = 0;
  let visteGiaFatte = new Set();

  const escluso = (p) => o.esclusi.some((e) => p === e || p.startsWith(e.replace(/\/$/, "") + "/"));

  function accoda(n, extra = {}) {
    if (!NOME_VALIDO.test(n)) return;
    const p = extra.p ?? paginaCorrente ?? percorsoAttuale();
    if (escluso(p)) return;
    // Le proprietà comuni (es. la piattaforma, la variante della pagina) vanno in ogni evento, pagine viste comprese;
    // quelle dell'evento vincono a parità di nome.
    const comuni = typeof o.proprieta === "function" ? o.proprieta(p) : o.proprieta;
    const x = comuni && Object.keys(comuni).length ? { ...comuni, ...(extra.x ?? {}) } : extra.x;
    coda.push({ n, p, t: adesso(), ...extra, ...(x ? { x } : {}) });
    if (coda.length >= o.maxInCoda) svuota();
  }

  function svuota() {
    if (!coda.length) return;
    const lotto = coda.splice(0, 20);
    const ora = adesso();
    const corpo = {
      v: 1,
      lingua: safe(o.lingua) || undefined,
      id: safe(o.idBrowser) || undefined,
      eventi: lotto.map(({ t, ...e }) => ({ ...e, dt: Math.max(0, ora - t) })),
    };
    const intestazioni = { "content-type": "text/plain" };
    const token = safe(o.token);
    if (token) intestazioni.authorization = `Bearer ${token}`;
    try {
      fetch(o.endpoint, {
        method: "POST",
        body: JSON.stringify(corpo),
        headers: intestazioni,
        keepalive: true,
        credentials: "same-origin",
      }).catch(() => {});
    } catch {
      /* il browser ha rifiutato: si perde il lotto, non la pagina */
    }
    if (coda.length) svuota();
  }

  function safe(f) {
    try {
      return typeof f === "function" ? f() : null;
    } catch {
      return null;
    }
  }

  /* ---- tempo attivo e scorrimento ---- */

  function tic() {
    const ora = adesso();
    const visibile = document.visibilityState === "visible";
    if (visibile && ora - ultimaInterazione < INATTIVITA_MS) attivoMs += Math.min(ora - ultimoTic, 5_000);
    ultimoTic = ora;
  }

  function misuraScroll() {
    const altezza = document.documentElement.scrollHeight - window.innerHeight;
    const pct = altezza > 0 ? Math.round((window.scrollY / altezza) * 100) : 100;
    if (pct > scrollMax) scrollMax = Math.min(100, pct);
  }

  function chiudiPagina() {
    tic();
    if (paginaCorrente !== null && attivoMs > 0) {
      accoda("engagement", { p: paginaCorrente, d: Math.round(attivoMs), x: { scroll: scrollMax } });
    }
    attivoMs = 0;
    scrollMax = 0;
  }

  const interazione = () => {
    tic();
    ultimaInterazione = adesso();
  };

  /* ---- click e link esterni ---- */

  function suClick(evento) {
    interazione();
    const bersaglio = evento.target instanceof Element ? evento.target : null;
    if (!bersaglio) return;
    const marcato = bersaglio.closest("[data-an]");
    if (marcato) accoda(marcato.getAttribute("data-an"), { x: proprietaDaDataset(marcato) });
    const link = bersaglio.closest("a[href]");
    if (link && link.host && link.host !== location.host && /^https?:$/.test(link.protocol)) {
      accoda("link_esterno", { x: { dominio: link.hostname.replace(/^www\./, "") } });
    }
  }

  /* ---- viste degli elementi dichiarati ---- */

  let osservatoreViste = null;
  let osservatoreDom = null;
  if ("IntersectionObserver" in window) {
    osservatoreViste = new IntersectionObserver(
      (voci) => {
        for (const v of voci) {
          if (!v.isIntersecting) continue;
          const nome = v.target.getAttribute("data-an-vista");
          const chiave = `${paginaCorrente}|${nome}|${v.target.getAttribute("data-an-id") ?? ""}`;
          osservatoreViste.unobserve(v.target);
          if (!nome || visteGiaFatte.has(chiave)) continue;
          visteGiaFatte.add(chiave);
          accoda("vista", { x: { elemento: nome.slice(0, 64), ...proprietaDaDataset(v.target) } });
        }
      },
      { threshold: 0.5 },
    );
    const osservaTutti = () => document.querySelectorAll("[data-an-vista]").forEach((el) => osservatoreViste.observe(el));
    osservaTutti();
    if ("MutationObserver" in window) {
      let programmato = false;
      osservatoreDom = new MutationObserver(() => {
        if (programmato) return;
        programmato = true;
        setTimeout(() => {
          programmato = false;
          osservaTutti();
        }, 500);
      });
      osservatoreDom.observe(document.body, { childList: true, subtree: true });
    }
  }

  /* ---- uscita dalla pagina ---- */

  function suVisibilita() {
    if (document.visibilityState === "hidden") {
      chiudiPagina();
      svuota();
    } else {
      ultimoTic = adesso();
      ultimaInterazione = adesso();
    }
  }

  const ascoltatori = [
    [document, "click", suClick, { capture: true, passive: true }],
    [document, "keydown", interazione, { passive: true }],
    [window, "scroll", () => { interazione(); misuraScroll(); }, { passive: true }],
    [window, "pointermove", interazione, { passive: true }],
    [window, "touchstart", interazione, { passive: true }],
    [document, "visibilitychange", suVisibilita, {}],
    [window, "pagehide", () => { chiudiPagina(); svuota(); }, {}],
  ];
  for (const [bersaglio, tipo, f, opz] of ascoltatori) bersaglio.addEventListener(tipo, f, opz);
  const timer = setInterval(() => {
    tic();
    svuota();
  }, o.intervalloMs);

  return {
    pagina(percorso) {
      const p = percorso || percorsoAttuale();
      if (p === paginaCorrente) return;
      chiudiPagina();
      paginaCorrente = p;
      visteGiaFatte = new Set();
      ultimoTic = adesso();
      ultimaInterazione = adesso();
      const extra = { p };
      const utm = utmDallaPagina();
      if (Object.keys(utm).length) extra.u = utm;
      if (primaPagina) {
        if (document.referrer) extra.r = document.referrer;
        primaPagina = false;
      }
      accoda("page_view", extra);
      misuraScroll();
    },
    traccia(nome, proprieta) {
      accoda(nome, proprieta ? { x: proprieta } : {});
    },
    svuota,
    ferma() {
      chiudiPagina();
      svuota();
      clearInterval(timer);
      for (const [bersaglio, tipo, f, opz] of ascoltatori) bersaglio.removeEventListener(tipo, f, opz);
      osservatoreViste?.disconnect();
      osservatoreDom?.disconnect();
    },
  };
}

/** Revoca del livello esteso: il server dimentica l'identificativo di questo browser. */
export function dimentica(idBrowser, endpoint = "/api/e/dimentica") {
  try {
    fetch(endpoint, {
      method: "POST",
      body: JSON.stringify({ id: idBrowser }),
      headers: { "content-type": "text/plain" },
      keepalive: true,
    }).catch(() => {});
  } catch {
    /* niente */
  }
}
