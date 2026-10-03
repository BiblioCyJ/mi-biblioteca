import base64
from datetime import datetime
import io
import json
import os
import re
import sqlite3
import subprocess
import time
import unicodedata
import urllib.parse

from google import genai
from google.genai import types
import pandas as pd
from PIL import Image, ImageEnhance
from pypdf import PdfReader
import requests
import streamlit as st

# Configuración inicial de la página (DEBE ser la primera llamada de Streamlit)
st.set_page_config(
    page_title="Biblioteca Personal", page_icon="📖", layout="wide"
)

# Obtención segura de la API Key compatible con secrets.toml y variables de entorno
api_key_secret = None
try:
  if "GEMINI_API_KEY" in st.secrets:
    api_key_secret = st.secrets["GEMINI_API_KEY"]
except Exception:
  api_key_secret = None

API_KEY = (
    os.environ.get("GEMINI_API_KEY")
    or api_key_secret
    or "AQ.Ab8RN6IFQ8QOJm_qtJdGnu2j5Zjir8nr6Vc0ADc6g7jwrlmkOQ"
)

MODELO_OFICIAL = "gemini-3.8-flash"
LIMITE_DIARIO = 5000  # Cuota ampliada para cuentas de pago

# --- INYECCIÓN DE ESTILOS CSS "BIBLIOTECA CÁLIDA" ---
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #2C221E;
    }

    h1, h2, h3, h4 {
        font-family: 'Inter', sans-serif !important;
        color: #4A2E1A !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em;
    }

    .title-banner {
        background-color: #EFE8DA;
        padding: 1.2rem 2rem;
        border-radius: 12px;
        border-left: 6px solid #8B5A2B;
        box-shadow: 0 4px 12px rgba(139, 90, 43, 0.08);
        margin-bottom: 2rem;
    }

    .stButton button {
        font-family: 'Inter', sans-serif !important;
        font-weight: 500 !important;
        border-radius: 6px !important;
        border: 1px solid #C5A075 !important;
        background-color: #F3EFE6 !important;
        color: #4A2E1A !important;
        padding: 0.2rem 0.5rem !important;
        font-size: 12px !important;
        min-height: 2.2rem !important;
        transition: all 0.2s ease-in-out;
    }

    .stButton button:hover {
        background-color: #8B5A2B !important;
        color: #FFFFFF !important;
        border-color: #8B5A2B !important;
    }

    .small-text { font-size: 13px !important; color: #6E5D4F; }

    /* PERSONALIZAR ANIMACIÓN DE ESPERA SUPERIOR DERECHA */
    [data-testid="stStatusWidget"] svg,
    [data-testid="stStatusWidget"] img {
        display: none !important;
    }
    [data-testid="stStatusWidget"]::before {
        content: "📖";
        font-size: 1.3rem;
        margin-right: 6px;
        display: inline-block;
        animation: paso-pagina 1.2s infinite ease-in-out;
    }
    @keyframes paso-pagina {
        0% { transform: scale(1) rotate(0deg); }
        50% { transform: scale(1.25) rotate(-12deg); }
        100% { transform: scale(1) rotate(0deg); }
    }
    </style>
""",
    unsafe_allow_html=True,
)


# --- BANNER CON MAPAMUNDI DEL BEATO DE OSMA ---
def cargar_mapamundi_html():
  nombre_archivo = "mapamundi_osma.jpg"
  img_tag = ""

  if os.path.exists(nombre_archivo):
    with open(nombre_archivo, "rb") as f:
      b64_data = base64.b64encode(f.read()).decode("utf-8")
      img_tag = (
          f'<img src="data:image/jpeg;base64,{b64_data}" alt="Mapamundi del'
          ' Beato de Osma" style="width: 110px; height: 85px; object-fit:'
          " cover; border-radius: 8px; border: 2px solid #8B5A2B; box-shadow: 0"
          ' 2px 6px rgba(0,0,0,0.15);">'
      )
  else:
    img_tag = '<div style="font-size: 2.8rem; line-height: 1;">📜</div>'

  return f"""
    <div class="title-banner" style="display: flex; align-items: center; gap: 1.5rem;">
        {img_tag}
        <div>
            <h1 style="margin: 0; padding: 0; font-size: 2.2rem; color: #4A2E1A;"> Biblioteca Personal de Carme i Jaume</h1>
            <p style="margin: 0.3rem 0 0 0; color: #6E5D4F; font-size: 0.95rem;">Col·lecció particular de llibres físics i digitals </p>
        </div>
    </div>
    """


st.markdown(cargar_mapamundi_html(), unsafe_allow_html=True)

if "peticiones_hoy" not in st.session_state:
  st.session_state["peticiones_hoy"] = 0

if "ultimos_ids_importados" not in st.session_state:
  st.session_state["ultimos_ids_importados"] = []


def registrar_peticion():
  st.session_state["peticiones_hoy"] += 1


# --- FUNCIONES DE IMAGEN Y DETECCIÓN ---
def reducir_resolucion_imagen(imagen, max_dim=800):
  if not isinstance(imagen, Image.Image):
    img = Image.open(imagen)
  else:
    img = imagen.copy()

  img.thumbnail((max_dim, max_dim))
  return img


def optimizar_foto_estante(
    imagen_pil,
    recorte_horizontal=0.08,
    aumento_brillo=1.25,
    aumento_contraste=1.2,
):
  ancho, alto = imagen_pil.size
  margen_x = int(ancho * recorte_horizontal)
  margen_y = int(alto * 0.04)

  imagen_recortada = imagen_pil.crop(
      (margen_x, margen_y, ancho - margen_x, alto - margen_y)
  )

  potenciador_brillo = ImageEnhance.Brightness(imagen_recortada)
  imagen_iluminada = potenciador_brillo.enhance(aumento_brillo)

  potenciador_contraste = ImageEnhance.Contrast(imagen_iluminada)
  return potenciador_contraste.enhance(aumento_contraste)


def convertir_imagen_a_base64(uploaded_file):
  try:
    bytes_data = uploaded_file.getvalue()
    base64_encoded = base64.b64encode(bytes_data).decode("utf-8")
    mime_type = uploaded_file.type
    return f"data:{mime_type};base64,{base64_encoded}"
  except Exception:
    return ""


def obtener_portada_libro(isbn="", titulo="", autor=""):
  isbn_limpio = str(isbn).replace("-", "").replace(" ", "").strip() if isbn else ""
  if (
      isbn_limpio
      and isbn_limpio.upper() != "S/N"
      and len(isbn_limpio) in [10, 13]
  ):
    try:
      url_gb = (
          f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn_limpio}"
      )
      res = requests.get(url_gb, timeout=3).json()
      if "items" in res and len(res["items"]) > 0:
        volume_info = res["items"][0].get("volumeInfo", {})
        image_links = volume_info.get("imageLinks", {})
        url_img = image_links.get("thumbnail") or image_links.get(
            "smallThumbnail"
        )
        if url_img:
          return url_img.replace("http://", "https://")
    except Exception:
      pass

    url_ol = f"https://covers.openlibrary.org/b/isbn/{isbn_limpio}-L.jpg?default=false"
    try:
      res = requests.get(url_ol, timeout=3)
      if res.status_code == 200 and len(res.content) > 1000:
        return url_ol
    except Exception:
      pass

  if titulo and titulo.upper() != "S/T":
    try:
      q_titulo = f'intitle:"{titulo}"'
      q_autor = (
          f' +inauthor:"{autor}"' if (autor and autor.upper() != "S/A") else ""
      )
      query = urllib.parse.quote(q_titulo + q_autor)
      url_gb = f"https://www.googleapis.com/books/v1/volumes?q={query}&maxResults=3"
      res = requests.get(url_gb, timeout=3).json()
      if "items" in res:
        for item in res["items"]:
          volume_info = item.get("volumeInfo", {})
          image_links = volume_info.get("imageLinks", {})
          url_img = image_links.get("thumbnail") or image_links.get(
              "smallThumbnail"
          )
          if url_img:
            return url_img.replace("http://", "https://")
    except Exception:
      pass

  return ""


# --- FUNCIONES DE BASE DE DATOS Y NORMALIZACIÓN DE DUPLICADOS ---
def conectar_bd():
  conn = sqlite3.connect("biblioteca.db")
  cursor = conn.cursor()

  cursor.execute("""
        CREATE TABLE IF NOT EXISTS libros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT,
            autor TEXT,
            editorial TEXT,
            isbn TEXT,
            sinopsis TEXT,
            anio_publicacion TEXT,
            lugar_publicacion TEXT,
            paginas TEXT,
            traduccion TEXT,
            tematica TEXT,
            portada_url TEXT,
            pendiente_revision INTEGER DEFAULT 0,
            formato TEXT DEFAULT 'Físico',
            ruta_archivo TEXT DEFAULT '',
            idioma TEXT DEFAULT 'Español',
            ubicacion_estante TEXT DEFAULT ''
        )
    """)

  cursor.execute(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='prestamos';"
  )
  tabla_existe = cursor.fetchone()

  if not tabla_existe:
    cursor.execute("""
            CREATE TABLE prestamos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                libro_id INTEGER,
                titulo_libro TEXT,
                persona TEXT,
                fecha_prestamo TEXT,
                estado TEXT,
                FOREIGN KEY(libro_id) REFERENCES libros(id)
            )
        """)
  else:
    cols_prestamos = [
        col[1]
        for col in cursor.execute("PRAGMA table_info(prestamos)").fetchall()
    ]
    if "titulo_libro" not in cols_prestamos:
      try:
        cursor.execute("ALTER TABLE prestamos RENAME TO prestamos_old;")
        cursor.execute("""
                    CREATE TABLE prestamos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        libro_id INTEGER,
                        titulo_libro TEXT,
                        persona TEXT,
                        fecha_prestamo TEXT,
                        estado TEXT,
                        FOREIGN KEY(libro_id) REFERENCES libros(id)
                    )
                """)
        cursor.execute("""
                    INSERT INTO prestamos (id, libro_id, titulo_libro, persona, fecha_prestamo, estado)
                    SELECT id, libro_id, 'Desconocido', persona, fecha_prestamo, estado FROM prestamos_old;
                """)
        cursor.execute("DROP TABLE prestamos_old;")
      except Exception:
        pass

  columnas_existentes = [
      col[1] for col in cursor.execute("PRAGMA table_info(libros)").fetchall()
  ]
  nuevas_columnas = {
      "anio_publicacion": "TEXT",
      "lugar_publicacion": "TEXT",
      "paginas": "TEXT",
      "traduccion": "TEXT",
      "tematica": "TEXT",
      "portada_url": "TEXT",
      "pendiente_revision": "INTEGER DEFAULT 0",
      "formato": "TEXT DEFAULT 'Físico'",
      "ruta_archivo": "TEXT DEFAULT ''",
      "idioma": "TEXT DEFAULT 'Español'",
      "ubicacion_estante": "TEXT DEFAULT ''",
  }
  for col_nombre, col_tipo in nuevas_columnas.items():
    if col_nombre not in columnas_existentes:
      cursor.execute(f"ALTER TABLE libros ADD COLUMN {col_nombre} {col_tipo}")

  conn.commit()
  return conn


def normalizar_texto(texto):
  if not texto:
    return ""
  texto = str(texto).lower().strip()
  texto = "".join(
      c
      for c in unicodedata.normalize("NFD", texto)
      if unicodedata.category(c) != "Mn"
  )
  texto = re.sub(r"[^a-z0-9]", "", texto)
  return texto


def buscar_duplicado_en_bd(cursor, titulo, autor, isbn=""):
  isbn_limpio = (
      str(isbn).replace("-", "").replace(" ", "").strip().upper() if isbn else ""
  )

  cursor.execute(
      "SELECT id, titulo, autor, isbn FROM libros WHERE id IS NOT NULL"
  )
  libros_bd = cursor.fetchall()

  if isbn_limpio and isbn_limpio != "S/N" and len(isbn_limpio) in [10, 13]:
    for libro in libros_bd:
      id_db, tit_db, aut_db, isbn_db = libro
      isbn_db_limpio = (
          str(isbn_db).replace("-", "").replace(" ", "").strip().upper()
          if isbn_db
          else ""
      )
      if isbn_db_limpio == isbn_limpio:
        return (id_db, tit_db, aut_db, "ISBN idéntico")

  tit_buscado = normalizar_texto(titulo)
  aut_buscado = normalizar_texto(autor)

  if tit_buscado and tit_buscado != "st":
    for libro in libros_bd:
      id_db, tit_db, aut_db, _ = libro
      tit_db_norm = normalizar_texto(tit_db)
      aut_db_norm = normalizar_texto(aut_db)

      if tit_buscado == tit_db_norm and (
          aut_buscado == aut_db_norm
          or aut_buscado in aut_db_norm
          or aut_db_norm in aut_buscado
      ):
        return (id_db, tit_db, aut_db, "Coincidencia de Título y Autor")

  return None


# --- FUNCIONES DE LECTURA Y PROCESAMIENTO DE PDFS ---
def extraer_texto_pdf(uploaded_file, max_paginas=4):
  try:
    reader = PdfReader(uploaded_file)
    texto = ""
    paginas_a_leer = min(len(reader.pages), max_paginas)
    for i in range(paginas_a_leer):
      t = reader.pages[i].extract_text()
      if t:
        texto += t + "\n--- PÁGINA ---\n"
    return texto
  except Exception as e:
    return f"Error al leer PDF: {str(e)}"


# --- FUNCIONES DE CONSULTA GEMINI (API DE PAGO OFICIAL) ---
def ejecutar_consulta_gemini(contents):
  clave_limpia = API_KEY.strip() if API_KEY else ""
  if not clave_limpia:
    raise Exception("No hay API Key de Gemini configurada.")

  http_opts = types.HttpOptions(
      retry_options=types.HttpRetryOptions(
          attempts=5, initial_delay=2.0, max_delay=20.0
      )
  )
  client = genai.Client(api_key=clave_limpia, http_options=http_opts)

  config = types.GenerateContentConfig(
      temperature=0.2,
  )

  for intento in range(5):
    try:
      if intento == 0:
        registrar_peticion()

      response = client.models.generate_content(
          model=MODELO_OFICIAL, contents=contents, config=config
      )
      if response and response.text:
        return response.text
    except Exception as e:
      err_str = str(e)

      if "503" in err_str or "UNAVAILABLE" in err_str:
        time.sleep(3)
        continue
      elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
        tiempo_espera = (intento + 1) * 5
        time.sleep(tiempo_espera)
        continue
      else:
        raise Exception(f"Error en la API de Gemini: {err_str}")

  raise Exception(
      "⚠️ No se pudo obtener respuesta del servicio de IA tras varios reintentos."
  )


def extraer_lomos_de_imagen(imagen):
  img_optimizada = reducir_resolucion_imagen(imagen, max_dim=800)
  prompt = """
    Analiza esta imagen y detecta todos los lomos de libros visibles.
    Devuelve una lista limpia de los títulos o textos visibles en los lomos, separados únicamente por comas.
    No añadas introducciones ni explicaciones.
    """
  try:
    resultado = ejecutar_consulta_gemini([img_optimizada, prompt])
    lomos = [lomo.strip() for lomo in resultado.split(",") if lomo.strip()]
    return lomos
  except Exception as e:
    st.error(f"{str(e)}")
    return []


def buscar_lote_libros_con_ia(lista_pistas, tamanio_bloque=5):
  fichas_totales = []
  total_libros = len(lista_pistas)

  progreso_bar = st.progress(0.0)
  status_text = st.empty()

  for i in range(0, total_libros, tamanio_bloque):
    sub_lote = lista_pistas[i : i + tamanio_bloque]
    num_bloque = (i // tamanio_bloque) + 1
    total_bloques = (total_libros + tamanio_bloque - 1) // tamanio_bloque

    status_text.write(
        f"⏳ Procesando bloque {num_bloque} de {total_bloques} ({len(sub_lote)}"
        " libros)..."
    )

    pistas_texto = "\n".join(
        [f"{idx+1}. {p}" for idx, p in enumerate(sub_lote)]
    )

    prompt = f"""
        Eres un bibliotecario profesional experto. A partir de la siguiente lista de {len(sub_lote)} libros:
        {pistas_texto}

        Identifica cada libro de la lista y devuelve UN ÚNICO array JSON estricto en español con la estructura completa para CADA libro:
        [
          {{
            "titulo": "Título exacto y completo",
            "autor": "Autor o autores principales",
            "editorial": "Editorial que suele publicarlo en español",
            "isbn": "Código ISBN-13 o ISBN-10 válido sin guiones ni espacios, o 'S/N'",
            "anio_publicacion": "Año de publicación original o de la edición (ej. '1967' o 'S/D')",
            "lugar_publicacion": "Ciudad/País de publicación (ej. 'Buenos Aires, Argentina' o 'Madrid, España' o 'S/L')",
            "paginas": "Número aproximado de páginas o 'S/N'",
            "traduccion": "Traductor o idioma original (ej. 'Traducido del inglés por Juan Pérez' o 'Obra original en español' o 'S/I')",
            "tematica": "Temáticas o géneros separados por comas si aplica más de uno (ej. 'Egiptología, Religión' o 'Novela histórica')",
            "idioma": "Idioma del libro: 'Español', 'Catalán' u 'Otro'",
            "sinopsis": "Una sinopsis analítica y bien redactada de 3 a 5 frases."
          }}
        ]
        Responde ÚNICAMENTE en formato JSON plano (un array de objetos), sin bloques de código Markdown como ```json.
        """

    try:
      texto_respuesta = ejecutar_consulta_gemini(prompt)
      texto_limpio = (
          texto_respuesta.replace("```json", "").replace("```", "").strip()
      )
      datos_sublote = json.loads(texto_limpio)

      for libro in datos_sublote:
        isbn = libro.get("isbn", "")
        tit = libro.get("titulo", "")
        aut = libro.get("autor", "")
        libro["portada_url"] = obtener_portada_libro(
            isbn=isbn, titulo=tit, autor=aut
        )

      fichas_totales.extend(datos_sublote)

      progreso_actual = min(1.0, (i + len(sub_lote)) / total_libros)
      progreso_bar.progress(progreso_actual)

      if i + tamanio_bloque < total_libros:
        time.sleep(1)

    except Exception as e:
      st.error(f"Error al procesar el bloque {num_bloque}: {str(e)}")
      break

  progreso_bar.empty()
  status_text.empty()
  return fichas_totales


def enriquecer_libros_antiguos_con_ia():
  conn = conectar_bd()
  cursor = conn.cursor()
  cursor.execute(
      "SELECT id, titulo, autor, editorial, isbn, anio_publicacion,"
      " lugar_publicacion, paginas, traduccion, tematica, idioma FROM libros"
  )
  todos_los_libros = cursor.fetchall()

  valores_incompletos = [
      None,
      "",
      "s/d",
      "s/l",
      "s/n",
      "s/i",
      "-",
      "n/a",
      "none",
  ]
  libros_a_procesar = []

  for l in todos_los_libros:
    id_b, tit, aut, ed, isbn_val, anio, lug, pag, trad, tem, idm = l
    if (
        str(anio).strip().lower() in valores_incompletos
        or str(lug).strip().lower() in valores_incompletos
        or str(pag).strip().lower() in valores_incompletos
        or str(trad).strip().lower() in valores_incompletos
        or not tem
        or str(tem).strip().lower() in valores_incompletos
        or not idm
    ):
      libros_a_procesar.append((id_b, tit, aut, ed))

  if not libros_a_procesar:
    conn.close()
    return (
        "ℹ️ ¡Todos tus libros ya tienen sus fichas y temáticas completamente"
        " completas!"
    )

  pistas = [
      f"ID {l[0]}: Título: '{l[1]}' | Autor: '{l[2]}' | Editorial: '{l[3]}'"
      for l in libros_a_procesar
  ]
  pistas_texto = "\n".join(pistas)

  prompt = f"""
    Eres un bibliotecario profesional. Para cada uno de los siguientes libros almacenados en mi biblioteca:
    {pistas_texto}

    Investiga los metadatos bibliográficos y asigna una o varias temáticas e idioma principal.
    Devuelve un array JSON plano con la siguiente estructura exacta:
    [
      {{
        "id": ID_NUMERICO_ORIGINAL,
        "anio_publicacion": "Año de publicación original o edición (ej. '1975')",
        "lugar_publicacion": "Lugar de publicación (ej. 'Madrid, España')",
        "paginas": "Número de páginas aproximado (ej. '288')",
        "traduccion": "Idioma original o traductor (ej. 'Obra original en español')",
        "tematica": "Género o géneros separados por comas",
        "idioma": "Idioma principal del texto: 'Español', 'Catalán' u 'Otro'"
      }}
    ]
    Responde ÚNICAMENTE en formato JSON plano (un array de objetos), sin bloques de código Markdown como ```json.
    """

  try:
    texto_respuesta = ejecutar_consulta_gemini(prompt)
    texto_limpio = (
        texto_respuesta.replace("```json", "").replace("```", "").strip()
    )
    datos_actualizados = json.loads(texto_limpio)

    actualizados_cnt = 0
    for item in datos_actualizados:
      id_libro = item.get("id")
      anio = item.get("anio_publicacion", "")
      lugar = item.get("lugar_publicacion", "")
      paginas = item.get("paginas", "")
      traduccion = item.get("traduccion", "")
      tematica = item.get("tematica", "Novela")
      idioma = item.get("idioma", "Español")

      if id_libro:
        cursor.execute(
            """
                    UPDATE libros 
                    SET anio_publicacion = CASE WHEN anio_publicacion IS NULL OR LOWER(TRIM(anio_publicacion)) IN ('', 's/d', '-', 'n/a', 'none') THEN ? ELSE anio_publicacion END,
                        lugar_publicacion = CASE WHEN lugar_publicacion IS NULL OR LOWER(TRIM(lugar_publicacion)) IN ('', 's/l', '-', 'n/a', 'none') THEN ? ELSE lugar_publicacion END,
                        paginas = CASE WHEN paginas IS NULL OR LOWER(TRIM(paginas)) IN ('', 's/n', '-', 'n/a', 'none') THEN ? ELSE paginas END,
                        traduccion = CASE WHEN traduccion IS NULL OR LOWER(TRIM(traduccion)) IN ('', 's/i', '-', 'n/a', 'none') THEN ? ELSE traduccion END,
                        tematica = CASE WHEN tematica IS NULL OR LOWER(TRIM(tematica)) IN ('', '-', 'n/a', 'none') THEN ? ELSE tematica END,
                        idioma = CASE WHEN idioma IS NULL OR LOWER(TRIM(idioma)) IN ('', '-') THEN ? ELSE idioma END
                    WHERE id = ?
                """,
            (anio, lugar, paginas, traduccion, tematica, idioma, id_libro),
        )
        actualizados_cnt += 1

    conn.commit()
    conn.close()
    return (
        f"✅ ¡Se han actualizado correctamente {actualizados_cnt} libros con"
        " sus metadatos y temáticas!"
    )

  except Exception as e:
    conn.close()
    return f"Error al actualizar registros antiguos: {str(e)}"


# --- MENÚ LATERAL Y CONTADOR DE CUOTA ---
st.sidebar.header("🧭 Navegación")
opcion = st.sidebar.radio(
    "Secciones",
    [
        "Libros Catalogados",
        "Añadir libro individual",
        "Añadir lote de libros",
        "Biblioteca Digital (PDF)",
        "Control de préstamos",
    ],
)

st.sidebar.markdown("---")
st.sidebar.subheader("🛠️ Mantenimiento")

if st.sidebar.button("🔄 Completar datos antiguos con IA"):
  if st.session_state["peticiones_hoy"] >= LIMITE_DIARIO:
    st.sidebar.error("⚠️ Has alcanzado el límite diario de peticiones de IA.")
  else:
    with st.spinner("Buscando temáticas y metadatos con IA..."):
      msg = enriquecer_libros_antiguos_con_ia()
      st.sidebar.success(msg)
      time.sleep(2)
      st.rerun()

# --- NUEVA OPCIÓN: ACTUALIZAR EN LA NUBE ---
if st.sidebar.button("🔄 Actualizar en la nube"):
  with st.sidebar.status("Actualizando biblioteca...", expanded=True) as status:
    try:
      st.write("Añadiendo cambios...")
      subprocess.run(["git", "add", "."], check=True)

      st.write("Guardando cambios...")
      subprocess.run(
          [
              "git",
              "commit",
              "-m",
              "Actualización automática de base de datos y registros",
          ],
          check=True,
      )

      st.write("Subiendo a GitHub...")
      subprocess.run(["git", "push", "origin", "main"], check=True)

      status.update(
          label="¡Actualización completada con éxito!",
          state="complete",
          expanded=False,
      )
    except subprocess.CalledProcessError as e:
      status.update(
          label="Error en la actualización", state="error", expanded=True
      )
      st.error(f"Detalles del error: {e}")

st.sidebar.markdown("---")
st.sidebar.subheader("📥 Exportar Datos")


def generar_excel_biblioteca():
  conn = conectar_bd()
  df = pd.read_sql_query(
      """
        SELECT titulo, autor, editorial, isbn, anio_publicacion, 
               lugar_publicacion, paginas, traduccion, tematica, idioma, ubicacion_estante, sinopsis, formato, ruta_archivo, portada_url 
        FROM libros 
        ORDER BY titulo COLLATE NOCASE ASC
    """,
      conn,
  )
  conn.close()

  df.columns = [
      "Título",
      "Autor",
      "Editorial",
      "ISBN",
      "Año de Publicación",
      "Lugar de Publicación",
      "Páginas",
      "Traducción",
      "Temática",
      "Idioma",
      "Ubicación en el estante",
      "Sinopsis",
      "Formato",
      "Archivo PDF",
      "URL Portada",
  ]

  output = io.BytesIO()
  with pd.ExcelWriter(output, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="Mi Biblioteca")
  processed_data = output.getvalue()
  return processed_data


excel_data = generar_excel_biblioteca()
st.sidebar.download_button(
    label="📊 Descargar Biblioteca en Excel",
    data=excel_data,
    file_name="mi_biblioteca_personal.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Estado de la Cuota de Pago")
usadas = st.session_state["peticiones_hoy"]
restantes = max(0, LIMITE_DIARIO - usadas)
porcentaje = min(1.0, usadas / LIMITE_DIARIO)

st.sidebar.progress(porcentaje)
st.sidebar.write(f"**Peticiones usadas:** {usadas} / {LIMITE_DIARIO}")
st.sidebar.write(f"**Disponibles:** {restantes}")

if st.sidebar.button("🔄 Reiniciar contador local"):
  st.session_state["peticiones_hoy"] = 0
  st.rerun()

# =====================================================================
# VISTA 1: VER COLECCIÓN
# =====================================================================
if opcion == "Libros Catalogados":
  st.subheader("📚 Libros Catalogados")

  conn = conectar_bd()
  cursor = conn.cursor()
  cursor.execute("""
        SELECT id, titulo, autor, editorial, isbn, sinopsis, anio_publicacion, lugar_publicacion, paginas, traduccion, tematica, portada_url, pendiente_revision, formato, ruta_archivo, idioma, ubicacion_estante 
        FROM libros 
        ORDER BY titulo COLLATE NOCASE ASC
    """)
  libros = cursor.fetchall()
  conn.close()

  if libros:
    col_s1, col_s2, col_s3, col_s4 = st.columns([2, 1, 1, 1])

    with col_s1:
      busqueda = (
          st.text_input(
              "🔍 Buscar por título, autor, editorial, año o ubicación:", ""
          )
          .lower()
          .strip()
      )

    with col_s2:
      tematicas_set = set()
      for l in libros:
        tem_str = l[10]
        if tem_str and str(tem_str).strip() != "":
          subtemas = [
              st.strip() for st in str(tem_str).split(",") if st.strip()
          ]
          for st_item in subtemas:
            tematicas_set.add(st_item.capitalize())

      tematicas_disponibles = sorted(list(tematicas_set))
      opciones_desplegable = [
          "📁 Todas",
          "⏳ Pendientes de revisión",
      ] + tematicas_disponibles
      filtro_tematica = st.selectbox(
          "📁 Filtro por temática:", opciones_desplegable
      )

    with col_s3:
      filtro_formato_cat = st.selectbox(
          "💻 Formato:", ["Todos", "Físico", "Digital"]
      )

    with col_s4:
      filtro_idioma_cat = st.selectbox(
          "🌐 Idioma:", ["Todos", "Español", "Catalán", "Otro"]
      )

    libros_filtrados = []
    for l in libros:
      (
          id_db,
          tit,
          aut,
          ed,
          isbn_val,
          sin,
          anio_val,
          lug_val,
          pag_val,
          trad_val,
          tem_val,
          port_val,
          pend_val,
      ) = l[:13]
      form_val = l[13] if len(l) > 13 and l[13] else "Físico"
      ruta_val = l[14] if len(l) > 14 and l[14] else ""
      idm_val = l[15] if len(l) > 15 and l[15] else "Español"
      ubicacion_val = l[16] if len(l) > 16 and l[16] else ""

      es_pendiente = (pend_val == 1) or (
          id_db in st.session_state["ultimos_ids_importados"]
      )

      coincide_busqueda = (
          not busqueda
          or busqueda in str(tit).lower()
          or busqueda in str(aut).lower()
          or busqueda in str(ed).lower()
          or busqueda in str(anio_val).lower()
          or busqueda in str(ubicacion_val).lower()
      )

      coincide_tematica = False
      if filtro_tematica == "📁 Todas":
        coincide_tematica = True
      elif filtro_tematica == "⏳ Pendientes de revisión":
        if es_pendiente:
          coincide_tematica = True
      elif tem_val:
        subtemas_libro = [
            st.strip().lower() for st in str(tem_val).split(",") if st.strip()
        ]
        if filtro_tematica.lower() in subtemas_libro:
          coincide_tematica = True

      coincide_formato = (
          filtro_formato_cat == "Todos" or form_val == filtro_formato_cat
      )

      coincide_idioma = True
      if filtro_idioma_cat != "Todos":
        if filtro_idioma_cat == "Otro":
          coincide_idioma = idm_val not in ["Español", "Catalán"]
        else:
          coincide_idioma = idm_val == filtro_idioma_cat

      if (
          coincide_busqueda
          and coincide_tematica
          and coincide_formato
          and coincide_idioma
      ):
        libros_filtrados.append(l)

    total_filtrados = len(libros_filtrados)

    if total_filtrados > 0:
      st.markdown("---")
      cp1, cp2, cp3 = st.columns([1.2, 2.2, 2.6])

      with cp1:
        libros_por_pagina = st.selectbox(
            "Por página:", [10, 20, 50, 100], index=1, key="select_lpp"
        )

      total_paginas = max(
          1, (total_filtrados + libros_por_pagina - 1) // libros_por_pagina
      )

      if "pagina_actual" not in st.session_state:
        st.session_state["pagina_actual"] = 1

      if st.session_state["pagina_actual"] > total_paginas:
        st.session_state["pagina_actual"] = total_paginas

      with cp2:
        col_b_ant, col_b_txt, col_b_sig = st.columns([1, 1.4, 1])
        with col_b_ant:
          st.markdown(
              "<div style='margin-top: 1.8rem;'></div>", unsafe_allow_html=True
          )
          if st.button("‹ Ant") and st.session_state["pagina_actual"] > 1:
            st.session_state["pagina_actual"] -= 1
            st.rerun()
        with col_b_txt:
          st.markdown(
              "<div style='text-align: center; margin-top: 2.1rem;'"
              f" class='small-text'>Pág. <b>{st.session_state['pagina_actual']}</b>"
              f" de {total_paginas}</div>",
              unsafe_allow_html=True,
          )
        with col_b_sig:
          st.markdown(
              "<div style='margin-top: 1.8rem;'></div>", unsafe_allow_html=True
          )
          if (
              st.button("Sig ›")
              and st.session_state["pagina_actual"] < total_paginas
          ):
            st.session_state["pagina_actual"] += 1
            st.rerun()

      with cp3:
        inicio_idx = (
            st.session_state["pagina_actual"] - 1
        ) * libros_por_pagina + 1
        fin_idx = min(inicio_idx + libros_por_pagina - 1, total_filtrados)
        st.markdown(
            "<div style='text-align: right; margin-top: 2.1rem;'"
            f" class='small-text'>Mostrando <b>{inicio_idx}–{fin_idx}</b> de"
            f" <b>{total_filtrados}</b> encontrados</div>",
            unsafe_allow_html=True,
        )

      st.markdown("---")

      inicio = (st.session_state["pagina_actual"] - 1) * libros_por_pagina
      fin = inicio + libros_por_pagina
      libros_pagina = libros_filtrados[inicio:fin]

      for l in libros_pagina:
        (
            id_db,
            tit,
            aut,
            ed,
            isbn_val,
            sin,
            anio_val,
            lug_val,
            pag_val,
            trad_val,
            tem_val,
            port_val,
            pend_val,
        ) = l[:13]
        form_val = l[13] if len(l) > 13 and l[13] else "Físico"
        ruta_val = l[14] if len(l) > 14 and l[14] else ""
        idm_val = l[15] if len(l) > 15 and l[15] else "Español"
        ubicacion_val = l[16] if len(l) > 16 and l[16] else ""

        es_pendiente = (pend_val == 1) or (
            id_db in st.session_state["ultimos_ids_importados"]
        )
        icono_expander = (
            "⏳" if es_pendiente else ("💻" if form_val == "Digital" else "📌")
        )
        badge_formato = (
            "  [PDF Digital]" if form_val == "Digital" else "  [Físico]"
        )
        badge_idioma = f"  🌐 [{idm_val}]"
        badge_ub = f"  📍 [{ubicacion_val}]" if ubicacion_val else ""
        titulo_expander = f"{icono_expander} {tit} — {aut} ({anio_val or 'S/D'})  |  🏷 [{tem_val or 'General'}]{badge_idioma}{badge_formato}{badge_ub}"

        with st.expander(titulo_expander, expanded=False):
          if es_pendiente:
            st.markdown(
                """
                        <div style="background-color: #FEF3C7; border: 1.5px solid #FCD34D; padding: 0.8rem 1.2rem; border-radius: 8px; margin-bottom: 1.2rem; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
                            <div style="display: flex; align-items: center; gap: 0.6rem;">
                                <span style="font-size: 1.2rem;">⏳</span>
                                <span style="font-family: 'Inter', sans-serif; font-weight: 600; color: #92400E; font-size: 0.95rem;">Pendiente de revisar</span>
                            </div>
                            <span style="font-family: 'Inter', sans-serif; color: #B45309; font-size: 0.85rem;">Esta incorporación reciente está pendiente de validación.</span>
                        </div>
                        """,
                unsafe_allow_html=True,
            )

          col_img, col_d1, col_d2 = st.columns([1, 2, 2])

          with col_img:
            if port_val:
              st.image(port_val, caption="Portada", use_container_width=True)
            else:
              st.info("Sin portada")

          with col_d1:
            edit_tit = st.text_input(
                "Título", value=tit or "", key=f"edit_t_{id_db}"
            )
            edit_aut = st.text_input(
                "Autor", value=aut or "", key=f"edit_a_{id_db}"
            )
            edit_ed = st.text_input(
                "Editorial", value=ed or "", key=f"edit_e_{id_db}"
            )
            edit_isbn = st.text_input(
                "ISBN", value=isbn_val or "", key=f"edit_i_{id_db}"
            )

          with col_d2:
            edit_anio = st.text_input(
                "Año", value=anio_val or "", key=f"edit_an_{id_db}"
            )
            edit_lug = st.text_input(
                "Lugar", value=lug_val or "", key=f"edit_l_{id_db}"
            )
            edit_pag = st.text_input(
                "Páginas", value=pag_val or "", key=f"edit_pg_{id_db}"
            )
            edit_trad = st.text_input(
                "Traducción", value=trad_val or "", key=f"edit_tr_{id_db}"
            )

          c_extra1, c_extra2, c_extra3, c_extra4 = st.columns([1.5, 1, 1, 1.5])
          with c_extra1:
            edit_tem = st.text_input(
                "Temática(s)", value=tem_val or "Novela", key=f"edit_tem_{id_db}"
            )
          with c_extra2:
            edit_form = st.selectbox(
                "Formato",
                ["Físico", "Digital"],
                index=0 if form_val == "Físico" else 1,
                key=f"edit_form_{id_db}",
            )
          with c_extra3:
            idx_idm = 0
            if idm_val == "Catalán":
              idx_idm = 1
            elif idm_val != "Español":
              idx_idm = 2
            edit_idm = st.selectbox(
                "Idioma",
                ["Español", "Catalán", "Otro"],
                index=idx_idm,
                key=f"edit_idm_{id_db}",
            )
          with c_extra4:
            edit_ubicacion = st.text_input(
                "Ubicación en el estante",
                value=ubicacion_val or "",
                key=f"edit_ub_{id_db}",
            )

          edit_sin = st.text_area(
              "Sinopsis", value=sin or "", key=f"edit_s_{id_db}", height=85
          )

          with st.expander("🖼 Opciones avanzadas de portada", expanded=False):
            c_img_opt1, c_img_opt2, c_img_opt3, c_img_opt4, c_img_opt5 = (
                st.columns([2, 1.3, 1, 1, 1])
            )

            with c_img_opt1:
              edit_port = st.text_input(
                  "URL Portada", value=port_val or "", key=f"edit_p_{id_db}"
              )

            with c_img_opt2:
              subir_img_pc = st.file_uploader(
                  "📁 Subir de PC",
                  type=["jpg", "png", "jpeg"],
                  key=f"file_pc_{id_db}",
              )
              if subir_img_pc:
                base64_img = convertir_imagen_a_base64(subir_img_pc)
                if base64_img:
                  conn = conectar_bd()
                  cursor = conn.cursor()
                  cursor.execute(
                      "UPDATE libros SET portada_url=? WHERE id=?",
                      (base64_img, id_db),
                  )
                  conn.commit()
                  conn.close()
                  st.success("¡Imagen subida!")
                  st.rerun()

            with c_img_opt3:
              st.write("")
              if st.button("⚡ Autodetectar", key=f"btn_autocover_{id_db}"):
                url_auto = obtener_portada_libro(
                    isbn=edit_isbn, titulo=edit_tit, autor=edit_aut
                )
                if url_auto:
                  conn = conectar_bd()
                  cursor = conn.cursor()
                  cursor.execute(
                      "UPDATE libros SET portada_url=? WHERE id=?",
                      (url_auto, id_db),
                  )
                  conn.commit()
                  conn.close()
                  st.success("¡Autodetectada!")
                  st.rerun()
                else:
                  st.warning("No encontrada.")

            with c_img_opt4:
              st.write("")
              query_google = urllib.parse.quote(
                  f"libro {tit} {aut} portada"
              )
              link_google = (
                  f"https://www.google.com/search?tbm=isch&q={query_google}"
              )
              st.markdown(
                  f"<br>🔍 [<span class='small-text'>Ver en Google</span>]({link_google})",
                  unsafe_allow_html=True,
              )

            with c_img_opt5:
              st.write("")
              if port_val:
                if st.button("🗑 Borrar", key=f"btn_del_port_{id_db}"):
                  conn = conectar_bd()
                  cursor = conn.cursor()
                  cursor.execute(
                      "UPDATE libros SET portada_url='' WHERE id=?", (id_db,)
                  )
                  conn.commit()
                  conn.close()
                  st.success("Borrada.")
                  st.rerun()

          c_btn1, c_btn2, c_btn3 = st.columns([1.2, 1.2, 1])
          with c_btn1:
            if st.button("💾 Actualizar ficha", key=f"btn_up_{id_db}"):
              conn = conectar_bd()
              cursor = conn.cursor()
              cursor.execute(
                  """
                                UPDATE libros 
                                SET titulo=?, autor=?, editorial=?, isbn=?, sinopsis=?, anio_publicacion=?, lugar_publicacion=?, paginas=?, traduccion=?, tematica=?, portada_url=?, formato=?, idioma=?, ubicacion_estante=?, pendiente_revision=0
                                WHERE id=?
                            """,
                  (
                      edit_tit,
                      edit_aut,
                      edit_ed,
                      edit_isbn,
                      edit_sin,
                      edit_anio,
                      edit_lug,
                      edit_pag,
                      edit_trad,
                      edit_tem,
                      edit_port,
                      edit_form,
                      edit_idm,
                      edit_ubicacion,
                      id_db,
                  ),
              )
              conn.commit()
              conn.close()

              if id_db in st.session_state["ultimos_ids_importados"]:
                st.session_state["ultimos_ids_importados"].remove(id_db)

              st.success(
                  "¡Ficha actualizada y retirada de pendientes de revisión!"
              )
              st.rerun()

          with c_btn2:
            if es_pendiente:
              if st.button("✅ Confirmar ficha", key=f"btn_confirm_{id_db}"):
                conn = conectar_bd()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE libros SET pendiente_revision=0 WHERE id=?",
                    (id_db,),
                )
                conn.commit()
                conn.close()

                if id_db in st.session_state["ultimos_ids_importados"]:
                  st.session_state["ultimos_ids_importados"].remove(id_db)

                st.success("¡Ficha validada correctamente!")
                st.rerun()

          with c_btn3:
            if st.button("🗑️ Eliminar libro", key=f"btn_del_init_{id_db}"):
              st.session_state[f"confirmar_borrado_{id_db}"] = True
              st.rerun()

          if st.session_state.get(f"confirmar_borrado_{id_db}", False):
            st.warning(
                "⚠️ ¿Estás seguro de que deseas eliminar este libro? Esta"
                " acción no se puede deshacer."
            )
            c_conf1, c_conf2 = st.columns([1, 1])
            with c_conf1:
              if st.button(
                  "🔴 Sí, confirmar eliminación", key=f"btn_del_yes_{id_db}"
              ):
                conn = conectar_bd()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM libros WHERE id=?", (id_db,))
                conn.commit()
                conn.close()
                if id_db in st.session_state["ultimos_ids_importados"]:
                  st.session_state["ultimos_ids_importados"].remove(id_db)
                st.session_state[f"confirmar_borrado_{id_db}"] = False
                st.success("Libro eliminado de la base de datos.")
                st.rerun()
            with c_conf2:
              if st.button("❌ Cancelar", key=f"btn_del_no_{id_db}"):
                st.session_state[f"confirmar_borrado_{id_db}"] = False
                st.rerun()
    else:
      st.warning(
          "No se encontraron libros con los filtros o criterios de búsqueda"
          " actuales."
      )
  else:
    st.info("Aún no hay libros registrados en la base de datos.")

# =====================================================================
# VISTA 2: AÑADIR LIBRO INDIVIDUAL
# =====================================================================
elif opcion == "Añadir libro individual":
  st.subheader("📖 Añadir un Libro Individual")
  st.markdown(
      "Puedes introducir los datos de forma manual o subir una fotografía de la"
      " portada/libro para que Gemini rellene la ficha automáticamente."
  )

  modo_ingreso = st.radio(
      "¿Cómo deseas rellenar los datos?",
      ["✍️ Escritura manual", "📸 Subir foto de portada (IA)"],
      horizontal=True,
  )

  if "single_titulo" not in st.session_state:
    st.session_state["single_titulo"] = ""
  if "single_autor" not in st.session_state:
    st.session_state["single_autor"] = ""
  if "single_editorial" not in st.session_state:
    st.session_state["single_editorial"] = ""
  if "single_isbn" not in st.session_state:
    st.session_state["single_isbn"] = ""
  if "single_anio" not in st.session_state:
    st.session_state["single_anio"] = ""
  if "single_lugar" not in st.session_state:
    st.session_state["single_lugar"] = ""
  if "single_paginas" not in st.session_state:
    st.session_state["single_paginas"] = ""
  if "single_traduccion" not in st.session_state:
    st.session_state["single_traduccion"] = ""
  if "single_tematica" not in st.session_state:
    st.session_state["single_tematica"] = "Novela"
  if "single_idioma" not in st.session_state:
    st.session_state["single_idioma"] = "Español"
  if "single_ubicacion" not in st.session_state:
    st.session_state["single_ubicacion"] = ""
  if "single_sinopsis" not in st.session_state:
    st.session_state["single_sinopsis"] = ""
  if "single_portada" not in st.session_state:
    st.session_state["single_portada"] = ""

  if modo_ingreso == "📸 Subir foto de portada (IA)":
    foto_individual = st.file_uploader(
        "Sube la foto de la portada",
        type=["jpg", "jpeg", "png"],
        key="subida_foto_single",
    )

    if foto_individual:
      img_single = Image.open(foto_individual)
      st.image(img_single, caption="Portada cargada", width=220)

      if st.button("🤖 Extraer metadatos con Gemini"):
        if restantes < 1:
          st.error("⚠️ Has alcanzado el límite de peticiones diario.")
        else:
          with st.spinner(
              "Analizando portada y buscando información bibliográfica..."
          ):
            img_optimizada = reducir_resolucion_imagen(
                img_single, max_dim=800
            )
            prompt_single = """
                        Analiza esta portada de libro y extrae toda la información bibliográfica posible.
                        Devuelve un objeto JSON estricto en español con las siguientes claves exactas:
                        {
                          "titulo": "Título exacto",
                          "autor": "Autor o autores",
                          "editorial": "Editorial probable",
                          "isbn": "ISBN si se ve o 'S/N'",
                          "anio_publicacion": "Año de publicación o edición",
                          "lugar_publicacion": "Lugar de publicación o 'S/L'",
                          "paginas": "Número estimado de páginas o 'S/N'",
                          "traduccion": "Traductor o idioma original o 'S/I'",
                          "tematica": "Género o temáticas separadas por comas",
                          "idioma": "Idioma del libro: 'Español', 'Catalán' u 'Otro'",
                          "sinopsis": "Breve sinopsis de 2 a 4 frases"
                        }
                        Responde ÚNICAMENTE en formato JSON plano, sin bloques de código Markdown como ```json.
                        """
            try:
              res_txt = ejecutar_consulta_gemini(
                  [img_optimizada, prompt_single]
              )
              json_limpio = (
                  res_txt.replace("```json", "").replace("```", "").strip()
              )
              data_book = json.loads(json_limpio)

              st.session_state["single_titulo"] = data_book.get("titulo", "")
              st.session_state["single_autor"] = data_book.get("autor", "")
              st.session_state["single_editorial"] = data_book.get(
                  "editorial", ""
              )
              st.session_state["single_isbn"] = data_book.get("isbn", "")
              st.session_state["single_anio"] = data_book.get(
                  "anio_publicacion", ""
              )
              st.session_state["single_lugar"] = data_book.get(
                  "lugar_publicacion", ""
              )
              st.session_state["single_paginas"] = data_book.get("paginas", "")
              st.session_state["single_traduccion"] = data_book.get(
                  "traduccion", ""
              )
              st.session_state["single_tematica"] = data_book.get(
                  "tematica", "Novela"
              )
              st.session_state["single_idioma"] = data_book.get(
                  "idioma", "Español"
              )
              st.session_state["single_sinopsis"] = data_book.get(
                  "sinopsis", ""
              )

              auto_p = obtener_portada_libro(
                  isbn=st.session_state["single_isbn"],
                  titulo=st.session_state["single_titulo"],
                  autor=st.session_state["single_autor"],
              )
              if not auto_p:
                auto_p = convertir_imagen_a_base64(foto_individual)
              st.session_state["single_portada"] = auto_p

              st.success(
                  "¡Ficha extraída con éxito! Revisa los campos abajo y guarda"
                  " el libro."
              )
            except Exception as e:
              st.error(f"Error al procesar la portada: {e}")

  st.markdown("### 📋 Ficha del Libro")
  with st.form("form_nuevo_libro_individual"):
    f_tit = st.text_input("Título", value=st.session_state["single_titulo"])
    f_aut = st.text_input("Autor", value=st.session_state["single_autor"])

    c_f1, c_f2 = st.columns(2)
    with c_f1:
      f_ed = st.text_input(
          "Editorial", value=st.session_state["single_editorial"]
      )
      f_anio = st.text_input(
          "Año de publicación", value=st.session_state["single_anio"]
      )
      f_pag = st.text_input("Páginas", value=st.session_state["single_paginas"])
    with c_f2:
      f_isbn = st.text_input("ISBN", value=st.session_state["single_isbn"])
      f_lug = st.text_input(
          "Lugar de publicación", value=st.session_state["single_lugar"]
      )
      f_trad = st.text_input(
          "Traducción / Idioma original",
          value=st.session_state["single_traduccion"],
      )

    c_f3, c_f4, c_f5 = st.columns([1.5, 1, 1.2])
    with c_f3:
      f_tem = st.text_input(
          "Temática(s) (separadas por comas)",
          value=st.session_state["single_tematica"],
      )
      f_form = st.selectbox("Formato", ["Físico", "Digital"])
    with c_f4:
      idx_idm_s = 0
      if st.session_state["single_idioma"] == "Catalán":
        idx_idm_s = 1
      elif st.session_state["single_idioma"] not in ["Español", "Catalán"]:
        idx_idm_s = 2
      f_idm = st.selectbox(
          "Idioma principal", ["Español", "Catalán", "Otro"], index=idx_idm_s
      )
    with c_f5:
      f_ubicacion = st.text_input(
          "Ubicación en el estante",
          value=st.session_state["single_ubicacion"],
      )

    f_sin = st.text_area(
        "Sinopsis", value=st.session_state["single_sinopsis"], height=100
    )
    f_port = st.text_input(
        "URL de la portada o Base64", value=st.session_state["single_portada"]
    )

    guardar_en_db = st.form_submit_button("💾 Guardar libro en la biblioteca")

    if guardar_en_db:
      if f_tit.strip() and f_aut.strip():
        portada_final = f_port.strip()
        if not portada_final:
          portada_final = obtener_portada_libro(
              isbn=f_isbn, titulo=f_tit, autor=f_aut
          )

        conn = conectar_bd()
        cursor = conn.cursor()
        cursor.execute(
            """
                    INSERT INTO libros (titulo, autor, editorial, isbn, sinopsis, anio_publicacion, lugar_publicacion, paginas, traduccion, tematica, portada_url, formato, idioma, ubicacion_estante, pendiente_revision)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
            (
                f_tit,
                f_aut,
                f_ed,
                f_isbn,
                f_sin,
                f_anio,
                f_lug,
                f_pag,
                f_trad,
                f_tem,
                portada_final,
                f_form,
                f_idm,
                f_ubicacion,
            ),
        )
        nuevo_id = cursor.lastrowid
        conn.commit()
        conn.close()

        if "ultimos_ids_importados" not in st.session_state:
          st.session_state["ultimos_ids_importados"] = []
        st.session_state["ultimos_ids_importados"].append(nuevo_id)

        st.session_state["single_titulo"] = ""
        st.session_state["single_autor"] = ""
        st.session_state["single_editorial"] = ""
        st.session_state["single_isbn"] = ""
        st.session_state["single_anio"] = ""
        st.session_state["single_lugar"] = ""
        st.session_state["single_paginas"] = ""
        st.session_state["single_traduccion"] = ""
        st.session_state["single_tematica"] = "Novela"
        st.session_state["single_idioma"] = "Español"
        st.session_state["single_ubicacion"] = ""
        st.session_state["single_sinopsis"] = ""
        st.session_state["single_portada"] = ""

        st.success(
            f"¡El libro '{f_tit}' se ha guardado correctamente en tu"
            " biblioteca!"
        )
        time.sleep(1)
        st.rerun()
      else:
        st.error(
            "El título y el autor son obligatorios para poder guardar el libro."
        )

# =====================================================================
# VISTA 3: AÑADIR LOTE CON IA
# =====================================================================
elif opcion == "Añadir lote de libros":
  st.subheader("1. Subir fotografía del estante / lote")
  foto = st.file_uploader(
      "Sube una foto donde se vean los lomos", type=["jpg", "jpeg", "png"]
  )

  if foto:
    image = Image.open(foto)
    st.image(
        image, caption="Fotografía del lote cargada", use_container_width=True
    )

    if st.button("🔍 Detectar lomos automáticamente desde la foto"):
      if restantes < 1:
        st.error("⚠️ Has alcanzado el límite diario de peticiones de IA.")
      else:
        with st.spinner("Optimizando imagen y analizando lomos con Gemini..."):
          img_optimizada = optimizar_foto_estante(image)
          lomos_detectados = extraer_lomos_de_imagen(img_optimizada)
          if lomos_detectados:
            st.session_state["texto_lomos_input"] = ", ".join(lomos_detectados)
            st.success(
                f"Se han detectado {len(lomos_detectados)} lomos en la imagen."
            )
          else:
            st.warning("No se pudieron detectar lomos automáticamente.")

  st.subheader("2. Títulos/Lomos a procesar")

  col_btn, _ = st.columns([1, 4])
  with col_btn:
    if st.button("🗑️ Limpiar lista de lomos"):
      st.session_state["texto_lomos_input"] = ""
      st.rerun()

  if "texto_lomos_input" not in st.session_state:
    st.session_state["texto_lomos_input"] = ""

  texto_lote = st.text_area(
      "Escribe o edita los títulos a procesar (separados por comas o saltos de"
      " línea):",
      key="texto_lomos_input",
      height=120,
  )

  if st.button("🤖 Generar fichas catalográficas con IA (Procesamiento Masivo)"):
    lista_pistas = [
        p.strip()
        for p in texto_lote.replace("\n", ",").split(",")
        if p.strip()
    ]
    if not lista_pistas:
      st.warning("Por favor introduce o detecta al menos un título o lomo.")
    elif restantes < 1:
      st.error("⚠️ Has alcanzado el límite diario de peticiones de IA.")
    else:
      with st.spinner(
          f"Procesando {len(lista_pistas)} libros en bloques controlados..."
      ):
        fichas_masivas = buscar_lote_libros_con_ia(
            lista_pistas, tamanio_bloque=5
        )
        if fichas_masivas:
          st.session_state["libros_lote"] = fichas_masivas
          st.success(
              f"¡Se han generado {len(fichas_masivas)} fichas completas!"
          )

  if "libros_lote" in st.session_state and st.session_state["libros_lote"]:
    st.subheader(
        "3. Revisar fichas catalográficas e importar a la base de datos"
    )

    conn = conectar_bd()
    cursor = conn.cursor()

    duplicados_detectados = 0
    for libro in st.session_state["libros_lote"]:
      resultado_dup = buscar_duplicado_en_bd(
          cursor,
          libro.get("titulo", ""),
          libro.get("autor", ""),
          libro.get("isbn", ""),
      )
      if resultado_dup:
        libro["es_duplicado"] = True
        libro["id_duplicado"] = resultado_dup[0]
        libro["motivo_duplicado"] = resultado_dup[3]
        duplicados_detectados += 1
      else:
        libro["es_duplicado"] = False

    conn.close()

    omitir_duplicados = st.checkbox(
        f"🚫 Omitir automáticamente los libros duplicados ({duplicados_detectados} detectados en este lote)",
        value=True,
    )

    if st.button("📥 Importar lote a la base de datos"):
      conn = conectar_bd()
      cursor = conn.cursor()

      ids_nuevos = []
      omitidos_cnt = 0

      for lib in st.session_state["libros_lote"]:
        if omitir_duplicados and lib.get("es_duplicado"):
          omitidos_cnt += 1
          continue

        cursor.execute(
            """
                    INSERT INTO libros (titulo, autor, editorial, isbn, sinopsis, anio_publicacion, lugar_publicacion, paginas, traduccion, tematica, portada_url, formato, idioma, ubicacion_estante, pendiente_revision)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Físico', ?, '', 1)
                """,
            (
                lib.get("titulo", "S/T"),
                lib.get("autor", "S/A"),
                lib.get("editorial", "S/E"),
                lib.get("isbn", "S/N"),
                lib.get("sinopsis", ""),
                lib.get("anio_publicacion", "S/D"),
                lib.get("lugar_publicacion", "S/L"),
                lib.get("paginas", "S/N"),
                lib.get("traduccion", "S/I"),
                lib.get("tematica", "Novela"),
                lib.get("portada_url", ""),
                lib.get("idioma", "Español"),
            ),
        )
        ids_nuevos.append(cursor.lastrowid)

      conn.commit()
      conn.close()

      if "ultimos_ids_importados" not in st.session_state:
        st.session_state["ultimos_ids_importados"] = []
      st.session_state["ultimos_ids_importados"].extend(ids_nuevos)

      msg = f"✅ ¡Se han importado {len(ids_nuevos)} libros nuevos!"
      if omitidos_cnt > 0:
        msg += (
            f" ({omitidos_cnt} libros duplicados se omitieron correctamente)."
        )

      st.success(msg)
      del st.session_state["libros_lote"]
      time.sleep(1.5)
      st.rerun()

    for idx, libro in enumerate(st.session_state["libros_lote"]):
      aviso_titulo = (
          f"  ⚠ [Ya existe - ID #{libro['id_duplicado']}]"
          if libro.get("es_duplicado")
          else ""
      )

      with st.expander(
          f"📖 #{idx+1}: {libro.get('titulo', '')} — {libro.get('autor', '')}{aviso_titulo}",
          expanded=False,
      ):
        if libro.get("es_duplicado"):
          st.warning(
              f"⚠ **Posible duplicado detectado:** Ya existe un libro en tu"
              f" colección (ID #{libro['id_duplicado']}) por"
              f" **{libro['motivo_duplicado']}**."
          )

        c_img, c_d1, c_d2 = st.columns([1, 2, 2])

        with c_img:
          url_portada = libro.get("portada_url", "")
          if url_portada:
            st.image(
                url_portada,
                caption="Portada Detectada",
                use_container_width=True,
            )
          else:
            st.info("Sin portada")

        with c_d1:
          st.markdown(f"**Título:** {libro.get('titulo')}")
          st.markdown(f"**Autor:** {libro.get('autor')}")
          st.markdown(f"**Editorial:** {libro.get('editorial')}")
          st.markdown(f"**ISBN:** {libro.get('isbn')}")
        with c_d2:
          st.markdown(f"**Año:** {libro.get('anio_publicacion')}")
          st.markdown(f"**Temática:** {libro.get('tematica')}")
          st.markdown(f"**Idioma:** {libro.get('idioma', 'Español')}")
          st.markdown(f"**Páginas:** {libro.get('paginas')}")

        st.markdown(f"**Sinopsis:** {libro.get('sinopsis')}")

# =====================================================================
# VISTA 4: BIBLIOTECA DIGITAL (PDF)
# =====================================================================
elif opcion == "Biblioteca Digital (PDF)":
  st.subheader("💻 Carga e Integración de Libros Digitales (PDF)")
  st.markdown(
      "Sube uno o varios archivos PDF. El sistema extraerá el texto de sus"
      " primeras páginas y Gemini analizará los metadatos bibliográficos para"
      " registrarlos en la **Biblioteca Digital**."
  )

  archivos_pdf = st.file_uploader(
      "Selecciona archivos PDF para procesar:",
      type=["pdf"],
      accept_multiple_files=True,
      key="uploader_pdf_seccion",
  )

  if archivos_pdf and st.button(
      "🚀 Procesar e Incorporar PDFs a la Biblioteca Digital"
  ):
    if restantes < len(archivos_pdf):
      st.error("⚠️ Has alcanzado el límite diario de peticiones de IA.")
    else:
      progreso_bar = st.progress(0.0)
      status_txt = st.empty()
      total_archivos = len(archivos_pdf)
      guardados_cnt = 0
      ids_nuevos_pdf = []

      for idx, pdf_file in enumerate(archivos_pdf):
        status_txt.write(
            f"⏳ Procesando ({idx+1}/{total_archivos}): **{pdf_file.name}**..."
        )

        texto_pdf = extraer_texto_pdf(pdf_file, max_paginas=4)

        if (
            texto_pdf
            and not texto_pdf.startswith("Error")
            and len(texto_pdf.strip()) > 20
        ):
          prompt_pdf = f"""
                    Eres un bibliotecario profesional. Analiza el siguiente texto extraído de las primeras páginas de un libro en PDF:
                    {texto_pdf}

                    Extrae los metadatos bibliográficos y devuelve UN ÚNICO objeto JSON estricto en español con las siguientes claves exactas:
                    {{
                      "titulo": "Título exacto del libro",
                      "autor": "Autor o autores",
                      "editorial": "Editorial que lo publica o 'S/E'",
                      "isbn": "ISBN si se observa o 'S/N'",
                      "anio_publicacion": "Año de publicación o edición o 'S/D'",
                      "lugar_publicacion": "Lugar de publicación o 'S/L'",
                      "paginas": "Número de páginas si consta o 'S/N'",
                      "traduccion": "Traducción o idioma original o 'S/I'",
                      "tematica": "Temáticas o géneros separados por comas",
                      "idioma": "Idioma principal en el que está escrito el texto ('Español', 'Catalán' u 'Otro')",
                      "sinopsis": "Breve sinopsis analítica de 2 a 4 frases"
                    }}
                    Responde ÚNICAMENTE en formato JSON plano, sin bloques de código Markdown como ```json.
                    """
          try:
            res_ia = ejecutar_consulta_gemini(prompt_pdf)
            json_limpio = (
                res_ia.replace("```json", "").replace("```", "").strip()
            )
            data_pdf = json.loads(json_limpio)

            tit_pdf = data_pdf.get("titulo") or pdf_file.name.replace(
                ".pdf", ""
            )
            aut_pdf = data_pdf.get("autor") or "S/A"
            ed_pdf = data_pdf.get("editorial") or "S/E"
            isbn_pdf = data_pdf.get("isbn") or "S/N"
            anio_pdf = data_pdf.get("anio_publicacion") or "S/D"
            lug_pdf = data_pdf.get("lugar_publicacion") or "S/L"
            pag_pdf = data_pdf.get("paginas") or "S/N"
            trad_pdf = data_pdf.get("traduccion") or "S/I"
            tem_pdf = data_pdf.get("tematica") or "General"
            idm_pdf = data_pdf.get("idioma") or "Español"
            sin_pdf = data_pdf.get("sinopsis") or ""

            url_portada_pdf = obtener_portada_libro(
                isbn=isbn_pdf, titulo=tit_pdf, autor=aut_pdf
            )

            conn = conectar_bd()
            cursor = conn.cursor()
            cursor.execute(
                """
                            INSERT INTO libros (titulo, autor, editorial, isbn, sinopsis, anio_publicacion, lugar_publicacion, paginas, traduccion, tematica, portada_url, formato, ruta_archivo, idioma, ubicacion_estante, pendiente_revision)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Digital', ?, ?, '', 1)
                        """,
                (
                    tit_pdf,
                    aut_pdf,
                    ed_pdf,
                    isbn_pdf,
                    sin_pdf,
                    anio_pdf,
                    lug_pdf,
                    pag_pdf,
                    trad_pdf,
                    tem_pdf,
                    url_portada_pdf,
                    pdf_file.name,
                    idm_pdf,
                ),
            )
            new_id = cursor.lastrowid
            conn.commit()
            conn.close()

            ids_nuevos_pdf.append(new_id)
            guardados_cnt += 1
            st.success(
                f"✅ Incorporado: **{tit_pdf}** — *{aut_pdf}* ({idm_pdf})"
            )

          except Exception as e:
            st.error(f"Error analizando metadatos de {pdf_file.name}: {e}")
        else:
          conn = conectar_bd()
          cursor = conn.cursor()
          cursor.execute(
              """
                        INSERT INTO libros (titulo, autor, formato, ruta_archivo, idioma, ubicacion_estante, pendiente_revision)
                        VALUES (?, 'S/A', 'Digital', ?, 'Español', '', 1)
                    """,
              (pdf_file.name.replace(".pdf", ""), pdf_file.name),
          )
          new_id = cursor.lastrowid
          conn.commit()
          conn.close()

          ids_nuevos_pdf.append(new_id)
          guardados_cnt += 1
          st.warning(
              f"⚠️ Texto de {pdf_file.name} no extraíble directamente. Guardado"
              " registro básico."
          )

        progreso_bar.progress((idx + 1) / total_archivos)

      if "ultimos_ids_importados" not in st.session_state:
        st.session_state["ultimos_ids_importados"] = []
      st.session_state["ultimos_ids_importados"].extend(ids_nuevos_pdf)

      status_txt.empty()
      progreso_bar.empty()
      st.balloons()
      st.success(
          f"🎉 ¡Se han procesado e incorporado {guardados_cnt} libros digitales"
          " a tu biblioteca!"
      )

# =====================================================================
# VISTA 5: CONTROL DE PRÉSTAMOS
# =====================================================================
elif opcion == "Control de préstamos":
  st.subheader("🤝 Gestión y Control de Préstamos")
  st.markdown(
      "Registra a quién has prestado tus libros y haz un seguimiento de las"
      " devoluciones."
  )

  tab_nuevo, tab_historial = st.tabs(
      ["➕ Registrar Nuevo Préstamo", "📋 Libros Prestados / Historial"]
  )

  conn = conectar_bd()
  cursor = conn.cursor()
  cursor.execute(
      "SELECT id, titulo, autor FROM libros ORDER BY titulo COLLATE NOCASE ASC"
  )
  libros_disponibles = cursor.fetchall()
  conn.close()

  with tab_nuevo:
    if not libros_disponibles:
      st.warning(
          "No hay libros en la biblioteca para prestar. ¡Añade algunos primero!"
      )
    else:
      with st.form("form_nuevo_prestamo"):
        opciones_libros = {
            f"{l[1]} — ({l[2]})": l[0] for l in libros_disponibles
        }
        libro_seleccionado_str = st.selectbox(
            "Selecciona el libro a prestar:", list(opciones_libros.keys())
        )

        persona_prestamo = st.text_input("Nombre y apellidos de la persona:")
        fecha_actual = datetime.now().strftime("%Y-%m-%d")
        fecha_prestamo = st.text_input(
            "Fecha del préstamo:", value=fecha_actual
        )

        btn_guardar_prestamo = st.form_submit_button("📤 Registrar Préstamo")

        if btn_guardar_prestamo:
          if persona_prestamo.strip():
            id_libro_sel = opciones_libros[libro_seleccionado_str]
            titulo_puro = libro_seleccionado_str.split("—")[0].strip()

            conn = conectar_bd()
            cursor = conn.cursor()
            cursor.execute(
                """
                            INSERT INTO prestamos (libro_id, titulo_libro, persona, fecha_prestamo, estado)
                            VALUES (?, ?, ?, ?, ?)
                        """,
                (
                    id_libro_sel,
                    titulo_puro,
                    persona_prestamo.strip(),
                    fecha_prestamo,
                    "Prestado",
                ),
            )
            conn.commit()
            conn.close()

            st.success(
                f"¡Préstamo registrado con éxito! '{titulo_puro}' prestado a"
                f" {persona_prestamo.strip()}."
            )
            time.sleep(1)
            st.rerun()
          else:
            st.error(
                "Por favor, introduce el nombre y apellidos de la persona."
            )

  with tab_historial:
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, libro_id, titulo_libro, persona, fecha_prestamo, estado"
        " FROM prestamos ORDER BY id DESC"
    )
    prestamos_db = cursor.fetchall()
    conn.close()

    if prestamos_db:
      filtro_estado = st.radio(
          "Filtrar por estado:",
          ["Todos", "Activos (Prestados)", "Devueltos"],
          horizontal=True,
      )

      st.markdown("---")
      for p in prestamos_db:
        id_p, id_l, tit_l, persona_p, fecha_p, estado_p = p

        if filtro_estado == "Activos (Prestados)" and estado_p != "Prestado":
          continue
        if filtro_estado == "Devueltos" and estado_p != "Devuelto":
          continue

        color_badge = (
            "🔴 **Prestado**" if estado_p == "Prestado" else "🟢 **Devuelto**"
        )

        with st.expander(f"📖 {tit_l}  |  👤 {persona_p}  |  {color_badge}"):
          col_p1, col_p2, col_p3 = st.columns([2, 2, 1])

          with col_p1:
            st.markdown(f"**Libro:** {tit_l}")
            st.markdown(f"**Prestatario:** {persona_p}")
          with col_p2:
            st.markdown(f"**Fecha de préstamo:** {fecha_p}")
            st.markdown(f"**Estado:** {estado_p}")
          with col_p3:
            st.markdown(
                "<div style='margin-top: 0.5rem;'></div>",
                unsafe_allow_html=True,
            )
            if estado_p == "Prestado":
              if st.button("📥 Marcar devuelto", key=f"dev_{id_p}"):
                conn = conectar_bd()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE prestamos SET estado='Devuelto' WHERE id=?", (id_p,)
                )
                conn.commit()
                conn.close()
                st.success("¡Libro devuelto a la biblioteca!")
                st.rerun()

            if st.button("🗑️ Borrar registro", key=f"del_prest_{id_p}"):
              conn = conectar_bd()
              cursor = conn.cursor()
              cursor.execute("DELETE FROM prestamos WHERE id=?", (id_p,))
              conn.commit()
              conn.close()
              st.success("Registro eliminado.")
              st.rerun()
    else:
      st.info("No hay registros de préstamos en el historial.")