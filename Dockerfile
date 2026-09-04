# 1. Define a imagem base oficial do Python (versão slim para ser mais leve)
FROM python:3.12-slim

# 2. Define a pasta de trabalho dentro do container
WORKDIR /app

# 3. Copia apenas o arquivo de dependências primeiro
COPY requirements.txt .

# 4. Instala as dependências do projeto
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copia o restante do projeto para o container
COPY . .

# 6. Expõe a porta 8000 para a internet
EXPOSE 8000

# 7. O comando que o container vai rodar quando for ligado
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]