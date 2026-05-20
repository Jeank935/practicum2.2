import pandas as pd
import os

def extraer_datos(ruta_archivo):
    """
    Lee el archivo de datos del MINEDUC.
    Soporta archivos .csv (con latin-1 y ';') y .xlsx.
    """
    print(f"Extrayendo datos de: {ruta_archivo}...")
    try:
        ext = os.path.splitext(ruta_archivo)[1].lower()
        if ext == '.xlsx':
            df = pd.read_excel(ruta_archivo)
        else:
            # El CSV usa encoding latin-1 (Windows-1252) y coma como separador
            df = pd.read_csv(ruta_archivo, encoding='latin-1', low_memory=False)
        print(f"Extracción exitosa. Filas: {df.shape[0]}, Columnas: {df.shape[1]}")
        return df
    except Exception as e:
        print(f"Error al leer el archivo: {e}")
        return None