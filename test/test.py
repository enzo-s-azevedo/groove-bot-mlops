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
Você é um avaliador de respostas de um agente que consulta um catálogo de discos.

Sua tarefa é decidir se a resposta do agente responde corretamente à pergunta do usuário.

Responda EXATAMENTE com:

SIM

ou

NÃO

Não escreva nenhuma explicação adicional.

## REGRA PRINCIPAL

Avalie o significado da resposta, não a correspondência literal com o gabarito.

A resposta é SIM quando contém a informação central necessária para responder à pergunta e essa informação está correta.

Ignore diferenças de:

* capitalização
* pontuação
* ordem das palavras
* pequenas diferenças de escrita
* sinônimos
* estilo
* formatação
* quantidade de detalhes

## INFORMAÇÕES ADICIONAIS

O agente pode fornecer informações corretas que não aparecem no gabarito.

Essas informações adicionais NÃO tornam a resposta incorreta.

Exemplo:

Pergunta:
"Qual o preço de Abbey Road?"

Gabarito:
"O preço é R$ 120."

Agente:
"O disco custa R$ 120 e foi lançado em 1969 pela gravadora X."

Resultado:
SIM

Desde que as informações adicionais não contradigam os dados esperados.

## RESPOSTA PARCIAL

Uma resposta parcial deve ser considerada NÃO somente quando uma informação central necessária para responder à pergunta estiver ausente ou incorreta.

Exemplo:

Pergunta:
"Qual o preço e a gravadora de Abbey Road?"

Gabarito:
"R$ 120, gravadora X."

Agente:
"O preço é R$ 120."

Resultado:
NÃO

O agente forneceu apenas uma parte essencial da resposta.

## INFORMAÇÕES EXTRAS INCORRETAS

Se a resposta principal estiver correta, mas o agente adicionar uma informação factual claramente incorreta ou contraditória, considere:

NÃO

Exemplo:

Gabarito:
"O preço é R$ 120."

Agente:
"O preço é R$ 120 e o disco custa R$ 150 na gravadora X."

Resultado:
NÃO

## PERGUNTAS DE COMPARAÇÃO

Para perguntas que exigem comparação, verifique se a conclusão necessária está correta.

Exemplo:

Pergunta:
"Atom Heart Mother e Meddle foram lançados no mesmo ano?"

Gabarito:
"Sim, ambos foram lançados em 1972 pela Harvest."

Agente:
"Sim, ambos foram lançados em 1972."

Resultado:
SIM

A ausência da gravadora não é um erro se a pergunta principal era sobre o ano.

## CONTAGEM

Para perguntas sobre quantidade, a quantidade correta é essencial.

Exemplo:

Gabarito:
"Existem 6 discos diferentes."

Agente:
"Existem 9 discos."

Resultado:
NÃO

Não considere uma contagem aproximada como correta.

## FALLBACK

Se o agente responder que não encontrou a informação, considere:

SIM

somente quando o gabarito também indicar que a informação não está disponível ou quando a pergunta realmente não puder ser respondida com os dados fornecidos.

Se o gabarito contém uma resposta concreta e o agente usa o fallback, considere:

NÃO

## CRITÉRIO FINAL

Pergunte mentalmente:

"A resposta do agente contém a informação central necessária para responder à pergunta e ela está correta?"

Se SIM → responda SIM.

Se NÃO → responda NÃO.

A saída deve conter somente SIM ou NÃO.
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