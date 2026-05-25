from decimal import Decimal
from itertools import combinations
from time import sleep
import time
from typing import List, Dict, Any, Optional, Union, Set
from openai import OpenAI
import entities
# import questions
from dotenv import load_dotenv
import os
from fastapi import HTTPException
import json
import requests
from entities import AnalisisAtestado, AnalisisClase, ObjetoClase, EntidadClase, PropiedadEntidad, ContextoElementoClase, ListaAnalisis
import copy
from datetime import datetime

# ---- Inicializar LLM ----
load_dotenv()

client = OpenAI(
   base_url=os.getenv("OPENROUTER_URL"),
   api_key=os.getenv("OPENROUTER_API_KEY"),
)

ROOT_CLASS = os.getenv("ROOT_CLASS")

# ---- Clase para manejar el contexto del atestado y las preguntas al modelo LLM ----
class AtestadoLLM:
    """Wrapper para interactuar con el modelo LLM usando un contexto de atestado."""

    def __init__(self, contexto_atestado: str):
        """Inicializar el asistente.

        Parameters
        ----------
        contexto_atestado: str
            Texto completo del atestado que servirá como contexto del modelo.
        """
        self.contexto_atestado = contexto_atestado
        self.mensajes = [
            {
                "role": "system",
                "content": (
                    "Eres un asistente jurídico. Intenta ser muy concreto y sintético denominado entidades."
                    f"Tienes que extraer información del siguiente atestado:\n\n{contexto_atestado}"
                ),
            }
        ]
    
    def preguntar_llm(self, pregunta: str, llm_model: str, output_schema: Any) ->  str: #Optional[Dict[str, Any]]:
        """Lanza una pregunta al modelo y devuelve su respuesta como texto.

        Parameters
        ----------
        pregunta: str
            Pregunta que se enviará al modelo de lenguaje.

        Returns
        -------
        str
            Respuesta devuelta por el modelo.
        """
    
        #sleep(0.5)  # Simula un tiempo de espera para evitar saturar el modelo
        self.mensajes.append({"role": "user", "content": pregunta})
        #print(f"\n📌 output_schema: {output_schema}")
        print(f"📌 llm_model: {llm_model}")
        # print(f"📌?self.mensajes: {self.mensajes}")
        try:
            completion = client.chat.completions.create(
                model=llm_model,
                messages=self.mensajes,
                temperature=0,
                top_p=1.0,
                #max_tokens=1024,
                extra_body={
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "structured_response",
                            "strict": True,
                            "schema": output_schema
                        }
                    }
                }
            )
        except Exception as e:
            raise RuntimeError(f"Error llamando a llm ({llm_model}): {e}")
    
        respuesta = completion.choices[0].message.content
        self.mensajes.append({"role": "system", "content": respuesta})
        # print(f"preguntar_llm : {respuesta}")
        return respuesta
    
    def preguntar_llm_openai(self, pregunta: str, llm_model: str, output_schema: Any) ->  str: #Optional[Dict[str, Any]]:
        """Lanza una pregunta al modelo y devuelve su respuesta como texto.

        Parameters
        ----------
        pregunta: str
            Pregunta que se enviará al modelo de lenguaje.

        Returns
        -------
        str
            Respuesta devuelta por el modelo.
        """
    
        self.mensajes.append({"role": "user", "content": pregunta})
        print(f"📌 llm_model: {llm_model}")
        try:
            completion = client.chat.completions.create(
                model=llm_model,
                messages=self.mensajes,
                temperature=0,
                top_p=1.0,
                #max_tokens=1024,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_response",
                        "strict": True,
                        "schema": output_schema
                    }
                }
            )
        except Exception as e:
            raise RuntimeError(f"Error llamando a llm ({llm_model}): {e}")
    
        respuesta = completion.choices[0].message.content
        self.mensajes.append({"role": "system", "content": respuesta})
        # print(f"preguntar_llm : {respuesta}")
        return respuesta

traversal_global = {}

# ---- Función principal del árbol de decisión de delito contra la propiedad ----
# def analizarAtestado(atestado_llm: AtestadoLLM, laws: List[str], traversal: Any) -> Union[List[Dict[str, Any]], Dict[str, str]]:
def analizarAtestado(atestado_llm: AtestadoLLM, name: str, laws: List[str], traversal: Any) -> ListaAnalisis:
    """
    Ejecuta el árbol de decisión principal para clasificar el delito, iterando por las leyes de entrada.

    Parameters
    ----------
    atestado_llm: AtestadoLLM
        Instancia de ``AtestadoLLM`` con el contexto del atestado.
    laws: List[str]
        Lista de leyes/clases raíz a analizar (e.g., ["PropertyCrimeReport"]).
    traversal: Any
        Instancia de la clase de manejo de la ontología.

    Returns
    -------
    list[dict] | dict[str, str]
        Lista de respuestas obtenidas del LLM o un mensaje de error.
    """
    global traversal_global

    try:
        # Simplificación de la selección del LLM y estructura inicial
        llms = [os.getenv("DEFAULT_LLM")] #["openai/gpt-5.2-chat"]

        llm_model = llms[0] # Modelo definido en el código original de pago: gpt-4.1-mini
        ak = os.getenv("OPENROUTER_API_KEY")
        print(f"\n📌 -LLM_model: {llm_model} api_key:{ak}")

        analisis_atestados = {
            "nombre_grafo": name,
            "respuestas": []
        }

        traversal_global = traversal
        inicio = datetime.now()
        ha = inicio.strftime("%H:%M:%S")
        print(f"\n⏳ {ha} Inicio extracción")

        for law in laws:
            analisis_atestado: AnalisisAtestado = {
                "ley": law,
                "llm_model": llm_model,
                "contexto_positivo": [],
                "contexto_negativo": [],
                "objetos": [],
                "entidades": [],  # Se inicializa vacío para poblar con las entidades reales
                "analisis": [],
            }
            

            # 2. Realizar el recorrido DFS para obtener las subclases
            dfs_result = traversal.dfs_equivalent_and_subclasses(law, None)
            clases = dfs_result.get("classes", {})
            
            # Se usa el bucle para todas las clases, aunque la restricción [:1] esté en el código original
            # Se ha eliminado la restricción [:1] para un recorrido completo, si es necesario.
            clases_disponibles = [cls for cls in clases] #[:20] #[:15] #para limitar 
            analisis_atestado["entidades"].append({
                "nombre": name,
                "repetido": False,
                "dominios": [ROOT_CLASS],
                "dominios_negativos": [],
                "propiedades": []
            })
            print(f"\n✅ Clases disponibles (incluido Report) para análisis: {clases_disponibles}")

            nivel_excluido = -1  # Inicializa el nivel que excluye clases (poda)

            # 3. Iterar sobre las clases (delitos)
            for clase_nombre in clases_disponibles:
                clase_data = clases[clase_nombre]

                # Llama a la función que procesa una clase (el nodo del árbol)
                analisis_clase = procesar_clase_atestado(
                    atestado_llm, traversal, clase_nombre, clase_data, llm_model, nivel_excluido, analisis_atestado
                )

                # 4. Acumular los resultados y gestionar la poda
                if analisis_clase:
                    analisis_atestado["analisis"].append(analisis_clase)
                    
                    # Acumulación de contextos, objetos y entidades
                    acumular_resultados_clase(analisis_atestado, analisis_clase, traversal)
                    # Lógica de poda: Si la clase actual no existe, establece el nivel de exclusión.
                    # Si existe, reinicia el nivel si previamente estaba en un nivel de poda.
                    if analisis_clase.get("existe"):
                        if nivel_excluido != -1 and analisis_clase.get("profundidad") <= nivel_excluido:
                            nivel_excluido = -1 # Se vuelve a la rama principal/equivalente
                    else:
                        if nivel_excluido == -1:
                            nivel_excluido = analisis_clase.get("profundidad")

            analisis_atestados["respuestas"].append(analisis_atestado)

        fin = datetime.now()
        ha = fin.strftime("%H:%M:%S")
        print(f"\n⏳ {ha} - Fin extracción Tiempo transcurrido: {tiempo_transcurrido(inicio, fin)}")

        # return {"respuestas": analisis_atestados}
        return analisis_atestados

    except Exception as e:
        print(f"Error en analizarAtestado: {e}")
        return {"error": str(e)}

def acumular_resultados_clase(analisis_atestado: AnalisisAtestado, analisis_clase: AnalisisClase, traversal: Any):
    """Función auxiliar para acumular los contextos, objetos y entidades de un AnalisisClase."""
    
    # Acumular contextos
    for contexto in analisis_clase.get("contexto", []):
        if contexto.get("positivo"):
            analisis_atestado["contexto_positivo"].append(contexto)
        else:
            analisis_atestado["contexto_negativo"].append(contexto)

    # Acumular objetos
    analisis_atestado["objetos"].extend(analisis_clase.get("objetos", []))

    # Acumular entidades (evitando duplicados si se considera una lógica de deduplicación)
    for entidad in analisis_clase["entidades"]:
        nombre_entidad = entidad.get("nombre")
        dominio_nuevo = entidad.get("dominios")[0]
        ens = [en for en in analisis_atestado["entidades"] if en.get("nombre") == nombre_entidad]
        if ens:
            dominio_almacenado = ens[0].get("dominios")[0]
            if sorted(dominio_almacenado) != sorted(dominio_nuevo):
                subclase = devolver_subclase_entre(traversal, dominio_nuevo, dominio_almacenado)
                if subclase:                    
                    ens[0].get("dominios")[0] = subclase
                else:
                    analisis_atestado["entidades"].append(entidad)
            else:
                pass
        else:
            analisis_atestado["entidades"].append(entidad)





def procesar_clase_atestado(atestado_llm: AtestadoLLM, traversal: Any, clase_nombre: str,
                            clase_data: Dict[str, Any], llm_model: str, nivel_excluido: int, analisis_atestado: AnalisisAtestado) -> AnalisisClase:
    """
    Procesa una clase específica (nodo en el árbol de decisión).

    Parameters
    ----------
    atestado_llm: AtestadoLLM
        Instancia de ``AtestadoLLM`` con el contexto del atestado.
    traversal: Traversal
        Instancia de ``Traversal`` para obtener detalles de la ontología.
    clase_nombre: str
        Nombre de la clase (delito) a analizar.
    clase_data: dict
        Datos de la clase obtenidos de ``dfs_result``.
    llm_model: str
        Nombre del modelo LLM a utilizar.
    nivel_excluido: int
        El nivel de profundidad que excluyó una rama anterior.

    Returns
    -------
    AnalisisClase
        Diccionario con el resultado completo del análisis de la clase.
    """
    detalles_clase = recuperarContexto(clase_nombre, clase_data)
    dfs_extended_info = clase_data.get("dfs_extended_info", {})
    depth = dfs_extended_info.get("depth_level", "N/A")
    visit_order = dfs_extended_info.get("visit_order", "N/A")

    if not detalles_clase:
        raise ValueError(f"📌?No hay detalles para la clase {clase_nombre}.")

    analisis_clase: AnalisisClase = {
        "nombre": clase_nombre,
        "existe": True,
        "excluido": False,
        "contexto": [],
        "objetos": [],
        "entidades": [],
        "profundidad": depth,
        "orden": visit_order
    }

    # 1. Lógica de Poda (Pruning)
    print(f"\n📌 Clase {clase_nombre} nivel {depth} (nivel excluido: {nivel_excluido}).")
    if nivel_excluido > -1 and depth > nivel_excluido:
        print(f"🧺 Clase {clase_nombre} descartada por poda (nivel anterior: {nivel_excluido}).")
        analisis_clase["existe"] = False
        analisis_clase["excluido"] = True
        return analisis_clase

    # 2. Obtener los elementos de la expresión equivalent_to
    equivalencias = clase_data.get("equivalent_classes", [])
    elementos_eq = []
    for eq in equivalencias:
        # Se asume que este método devuelve la estructura plana y ordenada por recorrido
        elementos_eq.extend(traversal.analizar_expresion_owl_simplificada_dict_v5(eq.get("raw")))

    # 3. Recorrido del Árbol de Restricciones (equivalent_to)
    nivel_anterior = 0
    operador_not = False
    dominios: List[str] = [] # Stack para los dominios (clases)
    resultados_clase = []  # Stack de resultados de existencia/extracción para preguntas anidadas
    preguntas_clase = detalles_clase.get("preguntas", [])
    no_preguntas = detalles_clase.get("no_preguntas", None)
    res_anterior = {}

    for elemento_eq in elementos_eq:
        nivel = elemento_eq.get("level")
        tipo = elemento_eq.get("type")
        elemento = elemento_eq.get("element")
        print(f"✓  Subclase: {clase_nombre} - {tipo} - {elemento}")

        # Poda interna: Si el último resultado fue 'no existe', salimos
        if resultados_clase and not resultados_clase[-1].get("existe"):
            # Si el último objeto de la expresión no existe, toda la conjunción (AND) falla
            analisis_clase["existe"] = False
            return analisis_clase 
        
        # Buscar la pregunta asociada a este elemento (propiedad de objeto)
        pregs = [preg for preg in preguntas_clase if preg.get("elemento") == str(elemento)]
        pregunta = pregs[0] if pregs else None
        elementos_a_preguntar = []

        if nivel < nivel_anterior:
            print(f"❗ procesar_clase_atestado - nivel menor:  {nivel} nivel_anterior: {nivel_anterior} ")
            # Retorno: Deshacer el anidamiento. Se debe sacar del stack
            for i in range(nivel_anterior -nivel):
                if dominios:
                    dominios.pop() # Sale del dominio interno
            if resultados_clase:
                resultados_clase.pop() # Sale del resultado anidado anterior
                res_anterior = resultados_clase[-1] if resultados_clase else None

        # Procesamiento basado en el tipo de elemento
        match tipo:
            case "entity_object":
                # # La entidad es la clase actual o una que define el dominio inicial
                # Ver si no existen resultados iniciales lo que implica clase inicial, "Report"
                if not resultados_clase:
                    dominios.append([ROOT_CLASS]) # dominio inicial hay que llevar a env
                    res_anterior = {
                        "class": ROOT_CLASS,
                        "existe": True,
                        "content": {
                            "respuesta": [analisis_atestado["entidades"][0].get("nombre")]
                        }
                    }
                    resultados_clase.append(res_anterior)
                    continue
                else:
                    dominios.append(elemento)

            case "data_property":
                if not pregunta:
                    # Si no hay pregunta para esta propiedad, se omite y se mantiene el nivel
                    nivel_anterior = nivel
                    continue
                # Llamada refactorizada a procesar_pregunta_objeto
                res_anterior = resultados_clase[-1] if resultados_clase else None
                dominios.append(rango)
                dominio_actual = dominios[-1] if dominios else clase_nombre

                print(f"💬 data_property:  {clase_nombre} {dominio_actual} {elemento}") 

                if res_anterior and res_anterior.get("content"):
                    elementos_a_preguntar = res_anterior["content"].get("respuesta", [])

                ctxs = [cp for cp in analisis_atestado["contexto_positivo"] if cp.get("nombre_elemento") == str(elemento)]
                ctxs.extend([cn for cn in analisis_atestado["contexto_negativo"] if cn.get("nombre_elemento") == str(elemento)])
                contexto_previo = False
                
                for ctx in ctxs:
                    for elemento_contexto in elementos_a_preguntar:
                        if ( sorted(ctx.get("domain")) == sorted(dominio_actual) and  
                                                ctx.get("nombre_elemento") == elemento and 
                                                ctx.get("elemento_dominio") in elemento_contexto):                            

                            print(f"🔄 data_property - repetido:  ({dominio_actual}) - {elemento} - ({rango})")
                            resultados_parciales.append({
                                "class": clase_nombre,
                                "existe": True,
                                "content": {
                                    "tipo_elemeto": "objeto",
                                    "nombre_elemento": elemento,
                                    "domain": dominio_actual,
                                    "elemento_dominio": elemento_contexto,
                                    "range": rango,
                                    "prompt":ctx.get("prompt"),
                                    "respuesta":ctx.get("respuesta")
                                }
                            })
                            contexto_previo = True
                            

                if not contexto_previo:
                    range_property = traversal.get_data_property_xsd_range(elemento)
                    resultados_parciales = procesar_preguntas_propiedad( atestado_llm, elemento, range_property.get("ranges_xsd", []), 
                                            dominio_actual, clase_nombre, pregunta, 
                                            llm_model, analisis_clase, analisis_atestado, res_anterior)
            case "operator":
                # Manejar operadores (ej. NOT) - la lógica de "NOT" se debe manejar en el
                # procesamiento de la restricción o en el LLM (aunque aquí no se ve
                # en el switch de la expresión equivalente original)
                if elemento.lower() == "not": # Tratamiento del operador not
                    operador_not =  True 

            case "object_property":
                # Es una restricción (Property: hasProperty, Target: Class)
                res_anterior = resultados_clase[-1] if resultados_clase else None
                rango = elemento_eq.get("range")
                resultados_parciales =[]
                
                # Lógica de cambio de nivel (anidamiento)
                if nivel > nivel_anterior:
                    # Profundización: El dominio pasa a ser la clase anterior o el rango de la propiedad anterior
                    dominios.append(traversal.get_object_property_detail(elemento, "domain"))
                dominio_actual = dominios[-1] if dominios else clase_nombre # Fallback a la clase actual

                #Contrastar si ya se ha evaluado este contexto positivamente o negativamente
                if res_anterior and res_anterior.get("content"):
                    elementos_a_preguntar = res_anterior["content"].get("respuesta", [])

                ctxs = [cp for cp in analisis_atestado["contexto_positivo"] if cp.get("nombre_elemento") == str(elemento)]
                ctxs.extend([cn for cn in analisis_atestado["contexto_negativo"] if cn.get("nombre_elemento") == str(elemento)])
                contexto_previo = False
                print(f"❓ objectproperty repetido:  ({dominio_actual}) - {elemento} - ({rango})")

                for ctx in ctxs:
                    for elemento_contexto in elementos_a_preguntar:
                        if (sorted(ctx.get("domain")) == sorted(dominio_actual) and
                                                sorted(ctx.get("range")) == sorted(rango) and  
                                                ctx.get("nombre_elemento") == elemento and 
                                                ctx.get("elemento_dominio") == elemento_contexto):                            
                            
                            resultados_parciales.append({
                                "class": clase_nombre,
                                "existe": True,
                                "content": {
                                    "tipo_elemeto": "objeto",
                                    "nombre_elemento": elemento,
                                    "domain": dominio_actual,
                                    "elemento_dominio": elemento_contexto,
                                    "range": rango,
                                    "prompt":ctx.get("prompt"),
                                    "respuesta":ctx.get("respuesta")
                                }
                            })
                            contexto_previo = True
                            print(f"🔄 objectproperty repetido:  ({dominio_actual}) - {elemento} - ({rango})")

                if not contexto_previo:
                    # Llamada refactorizada a procesar_pregunta_objeto
                    if pregunta:
                        resultados_parciales = procesar_pregunta_objeto(
                            atestado_llm, traversal, pregunta, clase_nombre, llm_model, 
                            dominio_actual, rango, analisis_clase, res_anterior
                        )
                        contexto_previo = False
                    elif no_preguntas: #Definición explicita de que no se necesita preguntar por una relación 
                        print(f"📌?Procesar_clase_atestado: No hay preguntas para la relación {elemento} de {clase_nombre} ")
                    else:
                        raise ValueError(f"📌?Procesar_clase_atestado: No hay preguntas para la relación {elemento} de {clase_nombre} ")

                if resultados_parciales:
                    #Gestion de los operadores not
                    if operador_not:
                        for re in resultados_parciales:
                            if not re.get("existe"):
                                for ent in analisis_atestado["entidades"]:
                                    if ent.get("nombre") == re.get("content").get("elemento_dominio"):
                                        rel = re.get("content").get("nombre_elemento")
                                        ran = re.get("content").get("range")[0]
                                        print(f"📌?Evaluando  NOT: not ({rel} some {ran}) ")
                                        ent["dominios_negativos"].append(f"not ({rel} some {ran})")
                                re["existe"] =  True
                            else:
                                re["existe"] =  False 
                        operador_not = False        
                    resultados_clase.extend(resultados_parciales)  
            case _:
                # Manejo de otros tipos (e.g., named_class a nivel hoja)
                pass
        nivel_anterior = nivel
        
    # El estado final de 'analisis_clase["existe"]' ya se ha gestionado en el bucle
    #print(f"📌 Procesar_clase_atestado: Fin {clase_nombre}")
    return analisis_clase


def procesar_pregunta_objeto(atestado_llm: AtestadoLLM, traversal: Any, pregunta_data: Dict[str, Any],
                              clase_nombre: str, llm_model: str, dominio: str, rango: str,
                              analisis_clase: AnalisisClase, respuesta_anterior: Union[Dict[str, Any], None], not_operator=False) \
                              -> List[Dict[str, Any]]:
    """
    Gestiona la lógica de una sola pregunta (existencia y extracción de objeto),
    posiblemente anidada a un resultado anterior.

    Parameters
    ----------
    ... (Mismos parámetros, renombrado `pregunta` a `pregunta_data` por claridad)
    respuesta_anterior: Union[Dict[str, Any], None]
        Resultado de la pregunta anterior, conteniendo la lista de elementos para anidar.

    Returns
    -------
    List[Dict[str, Any]]
        Lista de resultados (existencia/extracción) para cada elemento de la respuesta anterior.
    """
    elemento_nombre = pregunta_data.get("elemento")
    if not elemento_nombre:
        raise ValueError("📌?La pregunta no especifica un objeto para analizar.")

    resultados_pregunta = []
    
    # Determinar la lista de elementos sobre los que hacer la pregunta
    if respuesta_anterior and respuesta_anterior.get("content"):
        # Anidamiento: usar los resultados de la extracción anterior
        elementos_a_preguntar = respuesta_anterior["content"].get("respuesta", [])
    else:
        # No anidado: caso base (ej. PropertyCrimeReport)
        elementos_a_preguntar = [""]
    
    # 1. Iterar sobre los elementos (si no es anidado, solo se ejecuta una vez con "")
    for elemento_contexto in elementos_a_preguntar:
        llm = pregunta_data.get("llm_preferente", llm_model)
        # 1.1. Pregunta de Extracción (Si existe)
        extraccion_prompt = construir_prompt(
            pregunta_data.get("pre_contexto_extracción_objetos", {}),
            pregunta_data.get("extracción_objetos", {}),
            pregunta_data.get("post_contexto_extracción_objetos", {}),
            llm,
            elemento_contexto
        )

        inicio = datetime.now()
        ha = inicio.strftime("%H:%M:%S")
        print(f"⚙️\t{ha} preguntar objeto: **{extraccion_prompt}**")

        respuesta_extraccion_raw = atestado_llm.preguntar_llm(
            extraccion_prompt, llm, pregunta_data.get("formato_extraccion")
        )

        fin = datetime.now()
        ha = fin.strftime("%H:%M:%S")
        respuesta_extraccion = json.loads(respuesta_extraccion_raw)
        print(f"✍️  {ha} - {tiempo_transcurrido(inicio, fin)} respuesta_extraccion: {respuesta_extraccion}")

        # 1.2. Construir el Resultado
        resultados_extraccion = respuesta_extraccion.get("respuesta", [])
        referencia_extraccion = respuesta_extraccion.get("referencia", [])

        if not resultados_extraccion:
            # Si no existe, se registra el resultado de "no existe" y se actualiza el análisis de la clase
            resultado_no_existe = {
                "class": clase_nombre,
                "existe": False,
                "content": {
                    "tipo_elemeto": "objeto",
                    "nombre_elemento": elemento_nombre,
                    "domain": dominio,
                    "elemento_dominio": elemento_contexto,
                    "range": rango,
                    "prompt": extraccion_prompt,
                    "respuesta": resultados_extraccion
                }
            }
            resultados_pregunta.append(resultado_no_existe)
            contexto_extraccion_no_existe: ContextoElementoClase = {
                "tipo_elemeto": "extraccion",
                "nombre_elemento": elemento_nombre,
                "domain": dominio,
                "elemento_dominio": elemento_contexto,
                "range": rango,
                "prompt": extraccion_prompt,
                "respuesta": resultados_extraccion,
                "positivo": False
            }
            analisis_clase["contexto"].append( contexto_extraccion_no_existe)
            continue # Si una restricción obligatoria (AND) no existe, se rompe el bucle interno

        resultado_extraido = {
            "class": clase_nombre,
            "existe": not not_operator,
            "content": {
                "tipo_elemeto": "objeto",
                "nombre_elemento": elemento_nombre,
                "domain": dominio,
                "elemento_dominio": elemento_contexto,
                "range": rango,
                "prompt": extraccion_prompt,
                "respuesta": resultados_extraccion
            }
        }
        resultados_pregunta.append(resultado_extraido)

        # 1.3. Acumular en la Estructura de Análisis Final
        contexto_extraccion: ContextoElementoClase = {
            "tipo_elemeto": "extraccion",
            "nombre_elemento": elemento_nombre,
            "domain": dominio,
            "elemento_dominio": elemento_contexto,
            "range": rango,
            "prompt": extraccion_prompt,
            "respuesta": resultados_extraccion,
            "positivo": not not_operator
        }
        analisis_clase["contexto"].append(contexto_extraccion)

        # Jesús Galera Mapeo opcional de posición → clase ontológica (definido en preguntas_extendido.json
        # como "tipos_por_posicion"). Si está presente, la entidad de cada índice se tipa con
        # la clase indicada en esa posición; si no, se mantiene el comportamiento original
        # (tipo = rango del axioma OWL). Esto permite que una sola pregunta extraiga varias
        # características ontológicas distintas a partir de una respuesta posicional del LLM.
        #Desarrollado para reportes que tienen más de una relación hasOffenceCharacteristic

        tipos_por_posicion = traversal.get_property_ranges_in_equivalent(clase_nombre, elemento_nombre, exclude_negated=True)

        for i, (respuesta_individual, referencia_individual) in enumerate(
                zip(resultados_extraccion, referencia_extraccion)):
            # Saltar respuestas vacías (esa posición no aplica al atestado)
            if not respuesta_individual or not str(respuesta_individual).strip():
                continue

            # Tipo de la entidad para esta posición
            if i < len(tipos_por_posicion):
                dominios_entidad = [tipos_por_posicion[i]]
            else:
                dominios_entidad = rango

            # Acumular Objeto
            if not not_operator:
                analisis_clase["objetos"].append({
                    "nombre": elemento_nombre,
                    "repetido": False,
                    "dominios": dominio,
                    "entidad_dominio": elemento_contexto if elemento_contexto else dominio, # Si no es anidada, usa el dominio
                    "rangos": dominios_entidad,
                    "entidad_rango": respuesta_individual,
                    "referencia" :  "|".join(referencia_individual),
                    "clase_origen": clase_nombre
                })

                # Acumular Entidad
                analisis_clase["entidades"].append({
                    "nombre": respuesta_individual,
                    "dominios": dominios_entidad,
                    "dominios_negativos": [],
                    "propiedades": []
                })

    analisis_clase["existe"] = not not_operator
    analisis_clase["excluido"] = False      
    for res in resultados_pregunta:
        if res.get("existe"):
            analisis_clase["existe"] = not not_operator
    return resultados_pregunta

def procesar_preguntas_propiedad(atestado_llm: AtestadoLLM, propiedad: str, rango: str, dominio: str, clase_nombre: str, pregunta_data: Dict[str, Any],
                                llm_model: str, analisis_clase: AnalisisClase, analisis_atestado: AnalisisAtestado, respuesta_anterior: Union[Dict[str, Any], None]) -> List[Dict[str, Any]]:
    """
    Determina y extrae las propiedades (atributos) de una entidad dada, basándose
    en las preguntas definidas en la ontología/configuración.

    Parameters
    ----------
    atestado_llm: AtestadoLLM
        Instancia de AtestadoLLM con el contexto del atestado.
    entidad_nombre: str
        Nombre de la entidad cuyas propiedades se van a extraer (ej. "Report").
    preguntas_entidad: Dict[str, Any]
        Diccionario que contiene la configuración de las preguntas para la entidad.
        Se espera la clave "propiedades" con una lista de preguntas.
    llm_model: str
        Nombre del modelo LLM a utilizar.

    Returns
    -------
    List[Dict[str, Any]]
        Lista de propiedades extraídas en formato:
        [{"nombre_propiedad": "valor_extraido"}, ...]
    """
    entidades_extraidas: List[str] = []
    resultados_extraccion =[]

    # Determinar la lista de elementos sobre los que hacer la pregunta
    if respuesta_anterior and respuesta_anterior.get("content"):
        # Anidamiento: usar los resultados de la extracción anterior
        entidades_extraidas = respuesta_anterior["content"].get("respuesta", [])
    else:
        # No anidado: caso base (ej. PropertyCrimeReport)
        entidades_extraidas = [""]

    print(f"📌 entidades_extraidas: {entidades_extraidas}")
    # 1. Iterar sobre los elementos (si no es anidado, solo se ejecuta una vez con "")
    for entidad in entidades_extraidas: # [:1]:
        llm = pregunta_data.get("llm_preferente", llm_model)

        # 1.1. Pregunta de Extracción (Si existe)
        extraccion_prompt = construir_prompt(
            pregunta_data.get("pre_contexto_extracción_objetos", {}),
            pregunta_data.get("extracción_objetos", {}),
            pregunta_data.get("post_contexto_extracción_objetos", {}),
            llm,
            entidad
        )

        inicio = datetime.now()
        ha = inicio.strftime("%H:%M:%S")
        print(f"⚙️\t{ha} preguntar propiedad: **{extraccion_prompt}**")

        respuesta_extraccion_raw = atestado_llm.preguntar_llm(
            extraccion_prompt, llm, pregunta_data.get("formato_extraccion")
        )

        fin = datetime.now()
        ha = fin.strftime("%H:%M:%S")
        respuesta_extraccion = json.loads(respuesta_extraccion_raw)
        print(f"✍️  {ha} - {tiempo_transcurrido(inicio, fin)} respuesta_extraccion: {respuesta_extraccion}")
        
        # 1.2. Construir el Resultado
        respuesta = respuesta_extraccion.get("respuesta", [])
        if not respuesta:
            # Si no existe, se registra el resultado de "no existe" y se actualiza el an谩lisis de la clase
            # resultado_no_existe = {"class": clase_nombre, "existe": False, "content": {"elemento_dominio": elemento_contexto}}
            resultado_no_existe = {
                "class": clase_nombre,
                "existe": False,
                "content": {
                    "tipo_elemeto": "propiedad",
                    "nombre_elemento": propiedad,
                    "domain": dominio,
                    "elemento_dominio": entidad,
                    "range": rango,
                    "prompt": extraccion_prompt,
                    "respuesta": ""
                }
            }
            resultados_extraccion.append(resultado_no_existe)
            contexto_extraccion_no_existe: ContextoElementoClase = {
                "tipo_elemeto": "extraccion",
                "nombre_elemento": propiedad,
                "domain": dominio,
                "elemento_dominio": entidad,
                "range": rango,
                "prompt": extraccion_prompt,
                "respuesta": "",
                "positivo": False
            }
            analisis_clase["contexto"].append(contexto_extraccion_no_existe)
            continue # 

        resultado_extraido = {
            "class": clase_nombre,
            "existe": True,
            "content": {
                "tipo_elemeto": "objeto",
                "nombre_elemento": propiedad,
                "domain": dominio,
                "elemento_dominio": entidad,
                "range": rango,
                "prompt": extraccion_prompt,
                "respuesta": respuesta.get(propiedad)
            }
        }
        resultados_extraccion.append(resultado_extraido)

        # 1.3. Acumular en la Estructura de Analisis Final
        contexto_extraccion: ContextoElementoClase = {
            "tipo_elemeto": "extraccion",
            "nombre_elemento": propiedad,
            "domain": dominio,
            "elemento_dominio": entidad,
            "range": rango,
            "prompt": extraccion_prompt,
            "respuesta": respuesta.get(propiedad),
            "positivo": True
        }

        analisis_clase["contexto"].append(contexto_extraccion)   
        p: PropiedadEntidad = {
            "nombre": propiedad,
            "valor":  respuesta.get(propiedad),
            "rango": rango
        }
    
        # No estamos contando posibles repeticiones
        ents = [en for en in analisis_atestado["entidades"] if en.get("nombre") == str(entidad)]
        print(f"ℹ️ analisis_atestado['entidades'] de '{entidad}': {ents}")
        if ents:    
            props = [prop for prop in ents[-1]['propiedades'] if prop.get(propiedad, "") != ""]
            if not props:
                ents[-1]['propiedades'].append(p) 
            else:
                props[-1] = { p } 
            analisis_clase["entidades"].append(copy.deepcopy(ents[-1]))
        else:
            ents2 = [en for en in analisis_clase["entidades"] if en.get("nombre") == str(entidad)]
            print(f"ℹ️ analisis_clase['entidades'] de '{entidad}': {ents2}")
            if ents2: 
                props = [prop for prop in ents2[-1]['propiedades'] if prop.get(propiedad, "") != ""]
                if not props:
                    ents2[-1]['propiedades'].append(p) 
                else:
                    props[-1] = { p } 
            else:
                print(f"❌procesar_preguntas_propiedad: '{entidad}' no encontrada. No se puede añadir la respuesta {respuesta}")

        entis = analisis_clase["entidades"]
    ######################################       
    return resultados_extraccion

def procesar_preguntas_entidad(atestado_llm: AtestadoLLM, entidad_nombre: str, preguntas_entidad: Dict[str, Any],
                                llm_model: str, analisis_clase: AnalisisClase, respuesta_anterior: Union[Dict[str, Any], None]) -> List[Dict[str, Any]]:
    """
    Determina y extrae las propiedades (atributos) de una entidad dada, basándose
    en las preguntas definidas en la ontología/configuración.

    Parameters
    ----------
    atestado_llm: AtestadoLLM
        Instancia de AtestadoLLM con el contexto del atestado.
    entidad_nombre: str
        Nombre de la entidad cuyas propiedades se van a extraer (ej. "Report").
    preguntas_entidad: Dict[str, Any]
        Diccionario que contiene la configuración de las preguntas para la entidad.
        Se espera la clave "propiedades" con una lista de preguntas.
    llm_model: str
        Nombre del modelo LLM a utilizar.

    Returns
    -------
    List[Dict[str, Any]]
        Lista de propiedades extraídas en formato:
        [{"nombre_propiedad": "valor_extraido"}, ...]
    """
    propiedades_extraidas: List[Dict[str, Any]] = []
    
    # 1. Recuperar la lista de propiedades a preguntar
    propiedades_a_extraer = preguntas_entidad.get("propiedades", [])

    if not propiedades_a_extraer:
        print(f"Advertencia: No se encontraron preguntas de propiedades para la entidad {entidad_nombre}.")
        return propiedades_extraidas

    # 2. Iterar sobre cada propiedad definida para la entidad
    for propiedad_data in propiedades_a_extraer:
        propiedad_nombre = propiedad_data.get("nombre", "UNKNOWN_PROPERTY")

        # Se asume que la estructura de la pregunta de extracción de atributo
        # sigue un formato similar a la pregunta de extracción de objeto en la ontología       
        try:
            # 2.1. Construir el Prompt de Extracción de Atributo
            extraccion_prompt = construir_prompt(
                propiedad_data.get("pre_contexto_extracción", {}),
                propiedad_data.get("preguntas_extracción", {}), # O la clave que defina la pregunta central
                propiedad_data.get("post_contexto_extracción", {}), 
                propiedad_data.get("llm_preferente", llm_model),
                contexto_anidado=entidad_nombre # El contexto es la entidad actual
            )
            
            # 2.2. Consulta al LLM
            formato_extraccion = propiedad_data.get("formato_extraccion")
            respuesta_extraccion_raw = atestado_llm.preguntar_llm(
                extraccion_prompt, llm_model, formato_extraccion
            )
            
            respuesta_json = json.loads(respuesta_extraccion_raw)
            valor_extraido = respuesta_json.get("respuesta")
            
            # 2.3. Acumular el resultado
            if valor_extraido is not None and valor_extraido != "":
                propiedades_extraidas.append({
                    "nombre_propiedad": propiedad_nombre,
                    "valor": valor_extraido,
                    "tipo_dato": propiedad_data.get("tipo_dato", "string")
                })
                print(f"  -> Propiedad **{propiedad_nombre}** extraída con valor: {valor_extraido[:50]}...")
            else:
                print(f"  -> Propiedad **{propiedad_nombre}** no encontrada o valor vacío.")

        except Exception as e:
            print(f"  📌?Error al procesar la propiedad {propiedad_nombre} para {entidad_nombre}: {e}")
            # Se puede registrar el error y continuar con la siguiente propiedad
            
    return propiedades_extraidas


def construir_prompt(pre_contexto: Dict[str, str], pregunta_base: Dict[str, str], post_contexto: Dict[str, str], llm_model: str, elemento: str | None ) -> str:
    """Construye el prompt completo concatenando las partes."""    
    
    # Los valores de pre_contexto y post_contexto dependen de la clave del modelo LLM
    pre = pre_contexto.get(llm_model, None)

    if not pre:  
        pre = pre_contexto.get("default-llm", "") 

    pregunta = pregunta_base.get(llm_model, None)
    if not pregunta:
       pregunta = pregunta_base.get("default-llm", "") 

    if elemento:
        pregunta = pregunta.replace("$_elemento",elemento)

    post = post_contexto.get(llm_model, None)
    if not post:
        post = post_contexto.get("default-llm", "")

    return f"{pre} {pregunta} {post}".strip()
    
def recuperarContexto(clase_nombre: str, clase_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Recupera el contexto extendido (detalles_clase) para una clase a partir
    de la referencia en 'seeAlso' y el archivo JSON correspondiente.

    Parameters
    ----------
    clase_nombre: str
        El nombre de la clase cuya información se busca.
    clase_data: Dict[str, Any]
        El sub-árbol de datos para esa clase, que contiene 'seeAlso'.

    Returns
    -------
    Optional[Dict[str, Any]]
        El diccionario con los detalles de la clase (preguntas/contextos)
        o None si el archivo o la clase no se encuentran.
    """
    # 1. Recuperar seeAlso
    see_also = clase_data.get("seeAlso", [])
    if not see_also:
        # print("📌?No hay seeAlso para esta clase.") # Opcional: imprimir advertencia
        return None

    # 2. Buscar referencia al fichero JSON (parte del IRI antes del '#')
    fichero_json = None
    for ref in see_also:
        if "#" in ref:
            # Obtiene la parte antes del último '#', y reemplaza 'file://' si existe
            fichero_json = ref.split("#")[-2].replace('file://', '')
            break
    print(f"📌 Archivo JSON en {fichero_json}")        
    if not fichero_json:
        return None

    # 3. Cargar el fichero preguntas_extendido.json
    if not os.path.exists(fichero_json):
        # La lógica original de 'analizarAtestado' devolvía 'return' (terminando la función) en este punto.
        # Aquí solo devolvemos None, y el llamante (analizarAtestado) decide si terminar o continuar el bucle.
        print(f"📌?No se encontró el archivo JSON en {fichero_json}")
        return None

    try:
        with open(fichero_json, "r", encoding="utf-8") as f:
            preguntas_extendido = json.load(f)
    except Exception as e:
        print(f"📌?Error al cargar/parsear el archivo JSON {fichero_json}: {e}")
        return None

    # 4. Recuperar los detalles específicos de la clase
    detalles_clase = preguntas_extendido.get(clase_nombre, None)
    
    return detalles_clase


def obtenerEstructuraEquivalente(
    expression: Dict[str, Any],
    level: int = 0
) -> List[Dict[str, Union[str, int, List[Any]]]]:
    """
    Recorre recursivamente la estructura JSON de una expresión equivalente (equivalent_to)
    y devuelve una lista ordenada de los elementos y sus propiedades.

    Parameters
    ----------
    expression: Dict[str, Any]
        La expresión (clase, restricción, operador lógico) a analizar.
    level: int
        Nivel de anidamiento actual.

    Returns
    -------
    List[Dict[str, Union[str, int, List[Any]]]]
        Una lista de diccionarios, donde cada diccionario representa un elemento
        de la estructura con sus propiedades.
    """
    # Lista para almacenar el elemento actual y los elementos recursivos
    estructura_plana: List[Dict[str, Union[str, int, List[Any]]]] = []

    # 1. Capturar propiedades del elemento actual
    exp_type: str = expression.get("type", "unknown")
    description: str = expression.get("description", "Sin descripción")

    elemento_actual: Dict[str, Union[str, int, List[Any]]] = {
        "level": level,
        "type": exp_type,
        "description": description,
        "properties": {} # Propiedades específicas según el tipo
    }

    # 2. Manejo de Operadores Lógicos (AND, OR)
    if exp_type in ["intersection", "union"]:
        operands: List[Dict[str, Any]] = expression.get("operands", [])
        elemento_actual["properties"]["logical_operator"] = expression.get('logical_operator', 'N/A')
        elemento_actual["properties"]["num_operands"] = len(operands)
        
        # Agregar el elemento actual a la lista
        estructura_plana.append(elemento_actual)
        
        # Llamada recursiva para cada operando
        for i, operand in enumerate(operands):
            # Opcional: añadir un marcador para el operando
            operando_marcador: Dict[str, Union[str, int, List[Any]]] = {
                "level": level + 1,
                "type": "operand_marker",
                "description": f"Operando {i + 1} de {exp_type.upper()}",
                "properties": {}
            }
            estructura_plana.append(operando_marcador)
            
            # Recorrer el operando
            estructura_plana.extend(obtenerEstructuraEquivalente(operand, level + 2))

    # 3. Manejo de Complemento (NOT)
    elif exp_type == "complement":
        operand: Optional[Dict[str, Any]] = expression.get("operand")
        elemento_actual["properties"]["logical_operator"] = "NOT"
        
        # Agregar el elemento actual a la lista
        estructura_plana.append(elemento_actual)
        
        if operand:
            # Marcador del elemento negado
            negado_marcador: Dict[str, Union[str, int, List[Any]]] = {
                "level": level + 1,
                "type": "negated_element_marker",
                "description": "Elemento negado",
                "properties": {}
            }
            estructura_plana.append(negado_marcador)
            
            # Recorrer el elemento negado
            estructura_plana.extend(obtenerEstructuraEquivalente(operand, level + 2))

    # 4. Manejo de Restricciones
    elif exp_type == "restriction":
        details: Dict[str, Any] = expression.get("restriction_details", {})
        prop_name: str = details.get("property", "N/A")
        rest_type: str = details.get("restriction_type", "N/A")
        target: Optional[Dict[str, Any]] = details.get("target")

        elemento_actual["properties"]["property"] = prop_name
        elemento_actual["properties"]["restriction_type"] = rest_type
        
        # Agregar el elemento actual a la lista
        estructura_plana.append(elemento_actual)
        
        # Recorrido del Target de la restricción
        if target:
            # Marcador del target
            target_marcador: Dict[str, Union[str, int, List[Any]]] = {
                "level": level + 1,
                "type": "restriction_target_marker",
                "description": "Target de la restricción",
                "properties": {}
            }
            estructura_plana.append(target_marcador)
            
            # Recorrer el target
            estructura_plana.extend(obtenerEstructuraEquivalente(target, level + 2))

    # 5. Manejo de Clases Nombradas y Otros Tipos
    else:
        if exp_type == "named_class":
            class_name: str = expression.get("name", "N/A")
            elemento_actual["properties"]["name"] = class_name
        else: # anonymous_class, error, unknown, etc.
            elemento_actual["properties"]["raw_data"] = expression.get('raw', 'N/A')
        
        # Agregar el elemento actual (hoja o tipo simple)
        estructura_plana.append(elemento_actual)

    # Devolver la lista acumulada de elementos
    return estructura_plana

def recorrerEstructuraEquivalente(expression: Dict[str, Any], level: int = 0):
    """
    Recorre recursivamente la estructura JSON de una expresión equivalente (equivalent_to)
    y muestra sus componentes mediante print.

    Parameters
    ----------
    expression: Dict[str, Any]
        La expresión (clase, restricción, operador lógico) a analizar.
    level: int
        Nivel de indentación actual para la visualización.
    """
    indent = "  " * level
    exp_type = expression.get("type", "unknown")
    description = expression.get("description", "Sin descripción")

    print(f"{indent}├── TIPO: {exp_type.upper()}")
    print(f"{indent}📌?  └─ Descripción: {description}")

    # 1. Manejo de Operadores Lógicos (AND, OR)
    if exp_type in ["intersection", "union"]:
        operands: List[Dict[str, Any]] = expression.get("operands", [])
        print(f"{indent}📌?  └─ Operador: {expression.get('logical_operator', 'N/A')}")
        print(f"{indent}📌?  └─ Elementos ({len(operands)}):")
        for i, operand in enumerate(operands):
            # Llamada recursiva para cada operando
            print(f"{indent}📌?  ├── Operando {i + 1}:")
            recorrerEstructuraEquivalente(operand, level + 2)

    # 2. Manejo de Complemento (NOT)
    elif exp_type == "complement":
        operand: Optional[Dict[str, Any]] = expression.get("operand")
        print(f"{indent}📌?  └─ Operador: NOT")
        if operand:
            # Llamada recursiva para el elemento negado
            print(f"{indent}📌?  └─ Elemento negado:")
            recorrerEstructuraEquivalente(operand, level + 2)

    # 3. Manejo de Restricciones (some, cardinality, only, etc.)
    elif exp_type == "restriction":
        details = expression.get("restriction_details", {})
        prop_name = details.get("property", "N/A")
        rest_type = details.get("restriction_type", "N/A")
        
        print(f"{indent}📌?  └─ Propiedad: {prop_name}")
        print(f"{indent}📌?  └─ Restricción: {rest_type}")
        
        # El target (lo que restringe la propiedad, ej: 'some RobberyCharacteristic')
        target: Optional[Dict[str, Any]] = details.get("target")
        if target:
            print(f"{indent}📌?  └─ Target de la restricción:")
            # Llamada recursiva para el target (que puede ser otra expresión)
            recorrerEstructuraEquivalente(target, level + 2)

    # 4. Manejo de Clases Nombradas
    elif exp_type == "named_class":
        class_name = expression.get("name", "N/A")
        print(f"{indent}📌?  └─ Nombre: {class_name}")

    # 5. Otros tipos (anonymous_class, error, unknown)
    else:
        print(f"{indent}📌?  └─ Datos: {expression.get('raw', 'N/A')}")
    
def imprimir_contextos_y_preguntas(clase_nombre: str, detalles_clase: dict) -> None:
    """
    Imprime por consola los contextos y preguntas asociados a una clase.
    Parámetros:
    ----------
    clase_nombre : str
        Nombre de la clase ontológica.
    detalles_clase : dict
        Diccionario con contextos y preguntas de la clase.
    """
    # print(f"\n📌 Clase: {clase_nombre}")
    # print("-" * 50)

    # Imprimir contextos
    contextos = [
        "contexto_general", "pre_contexto_existencia", "post_contexto_existencia",
        "pre_contexto_extraccion_objetos", "post_contexto_extraccion_objetos",
        "pre_contexto_propiedades", "post_contexto_propiedades"
    ]
    for ctx in contextos:
        if ctx in detalles_clase and detalles_clase[ctx]:
            print(f"{ctx}: {detalles_clase[ctx]}")

    # Imprimir preguntas
    preguntas = detalles_clase.get("preguntas", [])
    if preguntas:
        print("\nPreguntas:")
        for p in preguntas:
            print(f" - {p}")
    else:
        print("📌?No hay preguntas definidas para esta clase.")


def es_subclase_de(traversal: Any, clase_a: str, clase_b: str) -> bool:
    """
    Determina si 'clase_a' es una subclase (propia) de 'clase_b'.

    Utiliza la lógica de 'dfs_equivalent_and_subclasses' asumiendo que:
    1. Ejecuta un DFS desde 'clase_b'.
    2. Si 'clase_a' se encuentra, está en la jerarquía (subclase o equivalente).
    3. 'dfs_extended_info.depth_level' indica la profundidad (0 para 'clase_b').

    Parameters
    ----------
    traversal: Any
        Instancia de la clase de manejo de la ontología (como en el script).
    clase_a: str
        Nombre de la clase que se sospecha es la subclase.
    clase_b: str
        Nombre de la clase que se sospecha es la superclase.

    Returns
    -------
    bool
        True si clase_a es una subclase propia de clase_b, False en caso contrario.
    """
    try:
        # 1. Ejecutar el DFS desde la supuesta superclase (clase_b)
        dfs_result = traversal.dfs_equivalent_and_subclasses(clase_b, None)
        clases_encontradas: Dict[str, Any] = dfs_result.get("classes", {})

        # 2. Si clase_a no está en los resultados, no es subclase.
        if clase_a not in clases_encontradas:
            return False

        # 3. Si A es B, no es subclase *propia*.
        if clase_a == clase_b:
            return False

        # 4. Verificar la profundidad. Asumimos que la raíz (clase_b) tiene depth_level 0.
        #    Cualquier descendiente propio debe tener una profundidad > 0.
        clase_a_data = clases_encontradas.get(clase_a, {})
        depth = clase_a_data.get("dfs_extended_info", {}).get("depth_level", -1)

        return depth > 0

    except Exception as e:
        print(f"Error en es_subclase_de: {e}")
        return False
    

def devolver_subclase_entre(traversal: Any, clase_a: str, clase_b: str) -> str:
    """
    Determina si 'clase_a' es una subclase (propia) de 'clase_b'.

    Utiliza la lógica de 'dfs_equivalent_and_subclasses' asumiendo que:
    1. Ejecuta un DFS desde 'clase_b'.
    2. Si 'clase_a' se encuentra, está en la jerarquía (subclase o equivalente).
    3. 'dfs_extended_info.depth_level' indica la profundidad (0 para 'clase_b').

    Parameters
    ----------
    traversal: Any
        Instancia de la clase de manejo de la ontología (como en el script).
    clase_a: str
        Nombre de la clase que se sospecha es la subclase.
    clase_b: str
        Nombre de la clase que se sospecha es la superclase.

    Returns
    -------
    bool
        True si clase_a es una subclase propia de clase_b, False en caso contrario.
    """
    try:
        # 1. Si A es B, no es subclase *propia*.
        if clase_a == clase_b:
            return clase_a
        
        # 2. Ejecutar el DFS desde la supuesta superclase (clase_b) y subclase (clase_a)
        dfs_result_b = traversal.dfs_subclasses(clase_b)
        if dfs_result_b:
            clases_encontradas_b: Dict[str, Any] = dfs_result_b.get("classes", {})
        else:
            clases_encontradas_b: Dict[str, Any] = {}

        # print(f"\t\t📌 devolver_subclase_entre clases_encontradas_b: {clases_encontradas_b}")

        dfs_result_a = traversal.dfs_subclasses(clase_a)
        if dfs_result_a:
            clases_encontradas_a: Dict[str, Any] = dfs_result_a.get("classes", {})
        else:
            clases_encontradas_a: Dict[str, Any] = {}
        # print(f"\t\t📌 devolver_subclase_entre clases_encontradas_a: {clases_encontradas_a}")

        # 3. Si clase_a no está en los resultados, no es subclase.
        if clase_a not in clases_encontradas_b:
            if clase_b not in clases_encontradas_a:
                return ""
            else:
                return clase_b
        else: 
            return clase_a 

        # # 4. Verificar la profundidad. Asumimos que la raíz (clase_b) tiene depth_level 0.
        # #    Cualquier descendiente propio debe tener una profundidad > 0.
        # clase_a_data = clases_encontradas.get(clase_a, {})
        # depth = clase_a_data.get("dfs_extended_info", {}).get("depth_level", -1)

        # return depth > 0

    except Exception as e:
        print(f"Error en devolver_subclase_entre: {e}")
        return False


def definicion_contiene_subclase(traversal: Any, clase_a: str) -> bool:
    """
    Determina si la definición 'equivalent_to' de 'clase_a' hace referencia
    directa a una clase que también es una subclase (propia) de 'clase_a'.

    Esto interpreta "anonymous ancestors" como las expresiones 'equivalent_to'
    que se analizan en tu script (línea 217 y 223).

    Parameters
    ----------
    traversal: Any
        Instancia de la clase de manejo de la ontología.
    clase_a: str
        Nombre de la clase a analizar.

    Returns
    -------
    bool
        True si la definición de clase_a referencia a una de sus propias subclases.
    """
    try:
        # 1. Obtener TODOS los descendientes Y la definición de clase_a en una llamada
        dfs_result = traversal.dfs_equivalent_and_subclasses(clase_a, None)
        clases_encontradas: Dict[str, Any] = dfs_result.get("classes", {})

        clase_a_data = clases_encontradas.get(clase_a)
        if not clase_a_data:
            print(f"No se encontró la definición de {clase_a}")
            return False

        # 2. Crear un set de descendientes PROPIOS (depth > 0)
        descendientes_propios: Set[str] = set()
        # Asumimos que la profundidad de la clase base (clase_a) es 0 en este DFS
        clase_a_depth = clase_a_data.get("dfs_extended_info", {}).get("depth_level", 0)

        for nombre, data in clases_encontradas.items():
            if nombre == clase_a:
                continue
            
            depth = data.get("dfs_extended_info", {}).get("depth_level", -1)
            if depth > clase_a_depth:
                descendientes_propios.add(nombre)
        
        # Si no tiene subclases, es imposible que su definición las contenga
        if not descendientes_propios:
            return False

        # 3. Extraer clases referenciadas de la definición de clase_a
        equivalencias = clase_a_data.get("equivalent_classes", [])
        clases_referenciadas: Set[str] = set()

        for eq in equivalencias:
            # Asumimos que traversal tiene este método (línea 223 del script)
            elementos_eq = traversal.analizar_expresion_owl_simplificada_dict_v5(eq.get("raw"))
            
            for elemento in elementos_eq:
                # Una clase referenciada directamente
                if elemento.get("type") == "entity_object":
                    clases_referenciadas.add(elemento.get("element"))
                # Una clase referenciada como el rango de una propiedad
                elif elemento.get("type") == "objeto":
                    rango = elemento.get("range")
                    if rango:
                        clases_referenciadas.add(rango)

        # 4. Comprobar la intersección
        interseccion = clases_referenciadas.intersection(descendientes_propios)
        
        if len(interseccion) > 0:
            print(f"Ciclo detectado: {clase_a} referencia a {interseccion}, que es su subclase.")
            return True
        
        return False

    except Exception as e:
        print(f"Error en definicion_contiene_subclase: {e}")
        return False

def tiempo_transcurrido(inicio: datetime, fin: datetime):
    """
    Calcula horas, minutos y segundos entre dos objetos datetime.
    """
    # Calculamos la diferencia (esto devuelve un objeto timedelta)
    diferencia = fin - inicio
    
    # Extraemos el total de segundos
    segundos_totales = int(diferencia.total_seconds())
    
    # Calculamos horas, minutos y segundos
    horas, resto = divmod(segundos_totales, 3600)
    minutos, segundos = divmod(resto, 60)
    
    return f"{horas}:{minutos}:{segundos}"




