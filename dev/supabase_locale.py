"""Un finto Supabase locale per provare ISIN Monitor senza toccare il database vero.

    ~/.venvs/bird-audio-suite/bin/python dev/supabase_locale.py [--azzera]

Avvia un Postgres incorporato (pgserver) con le tabelle watchlist e prezzi prese da
MyFinance/supabase/schema.sql, PostgREST sopra (la stessa API REST di Supabase, con al
massimo 1000 righe per richiesta) e un piccolo proxy su http://127.0.0.1:54331 che,
come Supabase, accetta la chiave nell'header apikey. Poi, in un altro terminale:

    SUPABASE_URL=http://127.0.0.1:54331 SUPABASE_SECRET_KEY=sb_secret_locale python3 monitor.py ...

Tutto sta in ~/.cache/isin-monitor/supabase-locale e si può buttare (--azzera).
Serve il pacchetto pgserver (c'è nel virtualenv di Bird Audio Suite) e il binario di
PostgREST, che si scarica la prima volta.
"""

import base64
import hashlib
import hmac
import json
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CARTELLA = Path.home() / '.cache' / 'isin-monitor' / 'supabase-locale'
POSTGREST = Path.home() / '.cache' / 'bird-audio-suite' / 'local-supabase' / 'bin' / 'postgrest'
POSTGREST_URL = ('https://github.com/PostgREST/postgrest/releases/download/v12.2.3/'
                 'postgrest-v12.2.3-linux-static-x64.tar.xz')
PORTA_POSTGREST = 3021
PORTA = 54331
CHIAVE = 'sb_secret_locale'
SEGRETO_JWT = 'solo-locale-isin-monitor-segreto-jwt-0123456789'

RUOLI = """
do $$
begin
  if not exists (select from pg_roles where rolname = 'anon') then create role anon nologin noinherit; end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated nologin noinherit; end if;
  if not exists (select from pg_roles where rolname = 'service_role') then create role service_role nologin noinherit bypassrls; end if;
  if not exists (select from pg_roles where rolname = 'authenticator') then
    create role authenticator login noinherit password 'locale';
  end if;
end
$$;
grant anon, authenticated, service_role to authenticator;
grant usage on schema public to service_role;
alter default privileges in schema public grant all on tables to service_role;
"""


def jwt(claims: dict) -> str:
    def b64(dati: bytes) -> str:
        return base64.urlsafe_b64encode(dati).rstrip(b'=').decode()
    testa = b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())
    corpo = b64(json.dumps({**claims, 'exp': int(time.time()) + 30 * 86400}).encode())
    firma = hmac.new(SEGRETO_JWT.encode(), f'{testa}.{corpo}'.encode(), hashlib.sha256).digest()
    return f'{testa}.{corpo}.{b64(firma)}'


def schema_isin_monitor() -> str:
    """Il blocco di schema.sql dalla watchlist a serie_prezzi (più i permessi locali)."""
    # MyFinance è accanto a ISIN Monitor (cercato anche più su, per i worktree di git)
    cartella = next(p for p in Path(__file__).resolve().parents
                    if (p / 'MyFinance' / 'supabase' / 'schema.sql').exists())
    testo = (cartella / 'MyFinance' / 'supabase' / 'schema.sql').read_text(encoding='utf-8')
    inizio = testo.index('create table if not exists public.watchlist')
    fine = testo.index('-- Conto Fineco')
    return testo[inizio:fine] + '\ngrant all on all tables in schema public to service_role;\n'


def avvia_postgrest(server) -> subprocess.Popen:
    if not POSTGREST.exists():
        POSTGREST.parent.mkdir(parents=True, exist_ok=True)
        archivio = POSTGREST.parent / 'postgrest.tar.xz'
        urllib.request.urlretrieve(POSTGREST_URL, archivio)
        with tarfile.open(archivio) as file:
            file.extract('postgrest', POSTGREST.parent)
        archivio.unlink()
    socket = server.get_uri().split('host=', 1)[1]
    conf = CARTELLA / 'postgrest.conf'
    conf.write_text('\n'.join([
        f'db-uri = "postgres://authenticator:locale@/postgres?host={socket}"',
        'db-schemas = "public"',
        'db-anon-role = "anon"',
        'db-max-rows = 1000',
        f'jwt-secret = "{SEGRETO_JWT}"',
        f'server-port = {PORTA_POSTGREST}',
        'server-host = "127.0.0.1"',
    ]), encoding='utf-8')
    processo = subprocess.Popen([str(POSTGREST), str(conf)], stdout=subprocess.DEVNULL,
                                stderr=subprocess.STDOUT)
    for _ in range(50):
        if processo.poll() is not None:
            raise RuntimeError(f'PostgREST non parte (porta {PORTA_POSTGREST} occupata?)')
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{PORTA_POSTGREST}/', timeout=1)
            return processo
        except urllib.error.HTTPError as errore:
            if errore.code != 503:
                return processo
        except OSError:
            pass
        time.sleep(0.2)
    processo.terminate()
    raise RuntimeError('PostgREST non parte')


class Proxy(BaseHTTPRequestHandler):
    """Come il gateway di Supabase: apikey → Authorization con il ruolo service_role."""
    token = jwt({'role': 'service_role'})

    def log_message(self, *args):
        pass

    def inoltra(self):
        if self.headers.get('apikey') != CHIAVE:
            self.send_response(401)
            self.end_headers()
            return
        lunghezza = int(self.headers.get('Content-Length') or 0)
        corpo = self.rfile.read(lunghezza) if lunghezza else None
        percorso = self.path.removeprefix('/rest/v1')
        intestazioni = {nome: valore for nome, valore in self.headers.items()
                        if nome.lower() in ('content-type', 'prefer', 'range', 'accept')}
        intestazioni['Authorization'] = f'Bearer {self.token}'
        richiesta = urllib.request.Request(f'http://127.0.0.1:{PORTA_POSTGREST}{percorso}', data=corpo,
                                           headers=intestazioni, method=self.command)
        try:
            risposta = urllib.request.urlopen(richiesta, timeout=60)
        except urllib.error.HTTPError as errore:
            risposta = errore
        dati = risposta.read()
        self.send_response(risposta.status if hasattr(risposta, 'status') else risposta.code)
        for nome in ('Content-Type', 'Content-Range'):
            if risposta.headers.get(nome):
                self.send_header(nome, risposta.headers[nome])
        self.send_header('Content-Length', str(len(dati)))
        self.end_headers()
        self.wfile.write(dati)

    do_GET = do_POST = do_PATCH = do_DELETE = do_HEAD = inoltra


def main():
    import pgserver

    if '--azzera' in sys.argv and CARTELLA.exists():
        shutil.rmtree(CARTELLA)
    CARTELLA.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(str(CARTELLA / 'pgdata'), cleanup_mode='stop')
    server.psql('\\set ON_ERROR_STOP on\n' + RUOLI + schema_isin_monitor())
    postgrest = avvia_postgrest(server)
    print(f'Supabase locale pronto: SUPABASE_URL=http://127.0.0.1:{PORTA} SUPABASE_SECRET_KEY={CHIAVE}', flush=True)
    print(f'psql: {server.get_uri()}', flush=True)
    try:
        ThreadingHTTPServer(('127.0.0.1', PORTA), Proxy).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        postgrest.terminate()


if __name__ == '__main__':
    main()
