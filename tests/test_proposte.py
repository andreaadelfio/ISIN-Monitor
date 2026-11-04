from core import proposte

URL = 'https://esempio.pages.dev'


def riga(isin, nome, segnale, punteggio, errore=None):
    return {'isin': isin, 'nome': nome, 'segnale': segnale, 'punteggio': punteggio, 'errore': errore}


def test_proposta_del_giorno_e_il_compra_migliore_senza_errori():
    stato = proposte.stato_attuale([
        riga('A', 'Alfa', 'compra', 60),
        riga('B', 'Beta', 'compra', 80, errore='dati mancanti'),
        riga('C', 'Gamma', 'compra', 70),
        riga('D', 'Delta', 'attendi', 95),
        riga('E', 'Eta', None, None),
    ])
    assert stato['proposta'] == 'C'
    assert stato['segnali'] == {'A': 'compra', 'C': 'compra', 'D': 'attendi'}


def test_nessun_cambiamento_nessun_messaggio():
    prima = proposte.stato_attuale([riga('A', 'Alfa', 'compra', 60)])
    adesso = proposte.stato_attuale([riga('A', 'Alfa', 'compra', 65)])
    cambi = proposte.cambiamenti(prima, adesso)
    assert cambi == {'segnali': [], 'proposta': False}
    assert proposte.messaggio(prima, adesso, cambi, URL) is None


def test_segnali_e_proposta_cambiati():
    prima = proposte.stato_attuale([riga('A', 'Alfa', 'compra', 60), riga('C', 'Gamma', 'attendi', 50)])
    adesso = proposte.stato_attuale([riga('A', 'Alfa', 'valuta', 40), riga('C', 'Gamma', 'compra', 75),
                                     riga('N', 'Nuovo & C', 'evita', 10)])
    cambi = proposte.cambiamenti(prima, adesso)
    assert sorted(cambi['segnali']) == [('A', 'compra', 'valuta'), ('C', 'attendi', 'compra'),
                                        ('N', None, 'evita')]
    assert cambi['proposta']
    testo = proposte.messaggio(prima, adesso, cambi, URL)
    assert 'Proposta del giorno: <a href="https://esempio.pages.dev/?isin=C">Gamma</a> · 75/100' in testo
    assert 'prima era <a href="https://esempio.pages.dev/?isin=A">Alfa</a>' in testo
    assert '🟡 <a href="https://esempio.pages.dev/?isin=A">Alfa</a>: Compra → <b>Da valutare</b> · 40/100' in testo
    assert 'Nuovo &amp; C</a>: nuovo → <b>Evita per ora</b> · 10/100' in testo
    # Prima i Compra, poi Da valutare, poi Evita
    segnali = [r for r in testo.split('\n') if r[:1] in '🟢🟡⚪🔴' and r]
    assert [r.split('>')[1].split('<')[0] for r in segnali] == ['Gamma', 'Alfa', 'Nuovo &amp; C']


def test_nessun_compra():
    prima = proposte.stato_attuale([riga('A', 'Alfa', 'compra', 60)])
    adesso = proposte.stato_attuale([riga('A', 'Alfa', 'attendi', 60)])
    testo = proposte.messaggio(prima, adesso, proposte.cambiamenti(prima, adesso), URL)
    assert 'Nessuna proposta oggi' in testo
