import pandas as pd

def limpiar_datos_base(df):
    
    print("Iniciando limpieza de datos...")
    
    #nombres columnas
    renombres = {
        'AMIE': 'cod_amie',
        'Anio_lectivo': 'anio_lectivo',
        'Nombre_Institucion': 'nombre_institucion',
        'Cod_Provincia': 'cod_provincia',
        'Cod_Canton': 'cod_canton',
        'Cod_Parroquia': 'cod_parroquia'
    }
    df = df.rename(columns=renombres)
    #minusculas columnas
    df.columns = [c.lower() for c in df.columns]

    
    columnas_numericas = [
        'total_docentes', 'docentes_femenino', 'docentes_masculino',
        'total_estudiantes', 'estudiantes_femenino', 'estudiantes_masculino',
        'ecuatoriana', 'colombiana', 'venezolana', 'peruana', 
        'otros_paises_de_america', 'otros_continentes'
    ]
    
    # Validamos que las columnas existan antes de rellenar
    cols_presentes = [c for c in columnas_numericas if c in df.columns]
    # Limpiar formato: quitar espacios y comas de miles (ej: ' 1,127 ' -> 1127)
    for col in cols_presentes:
        df[col] = df[col].astype(str).str.strip().str.replace(',', '', regex=False)
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    
    return df

# CONSTRUCCIÓN DE DIMENSIONES

def construir_dim_periodo(df):
    # Extraemos los años únicos y les asignamos un ID secuencial
    dim = df[['anio_lectivo']].drop_duplicates().dropna().reset_index(drop=True)
    dim.insert(0, 'id_periodo', range(1, len(dim) + 1))
    return dim

def construir_dim_ubicacion(df):
    cols = ['zona', 'cod_provincia', 'provincia', 'cod_canton', 'canton', 'cod_parroquia', 'parroquia']
    # Nos quedamos con ubicaciones únicas
    dim = df[cols].drop_duplicates().dropna(subset=['cod_parroquia']).reset_index(drop=True)
    dim.insert(0, 'id_ubicacion', range(1, len(dim) + 1))
    return dim

def construir_dim_perfil_educativo(df):
    cols = ['tipo_educacion', 'sostenimiento', 'area', 'regimen_escolar', 'jurisdiccion']
    dim = df[cols].drop_duplicates().dropna().reset_index(drop=True)
    dim.insert(0, 'id_perfil', range(1, len(dim) + 1))
    return dim

def construir_dim_institucion(df):
    cols = ['cod_amie', 'nombre_institucion']
    # Una institución no debería duplicarse, nos quedamos con la última versión de su nombre
    dim = df[cols].drop_duplicates(subset=['cod_amie'], keep='last').dropna(subset=['cod_amie']).reset_index(drop=True)
    return dim

# ==========================================
# CONSTRUCCIÓN DE TABLA DE HECHOS
# ==========================================

def construir_fact_matricula(df, dim_periodo, dim_ubicacion, dim_perfil):
    print("Construyendo tabla de hechos...")
    
    # 1. Hacemos MERGE (JOIN) de la tabla base con las dimensiones para obtener los IDs (Llaves foráneas)
    # Merge para obtener id_periodo
    hechos = df.merge(dim_periodo, on='anio_lectivo', how='left')
    
    # Merge para obtener id_ubicacion
    hechos = hechos.merge(dim_ubicacion, on=['zona', 'cod_provincia', 'provincia', 'cod_canton', 'canton', 'cod_parroquia', 'parroquia'], how='left')
    
    # Merge para obtener id_perfil
    hechos = hechos.merge(dim_perfil, on=['tipo_educacion', 'sostenimiento', 'area', 'regimen_escolar', 'jurisdiccion'], how='left')
    
    # 2. Seleccionamos solo las llaves foráneas y las métricas (números)
    columnas_finales = [
        'cod_amie', 'id_periodo', 'id_ubicacion', 'id_perfil',
        'total_docentes', 'docentes_femenino', 'docentes_masculino',
        'total_estudiantes', 'estudiantes_femenino', 'estudiantes_masculino',
        'ecuatoriana', 'colombiana', 'venezolana', 'peruana', 
        'otros_paises_de_america', 'otros_continentes'
    ]
    
    # En caso de que tu CSV tenga nombres un poco distintos para nacionalidades, 
    # asegúrate de que los nombres aquí coincidan con los que bajaste a minúsculas
    cols_existentes = [c for c in columnas_finales if c in hechos.columns]
    
    fact_final = hechos[cols_existentes].copy()
    
    # Renombramos las nacionalidades para que hagan match exacto con la base de datos de Postgres
    renombres_fact = {
        'estudiantes_femenino': 'est_femenino',
        'estudiantes_masculino': 'est_masculino',
        'ecuatoriana': 'est_ecuatoriana',
        'colombiana': 'est_colombiana',
        'venezolana': 'est_venezolana',
        'peruana': 'est_peruana',
        'otros_paises_de_america': 'est_otros_america',
        'otros_continentes': 'est_otros_continentes'
    }
    fact_final = fact_final.rename(columns=renombres_fact)
    
    return fact_final