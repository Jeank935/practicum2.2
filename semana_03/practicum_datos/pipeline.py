import os
from sqlalchemy import create_engine, text

from etl.extract import extraer_datos
from etl.transform import (limpiar_datos_base, construir_dim_periodo,
                           construir_dim_ubicacion, construir_dim_perfil_educativo,
                           construir_dim_institucion, construir_fact_matricula)
from etl.load import cargar_datos

# ---------------------------------------------------------
# CONFIGURACIÓN DE BASE DE DATOS 
# ---------------------------------------------------------
DB_USER = 'postgres'          
DB_PASS = '935475'             
DB_HOST = 'localhost'
DB_PORT = '5432'
DB_NAME = 'postgres'         

def ejecutar_pipeline():
    print("=== INICIANDO PIPELINE ETL ===")
    
    # 1. EXTRACCIÓN
    ruta_csv = 'data/registro-administrativo-historico_2009-2024-inicio.csv'
    df_raw = extraer_datos(ruta_csv)
    
    if df_raw is None:
        return

    # 2. TRANSFORMACIÓN
    print("\n--- FASE DE TRANSFORMACIÓN ---")
    df_clean = limpiar_datos_base(df_raw)
    
    dim_periodo = construir_dim_periodo(df_clean)
    dim_ubicacion = construir_dim_ubicacion(df_clean)
    dim_perfil = construir_dim_perfil_educativo(df_clean)
    dim_institucion = construir_dim_institucion(df_clean)
    
    fact_matricula = construir_fact_matricula(df_clean, dim_periodo, dim_ubicacion, dim_perfil)
    
    # 3. CARGA (LOAD)
    print("\n--- FASE DE CARGA (POSTGRESQL) ---")
    # Creamos la conexión a PostgreSQL (usamos psycopg v3 como driver)
    cadena_conexion = f'postgresql+psycopg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    engine = create_engine(cadena_conexion)
    
    # Crear el esquema si no existe
    with engine.connect() as conn:
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS amie_dw'))
        conn.commit()
    
    # carga en orden las dimensiones
    cargar_datos(dim_periodo, 'dim_periodo', engine)
    cargar_datos(dim_ubicacion, 'dim_ubicacion', engine)
    cargar_datos(dim_perfil, 'dim_perfil_educativo', engine)
    cargar_datos(dim_institucion, 'dim_institucion', engine)
    
    # carga tabla hechos
    cargar_datos(fact_matricula, 'fact_matricula', engine)
    
    print("\n=== PIPELINE EJECUTADO CON ÉXITO ===")

if __name__ == '__main__':
    ejecutar_pipeline()