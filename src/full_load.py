# -*- coding: utf-8 -*-
"""
Full Load das tabelas do schema db_loja do PostgreSQL (mydb)
usando PySpark para leitura e cliente MinIO para upload em parquet.
"""

from pyspark.sql import SparkSession
from minio import Minio
from io import BytesIO
from datetime import datetime
import psycopg2

# === CONFIGURAÇÕES ===
PG_HOST = "db"
PG_PORT = 5432
PG_DATABASE = "mydb"
PG_USER = "myuser"
PG_PASSWORD = "mypassword"
SCHEMA = "db_loja"

MINIO_ENDPOINT = "minio:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
BUCKET_NAME = "raw"
PREFIX = "fullload"
SECURE_CONNECTION = False

# === CRIA SESSÃO SPARK ===
spark = (
    SparkSession.builder
    .appName("FullLoad_Postgres_dbloja_to_MinIO")
    # usa pacote remoto (não precisa ter o jar local)
    .config("spark.jars.packages", "org.postgresql:postgresql:42.7.3")
    .getOrCreate()
)

# === CONECTA AO POSTGRES ===
print("🔗 Conectando ao PostgreSQL para listar tabelas...")
conn = psycopg2.connect(
    host=PG_HOST,
    port=PG_PORT,
    dbname=PG_DATABASE,
    user=PG_USER,
    password=PG_PASSWORD
)
cursor = conn.cursor()
cursor.execute(f"""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = '{SCHEMA}'
    ORDER BY table_name;
""")
tables = [row[0] for row in cursor.fetchall()]
cursor.close()
conn.close()

if not tables:
    print(f"⚠️ Nenhuma tabela encontrada no schema {SCHEMA}.")
    spark.stop()
    exit()

print(f"📦 {len(tables)} tabelas encontradas no schema {SCHEMA}: {tables}")

# === CONECTAR AO MINIO ===
print("🚀 Conectando ao MinIO...")
client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=SECURE_CONNECTION
)
client.list_buckets()
print("✅ Conexão com MinIO estabelecida.")

if not client.bucket_exists(BUCKET_NAME):
    client.make_bucket(BUCKET_NAME)
    print(f"🪣 Bucket '{BUCKET_NAME}' criado.")
else:
    print(f"🪣 Bucket '{BUCKET_NAME}' já existe.")

# === LOOP FULL LOAD ===
date_str = datetime.now().strftime("%Y%m%d")
timestamp_str = datetime.now().strftime("%H%M%S")

for table in tables:
    print(f"\n🔄 Lendo tabela '{SCHEMA}.{table}' do PostgreSQL...")

    df = spark.read.jdbc(
        url=f"jdbc:postgresql://{PG_HOST}:{PG_PORT}/{PG_DATABASE}",
        table=f"{SCHEMA}.{table}",
        properties={
            "user": PG_USER,
            "password": PG_PASSWORD,
            "driver": "org.postgresql.Driver"
        }
    )

    # Converter para pandas e salvar como parquet em memória
    pdf = df.toPandas()
    if pdf.empty:
        print(f"⚠️ Tabela '{table}' vazia, pulando.")
        continue

    parquet_buffer = BytesIO()
    pdf.to_parquet(parquet_buffer, index=False)
    parquet_buffer.seek(0)

    object_name = f"{PREFIX}/{SCHEMA}_{table}_{date_str}_{timestamp_str}.parquet"

    client.put_object(
        BUCKET_NAME,
        object_name,
        parquet_buffer,
        length=len(parquet_buffer.getvalue()),
        content_type="application/octet-stream"
    )

    print(f"✅ Tabela '{table}' enviada -> s3://{BUCKET_NAME}/{object_name}")

spark.stop()
print("\n🏁 Full Load concluído e arquivos enviados para o MinIO com sucesso!")
