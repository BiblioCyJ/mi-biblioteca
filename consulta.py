import os
import sqlite3
import pandas as pd

# Conexión a la base de datos SQLite
DB_NAME = "biblioteca.db"


def consultar_biblioteca():
  if not os.path.exists(DB_NAME):
    print(f"❌ Error: No se encuentra la base de datos '{DB_NAME}'.")
    return

  conn = sqlite3.connect(DB_NAME)

  try:
    df = pd.read_sql_query("SELECT * FROM libros", conn)
  except Exception:
    try:
      # Buscar la primera tabla disponible si 'libros' no existe
      cursor = conn.cursor()
      cursor.execute(
          "SELECT name FROM sqlite_master WHERE type='table' AND name NOT"
          " LIKE 'sqlite_%';"
      )
      tablas = cursor.fetchall()
      if tablas:
        nombre_tabla = tablas[0][0]
        df = pd.read_sql_query(f"SELECT * FROM {nombre_tabla}", conn)
      else:
        df = pd.DataFrame()
    except Exception:
      df = pd.DataFrame()

  conn.close()

  if df.empty:
    print("⚠️ La base de datos está vacía o no se han encontrado tablas.")
    return

  # Limpiar nombres de columnas (minúsculas y sin espacios)
  df.columns = [str(c).strip().lower() for c in df.columns]

  # Función auxiliar para extraer valores probando varios nombres de columnas
  def obtener_valor(row, posibles_nombres):
    for nombre in posibles_nombres:
      if nombre in df.columns:
        val = row.get(nombre)
        if pd.notna(val) and str(val).strip() != "" and str(val) != "None":
          return val
    return "-"

  print("\n" + "=" * 50)
  print("     BIBLIOTECA PERSONAL DE CARME I JAUME")
  print("=" * 50)
  print(f"Total de registros encontrados: {len(df)}\n")

  print("1. Ver todos los libros")
  print("2. Buscar por título, autor, editorial, año o ubicación")

  opcion = input("\nSelecciona una opción (1-2): ").strip()

  resultados = df.copy()

  if opcion == "2":
    termino = input(
        "Introduce el término de búsqueda (ej. autor, año, título): "
    ).lower()
    cond = pd.Series(False, index=resultados.index)
    for col in resultados.columns:
      cond |= resultados[col].astype(str).str.contains(
          termino, case=False, na=False
      )
    resultados = resultados[cond]
    print(f"\n--- Resultados de la búsqueda ({len(resultados)} encontrados) ---")

  print("-" * 50)

  for idx, row in resultados.iterrows():
    titulo = obtener_valor(row, ["titulo", "títol", "title", "nom"])
    autor = obtener_valor(row, ["autor", "autora", "author", "scriptor"])
    categoria = obtener_valor(
        row, ["categoria", "tematica", "temática", "genere", "género"]
    )
    editorial = obtener_valor(row, ["editorial", "editor", "casa_editorial"])
    anio = obtener_valor(
        row,
        [
            "año",
            "anio",
            "any",
            "year",
            "ano",
            "any_publicacio",
            "fecha",
            "publicacio",
        ],
    )
    isbn = obtener_valor(row, ["isbn", "issn", "codi"])
    idioma = obtener_valor(row, ["idioma", "llengua", "language"])
    formato = obtener_valor(row, ["formato", "soporte", "tipus"])
    ubicacion = obtener_valor(row, ["ubicacion", "ubicació", "lloc", "estanteria"])
    estado = obtener_valor(row, ["estado", "observaciones", "notes", "notas"])

    print(f"📖 [{idx + 1}] {titulo} — {autor}")
    print(f"    • Categoría / Temática : {categoria}")
    print(f"    • Editorial            : {editorial}")
    print(f"    • Año de publicación   : {anio}")
    print(f"    • ISBN                 : {isbn}")
    print(f"    • Idioma / Formato     : {idioma} | {formato}")
    print(f"    • Ubicación            : {ubicacion}")
    if estado != "-":
      print(f"    • Estado / Notas       : {estado}")
    print("-" * 50)


if __name__ == "__main__":
  consultar_biblioteca()