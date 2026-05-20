import pandas as pd
from sqlalchemy import create_engine

def cargar_datos(df, nombre_tabla, engine, schema='amie_dw'):
    """
    Carga un DataFrame en una tabla específica de PostgreSQL.
    """
    print(f"Cargando {len(df)} filas en la tabla {schema}.{nombre_tabla}...")
    try:
        # Usamos append porque la tabla ya existe con todas sus reglas (PK, FK)
        df.to_sql(
            name=nombre_tabla,
            con=engine,
            schema=schema,
            if_exists='append',
            index=False,
            method='multi', # Hace inserciones en bloque (más rápido)
            chunksize=1000  # Inserta de 1000 en 1000 para no saturar la memoria
        )
        print(f"-> Carga exitosa en {nombre_tabla}.")
    except Exception as e:
        print(f"-> ERROR al cargar en {nombre_tabla}: {e}")