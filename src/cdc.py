# -*- coding: utf-8 -*-
"""
CDC contínuo via replication slot do PostgreSQL (test_decoding)
- Consome mudanças incrementalmente do slot.
- Grava SOMENTE as mudanças (operação + colunas) em CSV no MinIO.
- Estrutura: s3://RAW/inc/date=YYYYMMDD/cdc_<timestamp>.csv
- Watermark (last LSN) persistido no MinIO: s3://RAW/inc/_watermark.txt

Requisitos do ambiente (já previstos no case):
- wal_level=logical, publication/slot criados (ex: data_sync_slot)  :contentReference[oaicite:2]{index=2}
"""

import os
import re
import time
from io import BytesIO
from datetime import datetime

import psycopg2
import pandas as pd
from minio import Minio
from minio.error import S3Error

# ====== CONFIG ======
PG_HOST = "db"
PG_PORT = 5432
PG_DATABASE = "mydb"
PG_USER = "myuser"
PG_PASSWORD = "mypassword"
REPLICATION_SLOT = "data_sync_slot"  # já existente no ambiente do case  :contentReference[oaicite:3]{index=3}

MINIO_ENDPOINT   = "minio:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
MINIO_SECURE     = False

BUCKET_NAME = "raw"
INC_PREFIX  = "inc"   # incremental
WATERMARK_OBJECT = f"{INC_PREFIX}/_watermark.txt"  # guarda o último LSN

# Polling
POLL_INTERVAL_SECS = 2      # intervalo entre leituras
BATCH_LIMIT = None          # None = todas as pendentes; ou use 100/1000 se preferir janelar
IDLE_ROUNDS_BEFORE_FLUSH = 5  # flush forçado de arquivo vazio? Mantemos só quando houver mudanças


# ====== MINIO HELPERS ======
def get_minio():
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE
    )

def ensure_bucket(client: Minio, bucket: str):
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

def read_watermark(client: Minio) -> str | None:
    try:
        obj = client.get_object(BUCKET_NAME, WATERMARK_OBJECT)
        wm = obj.read().decode("utf-8").strip()
        obj.close(); obj.release_conn()
        return wm or None
    except S3Error:
        return None

def write_watermark(client: Minio, lsn: str):
    data = lsn.encode("utf-8")
    client.put_object(
        BUCKET_NAME, WATERMARK_OBJECT,
        data=BytesIO(data), length=len(data),
        content_type="text/plain"
    )


# ====== PARSER test_decoding ======
# Exemplos de linhas (plugin test_decoding):
# "table db_loja.cliente: INSERT: id[integer]:1 nome[text]:'Ana'"
# "table db_loja.cliente: UPDATE: id[integer]:1 nome[text]:'Ana Maria'"
# "table db_loja.cliente: DELETE: id[integer]:1"
#
# Abaixo, parser simples que extrai:
#   schema, table, op (INSERT/UPDATE/DELETE) e pares col=valor em dict.

TABLE_RE = re.compile(r"table\s+([^.]+)\.([^\s:]+):\s+(INSERT|UPDATE|DELETE):\s*(.*)", re.IGNORECASE)

def parse_test_decoding_line(data: str):
    """
    Retorna dict: {'schema','table','op', 'cols': {col: value, ...}}
    """
    m = TABLE_RE.match(data)
    if not m:
        return None
    schema, table, op, tail = m.groups()
    cols = {}

    # Cada coluna vem como: colname[typename]:valor  (valor pode vir quoted)
    # Vamos quebrar por espaço que separa colunas, mas valores com espaço podem vir entre aspas.
    # Estratégia: encontrar padrões col[...]:'...'/numero
    # Regex por coluna:
    col_pattern = re.compile(r"(\w+)\[[^\]]+\]:(?:'([^']*)'|([^\s]+))")
    for cm in col_pattern.finditer(tail or ""):
        col = cm.group(1)
        val = cm.group(2) if cm.group(2) is not None else cm.group(3)
        cols[col] = val

    return {
        "schema": schema,
        "table": table,
        "op": op.upper(),
        "cols": cols
    }


# ====== MAIN LOOP ======
def main():
    print("🔗 Conectando ao PostgreSQL (CDC contínuo)...")
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT,
        dbname=PG_DATABASE, user=PG_USER, password=PG_PASSWORD
    )
    cur = conn.cursor()

    minio = get_minio()
    ensure_bucket(minio, BUCKET_NAME)

    last_lsn = read_watermark(minio)
    if last_lsn:
        base_query = f"SELECT * FROM pg_logical_slot_get_changes('{REPLICATION_SLOT}', '{last_lsn}', {BATCH_LIMIT if BATCH_LIMIT else 'NULL'});"
        print(f"📡 Retomando a partir do LSN: {last_lsn}")
    else:
        base_query = f"SELECT * FROM pg_logical_slot_get_changes('{REPLICATION_SLOT}', NULL, {BATCH_LIMIT if BATCH_LIMIT else 'NULL'});"
        print("📡 Iniciando do começo do slot.")

    idle_rounds = 0

    try:
        while True:
            cur.execute(base_query)
            changes = cur.fetchall()

            rows = []
            for (lsn, xid, data) in changes:
                parsed = parse_test_decoding_line(data)
                # grava SOMENTE mudanças (linhas parseadas); ignora qualquer coisa que não seja a mudança interpretável
                if parsed:
                    row = {
                        "lsn": lsn,
                        "xid": xid,
                        "op": parsed["op"],
                        "schema": parsed["schema"],
                        "table": parsed["table"]
                    }
                    # "explode" cols para colunas individuais no CSV
                    for k, v in parsed["cols"].items():
                        row[f"col_{k}"] = v
                    rows.append(row)
                    last_lsn = lsn  # avança watermark com o último LSN visto

            if rows:
                # monta DataFrame e salva CSV
                df = pd.DataFrame(rows)
                csv_buf = BytesIO()
                df.to_csv(csv_buf, index=False)
                csv_buf.seek(0)

                date_str = datetime.now().strftime("%Y%m%d")
                ts_str   = datetime.now().strftime("%H%M%S")
                object_name = f"{INC_PREFIX}/date={date_str}/cdc_{date_str}_{ts_str}.csv"

                minio.put_object(
                    BUCKET_NAME, object_name,
                    data=csv_buf, length=len(csv_buf.getvalue()),
                    content_type="text/csv"
                )
                print(f"✅ CSV de mudanças enviado: s3://{BUCKET_NAME}/{object_name}")

                # persiste o watermark
                if last_lsn:
                    write_watermark(minio, last_lsn)
                    print(f"💾 Watermark atualizado: {last_lsn}")

                idle_rounds = 0  # reset, tivemos atividade
            else:
                idle_rounds += 1

            # aguarda próximo poll
            time.sleep(POLL_INTERVAL_SECS)

    except KeyboardInterrupt:
        print("🛑 Encerrando CDC contínuo (Ctrl+C).")
    finally:
        cur.close()
        conn.close()
        print("🏁 CDC finalizado.")
        

if __name__ == "__main__":
    main()
