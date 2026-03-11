from google import genai

# Poné tu clave real acá entre las comillas
MI_CLAVE = "AIzaSyDo9pzJ5BR7BQrcfpAPBh6SdMHReBTJZSA"

try:
    client = genai.Client(api_key=MI_CLAVE)
    print("Conexión exitosa. Buscando modelos disponibles...\n")
    
    # Le pedimos a Google que nos liste todo lo que tenés habilitado
    for m in client.models.list():
        # Filtramos para que solo muestre los de la familia Gemini
        if 'gemini' in m.name.lower():
            print(f"Modelo encontrado: {m.name}")
            
except Exception as e:
    print(f"Error al conectar: {e}")