from lanterna.avvisi import valuta

NORMALE = [40, 42, 38, 45, 41, 39, 44, 40, 43, 37, 41, 42, 40, 39]


def test_nessun_avviso_nel_normale():
    assert valuta("sessioni", "Visite", NORMALE, 44) is None


def test_zero_quando_di_solito_non_lo_e():
    a = valuta("letture", "Letture completate", NORMALE, 0)
    assert a.tipo == "zero" and "Possibile guasto" in a.testo()


def test_picco_e_crollo():
    assert valuta("sessioni", "Visite", NORMALE, 120).tipo == "picco"
    assert valuta("sessioni", "Visite", NORMALE, 10).tipo == "crollo"


def test_numeri_piccoli_e_poca_storia_non_avvisano():
    assert valuta("acquisti", "Acquisti", [0, 1, 0, 2, 0, 1, 0, 0], 3) is None
    assert valuta("sessioni", "Visite", NORMALE[:5], 500) is None


def test_errori_solo_in_salita():
    storia = [0, 0, 1, 0, 0, 0, 1, 0]
    assert valuta("errori", "Errori", storia, 5, cattiva=True).tipo == "errori"
    assert valuta("errori", "Errori", storia, 1, cattiva=True) is None
    assert valuta("errori", "Errori", [5] * 10, 0, cattiva=True) is None
