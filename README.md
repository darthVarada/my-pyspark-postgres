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

## 🚀 Instruções de Execução Completa

### 1️⃣ Etapa 1 -- Executar o script do banco de dados

Primeiro, execute o arquivo **`Script-DDL-dbloja.sql`** para criar o
schema `db_loja` e todas as tabelas necessárias.\
Esse passo garante que o banco esteja com a estrutura correta para as
próximas etapas de ingestão.

------------------------------------------------------------------------

### 2️⃣ Etapa 2 -- Criar a publicação e o slot de replicação

Em seguida, execute o arquivo **`demo_cdc_cliente_sync.sql`**,
responsável por configurar o ambiente de Change Data Capture (CDC).\
Esse script cria a publicação e o *replication slot* (chamado
`data_sync_slot`) utilizado para capturar alterações da tabela
`db_loja.cliente`.

> Essa configuração permite que o processo de CDC receba automaticamente
> as mudanças realizadas na base.

------------------------------------------------------------------------

### 3️⃣ Etapa 3 -- Executar o pipeline de carga completa

Após o banco estar configurado, execute o arquivo **`full_load.py`**.\
Esse pipeline realiza a **carga inicial** dos dados da tabela
`db_loja.cliente`, gravando um snapshot completo no bucket
`RAW/full/date=YYYYMMDD/`.

> O resultado será um arquivo CSV contendo todos os registros existentes
> no momento da execução.

------------------------------------------------------------------------

### 4️⃣ Etapa 4 -- Executar o pipeline de CDC contínuo

Com o *replication slot* ativo e a carga inicial concluída, execute o
arquivo **`cdc.py`**.\
Esse pipeline inicia a **captura contínua de alterações**, lendo os
eventos de `INSERT`, `UPDATE` e `DELETE` a partir do slot e salvando
apenas as mudanças (não os logs brutos) no bucket
`RAW/inc/date=YYYYMMDD/`.

> O arquivo `cdc.py` permanece em execução, monitorando constantemente o
> banco e criando novos CSVs conforme as alterações ocorrem.

------------------------------------------------------------------------

### 5️⃣ Etapa 5 -- Verificar o resultado no MinIO

Ao final, acesse o bucket `RAW` no MinIO.\
Você deverá visualizar duas estruturas:

-   **Carga completa (snapshot):**

        RAW/full/date=YYYYMMDD/full_clientes_YYYYMMDD_HHMMSS.csv

-   **Alterações capturadas (incremental):**

        RAW/inc/date=YYYYMMDD/cdc_YYYYMMDD_HHMMSS.csv
        RAW/inc/_watermark.txt

Cada nova atualização na tabela `db_loja.cliente` resultará em um novo
arquivo de mudanças na pasta `inc/`, refletindo apenas as alterações
detectadas pelo CDC.

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

✅ Scripts `Script-DDL-dbloja.sql` e `demo_cdc_cliente_sync.sql`
executados em sequência\
✅ `full_load.py` executado para captura completa\
✅ `cdc.py` executando em modo contínuo\
✅ Dados salvos nas estruturas `RAW/full/` e `RAW/inc/`\
✅ README completo com instruções e decisões técnicas
