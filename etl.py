import pandas as pd
from azure.storage.blob import BlobServiceClient
import os
from dotenv import load_dotenv
import io
from sqlalchemy import create_engine

load_dotenv()
blob_api_key = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

blob_service_client = BlobServiceClient.from_connection_string(blob_api_key)
container_client = blob_service_client.get_container_client("raw-data")
blob_client = container_client.get_blob_client("dataset_raw.xlsx")

df = pd.read_excel(io.BytesIO(blob_client.download_blob().readall()))

# print(df.head())

# print(df.columns)

clean_df = df.drop(columns=["Unnamed: 2", "Unnamed: 3", "Nome do Sebo", "Origem", "Valor pago", "Destaque ", "Fabricação", "Unnamed: 14"])
clean_df = clean_df.rename(columns={"Preço de mercado": "Preco"})
clean_df = clean_df.rename(columns={"Título": "Titulo"})
clean_df = clean_df.rename(columns={"Gênero": "Genero"})
clean_df[['Album', 'Titulo', 'Genero', 'Ano', 'Selo']] = clean_df[['Album', 'Titulo', 'Genero', 'Ano', 'Selo']].fillna("Não Informado")


engine = create_engine('sqlite:///database.db')
clean_df.to_sql('records', con=engine, if_exists='replace', index=False)

send_container_client = blob_service_client.get_container_client("clean-data")
send_blob_client = send_container_client.get_blob_client("database.db")

with open("database.db", "rb") as data:
    send_blob_client.upload_blob(data, overwrite=True)