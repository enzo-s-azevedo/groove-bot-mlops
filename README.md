# Groove Bot MLOps

Agente conversacional para consultar um catálogo de discos usando linguagem natural. A aplicação utiliza RAG com Azure OpenAI: o modelo interpreta a pergunta, consulta o catálogo em SQLite por meio de uma ferramenta SQL somente leitura e monta a resposta com base nos registros encontrados.

## Tecnologias

- Python 3.12
- FastAPI e Uvicorn para a API HTTP
- LangChain e LangGraph para orquestrar o agente e suas ferramentas
- Azure OpenAI para o modelo de linguagem
- Azure Blob Storage para armazenar os dados brutos e o banco processado
- Pandas para o ETL e SQLAlchemy/SQLite para persistência
- Azure ML e MLflow para avaliar e acompanhar as execuções
- Docker para empacotamento e execução do serviço

## Como foi construído

1. `etl.py` baixa `dataset_raw.xlsx` do container `raw-data` no Azure Blob Storage.
2. O arquivo é limpo com Pandas, as colunas são padronizadas e os dados são gravados na tabela `records` de um banco SQLite.
3. O `database.db` processado é enviado ao container `clean-data`.
4. Ao iniciar, `agent/agent.py` baixa o banco processado e configura um grafo LangGraph com um nó de LLM e um nó de ferramentas.
5. A ferramenta `consultar_banco` executa consultas `SELECT` no SQLite. O prompt orienta o agente a variar as buscas e consultar novamente quando o resultado for insuficiente.
6. `main.py` expõe o agente por uma API FastAPI.
7. `test/test.py` executa perguntas do dataset, usa um segundo modelo como juiz e registra métricas, artefatos e o resultado no Azure ML/MLflow.

## Configuração

Crie um arquivo `.env` com as credenciais e identificadores necessários:

```env
AZURE_STORAGE_CONNECTION_STRING=...
AZURE_OPENAI_DEPLOYMENT_NAME=...
AZURE_LLM_ENDPOINT=...
AZURE_LLM_KEY=...
AZURE_OPENAI_DEPLOYMENT_NAME_JUDGE=...
AZURE_LLM_JUDGE_ENDPOINT=...
AZURE_LLM_JUDGE_KEY=...
AZURE_TENANT_ID=...
AZURE_SUBSCRIPTION_ID=...
AZURE_RESOURCE_GROUP=...
AZURE_WORKSPACE_NAME=...
```

Os containers `raw-data` e `clean-data` devem existir no Storage Account. O arquivo de entrada deve estar disponível como `raw-data/dataset_raw.xlsx`.

## Execução

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python etl.py
uvicorn main:app --reload
```

Após iniciar, a documentação interativa fica disponível em `http://localhost:8000/docs`.

### Endpoints

`GET /` verifica se a API está online.

`POST /chat` recebe uma pergunta:

```json
{
	"pergunta": "Qual o disco do gênero Sertanejo mais caro?"
}
```

Resposta:

```json
{
	"resposta": "..."
}
```

## Docker

```bash
docker build -t groove-bot .
docker run --env-file .env -p 8000:8000 groove-bot
```

## Avaliação

Com o banco processado e as variáveis do Azure ML configuradas, execute:

```bash
python test/test.py
```

As perguntas e respostas esperadas ficam em `test/test.json`. O pipeline calcula a taxa de acerto, salva os detalhes da avaliação no MLflow e só considera a execução aprovada quando ela mantém ou supera o melhor resultado registrado.