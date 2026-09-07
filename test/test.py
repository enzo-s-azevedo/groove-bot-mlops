import json
import os
import sys
import mlflow
from mlflow.client import MlflowClient
from dotenv import load_dotenv
from azure.ai.ml import MLClient
from azure.identity import InteractiveBrowserCredential, DefaultAzureCredential
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

caminho_raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(caminho_raiz)
from agent.agent import rag_agent

load_dotenv()

# Autenticação

def autenticar_azure_ml():
    tenant_id = os.getenv("AZURE_TENANT_ID")
    print("🔐 Iniciando protocolo de autenticação com o Azure...")
    
    # Detecção Inteligente de Ambiente
    if os.getenv("GITHUB_ACTIONS") == "true":
        print("☁️ Ambiente de Nuvem detectado (GitHub Actions). Usando credencial de servidor...")
        # A trava de segurança máxima: proíbe a biblioteca de usar o navegador no fallback
        credencial = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    else:
        print("💻 Ambiente Local detectado. Abrindo navegador...")
        credencial = InteractiveBrowserCredential(tenant_id=tenant_id)

    ml_client = MLClient(
        credential=credencial,
        subscription_id=os.getenv("AZURE_SUBSCRIPTION_ID"),
        resource_group_name=os.getenv("AZURE_RESOURCE_GROUP"),
        workspace_name=os.getenv("AZURE_WORKSPACE_NAME")
    )
    return ml_client

juiz_llm = AzureChatOpenAI(
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME_JUDGE"),
    api_version="2024-12-01-preview",
    azure_endpoint=os.getenv("AZURE_LLM_JUDGE_ENDPOINT"),
    api_key=os.getenv("AZURE_LLM_JUDGE_KEY"),
)

PROMPT_JUIZ = """
Você é um Especialista em Avaliação de Sistemas de IA (LLM-as-a-Judge).

Sua tarefa é comparar a RESPOSTA DO AGENTE com a RESPOSTA ESPERADA (GABARITO)
e determinar se a resposta do agente atende corretamente à pergunta.

REGRAS:

1. Avalie principalmente a CORREÇÃO FACTUAL e a EQUIVALÊNCIA SEMÂNTICA,
e não a similaridade textual.

2. Considere como CORRETA (SIM) uma resposta que transmita corretamente
a mesma informação essencial do gabarito, mesmo que utilize palavras,
estruturas, ordem ou expressões diferentes.

3. Ignore diferenças irrelevantes de:

- formatação;
- pontuação;
- maiúsculas/minúsculas;
- redação;
- ordem das informações;
- sinônimos;
- pequenas variações linguísticas.

4. A resposta deve conter a informação central necessária para responder
à pergunta. Não exija que ela seja idêntica ao gabarito.

5. Informações adicionais são PERMITIDAS quando forem corretas, relevantes
e compatíveis com o gabarito.

Por exemplo, se o gabarito informa apenas o preço e o agente também informa
corretamente o ano, selo ou gravadora obtidos do banco, classifique como SIM.

6. NÃO penalize o agente por fornecer contexto adicional útil, desde que
esse contexto não contradiga o gabarito nem introduza informações incorretas.

7. Classifique como NÃO quando ocorrer qualquer uma das seguintes situações:

- erro factual relevante;
- contradição com o gabarito;
- ausência de uma informação essencial;
- resposta que não atende à pergunta;
- informação adicional incorreta que comprometa a resposta.

8. Pequenas diferenças de redação NÃO devem gerar falso negativo.

9. Valores, datas, nomes, preços, quantidades e outros dados objetivos
devem estar corretos quando forem essenciais à resposta.

10. Se o gabarito contiver uma informação específica e o agente apresentar
essa mesma informação corretamente, considere a resposta correta mesmo que
a redação seja diferente.

11. Não exija correspondência textual entre a resposta do agente e o gabarito.

12. Não penalize uma resposta por ser mais detalhada que o gabarito quando
as informações adicionais forem corretas e não contraditórias.

13. Respostas parcialmente corretas devem ser classificadas como NÃO apenas
quando faltar uma informação essencial necessária para responder corretamente
à pergunta.

14. Uma resposta pode ser considerada SIM mesmo quando não reproduzir todas
as palavras ou informações secundárias do gabarito, desde que a informação
central exigida esteja correta.

========================
CRITÉRIO FINAL
========================

SIM = A resposta atende corretamente à pergunta e contém a informação
essencial correta, permitindo variações de redação e informações adicionais
corretas.

NÃO = A resposta possui erro factual relevante, contradição, omite informação
essencial ou não responde adequadamente à pergunta.

SAÍDA:

Se a resposta do agente estiver correta, responda EXATAMENTE:

SIM

Caso contrário, responda EXATAMENTE:

NÃO

Responda SOMENTE com SIM ou NÃO.
Não forneça explicações ou qualquer outro texto.
"""

def obter_nota_do_campeao(client, experiment_id):
    """Lê o recorde atual diretamente do 'Cache' (Tags) do Experimento no Azure."""
    print("⚡ Buscando o Campeão no Cache Global do Azure...")
    try:
        # Puxa os dados da "sala" do experimento
        experimento = client.get_experiment(experiment_id)
        
        # Procura pelo nosso "Post-it" virtual chamado 'recorde_atual'
        nota_cache = experimento.tags.get("recorde_atual")
        
        if nota_cache is not None:
            nota = float(nota_cache)
            print(f"🏆 Campeão Global recuperado do cache: {nota:.1f}%")
            return nota

        print("   Cache vazio (Primeira execução). Estabelecendo baseline de 50.0%.")
        return 50.0
        
    except Exception as e:
        print(f"⚠️ Erro ao ler o cache: {e}. Assumindo baseline de 50.0%.")
        return 50.0

def executar_avaliacao_mlflow_azure():
    try:
        # 1. Autenticação e Configuração do MLflow
        cliente_azure = autenticar_azure_ml()
        tracking_uri = cliente_azure.workspaces.get(cliente_azure.workspace_name).mlflow_tracking_uri
        mlflow.set_tracking_uri(tracking_uri)
        
        nome_experimento = "Testes_Agente_RAG"
        mlflow.set_experiment(nome_experimento)
        client = MlflowClient()
        
        experiment = client.get_experiment_by_name(nome_experimento)
        experiment_id = experiment.experiment_id

        # 2. Busca de Baseline e Criação da Run
        nota_campeao = obter_nota_do_campeao(client, experiment_id)
        
        run = client.create_run(experiment_id, run_name="Avaliacao_Juiz")
        run_id = run.info.run_id
        print(f"🔗 Conectado e Run criada! Run ID: {run_id}")

        # 3. Testes

        diretorio_atual = os.path.dirname(os.path.abspath(__file__))
        caminho_json = os.path.join(diretorio_atual, "test.json")
        
        with open(caminho_json, "r", encoding="utf-8") as f:
            dataset = json.load(f)

        total = len(dataset)
        acertos = 0
        resultados_detalhados = []

        print(f"🚀 Iniciando bateria de {total} testes...\n")

        # Registra parâmetros técnicos no Azure ML
        client.log_param(run_id, "modelo_agente", os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "Não Informado"))
        client.log_param(run_id, "modelo_juiz", os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME_JUDGE", "Não Informado"))
        client.log_param(run_id, "versao_api_juiz", "2024-12-01-preview")
        client.log_param(run_id, "tamanho_dataset", total)
        client.log_param(run_id, "metodo_avaliacao", "LLM-as-a-Judge")

        # Loop de Perguntas
        for i, item in enumerate(dataset, 1):
            pergunta = item["question"]
            esperado = item["expected_answer"]
            
            print(f"[{i}/{total}] Testando: {pergunta}")

            try:
                resultado_agente = rag_agent.invoke({"messages": [("user", pergunta)]})
                resposta_agente = resultado_agente["messages"][-1].content
            except Exception as e:
                resposta_agente = f"ERRO NA EXECUÇÃO: {e}"

            # O Juiz IA avalia
            mensagem_avaliacao = f"RESPOSTA ESPERADA: {esperado}\nRESPOSTA DO AGENTE: {resposta_agente}"
            resposta_juiz = juiz_llm.invoke([
                SystemMessage(content=PROMPT_JUIZ),
                HumanMessage(content=mensagem_avaliacao)
            ]).content.strip().upper()

            passou = "SIM" in resposta_juiz
            if passou:
                acertos += 1
                veredito = "CORRETO"
                print("✅ Veredito: CORRETO\n")
            else:
                veredito = "INCORRETO"
                print(f"❌ Veredito: INCORRETO\n   Gabarito: {esperado}\n   Agente  : {resposta_agente}\n")

            resultados_detalhados.append({
                "pergunta": pergunta,
                "resposta_esperada": esperado,
                "resposta_agente": resposta_agente,
                "veredito_juiz": veredito
            })

        # 4: O VEREDITO, CACHE GLOBAL E CI/CD

        taxa_acerto = (acertos / total) * 100

        # Envia as métricas para a gaveta atual
        client.log_metric(run_id, "taxa_acerto_percentual", taxa_acerto)
        client.log_metric(run_id, "total_acertos", acertos)
        client.log_metric(run_id, "total_erros", total - acertos)

        # Salva o JSON de auditoria
        temp_file = "detalhes_avaliacao.json"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump({"resultados": resultados_detalhados}, f, indent=4, ensure_ascii=False)
            
        client.log_artifact(run_id, temp_file)
        os.remove(temp_file) 

        # O Showdown: Campeão vs Desafiante
        print("-" * 50)
        print("⚔️ BATALHA FINAL: CAMPEÃO VS DESAFIANTE ⚔️")
        print(f"🏆 Campeão (Cache)   : {nota_campeao:.1f}%")
        print(f"🥊 Desafiante (Novo) : {taxa_acerto:.1f}%")
        print("-" * 50)

        # Decisão Final e Atualização da Tag
        if taxa_acerto >= nota_campeao:
            print("\n✅ SUCESSO: O Desafiante superou/empatou com o Campeão! Deploy Autorizado.")
            
            if taxa_acerto > nota_campeao:
                client.set_experiment_tag(experiment_id, "recorde_atual", str(taxa_acerto))
                print(f"💾 NOVO RECORDE GLOBAL SALVO NO CACHE: {taxa_acerto:.1f}%!")

            client.set_terminated(run_id, status="FINISHED")
            sys.exit(0)
        else:
            print("\n❌ FALHA: O Desafiante piorou o modelo. Protegendo a produção e cancelando Deploy!")
            client.set_terminated(run_id, status="FAILED")
            sys.exit(1)

    except Exception as e:
        if 'client' in locals() and 'run_id' in locals():
            client.set_terminated(run_id, status="FAILED")
        print(f"\n❌ Erro crítico no pipeline de avaliação: {e}")
        sys.exit(1)

if __name__ == "__main__":
    executar_avaliacao_mlflow_azure()