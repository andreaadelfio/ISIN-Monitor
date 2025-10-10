#!/usr/bin/env python3
"""
Analisi temporale delle performance - Top 10 funzioni peggiori
"""

import os
import sys
import pandas as pd
import matplotlib.pyplot as plt

# Aggiungi il path per importare core.profiler
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.profiler import PerformanceProfiler

def plot_performance_trends(csv_file: str, output_dir: str = None, show_plots: bool = True):
    """
    Crea grafici temporali per le top 10 funzioni peggiori (versione ottimizzata)
    
    Args:
        csv_file: Path al file CSV dei dati
        output_dir: Directory dove salvare i grafici (opzionale)
        show_plots: Se True mostra i grafici interattivamente
    """
    
    print("Analisi Andamenti Temporali - Top 10 Funzioni Peggiori")
    print("=" * 60)
    
    # Carica dati
    try:
        df = pd.read_csv(csv_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    except Exception as e:
        print(f"❌ Errore nel caricamento dati: {e}")
        return
    
    if df.empty:
        print("❌ Nessun dato disponibile")
        return
    
    print(f"✅ Dati caricati: {len(df):,} record")
    print(f"📅 Periodo: {df['timestamp'].min()} → {df['timestamp'].max()}")
    
    # Identifica le top 10 funzioni per tempo totale
    total_time_by_function = df.groupby('function_name')['execution_time'].sum().sort_values(ascending=False)
    top_10_functions = total_time_by_function.head(10)
    
    print(f"\n🏆 Top 10 Funzioni per Tempo Totale:")
    for i, (func, total_time) in enumerate(top_10_functions.items(), 1):
        print(f"  {i:2d}. {func}: {total_time:.3f}s")
    
    # Setup matplotlib con colori default e legenda unificata
    plt.style.use('default')
    
    # Crea figura con 2 subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 8))
    fig.suptitle('Andamenti Temporali Performance - Top 10 Funzioni Peggiori', 
                 fontsize=16, fontweight='bold')
    
    # Usa colori standard matplotlib (ciclo automatico)
    colors = plt.cm.tab10(range(10))  # 10 colori distinti standard
    
    # Plot 1: Timeline tutte le funzioni insieme (punti + linea continua)
    for i, func_name in enumerate(top_10_functions.index):
        func_data = df[df['function_name'] == func_name].copy()
        if not func_data.empty:
            short_name = func_name.split('.')[-1]  # Nome breve per legenda
            # Ordina per timestamp per la linea
            func_data = func_data.sort_values('timestamp')
            # Linea continua
            ax1.plot(func_data['timestamp'], func_data['execution_time'], 
                     label=short_name, color=colors[i], linewidth=1.5, alpha=0.7)
            # Punti
            ax1.scatter(func_data['timestamp'], func_data['execution_time'], 
                        color=colors[i], alpha=0.7, s=30)
    
    ax1.set_title('Timeline Esecuzioni - Tutte le Funzioni')
    ax1.set_xlabel('Tempo')
    ax1.set_ylabel('Tempo Esecuzione (s)')
    ax1.grid(True, alpha=0.3)
    ax1.tick_params(axis='x', rotation=45)
    
    # Plot 2: Frequenza chiamate nel tempo
    # Raggruppa per intervalli di tempo (es. per minuto)
    df['time_bin'] = df['timestamp'].dt.floor('1min')  # Bin di 1 minuto (uso 'min' invece di 'T')
    
    for i, func_name in enumerate(top_10_functions.index):
        func_data = df[df['function_name'] == func_name]
        if not func_data.empty:
            freq_data = func_data.groupby('time_bin').size()
            short_name = func_name.split('.')[-1]  # Nome breve per legenda
            ax2.plot(freq_data.index, freq_data.values, 
                    label=short_name, linewidth=2, color=colors[i], marker='s', markersize=4)
    
    ax2.set_title('Frequenza Chiamate nel Tempo')
    ax2.set_xlabel('Tempo')
    ax2.set_ylabel('Chiamate per Minuto')
    ax2.grid(True, alpha=0.3)
    ax2.tick_params(axis='x', rotation=45)
    
    # Legenda unificata per entrambi i grafici (posizionata tra i due)
    handles, labels = ax1.get_legend_handles_labels()
    fig.legend(handles, labels, loc='center', bbox_to_anchor=(0.5, 0.02), ncol=5, 
               frameon=True, fancybox=True, shadow=True)
    
    # Ajusta layout per fare spazio alla legenda
    plt.subplots_adjust(bottom=0.15)
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.15)  # Ripeti per assicurare spazio
    
    # Salva grafico sempre se output_dir è specificato (SOVRASCRIVE)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{output_dir}/performance_trends.png"  # NOME FISSO, niente timestamp
        plt.savefig(filename, dpi=300, bbox_inches='tight')
        print(f"\n💾 Grafico salvato: {filename}")
    
    # Mostra grafico solo se richiesto
    if show_plots:
        plt.show()
    else:
        plt.close()
    
    # Statistiche finali compatte
    print(f"\nStatistiche Compatte:")
    for i, func_name in enumerate(top_10_functions.index, 1):
        func_data = df[df['function_name'] == func_name]
        if not func_data.empty:
            stats = func_data['execution_time'].describe()
            short_name = func_name.split('.')[-1]
            print(f"{i:2d}. {short_name}: {len(func_data)} chiamate, "
                  f"avg={stats['mean']:.4f}s, max={stats['max']:.4f}s")

def create_summary_report(csv_file: str, output_dir: str = None):
    """
    Crea un file riassuntivo con le liste delle funzioni ordinate per chiamate e tempo
    """
    try:
        df = pd.read_csv(csv_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    except Exception as e:
        print(f"❌ Errore nel caricamento dati per report: {e}")
        return
    
    if df.empty:
        print("❌ Nessun dato disponibile per report")
        return
    
    # Statistiche aggregate per funzione
    function_stats = df.groupby('function_name').agg({
        'execution_time': ['count', 'sum', 'mean', 'std', 'min', 'max'],
        'session_id': 'nunique',
        'timestamp': ['min', 'max']
    }).round(6)

    # Flatten column names
    function_stats.columns = [
        'call_count', 'total_time', 'avg_time', 'std_time', 'min_time', 'max_time',
        'sessions_count', 'first_seen', 'last_seen'
    ]

    # Reset index per avere function_name come colonna
    function_stats = function_stats.reset_index()

    # Conta il numero totale di sessioni (esecuzioni di monitor.py)
    total_sessions = df['session_id'].nunique() if 'session_id' in df.columns else 1
    
    # Ordina per chiamate (decrescente)
    by_calls = function_stats.sort_values('call_count', ascending=False).copy()
    # Ordina per tempo totale (decrescente)
    by_time = function_stats.sort_values('total_time', ascending=False).copy()
    # Ordina per tempo medio (decrescente) per la sezione dettagli
    by_avg = function_stats.sort_values('avg_time', ascending=False).copy()
    
    # Crea report
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        report_file = f"{output_dir}/performance_summary.txt"  # NOME FISSO
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("REPORT PERFORMANCE SUMMARY\n")
            f.write("=" * 60 + "\n")
            f.write(f"📅 Periodo analisi: {df['timestamp'].min()} → {df['timestamp'].max()}\n")
            f.write(f"📈 Totale record: {len(df):,}\n")
            f.write(f"🔧 Funzioni monitorate: {len(function_stats)}\n")
            f.write(f"📋 Sessioni totali: {df['session_id'].nunique()}\n\n")
            
            # TOP 20 per numero di chiamate
            f.write("TOP 20 FUNZIONI PER NUMERO DI CHIAMATE\n")
            f.write("-" * 60 + "\n")
            f.write(f"{'Pos':<3} {'Chiamate':<10} {'Tempo Tot':<12} {'Tempo Avg':<12} {'Funzione'}\n")
            f.write("-" * 60 + "\n")
            for i, row in enumerate(by_calls.head(20).itertuples(), 1):
                f.write(f"{i:<3} {row.call_count:<10} {row.total_time:<12.3f} {row.avg_time:<12.6f} {row.function_name}\n")
            
            f.write("\n" + "=" * 60 + "\n\n")
            
            # TOP 20 per tempo totale
            f.write("TOP 20 FUNZIONI PER TEMPO TOTALE DI ESECUZIONE\n")
            f.write("-" * 60 + "\n")
            f.write(f"{'Pos':<3} {'Tempo Tot':<12} {'Chiamate':<10} {'Tempo Avg':<12} {'Funzione'}\n")
            f.write("-" * 60 + "\n")
            for i, row in enumerate(by_time.head(20).itertuples(), 1):
                f.write(f"{i:<3} {row.total_time:<12.3f} {row.call_count:<10} {row.avg_time:<12.6f} {row.function_name}\n")
            
            f.write("\n" + "=" * 60 + "\n\n")
            
            # Dettagli completi (tutte le funzioni ordinate per tempo medio)
            f.write("DETTAGLI COMPLETI - TUTTE LE FUNZIONI (ordinate per tempo medio)\n")
            f.write("-" * 120 + "\n")
            f.write(f"{'Funzione':<60} {'Chiamate':<8} {'Tot(s)':<10} {'Avg(s)':<10} {'Min(s)':<10} {'Max(s)':<10} {'Sessioni':<8}\n")
            f.write("-" * 120 + "\n")
            for row in by_avg.itertuples():
                f.write(f"{row.function_name:<60} {row.call_count:<8} {row.total_time:<10.3f} {row.avg_time:<10.6f} "
                       f"{row.min_time:<10.6f} {row.max_time:<10.6f} {total_sessions:<8}\n")
        
        print(f"📄 Report salvato: {report_file}")
    
    return function_stats

def main():
    """Demo standalone del tool di analisi temporale"""
    
    profiler = PerformanceProfiler()
    
    if not os.path.exists(profiler.csv_file):
        print(f"❌ File CSV non trovato: {profiler.csv_file}")
        print("Esegui prima il monitor per generare dati")
        return
    
    print("🎯 Analisi Temporale Performance - Top 10 Funzioni Peggiori")
    print("=" * 60)
    
    # Analisi temporale (grafico aggiornato automaticamente)
    plot_performance_trends(
        csv_file=profiler.csv_file,
        output_dir=profiler.output_dir,
        show_plots=False
    )
    
    # Crea report riassuntivo
    create_summary_report(
        csv_file=profiler.csv_file,
        output_dir=profiler.output_dir
    )
    
    print(f"\n✅ Analisi temporale e report completati!")

if __name__ == "__main__":
    main()