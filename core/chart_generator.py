#!/usr/bin/env python3
"""
Generatore di grafici per ISIN Monitor.

I dati arrivano solo dalla tabella prezzi di Supabase (vedi ISINMonitor.dati_grafico):
  - oggi: tutti i prezzi di oggi di Borsa Italiana (circa uno al minuto);
  - recente: un prezzo ogni 15 minuti dell'ultimo mese, con le chiusure di Yahoo
    nei giorni a PC spento;
  - giornaliero: una chiusura al giorno dell'ultimo anno.
Pannelli: in alto 360, 30 e 7 giorni, in basso Oggi e la tabella riassuntiva.
Ogni periodo ha un colore (blu 360 giorni, verde acqua 30, arancio 7, viola oggi) che
resta lo stesso anche dentro i pannelli più lunghi; la legenda dà la variazione del periodo.
Nel pannello annuale anche le righe del massimo e del minimo.
In alto a destra il segnale dell'analisi di MyFinance. Se hai il titolo in portafoglio, una
riga punteggiata scura segna il prezzo di carico e dei triangoli i tuoi acquisti e vendite.
"""

import io
import math
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional

import matplotlib
import pandas as pd
from .proposte import ETICHETTE
from .utils import NumberFormatter
from .profiler import profile
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

# Fino a quanti giorni un pannello usa i dati ogni 15 minuti (oltre, una chiusura al giorno)
GIORNI_DETTAGLIO = 31
# Spazio di una seduta sull'asse a sedute: il resto, fino a 1, è lo stacco fra un giorno e l'altro
SEDUTA = 0.8
# Un colore per periodo, dal più lungo a oggi: blu, verde acqua, arancio, viola
# (niente rosso e verde, che nel grafico vogliono già dire prezzo attuale, su e giù)
COLORI_PERIODI = ['#2a78d6', '#1baf7a', '#eb6834', '#6250d6']
# Le tue posizioni (carico, acquisti e vendite): scuro, per non confondersi coi periodi
SCURO = '#2b2b2b'
GRIGIO_RIGHE = '#9a9a9a'
# Il segnale come nei badge del sito di MyFinance: (fondo, testo)
COLORI_SEGNALI = {
    'compra': ('#3f6d56', '#ffffff'),
    'valuta': ('#f3dfbf', '#7a4d12'),
    'attendi': ('#ececeb', '#59655d'),
    'evita': ('#f6d9d4', '#a23b2f'),
}


def prima_cifra(valore: float) -> str:
    """Col segno e i decimali fino alla prima cifra significativa (una sola da 1 in su):
    11.313 → +11.3, 0.808 → +0.8, -0.048 → -0.05, -0.0098 → -0.01, 0.0021 → +0.002."""
    if valore == 0 or abs(valore) >= 0.95:   # da 0.95 arrotonda già a 1.0
        return f'{valore:+.1f}'
    return f'{valore:+.1g}'


def etichetta_segnale(segnale: Optional[str], punteggio: Optional[int]) -> Optional[str]:
    if segnale not in ETICHETTE:
        return None
    return f'MyFinance: {ETICHETTE[segnale]}' + (f' · {punteggio}/100' if punteggio is not None else '')


def riga_di(table_data: Optional[List[Dict]], etichetta: str) -> Optional[Dict]:
    """Una riga della tabella (es. '30gg', 'Max'): così grafico e tabella coincidono."""
    return next((riga for riga in table_data or [] if riga['label'] == etichetta), None)


def variazione_di(table_data: Optional[List[Dict]], etichetta: str) -> Optional[float]:
    riga = riga_di(table_data, etichetta)
    return riga['variation'] if riga else None
FONDO_SEDUTA = '#edf1f5'


def tabella_prezzi(righe: List[Dict]) -> pd.DataFrame:
    """Righe del database (ts ISO con fuso, prezzo) → DataFrame con ts nell'ora di Roma."""
    if not righe:
        return pd.DataFrame({'ts': pd.Series(dtype='datetime64[ns]'),
                             'prezzo': pd.Series(dtype='float64')})
    dati = pd.DataFrame(righe)
    ts = pd.to_datetime(dati['ts'], utc=True, format='ISO8601')
    return pd.DataFrame({
        'ts': ts.dt.tz_convert('Europe/Rome').dt.tz_localize(None),
        'prezzo': pd.to_numeric(dati['prezzo']).astype(float),
    }).sort_values('ts').reset_index(drop=True)


def dati_pannello(giorni: int, recente: pd.DataFrame, giornaliero: pd.DataFrame,
                  adesso: datetime) -> pd.DataFrame:
    """I punti di un pannello di `giorni` giorni (oggi compreso).

    Fino a un mese i dati ogni 15 minuti, oltre una chiusura al giorno (senza il
    dettaglio dell'ultimo mese, che nel pannello annuale sarebbe solo rumore).
    """
    sorgente = recente if giorni <= GIORNI_DETTAGLIO else giornaliero
    inizio = datetime.combine(adesso.date() - timedelta(days=giorni), time())
    return sorgente[sorgente['ts'] >= inizio].reset_index(drop=True)


def periodi(giorni_pannelli: List[int], adesso: datetime) -> List[tuple]:
    """(giorni, inizio, colore) dal periodo più lungo a oggi, che ha 0 giorni.

    Gli inizi sono quelli dei pannelli (vedi dati_pannello).
    """
    giorni = sorted(giorni_pannelli, reverse=True) + [0]
    return [(numero, datetime.combine(adesso.date() - timedelta(days=numero), time()), colore)
            for numero, colore in zip(giorni, COLORI_PERIODI)]


def colore_di(istante, elenco_periodi: List[tuple]) -> str:
    """Il colore del periodo più breve che contiene l'istante."""
    colore = elenco_periodi[0][2]
    for _, inizio, colore_periodo in elenco_periodi:
        if istante >= inizio:
            colore = colore_periodo
    return colore


def in_orario(dati: pd.DataFrame, apertura: time, chiusura: time) -> pd.DataFrame:
    """Solo i punti dentro l'orario: quelli di notte (giri a mano, prove) sull'asse a sedute
    finirebbero sul bordo e sembrerebbe che la seduta inizi o finisca lì."""
    orari = dati['ts'].dt.time
    return dati[(orari >= apertura) & (orari <= chiusura)].reset_index(drop=True)


def dati_oggi(oggi: pd.DataFrame, adesso: datetime) -> pd.DataFrame:
    return oggi[oggi['ts'].dt.date == adesso.date()].reset_index(drop=True)


def con_prezzo_attuale(dati: pd.DataFrame, adesso: datetime, prezzo: float) -> pd.DataFrame:
    """Aggiunge il prezzo appena letto (non ancora salvato nel database) come ultimo punto."""
    punto = pd.DataFrame({'ts': [pd.Timestamp(adesso)], 'prezzo': [float(prezzo)]})
    return pd.concat([dati, punto], ignore_index=True) if not dati.empty else punto


def asse_sedute(ts: pd.Series, apertura: time, chiusura: time, max_etichette: int = 7):
    """Asse X a sedute: ogni giorno con dati occupa lo stesso spazio, senza notti e weekend.

    Ogni seduta (dall'apertura alla chiusura) va da `indice` a `indice + SEDUTA`.
    Restituisce le posizioni dei punti e i tick (uno per giorno, al centro della sua
    seduta, diradati se sono tanti).
    """
    giorni = ts.dt.normalize()
    elenco = giorni.drop_duplicates().tolist()
    posizione = {giorno: indice for indice, giorno in enumerate(elenco)}
    durata = (datetime.combine(datetime.min, chiusura)
              - datetime.combine(datetime.min, apertura)).total_seconds()
    x = []
    for istante, giorno in zip(ts, giorni):
        trascorso = (istante - giorno).total_seconds() - (apertura.hour * 3600 + apertura.minute * 60)
        frazione = min(max(trascorso / durata, 0.0), 1.0)
        x.append(posizione[giorno] + SEDUTA * frazione)
    passo = max(1, math.ceil(len(elenco) / max_etichette))
    # L'ultimo giorno (oggi) ha sempre l'etichetta; gli altri a ritroso ogni `passo`
    indici = list(range(len(elenco) - 1, -1, -passo))[::-1]
    return x, [i + SEDUTA / 2 for i in indici], [pd.Timestamp(elenco[i]).strftime('%d/%m') for i in indici]


def _formato_euro(asse) -> None:
    asse.yaxis.set_major_formatter(
        FuncFormatter(lambda valore, _: f'€{NumberFormatter.format_number(valore)}')
    )


def _legenda(asse, titolo: str, colore: str, voci: List = (), variazione=None) -> None:
    """Il nome del pannello col colore del suo periodo e la variazione del periodo, più
    carico, operazioni e massimo e minimo se ci sono."""
    if variazione is not None:
        titolo = f'{titolo} {prima_cifra(variazione)}%'
    maniglie = [Line2D([], [], color=colore, linewidth=1.5, label=titolo), *voci]
    asse.legend(handles=maniglie, frameon=False, loc='best',
                fontsize=10 if len(maniglie) == 1 else 8)


def _voce_carico(asse, carico: Optional[float], prezzi) -> List:
    """La riga del prezzo di carico, se cade vicino ai prezzi del pannello, e la sua voce
    di legenda; se è lontano (sopra o sotto) solo la voce, per non schiacciare la curva."""
    if carico is None:
        return []
    basso, alto = min(prezzi), max(prezzi)
    margine = (alto - basso) * 0.15
    etichetta = f'Carico €{NumberFormatter.format_number(carico, 2)}'
    if carico > alto + margine:
        etichetta += ' (sopra)'
    elif carico < basso - margine:
        etichetta += ' (sotto)'
    else:
        asse.axhline(carico, color=SCURO, linestyle=':', linewidth=1.6, zorder=2)
    return [Line2D([], [], color=SCURO, linestyle=':', linewidth=1.6, label=etichetta)]


def _segna_operazioni(asse, punti: List[tuple]) -> List:
    """Triangoli dei tuoi acquisti (in su) e vendite (in giù) da (x, prezzo, acquisto);
    restituisce le voci di legenda."""
    voci = []
    for acquisto, simbolo, nome in ((True, '^', 'Acquisto'), (False, 'v', 'Vendita')):
        scelti = [(x, y) for x, y, tipo in punti if tipo == acquisto]
        if scelti:
            x, y = zip(*scelti)
            asse.scatter(x, y, marker=simbolo, s=70, color=SCURO, edgecolor='white',
                         linewidth=1, zorder=6)
            voci.append(Line2D([], [], marker=simbolo, linestyle='', color=SCURO,
                               markeredgecolor='white', markersize=8, label=nome))
    return voci


def _massimo_minimo(asse, valori: List[float]) -> List:
    """Righe sottili al massimo e al minimo (i valori sono nelle righe Max e Min della tabella)."""
    for valore in valori:
        asse.axhline(valore, color=GRIGIO_RIGHE, linewidth=1, linestyle=(0, (1, 2)), zorder=1)
    return [Line2D([], [], color=GRIGIO_RIGHE, linewidth=1, linestyle=(0, (1, 2)),
                   label='Max e min')]


def _nessun_dato(asse, titolo: str) -> None:
    asse.text(0.5, 0.5, f'Dati non disponibili\nper {titolo.lower()}', ha='center',
              va='center', transform=asse.transAxes, fontsize=16, fontweight='bold')
    asse.set_xticks([])
    asse.set_yticks([])


class ChartGenerator:

    def __init__(self, comparison_days: Optional[List[int]] = None,
                 market_open: str = '08:55', market_close: str = '18:05'):
        configured_days = comparison_days or [7, 30, 360]
        self.comparison_days = sorted(
            {int(days) for days in configured_days if int(days) > 1}, reverse=True,
        )[:3]
        self.apertura = datetime.strptime(market_open, '%H:%M').time()
        self.chiusura = datetime.strptime(market_close, '%H:%M').time()

        plt.style.use('default')
        plt.rcParams['font.size'] = 14
        plt.rcParams['axes.titlesize'] = 16
        plt.rcParams['xtick.labelsize'] = 12
        plt.rcParams['ytick.labelsize'] = 12
        plt.rcParams['legend.fontsize'] = 12
        self.table_fontsize = 14

    @profile()
    def create_comprehensive_chart(self, nome: str, current_price: float,
                                   previous_price: Optional[float],
                                   table_data: Optional[List[Dict]],
                                   oggi: pd.DataFrame, recente: pd.DataFrame,
                                   giornaliero: pd.DataFrame,
                                   adesso: Optional[datetime] = None,
                                   carico: Optional[float] = None,
                                   segni: Optional[List[Dict]] = None,
                                   segnale: Optional[str] = None,
                                   punteggio: Optional[int] = None) -> bytes:
        """Il grafico completo (PNG): tre periodi in alto, oggi e la tabella in basso.

        carico e segni (vedi core.posizioni) ci sono solo per i titoli che hai avuto;
        segnale e punteggio sono quelli dell'analisi di MyFinance (watchlist).
        """
        adesso = adesso or datetime.now()

        title_color = 'black'
        if previous_price:
            variazione = current_price - previous_price
            title_color = 'green' if variazione > 0 else 'red' if variazione < 0 else 'black'
        title = (f'{nome} - €{NumberFormatter.format_number(current_price)} - '
                 f'{adesso.strftime("%H:%M:%S")}')

        fig = plt.figure(figsize=(12.5, 6.6), facecolor='#f4f6f8')
        outer_gs = fig.add_gridspec(2, 1, height_ratios=[1.08, 0.92], hspace=0.16)
        fig.subplots_adjust(top=0.93, bottom=0.045, left=0.06, right=0.94)
        top_gs = outer_gs[0].subgridspec(1, 3, wspace=0.17)
        bot_gs = outer_gs[1].subgridspec(1, 2, wspace=0.08)

        axes_top = [fig.add_subplot(top_gs[0, index]) for index in range(3)]
        ax_oggi = fig.add_subplot(bot_gs[0, 0])
        ax_tabella = fig.add_subplot(bot_gs[0, 1])
        for axis in [*axes_top, ax_oggi, ax_tabella]:
            axis.set_facecolor('white')
            for spine in axis.spines.values():
                spine.set_color('#d9dee3')

        elenco = periodi(self.comparison_days, adesso)
        for index, (axis, days) in enumerate(zip(axes_top, self.comparison_days)):
            dati = dati_pannello(days, recente, giornaliero, adesso)
            variazione = variazione_di(table_data, f'{days}gg')
            if variazione is None and not dati.empty:
                variazione = (current_price / dati['prezzo'].iloc[0] - 1) * 100
            if days <= GIORNI_DETTAGLIO:
                dati = in_orario(dati, self.apertura, self.chiusura)
                self._plot_sedute(axis, con_prezzo_attuale(dati, adesso, current_price),
                                  days, current_price, elenco, carico, segni or [], variazione)
            else:
                dati = con_prezzo_attuale(dati, adesso, current_price)
                estremi = [riga['price'] for riga in (riga_di(table_data, 'Max'),
                                                      riga_di(table_data, 'Min')) if riga]
                self._plot_giornaliero(axis, dati, days, current_price, elenco, carico, segni or [],
                                       variazione, estremi or [dati['prezzo'].max(), dati['prezzo'].min()])
            if index == 2:
                axis.yaxis.tick_right()
        self._plot_oggi(ax_oggi, dati_oggi(oggi, adesso), adesso, current_price, elenco[-1][2],
                        carico, variazione_di(table_data, 'Open'))
        self._create_summary_table(ax_tabella, table_data=table_data)

        # Titolo a sinistra, così a destra c'è posto per il segnale anche coi nomi lunghi
        fig.suptitle(title, fontsize=18, fontweight='bold', x=0.06, y=0.975, ha='left',
                     color=title_color)
        badge = etichetta_segnale(segnale, punteggio)
        if badge:
            fondo, inchiostro = COLORI_SEGNALI[segnale]
            fig.text(0.94, 0.975, badge, ha='right', va='center', fontsize=11, fontweight='bold',
                     color=inchiostro,
                     bbox=dict(boxstyle='round,pad=0.4', facecolor=fondo, edgecolor='none'))

        img_buffer = io.BytesIO()
        fig.savefig(img_buffer, format='png', dpi=100, facecolor='white',
                    edgecolor='none', pil_kwargs={'compress_level': 6})
        plt.close(fig)
        return img_buffer.getvalue()

    def _rifinisci(self, axis, current_price: float) -> None:
        """Parti comuni dei pannelli: linea del prezzo attuale, griglia, tick, euro."""
        axis.axhline(y=current_price, color='grey', linestyle='--', alpha=0.7, linewidth=1.2)
        axis.grid(True, alpha=0.25)
        axis.tick_params(axis='both', direction='in', labelsize=9)
        _formato_euro(axis)

    def _plot_sedute(self, axis, dati: pd.DataFrame, giorni: int, current_price: float,
                     elenco: List[tuple], carico: Optional[float] = None,
                     segni: List[Dict] = (), variazione: Optional[float] = None) -> None:
        """7 e 30 giorni: una linea per seduta su fondo grigio, staccata dalle altre.

        Il fondo va dall'apertura alla chiusura, così si vede quando iniziano e finiscono
        i prezzi di ogni giorno. Un giorno con un prezzo solo resta un punto. Ogni seduta
        ha il colore del periodo più breve in cui cade.
        """
        titolo = f"Ultimi {giorni} giorni"
        if len(dati) < 2:
            _nessun_dato(axis, titolo)
            return
        x, tick, etichette = asse_sedute(dati['ts'], self.apertura, self.chiusura)
        sedute = dati.assign(x=x).groupby(dati['ts'].dt.normalize(), sort=False)
        per_giorno = {}
        for indice, (giorno, seduta) in enumerate(sedute):
            per_giorno[giorno] = (indice, seduta)
            axis.axvspan(indice, indice + SEDUTA, color=FONDO_SEDUTA, linewidth=0, zorder=0)
            axis.plot(seduta['x'], seduta['prezzo'], color=colore_di(giorno, elenco),
                      linewidth=1.5, marker='o' if len(seduta) == 1 else None, markersize=3)
        axis.scatter([x[-1]], [dati['prezzo'].iloc[-1]], color='red', s=50, zorder=5,
                     edgecolor='darkred', linewidth=1.5)
        axis.set_xticks(tick)
        axis.set_xticklabels(etichette)
        axis.set_xlim(-0.1, len(sedute) - 1 + SEDUTA + 0.1)
        # Le operazioni hanno solo la data: al centro della seduta (sulla curva se manca il prezzo)
        punti = []
        for segno in segni:
            if pd.Timestamp(segno['data']) in per_giorno:
                indice, seduta = per_giorno[pd.Timestamp(segno['data'])]
                prezzo = segno['prezzo'] if segno['prezzo'] is not None else seduta['prezzo'].iloc[-1]
                punti.append((indice + SEDUTA / 2, prezzo, segno['acquisto']))
        voci = _voce_carico(axis, carico, dati['prezzo']) + _segna_operazioni(axis, punti)
        _legenda(axis, titolo, next(c for numero, _, c in elenco if numero == giorni), voci,
                 variazione)
        self._rifinisci(axis, current_price)
        axis.grid(False, axis='x')   # le sedute si distinguono già dal fondo

    def _plot_giornaliero(self, axis, dati: pd.DataFrame, giorni: int, current_price: float,
                          elenco: List[tuple], carico: Optional[float] = None,
                          segni: List[Dict] = (), variazione: Optional[float] = None,
                          estremi: List[float] = ()) -> None:
        """Il pannello annuale: una chiusura al giorno, tick ogni 15 giorni (il 1° e il 15).

        Un tratto per periodo, col suo colore, che riparte dall'ultimo punto del precedente;
        sotto, le righe del massimo e del minimo.
        """
        titolo = f"Ultimi {giorni} giorni"
        if len(dati) < 2:
            _nessun_dato(axis, titolo)
            return
        for numero, (_, inizio, colore) in enumerate(elenco):
            dentro = dati['ts'] >= inizio if numero else pd.Series(True, index=dati.index)
            if numero + 1 < len(elenco):
                dentro &= dati['ts'] < elenco[numero + 1][1]
            if dentro.any():
                indici = dati.index[dentro]
                tratto = dati.loc[max(indici[0] - 1, 0):indici[-1]]
                axis.plot(tratto['ts'], tratto['prezzo'], color=colore, linewidth=1.5)
        axis.scatter([dati['ts'].iloc[-1]], [dati['prezzo'].iloc[-1]], color='red', s=50,
                     zorder=5, edgecolor='darkred', linewidth=1.5)
        axis.xaxis.set_major_locator(mdates.DayLocator(bymonthday=[1, 15]))
        axis.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
        axis.set_xlim(dati['ts'].iloc[0], dati['ts'].iloc[-1] + timedelta(days=3))
        punti = []
        for segno in segni:
            giorno = pd.Timestamp(segno['data'])
            if giorno >= dati['ts'].iloc[0]:
                prezzo = segno['prezzo']
                if prezzo is None:   # sulla curva, alla chiusura di quel giorno
                    prezzo = dati.loc[dati['ts'] <= giorno, 'prezzo'].iloc[-1]
                punti.append((giorno, prezzo, segno['acquisto']))
        voci = _massimo_minimo(axis, estremi) if estremi else []
        voci += _voce_carico(axis, carico, dati['prezzo']) + _segna_operazioni(axis, punti)
        _legenda(axis, titolo, next(c for numero, _, c in elenco if numero == giorni), voci,
                 variazione)
        self._rifinisci(axis, current_price)
        axis.tick_params(axis='x', labelsize=7, labelrotation=90, pad=2)

    def _plot_oggi(self, axis, oggi: pd.DataFrame, adesso: datetime, current_price: float,
                   colore: str = COLORI_PERIODI[-1], carico: Optional[float] = None,
                   variazione: Optional[float] = None) -> None:
        """Oggi: tutti i prezzi di Borsa Italiana con i marker (verdi sopra l'apertura, rossi sotto)."""
        dati = con_prezzo_attuale(oggi, adesso, current_price)
        apertura = dati['prezzo'].iloc[0]
        colori = ['green' if prezzo >= apertura else 'red' for prezzo in dati['prezzo']]
        etichetta = 'Oggi' if variazione is None else f'Oggi {prima_cifra(variazione)}%'
        linea, = axis.plot(dati['ts'], dati['prezzo'], color=colore, linewidth=1.5, label=etichetta)
        axis.scatter(dati['ts'], dati['prezzo'], c=colori, s=14, alpha=0.8)
        axis.scatter([dati['ts'].iloc[0]], [apertura], color='green', s=70, marker='^', zorder=5)
        axis.scatter([dati['ts'].iloc[-1]], [dati['prezzo'].iloc[-1]], color='red', s=70,
                     marker='v', zorder=5)

        locator = mdates.AutoDateLocator(minticks=4, maxticks=10)
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        inizio, fine = dati['ts'].iloc[0], dati['ts'].iloc[-1]
        if fine - inizio < timedelta(minutes=10):
            inizio, fine = inizio - timedelta(minutes=5), fine + timedelta(minutes=5)
        axis.set_xlim(inizio, fine)
        voci = _voce_carico(axis, carico, dati['prezzo'])
        axis.legend(handles=[linea, *voci], frameon=False, loc='upper left',
                    fontsize=10 if not voci else 8)
        self._rifinisci(axis, current_price)

    @staticmethod
    def _calculate_dynamic_column_widths(table_data: List[List[str]], headers: List[str]) -> List[float]:
        """Larghezze relative delle colonne in base al testo più lungo (somma 1)."""
        lunghezze = [
            max([len(headers[col])] + [len(str(row[col])) for row in table_data])
            for col in range(len(headers))
        ]
        totale = sum(lunghezze)
        return [lunghezza / totale for lunghezza in lunghezze]

    def _create_summary_table(self, ax, table_data: Optional[List[Dict]] = None):
        """Tabella riassuntiva: prezzo di riferimento (in centesimi), variazione % e differenza
        (fino alla prima cifra decimale significativa)."""
        ax.axis('off')
        righe = [
            [row['label'], f'€{row["price"]:.2f}', f'{prima_cifra(row["variation"])}%',
             prima_cifra(row['difference'])]
            for row in table_data or []
        ]
        if not righe:
            ax.text(0.5, 0.5, 'Nessun dato disponibile\nper la tabella', ha='center',
                    va='center', transform=ax.transAxes, fontsize=20, fontweight='bold')
            return

        headers = ['', 'Price', 'Var.', 'Diff.']
        table = ax.table(cellText=righe, colLabels=headers, cellLoc='center',
                         bbox=(0, 0, 1, 1),
                         colWidths=self._calculate_dynamic_column_widths(righe, headers))
        table.auto_set_font_size(False)
        table.set_fontsize(self.table_fontsize)

        for col in range(4):
            table[(0, col)].set_facecolor('#2E86AB')
            table[(0, col)].set_text_props(weight='bold', color='white')
        for row in range(1, len(righe) + 1):
            for col in range(4):
                cella = table[(row, col)]
                cella.set_facecolor('#f8f9fa' if row % 2 == 0 else 'white')
                cella.set_text_props(weight='bold')
                if col == 2:  # colonna variazione, colorata per segno
                    variazione = table_data[row - 1]['variation']
                    if variazione > 0:
                        cella.set_facecolor('#d1e7dd')
                        cella.set_text_props(color='#0a3622')
                    elif variazione < 0:
                        cella.set_facecolor('#f8d7da')
                        cella.set_text_props(color='#58151c')
