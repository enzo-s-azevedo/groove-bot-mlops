from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
from pydantic import BaseModel
import os

from agent.agent import rag_agent

load_dotenv()

app = FastAPI(
    title = "RAG Agent API",
    description = "API para interagir com o Agente RAG",
    version = "1.0.0"
)

class ChatRequest(BaseModel):
    pergunta: str

class ChatResponse(BaseModel):
    resposta: str

@app.get("/")
def health_check():
    return {"status": "A API do Groove Bot está online e pronta para consultas."}

@app.post("/chat", response_model=ChatResponse)
def chat_com_agente(request: ChatRequest):
    try:
        # O input respeita exatamente a tipagem AgentState do LangGraph
        resultado_agente = rag_agent.invoke({"messages": [("user", request.pergunta)]})
        
        # Extrai o texto da última mensagem gerada pelo LLM
        resposta_agente = resultado_agente["messages"][-1].content
        
        return ChatResponse(resposta=resposta_agente)
        
    except Exception as e:
        # Se o Azure cair ou o banco falhar, devolvemos um erro 500
        print(f"❌ Erro interno: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao processar a consulta no agente.")