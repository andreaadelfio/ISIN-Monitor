#!/usr/bin/env python3
"""
Sistema di profiling per ISIN Monitor
"""

import cProfile
import functools
import builtins
import time
import threading
from datetime import datetime
from typing import Dict, Callable, Any
import os
import csv
import pandas as pd


class PerformanceProfiler:
    """
    Sistema di profiling per monitorare prestazioni delle funzioni
    """
    
    def __init__(self, output_dir: str = "profiling_results"):
        self.output_dir = output_dir
        self.function_stats = {}
        self.call_counts = {}
        self.execution_times = {}
        self.lock = threading.Lock()
        
        # File CSV centralizzato per i dati
        self.csv_file = os.path.join(output_dir, "performance_data.csv")
        
        # Crea directory se non esiste
        os.makedirs(output_dir, exist_ok=True)
        
        # Inizializza CSV se non esiste
        self._init_csv_file()
    
    def _init_csv_file(self):
        """Inizializza il file CSV se non esiste"""
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'function_name', 'execution_time', 
                    'call_number', 'session_id', 'module', 'class_name'
                ])
    
    def _append_to_csv(self, func_name: str, execution_time: float, call_number: int):
        """Aggiunge una riga al CSV e aggiorna automaticamente i grafici"""
        timestamp = datetime.now().isoformat()
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Parsing del nome funzione
        parts = func_name.split('.')
        if len(parts) >= 3:
            module = parts[0]
            class_name = parts[1] if len(parts) > 2 else ''
            function = parts[-1]
        else:
            module = parts[0] if len(parts) > 1 else 'unknown'
            class_name = ''
            function = parts[-1]
        
        write_header = False
        if not os.path.exists(self.csv_file) or os.path.getsize(self.csv_file) == 0:
            write_header = True
        with open(self.csv_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow([
                    'timestamp', 'function_name', 'execution_time', 'call_number',
                    'session_id', 'module', 'class_name'
                ])
            writer.writerow([
                timestamp, func_name, execution_time, 
                call_number, session_id, module, class_name
            ])
        
        # Aggiornamento plot/report spostato a fine sessione (monitor.py)
    
    # Metodo _auto_update_plots rimosso: ora il plot viene aggiornato solo a fine sessione
    
    def profile_function(self, include_detailed=False):
        """
        Decoratore per profilare singole funzioni
        
        Args:
            include_detailed: Se True, include profiling dettagliato con cProfile
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                func_name = f"{func.__module__}.{func.__qualname__}"
                
                # Registra chiamata
                with self.lock:
                    self.call_counts[func_name] = self.call_counts.get(func_name, 0) + 1
                
                if include_detailed:
                    # Profiling dettagliato con cProfile - SOLO CSV, NO FILES
                    func_profiler = cProfile.Profile()
                    func_profiler.enable()
                    
                    start_time = time.perf_counter()
                    try:
                        result = func(*args, **kwargs)
                        return result
                    finally:
                        end_time = time.perf_counter()
                        func_profiler.disable()
                        
                        execution_time = end_time - start_time
                        
                        with self.lock:
                            if func_name not in self.execution_times:
                                self.execution_times[func_name] = []
                            self.execution_times[func_name].append(execution_time)
                            
                            # Aggiorna contatori e CSV - NO FILE GENERATION
                            call_number = self.call_counts[func_name]
                            self._append_to_csv(func_name, execution_time, call_number)
                            
                            # RIMOSSO: Non salviamo più file .prof e .txt individuali
                else:
                    # Profiling semplice solo per tempo di esecuzione
                    start_time = time.perf_counter()
                    try:
                        result = func(*args, **kwargs)
                        return result
                    finally:
                        end_time = time.perf_counter()
                        execution_time = end_time - start_time
                        
                        with self.lock:
                            if func_name not in self.execution_times:
                                self.execution_times[func_name] = []
                            self.execution_times[func_name].append(execution_time)
                            
                            # Aggiorna contatori e CSV
                            call_number = self.call_counts[func_name]
                            self._append_to_csv(func_name, execution_time, call_number)
            
            return wrapper
        return decorator
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Restituisce statistiche aggregate
        """
        stats = {}
        
        for func_name in self.execution_times:
            times = self.execution_times[func_name]
            calls = self.call_counts.get(func_name, 0)
            
            stats[func_name] = {
                'total_calls': calls,
                'total_time': sum(times),
                'avg_time': sum(times) / len(times) if times else 0,
                'min_time': min(times) if times else 0,
                'max_time': max(times) if times else 0,
                'last_execution': times[-1] if times else 0
            }
        
        return stats
    
    def print_report(self, sort_by='total_time'):
        """
        Stampa report delle prestazioni
        
        Args:
            sort_by: Campo per ordinamento ('total_time', 'avg_time', 'total_calls')
        """
        stats = self.get_statistics()
        
        if not stats:
            print("Nessuna statistica disponibile")
            return
        
        # Ordina per criterio scelto
        sorted_stats = sorted(
            stats.items(), 
            key=lambda x: x[1][sort_by], 
            reverse=True
        )
        
        print(f"\n{'='*80}")
        print(f"REPORT PRESTAZIONI - Ordinato per {sort_by}")
        print(f"{'='*80}")
        print(f"{'Funzione':<40} {'Chiamate':>8} {'Tempo Tot':>10} {'Tempo Med':>10} {'Ultimo':>10}")
        print(f"{'-'*80}")
        
        for func_name, func_stats in sorted_stats:
            # Accorcia nome funzione se troppo lungo
            display_name = func_name if len(func_name) <= 40 else f"...{func_name[-37:]}"
            
            print(f"{display_name:<40} "
                  f"{func_stats['total_calls']:>8} "
                  f"{func_stats['total_time']:>10.4f}s "
                  f"{func_stats['avg_time']:>10.4f}s "
                  f"{func_stats['last_execution']:>10.4f}s")
        
        print(f"{'-'*80}")
        total_functions = len(stats)
        total_calls = sum(s['total_calls'] for s in stats.values())
        total_time = sum(s['total_time'] for s in stats.values())
        
        print(f"Totale funzioni monitorate: {total_functions}")
        print(f"Totale chiamate: {total_calls}")
        print(f"Tempo totale esecuzione: {total_time:.4f}s")
    
    
    def get_csv_data(self, function_filter: str = None) -> pd.DataFrame:
        """
        Legge i dati dal CSV centralizzato
        
        Args:
            function_filter: Filtro per nome funzione (opzionale)
        
        Returns:
            DataFrame con i dati di profiling
        """
        try:
            df = pd.read_csv(self.csv_file)
            
            if function_filter:
                df = df[df['function_name'].str.contains(function_filter, case=False, na=False)]
            
            # Converti timestamp in datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            return df
        except Exception as e:
            print(f"Errore nel leggere CSV: {e}")
            return pd.DataFrame()
    
    
    


# Istanza globale del profiler
profiler = PerformanceProfiler()

# Decoratori di convenienza
def profile(include_detailed=False):
    """
    Decoratore per abilitare/disabilitare il profiling a runtime
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if getattr(builtins, 'ENABLE_PROFILING', False):
                profiler = PerformanceProfiler()
                return profiler.profile_function(include_detailed=include_detailed)(func)(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        return wrapper
    return decorator



if __name__ == "__main__":
    # Test del profiler
    @profile()
    def test_function_fast():
        time.sleep(0.1)
        return "fast"
    
    @profile(include_detailed=True)
    def test_function_slow():
        time.sleep(0.5)
        return "slow"
    
    # Test
    print("Testing profiler...")
    for i in range(3):
        test_function_fast()
        test_function_slow()
    
    profiler.print_report()