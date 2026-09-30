from datetime import date

from lanterna.insight import Fatti, anomalie, da_imbuto, da_risultato, numeri_nel_testo, pendenza, significativita, valida
from lanterna.interroga import Risultato


def _risultato():
    colonne = [
        {"nome": "canale", "etichetta": "Canale", "tipo": "dimensione"},
        {"nome": "sessioni", "etichetta": "Sessioni", "tipo": "misura", "formato": "intero"},
    ]
    return Risultato(
        colonne=colonne,
        righe=[{"canale": "ricerca", "sessioni": 300}, {"canale": "social", "sessioni": 100}],
        totali={"sessioni": 400},
        da=date(2026, 9, 1), a=date(2026, 9, 30),
        confronto={"tipo": "precedente", "da": "2026-08-02", "a": "2026-08-31",
                   "righe": [{"canale": "ricerca", "sessioni": 200}, {"canale": "social", "sessioni": 100}],
                   "totali": {"sessioni": 300}, "soppresse": 0},
    )


def test_significativita():
    assert "pochi dati" in significativita(10, 12)
    assert "oltre il caso" in significativita(400, 300)
    assert "compatibile" in significativita(310, 300)


def test_anomalie_e_pendenza():
    serie = [10, 11, 9, 10, 12, 10, 60, 11, 10]
    assert anomalie(serie) == [6]
    assert pendenza([1, 2, 3, 4, 5]) > 0
    assert pendenza([5, 4, 3, 2, 1]) < 0


def test_fatti_da_un_risultato_con_confronto():
    fatti = Fatti()
    da_risultato(fatti, "Traffico", _risultato())
    testi = [f.testo for f in fatti.elenco]
    assert testi[0].startswith("Sessioni: 400 (periodo precedente 300, +33.3%)")
    ricerca = next(t for t in testi if "ricerca" in t)
    assert "quota 75.0%" in ricerca and "+50.0%" in ricerca and "spiega il 100%" in ricerca
    assert [f.id for f in fatti.elenco] == [f"M{i}" for i in range(1, len(fatti.elenco) + 1)]


def test_fatti_da_imbuto():
    fatti = Fatti()
    da_imbuto(fatti, "Lettura", {"passi": [
        {"etichetta": "A", "n": 100, "dal_primo": 1, "dal_precedente": 1},
        {"etichetta": "B", "n": 40, "dal_primo": 0.4, "dal_precedente": 0.4},
        {"etichetta": "C", "n": 30, "dal_primo": 0.3, "dal_precedente": 0.75},
    ]})
    assert any("perdita più grande" in f.testo and "«A» e «B»" in f.testo for f in fatti.elenco)


def test_numeri_nel_testo_formati_italiani():
    assert numeri_nel_testo("1.234,5 euro, +33,3% e 75.0% (M12)") == [1234.5, 33.3, 75.0]


def test_la_verifica_segnala_numeri_inventati_e_citazioni_false():
    fatti = Fatti()
    da_risultato(fatti, "Traffico", _risultato())
    risposta = {
        "sintesi": "Le sessioni sono salite a 400 (+33,3%).",
        "osservazioni": [
            {"titolo": "Cresce la ricerca", "testo": "La ricerca porta il 75% delle sessioni.", "fatti": ["M2"]},
            {"titolo": "Inventato", "testo": "Il social vale 912 sessioni.", "fatti": ["M3"]},
            {"titolo": "Senza fonti", "testo": "Tutto bene.", "fatti": ["M99"]},
        ],
        "azioni": [{"testo": "Investire in SEO", "metrica": "sessioni da ricerca", "fatti": []}],
    }
    v = valida(risposta, fatti)
    assert v["sintesi_verificata"]
    stato = [(o["titolo"], o["verificato"]) for o in v["osservazioni"]]
    assert stato == [("Cresce la ricerca", True), ("Inventato", False), ("Senza fonti", False)]
    assert v["osservazioni"][1]["numeri_non_trovati"] == [912.0]
    assert v["osservazioni"][2]["fatti"] == []
    assert v["azioni"][0]["verificato"]  # un'azione senza numeri non ha bisogno di citazioni
    assert v["verifica"]["citazioni_inesistenti"] == 1
