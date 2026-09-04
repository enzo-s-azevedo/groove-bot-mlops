import json
import os
import sys
import mlflow
from mlflow.client import MlflowClient
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

caminho_raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(caminho_raiz)

from agent.agent import rag_agent

load_dotenv()

juiz_llm = AzureChatOpenAI(
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME_JUDGE"),
    api_version="2024-12-01-preview",
    azure_endpoint=os.getenv("AZURE_LLM_JUDGE_ENDPOINT"),
    api_key=os.getenv("AZURE_LLM_JUDGE_KEY"),
)

PROMPT_JUIZ = """
Você é um avaliador de sistemas de IA (LLM-as-a-Judge).
Sua tarefa é comparar a RESPOSTA DO AGENTE com a RESPOSTA ESPERADA (Gabarito).

Regras:
1. Ignore diferenças puramente de formatação, pontuação, maiúsculas/minúsculas ou palavras sinônimas.
2. O foco é a precisão factual e semântica. A resposta do agente contém a informação correta exigida no gabarito?
3. Se a resposta for semanticamente equivalente e correta, responda EXATAMENTE com a palavra: SIM.
4. Se houver erro factual, falta de informação crítica ou contradição, responda EXATAMENTE com a palavra: NÃO.

NÃO forneça explicações, apenas SIM ou NÃO.
"""

# ==========================================
# FUNÇÃO: BUSCAR O CAMPEÃO (BASELINE)
# ==========================================
def obter_nota_do_campeao(client, experiment_id, nome_da_metrica="taxa_acerto_percentual"):
    """
    Procura no histórico do Azure ML qual foi a melhor nota já registrada 
    para este experimento.
    """
    runs = client.search_runs(
        experiment_ids=[experiment_id],
        order_by=[f"metrics.{nome_da_metrica} DESC"],
        max_results=1
    )
    
    # Se não houver histórico (primeira vez), a baseline é 50%
    if not runs:
        return 50.0
        
    return runs[0].data.metrics.get(nome_da_metrica, 50.0)

# ==========================================
# MOTOR DE AVALIAÇÃO COM MLFLOW (AZURE)
# ==========================================
def executar_avaliacao_mlflow_azure():
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    mlflow.set_tracking_uri(tracking_uri)

    client = MlflowClient()

    # Gerencia o Experimento
    nome_experimento = "Testes_Agente_RAG"
    experimento = client.get_experiment_by_name(nome_experimento)
    
    if experimento is None:
        experiment_id = client.create_experiment(nome_experimento)
    else:
        experiment_id = experimento.experiment_id

    # 1. BUSCA O CAMPEÃO ANTES DE COMEÇAR O NOVO TESTE
    nota_campeao = obter_nota_do_campeao(client, experiment_id, "taxa_acerto_percentual")
    print(f"🏆 Campeão Atual (Produção): {nota_campeao:.1f}%\n")

    # Cria uma nova execução (Run) dentro do Azure ML para o Desafiante
    run = client.create_run(experiment_id, run_name="Avaliacao_Juiz")
    run_id = run.info.run_id

    print(f"🔗 Conectado ao Azure ML! Run ID: {run_id}")

    try:
        with open("test/test.json", "r", encoding="utf-8") as f:
            dataset = json.load(f)

        total = len(dataset)
        acertos = 0
        resultados_detalhados = []

        print(f"🚀 Iniciando bateria de {total} testes...\n")

        # Loga os parâmetros de engenharia no Azure
        client.log_param(run_id, "modelo_agente", os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"))
        client.log_param(run_id, "modelo_juiz", os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME_JUDGE"))
        client.log_param(run_id, "versao_api_juiz", "2024-12-01-preview")
        client.log_param(run_id, "tamanho_dataset", total)
        client.log_param(run_id, "metodo_avaliacao", "LLM-as-a-Judge")

        # Loop principal de testes
        for i, item in enumerate(dataset, 1):
            pergunta = item["question"]
            esperado = item["expected_answer"]
            
            print(f"[{i}/{total}] Testando: {pergunta}")

            # ETAPA A: O Agente RAG pesquisa e gera a resposta
            try:
                resultado_agente = rag_agent.invoke({"messages": [("user", pergunta)]})
                resposta_agente = resultado_agente["messages"][-1].content
            except Exception as e:
                resposta_agente = f"ERRO NA EXECUÇÃO: {e}"

            # ETAPA B: O Juiz (IA) avalia a resposta do Agente comparando com o Gabarito
            mensagem_avaliacao = f"RESPOSTA ESPERADA: {esperado}\nRESPOSTA DO AGENTE: {resposta_agente}"
            
            resposta_juiz = juiz_llm.invoke([
                SystemMessage(content=PROMPT_JUIZ),
                HumanMessage(content=mensagem_avaliacao)
            ]).content.strip().upper()

            # ETAPA C: Consolida os resultados
            passou = "SIM" in resposta_juiz
            if passou:
                acertos += 1
                veredito = "CORRETO"
                print("✅ Veredito: CORRETO\n")
            else:
                veredito = "INCORRETO"
                print(f"❌ Veredito: INCORRETO")
                print(f"   Gabarito: {esperado}")
                print(f"   Agente  : {resposta_agente}\n")

            resultados_detalhados.append({
                "pergunta": pergunta,
                "resposta_esperada": esperado,
                "resposta_agente": resposta_agente,
                "veredito_juiz": veredito
            })

        # Calcula a métrica final do Desafiante
        taxa_acerto = (acertos / total) * 100

        # Envia as métricas finais para o painel do Azure ML
        client.log_metric(run_id, "taxa_acerto_percentual", taxa_acerto)
        client.log_metric(run_id, "total_acertos", acertos)
        client.log_metric(run_id, "total_erros", total - acertos)

        # Salva o arquivo de depuração detalhado como um "Artifact" na nuvem
        temp_file = "detalhes_avaliacao.json"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump({"resultados": resultados_detalhados}, f, indent=4, ensure_ascii=False)
            
        client.log_artifact(run_id, temp_file)
        os.remove(temp_file) 

        # ==========================================
        # O VEREDITO FINAL DA ARENA
        # ==========================================
        print("-" * 50)
        print("⚔️ BATALHA FINAL: CAMPEÃO VS DESAFIANTE ⚔️")
        print(f"🏆 Campeão (Produção) : {nota_campeao:.1f}%")
        print(f"🥊 Desafiante (Novo)  : {taxa_acerto:.1f}%")
        print("-" * 50)

        if taxa_acerto >= nota_campeao:
            print("\n✅ SUCESSO: O Desafiante superou/empatou com o Campeão! Deploy Autorizado.")
            client.set_terminated(run_id, status="FINISHED")
            sys.exit(0) # Retorna "Verde" para o GitHub (Avança para o Docker)
        else:
            print("\n❌ FALHA: O Desafiante piorou o modelo. Protegendo a produção e cancelando Deploy!")
            client.set_terminated(run_id, status="FAILED") # Marca no Azure que a run foi reprovada
            sys.exit(1) # Retorna "Vermelho" para o GitHub (Trava tudo)

    except Exception as e:
        client.set_terminated(run_id, status="FAILED")
        print(f"\n❌ Erro crítico durante a avaliação: {e}")
        sys.exit(1) # Garante que o pipeline trave caso dê erro de código

if __name__ == "__main__":
    executar_avaliacao_mlflow_azure()