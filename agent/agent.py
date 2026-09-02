from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage, SystemMessage
from langchain_openai import AzureChatOpenAI
from agent.prompt import SYSTEM_PROMPT
from langchain_core.tools import tool
import sqlite3
from azure.storage.blob import BlobServiceClient
import os
from dotenv import load_dotenv
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.prebuilt import ToolNode, tools_condition

load_dotenv()
blob_api_key = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

blob_service_client = BlobServiceClient.from_connection_string(blob_api_key)
container_client = blob_service_client.get_container_client("clean-data")
blob_client = container_client.get_blob_client("database.db")

database = blob_client.download_blob().readall()

with open("database.db", "wb") as f:
    f.write(database)

@tool
def consultar_banco(query: str) -> str:

    """
    Executa uma consulta SQL no banco de dados do catálogo de discos.
    Sempre envie consultas do tipo SELECT.
    """
    
    print(f"\n[DEBUG SQL] O Agente tentou rodar: {query}") # <-- ADICIONE ESTA LINHA
    
    try:
        with sqlite3.connect("database.db") as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            resultado = cursor.fetchall()
            
            # Se o banco não achar nada, avise o terminal
            if not resultado:
                print("[DEBUG SQL] Resultado: VAZIO")
                
        return str(resultado)
        
    except sqlite3.Error as e:
        print(f"[DEBUG SQL] Erro no SQLite: {e}") # <-- AJUDA A VER SE ELE ERROU A COLUNA
        return f"Erro ao consultar o banco: {e}"
    
llm = AzureChatOpenAI(
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
    api_version="2024-12-01-preview",
    azure_endpoint=os.getenv("AZURE_LLM_ENDPOINT"),
    api_key=os.getenv("AZURE_LLM_KEY"),
)

llm_with_tools = llm.bind_tools([consultar_banco])

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

builder = StateGraph(AgentState)

def llm_node(state: AgentState) -> dict:
    messages = state["messages"]
    messages_for_llm = [SystemMessage(content=SYSTEM_PROMPT)] + messages
    response = llm_with_tools.invoke(messages_for_llm)
    return {"messages": [response]}

tools_node = ToolNode(tools=[consultar_banco])

builder.add_node("llm", llm_node)
builder.add_node("tools", tools_node)
builder.add_edge(START, "llm")
builder.add_conditional_edges("llm", tools_condition)
builder.add_edge("tools", "llm")

rag_agent = builder.compile()