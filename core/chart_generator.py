#!/usr/bin/env python3
"""
Generatore di grafici per ISIN Monitor
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, List
import io
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter
import matplotlib
from .utils import NumberFormatter
from .profiler import profile, profile_detailed
matplotlib.use('Agg')


class ChartGenerator:
    
    @profile()    
    def __init__(self, price_history_df: pd.DataFrame):
        """
        Inizializza il generatore di grafici.

        Args:
            price_history_df: DataFrame con storico prezzi (timestamp, ticker, price, isin)
        """
        self.price_history_df = price_history_df
        
        plt.style.use('default')
        
        plt.rcParams['font.size'] = 14           # Dimensione standard, dettagli da alta risoluzione
        plt.rcParams['axes.titlesize'] = 16      # Titoli leggibili ma proporzionati
        plt.rcParams['axes.labelsize'] = 14      # Etichette assi proporzionate
        plt.rcParams['xtick.labelsize'] = 12     # Tick X naturali
        plt.rcParams['ytick.labelsize'] = 12     # Tick Y naturali  
        plt.rcParams['legend.fontsize'] = 12     # Legenda proporzionata
        plt.rcParams['figure.titlesize'] = 18   # Titolo principale prominente ma non eccessivo
        plt.rcParams['font.weight'] = 'normal'  # Peso normale per leggibilità naturale
        
        self.figure_fontsize = 20   # Titolo principale figura
        self.text_fontsize = 16     # Testo all'interno dei grafici
        self.table_fontsize = 14    # Testo tabella

    @profile_detailed
    def create_comprehensive_chart(self, isin_data: Dict, current_price: float, 
                                 previous_price: Optional[float] = None,
                                 table_data: Optional[List[Dict]] = None) -> bytes:
        """
        Crea un grafico completo con tutti i timeframes e tabella riassuntiva.
        
        Returns:
            bytes: Dati binari dell'immagine PNG
        """
        ticker = isin_data['ticker']
        company_name = isin_data.get('company_name', ticker)
        
        # OPTIMIZATION: Filter data once and cache the sorted result
        ticker_data = self.price_history_df[self.price_history_df['ticker'] == ticker]
        if not ticker_data.empty:
            ticker_data = ticker_data.sort_values('timestamp').copy()
        
        # OPTIMIZATION: Pre-calculate title elements to avoid repeated datetime calls
        timestamp_str = datetime.now().strftime("%H:%M:%S")
        price_change = 0
        title_color = 'black'
        if previous_price:
            price_change = ((current_price - previous_price) / previous_price) * 100
            title_color = 'green' if price_change > 0 else 'red' if price_change < 0 else 'black'
        
        title = f'{company_name} - €{NumberFormatter.format_number(current_price)} - {timestamp_str}'
        
        # OPTIMIZATION: Create figure with optimized parameters
        fig = plt.figure(figsize=(10, 8))
        gs = fig.add_gridspec(2, 2, height_ratios=[1, 1], wspace=0.05, hspace=0.15)
        plt.subplots_adjust(top=0.875, bottom=0.02)

        # OPTIMIZATION: Create all subplots at once to avoid repeated calls
        ax1 = fig.add_subplot(gs[0, 0])
        ax2 = fig.add_subplot(gs[0, 1])
        ax3 = fig.add_subplot(gs[1, 0])
        ax4 = fig.add_subplot(gs[1, 1])

        # OPTIMIZATION: Plot in parallel data preparation where possible
        self._plot_timeframe_with_potential_breaks(ax1, ticker_data, 30, current_price, yaxis_side='left', gs_position=gs[0, 0], figure=fig)
        self._plot_timeframe_with_potential_breaks(ax2, ticker_data, 7, current_price, yaxis_side='right', gs_position=gs[0, 1], figure=fig)
        self._plot_intraday_data(ax3, ticker_data, "Oggi", current_price, yaxis_side='left')
        self._create_summary_table(ax4, table_data=table_data)
        
        # Set title once at the end
        fig.suptitle(title, fontsize=self.figure_fontsize, fontweight='bold', y=0.92, color=title_color)

        # OPTIMIZATION: Use more efficient PNG compression
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', dpi=300,  # Reduced DPI for faster performance
                   bbox_inches='tight', facecolor='white', edgecolor='none',
                   pil_kwargs={'compress_level': 6})  # PNG optimization
        img_buffer.seek(0)
        
        chart_data = img_buffer.getvalue()
        img_buffer.close()
        plt.close(fig)  # Explicitly close figure
        
        return chart_data
    
    @profile_detailed    
    def _plot_timeframe_data(self, ax, ticker_data: pd.DataFrame, days: int, current_price: float, yaxis_side: str = 'left'):
        """Plotta i dati per un timeframe specifico."""
        cutoff_date = datetime.now() - timedelta(days=days)
        period_data = ticker_data[ticker_data['timestamp'] >= cutoff_date].copy()
        
        title = f"Ultimi {days} giorni"
        if period_data.empty:
            ax.text(0.5, 0.5, f'Dati non disponibili\nper {title.lower()}', 
                   ha='center', va='center', transform=ax.transAxes, fontsize=24, fontweight='bold')  # Aumentato da 10
            ax.set_title(title, fontweight='bold')
            return
        
        time_column = 'update_timestamp' if 'update_timestamp' in period_data.columns else 'timestamp'
        
        last_timestamp = period_data[time_column].max()
        if (datetime.now() - last_timestamp).total_seconds() > 3600:  # Se più vecchio di 1 ora
            current_point = pd.DataFrame({
                'timestamp': [datetime.now()],
                time_column: [datetime.now()],
                'price': [current_price],
                'ticker': [ticker_data['ticker'].iloc[0]],
                'isin': [ticker_data['isin'].iloc[0]]
            })
            period_data = pd.concat([period_data, current_point], ignore_index=True)

        ax.plot(period_data[time_column], period_data['price'], 'b-', linewidth=2, alpha=0.8, label=title)
        ax.scatter(period_data[time_column], period_data['price'], color='blue', s=20, alpha=0.6)

        ax.scatter([period_data[time_column].iloc[-1]], [period_data['price'].iloc[-1]], 
                  color='red', s=60, zorder=5, edgecolor='darkred', linewidth=2)

        ax.axhline(y=current_price, color='grey', linestyle='--', alpha=0.7, linewidth=1.5)

        ax.grid(True, alpha=0.3, which='major', axis='both')
        ax.legend()
        
        # **NUOVO: Aggiungi separatori tra giorni**
        # self._add_day_separators(ax, period_data, time_column)
        
        if days <= 1:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        elif days <= 7:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
        else:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
        
        last_time = period_data[time_column].iloc[-1]
        current_ticks = ax.get_xticks()
        
        if last_time not in current_ticks:
            new_ticks = list(current_ticks) + [mdates.date2num(last_time)]
            new_labels = [mdates.num2date(t).strftime('%H:%M' if days <= 1 else '%d/%m') for t in new_ticks]
            ax.set_xticks(new_ticks)
            ax.set_xticklabels(new_labels)

        ax.set_xlim(period_data[time_column].min(), period_data[time_column].max())

        if yaxis_side == 'right':
            ax.yaxis.tick_right()
            ax.yaxis.set_label_position('right')

        plt.setp(ax.yaxis.get_majorticklabels(), rotation=45 if yaxis_side == 'left' else -45)
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        # Tick verso l'interno per entrambi gli assi
        ax.tick_params(axis='both', direction='in')
        
        @profile_detailed        
        def price_formatter(x, _):
            return f'€{NumberFormatter.format_number(x)}'
        ax.yaxis.set_major_formatter(FuncFormatter(price_formatter))
        
    @profile()        
    def _plot_intraday_data(self, ax, ticker_data: pd.DataFrame, title: str, current_price: float, yaxis_side: str = 'left'):
        """Plotta i dati intraday (giornata corrente)."""
        today = datetime.now().date()
        
        time_column = 'update_timestamp' if 'update_timestamp' in ticker_data.columns else 'timestamp'
        today_data = ticker_data[ticker_data[time_column].dt.date == today].copy()
        
        if today_data.empty:
            self._plot_timeframe_data(ax, ticker_data, 1, current_price)
            return
        
        current_point = pd.DataFrame({
            'timestamp': [datetime.now()],
            time_column: [datetime.now()],
            'price': [current_price],
            'ticker': [ticker_data['ticker'].iloc[0]],
            'isin': [ticker_data['isin'].iloc[0]]
        })
        today_data = pd.concat([today_data, current_point], ignore_index=True)
        
        opening_price = today_data['price'].iloc[0]
        price_changes = ((today_data['price'] - opening_price) / opening_price * 100)
        
        colors = ['green' if pc >= 0 else 'red' for pc in price_changes]
        ax.plot(today_data[time_column], today_data['price'], 'b-', linewidth=2, label=title)
        ax.scatter(today_data[time_column], today_data['price'], c=colors, s=30, alpha=0.7)

        first_timestamp = today_data[time_column].iloc[0]
        last_timestamp = today_data[time_column].iloc[-1]

        ax.scatter([first_timestamp], [today_data['price'].iloc[0]], 
                  color='green', s=80, marker='^', zorder=5)
        ax.scatter([last_timestamp], [today_data['price'].iloc[-1]], 
                  color='red', s=80, marker='v', zorder=5)

        ax.axhline(y=current_price, color='grey', linestyle='--', alpha=0.7, linewidth=1.5)

        ax.grid(True, alpha=0.3, which='major', axis='both')
        ax.legend()

        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        
        current_ticks = ax.get_xticks()
        
        if last_timestamp not in current_ticks:
            new_ticks = list(current_ticks) + [mdates.date2num(last_timestamp)]
            new_labels = [mdates.num2date(t).strftime('%H:%M') for t in new_ticks]
            ax.set_xticks(new_ticks)
            ax.set_xticklabels(new_labels)
        
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)


        today_date = first_timestamp.date()
        market_start = pd.to_datetime(f"{today_date} 08:55:00")
        market_end = pd.to_datetime(f"{today_date} 18:05:00")
        ax.set_xlim(max(market_start, first_timestamp), min(market_end, last_timestamp))
        
        if yaxis_side == 'right':
            ax.yaxis.tick_right()
            ax.yaxis.set_label_position('right')
        plt.setp(ax.yaxis.get_majorticklabels(), rotation=45)
        
        # Tick verso l'interno per entrambi gli assi
        ax.tick_params(axis='both', direction='in')

        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f'€{NumberFormatter.format_number(x)}'))

    @profile()
    def _add_day_separators(self, ax, data: pd.DataFrame, time_column: str = 'timestamp'):
        """
        Aggiunge linee verticali sottili per separare i giorni di trading.
        
        Args:
            ax: L'asse matplotlib
            data: DataFrame con i dati
            time_column: Nome della colonna con i timestamp
        """
        if data.empty or len(data) < 2:
            return
        
        # Ordina i dati per timestamp
        data_sorted = data.sort_values(time_column)
        
        current_date = None
        for i, (_, row) in enumerate(data_sorted.iterrows()):
            dt = row[time_column]
            dt_date = dt.date()
            
            # Se cambia la data e non è il primo elemento, aggiungi linea separatrice
            if current_date is not None and dt_date != current_date and i > 0:
                # Posiziona la linea esattamente a mezzanotte del nuovo giorno
                midnight = datetime.combine(dt_date, datetime.min.time())
                
                # Linea verticale sottile tra i giorni
                ax.axvline(x=midnight, color='gray', linestyle='--', alpha=0.4, linewidth=1, zorder=1)
            
            current_date = dt_date

    @profile()
    def _plot_timeframe_with_potential_breaks(self, ax, ticker_data: pd.DataFrame, days: int, current_price: float, yaxis_side: str = 'left', gs_position=None, figure=None):
        """
        Plotta i dati per un timeframe, decidendo se usare assi spezzati per nascondere le ore notturne.
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        period_data = ticker_data[ticker_data['timestamp'] >= cutoff_date].copy()
        
        title = f"Ultimi {days} giorni"
        if period_data.empty:
            ax.text(0.5, 0.5, f'Dati non disponibili\nper {title.lower()}', 
                   ha='center', va='center', transform=ax.transAxes, fontsize=24, fontweight='bold')
            ax.set_title(title, fontweight='bold')
            return
        
        time_column = 'update_timestamp' if 'update_timestamp' in period_data.columns else 'timestamp'
        
        # Controlla se ci sono più giorni di trading che giustifichino broken axis
        data_dt = pd.to_datetime(period_data[time_column])
        unique_dates = data_dt.dt.date.unique()
        
                # Broken axis per timeframe multi-giorno
        if len(unique_dates) > 2 and days > 1:
            self._create_broken_timeframe_plot(ax, period_data, time_column, title, current_price, yaxis_side, gs_position, figure)
        else:  # Un solo giorno o pochi dati, plot normale
            self._plot_timeframe_data(ax, ticker_data, days, current_price, yaxis_side)

    @profile_detailed
    def _create_broken_timeframe_plot(self, original_ax, period_data: pd.DataFrame, time_column: str, title: str, current_price: float, yaxis_side: str, gs_position, figure):
        """
        Crea un plot con assi spezzati per nascondere le ore notturne, seguendo fedelmente 
        l'esempio matplotlib broken axis con subplot orizzontali affiancati.
        """
        try:
            # Nasconde l'asse originale
            original_ax.set_visible(False)
            
            # Raggruppa dati per giorno e filtra per orario di mercato
            data_dt = pd.to_datetime(period_data[time_column])
            daily_segments = []
            
            for date in sorted(data_dt.dt.date.unique()):
                day_data = period_data[data_dt.dt.date == date]
                if not day_data.empty:
                    # Filtra per orario di mercato (8:55-18:05)
                    day_times = pd.to_datetime(day_data[time_column])
                    market_start = pd.to_datetime(f"{date} 08:55:00")
                    market_end = pd.to_datetime(f"{date} 18:05:00")
                    
                    market_mask = (day_times >= market_start) & (day_times <= market_end)
                    market_data = day_data[market_mask]
                    
                    if not market_data.empty:
                        daily_segments.append({
                            'data': market_data,
                            'date': date,
                            'times': day_times[market_mask]
                        })
            
            if len(daily_segments) <= 1:
                # Fallback al plot normale se non ci sono abbastanza segmenti
                original_ax.set_visible(True)
                self._plot_single_segment(original_ax, period_data, time_column, title, current_price, yaxis_side)
                return
            
            # Calcola il range Y comune per tutti i segmenti
            all_prices = []
            for segment in daily_segments:
                all_prices.extend(segment['data']['price'].tolist())
            all_prices.append(current_price)
            
            y_min = min(all_prices) * 0.995  # Piccolo margine
            y_max = max(all_prices) * 1.005
            
            # Crea subplot spezzati - tecnica dall'esempio matplotlib
            num_segments = len(daily_segments)
            
            # Calcola posizioni per i subplot in base alla durata temporale
            left, bottom, width, height = gs_position.get_position(figure).bounds
            
            # Calcola la durata di ogni segmento in minuti
            segment_durations = []
            total_duration = 0
            
            for segment in daily_segments:
                times = segment['times']
                if len(times) > 1:
                    duration = (times.max() - times.min()).total_seconds() / 60  # minuti
                else:
                    duration = 1  # Minimo 1 minuto per punti singoli
                segment_durations.append(duration)
                total_duration += duration
            
            # Calcola gap proporzionale
            gap_width = width * 0.007  # 0.7% del totale per i gap
            total_gap_width = gap_width * (num_segments - 1)
            usable_width = width - total_gap_width
            
            # Calcola larghezze proporzionali alla durata
            segment_widths = []
            for duration in segment_durations:
                prop_width = (duration / total_duration) * usable_width
                segment_widths.append(prop_width)
            
            axes = []
            current_left = left
            
            for i, segment in enumerate(daily_segments):
                # Larghezza proporzionale per questo segmento
                segment_width = segment_widths[i]
                
                # Crea il subplot con larghezza proporzionale
                ax = figure.add_axes([current_left, bottom, segment_width, height])
                axes.append(ax)
                
                # Plotta i dati per questo segmento
                seg_data = segment['data']
                seg_times = segment['times']
                
                # Solo l'ultimo segmento ha il label per la legenda (dove sarà mostrata)
                label = title if i == len(daily_segments) - 1 else None
                ax.plot(seg_times, seg_data['price'], 'b-', linewidth=2, alpha=0.8, label=label)
                ax.scatter(seg_times, seg_data['price'], color='blue', s=20, alpha=0.6)
                
                # Evidenzia ultimo punto se è l'ultimo segmento
                if i == len(daily_segments) - 1:
                    ax.scatter([seg_times.iloc[-1]], [seg_data['price'].iloc[-1]], 
                              color='red', s=60, zorder=5, edgecolor='darkred', linewidth=2)
                    # Aggiungi legenda all'ultimo subplot (ultimo giorno)
                    ax.legend(loc='upper right', fontsize=8)
                
                # Linea orizzontale di riferimento
                ax.axhline(y=current_price, color='grey', linestyle='--', alpha=0.7, linewidth=1.5)
                
                # Imposta stesso range Y per tutti
                ax.set_ylim(y_min, y_max)
                
                # Aggiorna posizione per il prossimo segmento
                current_left += segment_width + gap_width
                
                # Formattazione asse X - mostra solo orari di mercato
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, fontsize=10)
                
                # Tick verso l'interno per entrambi gli assi
                ax.tick_params(axis='both', direction='in')
                
                # Gestione asse Y
                if i == 0:  # Primo segmento - mostra Y a sinistra
                    if yaxis_side == 'left':
                        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f'€{NumberFormatter.format_number(x)}'))
                        plt.setp(ax.yaxis.get_majorticklabels(), rotation=45)
                    else:
                        ax.yaxis.set_visible(True)
                        ax.yaxis.tick_right()
                        # ax.yaxis.set_label_position('right')
                elif i == len(daily_segments) - 1:  # Ultimo segmento - mostra Y a destra se richiesto
                    if yaxis_side == 'right':
                        ax.yaxis.tick_right()
                        ax.yaxis.set_label_position('right')
                        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f'€{NumberFormatter.format_number(x)}'))
                        plt.setp(ax.yaxis.get_majorticklabels(), rotation=-45)
                    else:
                        ax.yaxis.set_visible(True)
                else:  # Segmenti intermedi - mostra Y a destra per evitare conflitti
                    ax.yaxis.tick_right()
                    ax.yaxis.set_label_position('right')
                    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f'€{NumberFormatter.format_number(x)}'))
                    plt.setp(ax.yaxis.get_majorticklabels(), rotation=-45)
                
                # Nasconde spines tra subplot (pattern dell'esempio) - TEMPORANEAMENTE DISABILITATO
                if i > 0:
                    ax.spines.left.set_visible(False)
                    ax.tick_params(left=False, labelleft=False)  # nasconde tick e label a sinistra ma mantiene grid
                if i < len(daily_segments) - 1:
                    ax.spines.right.set_visible(False)
                    ax.tick_params(right=False, labelright=False)  # nasconde tick e label a destra ma mantiene grid
                
                ax.grid(True, alpha=0.3, which='major', axis='both')  # Grid completa
                # Aggiungi data come etichetta
                date_str = segment['date'].strftime('%d/%m')
                ax.text(0.5, 1.04, date_str, transform=ax.transAxes, 
                       ha='center', va='top', fontsize=9, fontweight='bold')
            
            kwargs_top = dict(marker=[(0, -1), (0, 0)], markersize=12,
                          linestyle="none", color='k', mec='k', mew=1, clip_on=False)
            kwargs_bottom = dict(marker=[(0, 1), (0, 0)], markersize=12,
                          linestyle="none", color='k', mec='k', mew=1, clip_on=False)
            
            for i in range(len(axes) - 1):
                ax_left = axes[i]
                ax_right = axes[i + 1]
                
                ax_left.plot([1], [0], transform=ax_left.transAxes, **kwargs_bottom)
                ax_left.plot([1], [1], transform=ax_left.transAxes, **kwargs_top)
                
                ax_right.plot([0], [0], transform=ax_right.transAxes, **kwargs_bottom)
                ax_right.plot([0], [1], transform=ax_right.transAxes, **kwargs_top)

        except Exception as e:
            print(f"❌ ERRORE nella creazione broken axis: {e}")
            import traceback
            traceback.print_exc()
            # Fallback al plot normale
            original_ax.set_visible(True)
            self._plot_single_segment(original_ax, period_data, time_column, title, current_price, yaxis_side)

    @profile()
    def _plot_single_segment(self, ax, period_data: pd.DataFrame, time_column: str, title: str, current_price: float, yaxis_side: str):
        """Plot normale per un singolo segmento o fallback."""
        ax.plot(period_data[time_column], period_data['price'], 'b-', linewidth=2, alpha=0.8, label=title)
        ax.scatter(period_data[time_column], period_data['price'], color='blue', s=20, alpha=0.6)
        ax.scatter([period_data[time_column].iloc[-1]], [period_data['price'].iloc[-1]], 
                  color='red', s=60, zorder=5, edgecolor='darkred', linewidth=2)
        ax.axhline(y=current_price, color='grey', linestyle='--', alpha=0.7, linewidth=1.5)
        ax.grid(True, alpha=0.3, which='major', axis='both')
        ax.legend()
        ax.set_title(title, fontweight='bold')
        
        if yaxis_side == 'right':
            ax.yaxis.tick_right()
            ax.yaxis.set_label_position('right')
        
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f'€{NumberFormatter.format_number(x)}'))

    @profile()
    def _calculate_dynamic_column_widths(self, table_data: List[List[str]], headers: List[str]) -> List[float]:
        """
        Calcola larghezze dinamiche delle colonne basate sul contenuto.

        Args:
            table_data: Dati della tabella (righe x colonne)
            
        Returns:
            List[float]: Larghezze relative delle colonne (somma = 1.0)
        """
        if not table_data:
            return [0.25, 0.25, 0.25, 0.25]
        
        max_lengths = []
        num_cols = len(headers)
        
        for col_idx in range(num_cols):
            data_lengths = [len(str(row[col_idx])) for row in table_data if col_idx < len(row)]
            max_data_len = max(data_lengths) if data_lengths else 0
            
            header_len = len(headers[col_idx])
            max_lengths.append(max(header_len, max_data_len))
        
        total_weighted = sum(length for length in max_lengths)
        
        widths = []
        for length in max_lengths:
            width = length / total_weighted
            widths.append(width)
        
        total = sum(widths)
        if total > 0:
            widths = [w / total for w in widths]
        
        return widths

    @profile()
    def _create_summary_table(self, ax, table_data: Optional[List[Dict]] = None):
        """Crea tabella riassuntiva ottimizzata per un quadrante."""
        ax.axis('off')  # Nasconde assi
        
        if table_data is None:
            ax.text(0.5, 0.5, 'Dati tabella\nnon forniti', 
                   ha='center', va='center', transform=ax.transAxes, 
                   fontsize=24, fontweight='bold')
            return
        
        table_rows = table_data
        
        table_data = []
        for row in table_rows:
            table_data.append([
                row['label'],
                f'€{NumberFormatter.format_number(row["price"])}',
                f'{row["variation"]:+.3f}%',
                f'{row["difference"]:+.3f}'
            ])
        
        if not table_data:
            ax.text(0.5, 0.5, 'Nessun dato disponibile\nper la tabella', 
                   ha='center', va='center', transform=ax.transAxes, 
                   fontsize=24, fontweight='bold')  # Aumentato da 12 a 24
            return
        
        headers = ['', 'Price', 'Var.', 'Diff.']
        col_widths = self._calculate_dynamic_column_widths(table_data, headers)
        table = ax.table(cellText=table_data,
                        colLabels=headers,
                        cellLoc='center',
                        bbox=(0, 0, 1, 1),
                        colWidths=col_widths)
        
        table.auto_set_font_size(False)
        table.set_fontsize(self.table_fontsize)           # Aumentato da 12 per mobile
        table.scale(1, 3.5)              # Aumentato scaling per più spazio su mobile
        
        header_color = '#2E86AB'  # Blu professionale
        for i in range(4):
            table[(0, i)].set_facecolor(header_color)
            table[(0, i)].set_text_props(weight='bold', color='white', size=self.table_fontsize)  # Aumentato da 13 per mobile
        
        for i in range(1, len(table_data) + 1):
            for j in range(4):
                # Colore base alternato
                base_color = '#f8f9fa' if i % 2 == 0 else 'white'
                table[(i, j)].set_facecolor(base_color)
                table[(i, j)].set_text_props(weight='bold', size=self.table_fontsize)  # Aumentato da 15 per mobile
                
                # Colora colonna variazione in base al segno
                if j == 2:  # Colonna variazione
                    text = table_data[i-1][j]
                    if '-' not in text and not '+0.000%' in text:
                        table[(i, j)].set_facecolor('#d1e7dd')  # Verde chiaro
                        table[(i, j)].set_text_props(color='#0a3622')
                    elif '-' in text and not '-0.000%' in text:
                        table[(i, j)].set_facecolor('#f8d7da')  # Rosso chiaro  
                        table[(i, j)].set_text_props(color='#58151c')
