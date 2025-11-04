# 🧠 Case 2 -- Ingestão de Dados CDC (Change Data Capture)

## 🎯 Objetivo

Este projeto implementa dois pipelines de ingestão de dados a partir do
banco **PostgreSQL (OLTP)** para o **Data Lake (MinIO/S3)**:

1.  **Carga Completa (Batch):** leitura integral da tabela
    `db_loja.cliente` e gravação em CSV.
2.  **Carga Incremental (CDC):** captura contínua de alterações via
    *logical replication slot*, transformando apenas as **mudanças
    (INSERT, UPDATE, DELETE)** em arquivos CSV.

------------------------------------------------------------------------

## 🏗️ Arquitetura do Ambiente

O ambiente é composto por três containers Docker configurados via
**DevContainer**:

  -----------------------------------------------------------------------
  Serviço                          Descrição
  -------------------------------- --------------------------------------
  `app`                            Container de desenvolvimento com
                                   Python 3.11, PySpark, pandas e MinIO
                                   SDK.

  `db`                             Banco de dados PostgreSQL v15, com
                                   schema `db_loja` e CDC habilitado
                                   (`wal_level=logical`).

  `minio`                          Armazenamento de objetos
                                   (S3-compatible) atuando como Data
                                   Lake.
  -----------------------------------------------------------------------

**Bucket alvo:** `RAW`\
**Pastas esperadas:**

    RAW/
    ├── full/  → snapshot completo (carga inicial)
    └── inc/   → alterações incrementais (CDC)

------------------------------------------------------------------------

## ⚙️ 1. Carga Completa (Batch)

### Arquivo: `src/full_load.py`

-   Conecta ao PostgreSQL (`db_loja.cliente`);
-   Lê todos os registros em um DataFrame Spark;
-   Grava em CSV no bucket `RAW/full/date=YYYYMMDD/`;
-   O nome do arquivo inclui um *timestamp* como *watermark* para
    unicidade.

**Exemplo de destino:**

    RAW/full/date=20251103/full_clientes_20251103_101530.csv

### Execução

``` bash
python src/full_load.py
```

------------------------------------------------------------------------

## 🔁 2. Carga Incremental (CDC)

### Arquivo: `src/cdc.py`

-   Conecta ao PostgreSQL e consome continuamente o slot lógico
    `data_sync_slot`;
-   Parseia os eventos de `INSERT`, `UPDATE` e `DELETE` gerados pelo
    plugin `test_decoding`;
-   Gera CSVs apenas com as **mudanças relevantes** (sem logs brutos);
-   Persiste os arquivos em `RAW/inc/date=YYYYMMDD/`;
-   Mantém um marcador (`_watermark.txt`) com o último LSN processado no
    próprio MinIO.

**Exemplo de destino:**

    RAW/inc/date=20251103/cdc_20251103_101540.csv
    RAW/inc/_watermark.txt

### Execução contínua

``` bash
python src/cdc.py
```

O script permanece ativo, consultando o slot a cada 2 segundos.\
Para encerrar, pressione `Ctrl + C`.

### Pré-requisitos SQL

Execute o script de demonstração para criar a publicação e o slot de
replicação:

``` sql
-- arquivo: query/demo_cdc_cliente_sync.sql
```

------------------------------------------------------------------------

## 🧩 Estrutura Final no MinIO

    RAW/
    ├── full/
    │   └── date=20251103/
    │       └── full_clientes_20251103_101530.csv
    └── inc/
        ├── date=20251103/
        │   └── cdc_20251103_101540.csv
        └── _watermark.txt

------------------------------------------------------------------------

## 💬 Decisões de Design

  -----------------------------------------------------------------------
  Item                       Decisão
  -------------------------- --------------------------------------------
  **Persistência do LSN**    Utilização de `_watermark.txt` no MinIO para
                             manter o estado entre execuções.

  **Formato de Saída**       CSV simples para compatibilidade e
                             visualização direta no console MinIO.

  **Captura contínua**       Loop com *polling* periódico via
                             `pg_logical_slot_get_changes`, garantindo
                             execução constante.

  **Parser de logs**         Expressões regulares extraem apenas colunas
                             alteradas, removendo ruído dos logs.

  **Estrutura Hive-style**   Particionamento por data (`date=YYYYMMDD`)
                             simplifica integração futura em camadas
                             bronze/silver.
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 🧠 Desafios Técnicos e Soluções

  -----------------------------------------------------------------------
  Desafio                             Solução
  ----------------------------------- -----------------------------------
  Conversão de logs do                Implementado parser regex que
  `test_decoding` em colunas legíveis converte as strings de log em pares
                                      `coluna:valor`.

  Persistência entre execuções        Armazenamento do último LSN
                                      processado no MinIO (watermark).

  Captura contínua sem duplicação     Uso do LSN como checkpoint e filtro
                                      incremental no slot.

  Evitar gravação de logs             Somente alterações reais são
  irrelevantes                        exportadas para CSV.

  Organização de pastas compatível    Estrutura `RAW/full/date=...` e
  com Hive/Glue                       `RAW/inc/date=...` aplicada.
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 🧾 Critérios de Entrega (Checklist)

✅ Screenshots do console MinIO com as pastas `RAW/full/` e `RAW/inc/`\
✅ Script `full_load.py` executando snapshot inicial\
✅ Script `cdc.py` executando CDC contínuo\
✅ README.md completo com instruções e decisões técnicas
