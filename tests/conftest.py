"""Impostazioni comuni dei test: niente rete vera, stato locale in una cartella temporanea."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import stato  # noqa: E402


@pytest.fixture(autouse=True)
def stato_temporaneo(tmp_path, monkeypatch):
    monkeypatch.setattr(stato, 'CARTELLA', tmp_path / 'stato')
    # La chiave vera (in ~/.config) non deve mai entrare nei test
    monkeypatch.setenv('SUPABASE_SECRET_KEY', 'sb_secret_finta')
    monkeypatch.delenv('SUPABASE_URL', raising=False)


@pytest.fixture
def config():
    return {
        'test': False,
        'myfinance_url': 'https://esempio.pages.dev',
        'telegram': {'bot_token': 'finto', 'chat_id': '1', 'enabled': True, 'send_charts': True},
        'monitoring': {'market_hours_only': True, 'weekdays_only': True,
                       'market_open_time': '08:55', 'market_close_time': '18:05',
                       'price_comparison_days': [1, 7, 30, 360],
                       'historical_table_days': [1, 7, 30, 360]},
        'api': {'request_timeout': 5, 'rate_limit_delay': 0},
        'yahoo': {'enabled': True},
    }
