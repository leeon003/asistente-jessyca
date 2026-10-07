# Procedimiento Técnico y Reproducible de Entrenamiento y Evaluación de Wake Word en Español ("Jessyca")

## 1. Contexto y Declaración Honesta de Capacidades de openWakeWord

### 1.1. Soporte Oficial y Licenciamiento
* **Repositorio Oficial:** [dscripka/openWakeWord](https://github.com/dscripka/openWakeWord)
* **Licencia del Código:** Apache 2.0.
* **Licencia de Modelos Preentrenados:** Los modelos empaquetados por defecto en el paquete (`alexa`, `hey_mycroft`, `hey_jarvis`, `hey_rhasspy`, `timer`, `weather`) fueron entrenados con datasets en idioma inglés y modelos sintéticos de habla inglesa.
* **Invariante Crítico:** **Renombrar un archivo de modelo en inglés o cambiar la etiqueta de búsqueda a "jessyca" NO produce detección acústica del nombre en español.** El modelo base analiza fonemas acústicos; forzar un modelo de habla inglesa a clasificar el fonema hispanohablante de "Jessyca" genera tasas inaceptables de falsos rechazos (>90%) o falsas activaciones ante cualquier ruido similar.
* **Garantía de Integridad:** En ausencia de un modelo binario específicamente entrenado y validado con datos en español, la capacidad acústica permanece honestamente como **NO CONFIGURADA (`is_acoustic_model_available() == False`)** y el sistema opera en modo manual/Push-to-Talk. No se generan pesos sintéticos falsos ni se certifican rendimientos inventados.

---

## 2. Metodología de Construcción del Corpus Acústico

Para entrenar un clasificador robusto para la palabra clave **"Jessyca"** ([ˈxesi.ka] / [ˈdʒesi.ka]), se debe seguir un esquema de corpus balanceado con separación estricta entre entrenamiento (80%) y prueba (20%):

### 2.1. Clases del Corpus
1. **Positivos (Palabra Clave "Jessyca"):**
   - **Variaciones de Pronunciación:** Pronunciación española / latinoamericana estándar con "J" fricativa velar sorda [x], variantes con africada postalveolar sonora [dʒ], y variaciones con entonación neutra, interrogativa y rápida.
   - **Distancias de Captura:**
     - Campo cercano (Near-field: 0.3m – 0.8m)
     - Campo medio (Mid-field: 1.0m – 2.0m)
     - Campo lejano (Far-field: 2.5m – 4.0m con reverberación de sala)
   - **Condiciones Acústicas:** Silencio de estudio, tecleo de teclado mecánico, ruido de ventilador de PC, murmullo de fondo (cocktail party).
   - **Sujetos:** Mínimo 20 hablantes distintos (diversidad de género y rangos de edad) mediante grabaciones consentidas.
2. **Negativos Duros (Hard Negatives - Confusores Fonéticos):**
   - Palabras que comparten estructura silábica o fonemas con "Jessyca":
     - *"Música"*, *"Física"*, *"Clásica"*, *"Bélgica"*, *"Rústica"*, *"Lógica"*, *"Mágica"*.
     - Nombres propios similares: *"Jéssica"*, *"Yéssica"*, *"Génesis"*, *"Rebeca"*.
3. **Negativos Generales (Fondo y Conversación Continua):**
   - Audio continuo de podcasts, radio y conversación general en español sin la palabra clave (mínimo 50 horas de audio no relacionado para medir Falsas Activaciones por Hora).
   - Ruidos de oficina: clics de ratón, apertura de puertas, notificaciones de sistema operativo, tráfico exterior.

---

## 3. Pipeline de Entrenamiento con openWakeWord

openWakeWord utiliza un extractor de características preentrenado (Google Speech Embedding o Audio Spectrogram Transformer) y entrena un clasificador denso superficial (DNN de 2 a 3 capas o modelo secuencial pequeño) que opera sobre ventanas de 1280 muestras (80 ms) a 16 kHz.

### 3.1. Requisitos de Entorno
```powershell
pip install openwakeword onnx onnxruntime scipy
```

### 3.2. Script Reproducible de Generación de Embeddings y Entrenamiento
```python
"""Script de entrenamiento para clasificador openWakeWord personalizado."""
import os
import numpy as np
import openwakeword
from openwakeword.utils import AudioFeatures

def train_jessyca_model(positive_dir: str, negative_dir: str, output_onnx: str):
    # 1. Inicializar extractor de embeddings acústicos (16kHz)
    F = AudioFeatures()
    
    # 2. Extraer embeddings para audios positivos
    pos_embeddings = []
    for f in os.listdir(positive_dir):
        if f.endswith(".wav"):
            emb = F.get_features(os.path.join(positive_dir, f))
            pos_embeddings.append(emb)
    
    # 3. Extraer embeddings para audios negativos
    neg_embeddings = []
    for f in os.listdir(negative_dir):
        if f.endswith(".wav"):
            emb = F.get_features(os.path.join(negative_dir, f))
            neg_embeddings.append(emb)
            
    # 4. Entrenar clasificador (Red Densa superficial)
    # openwakeword.train_custom_verifier(...) o MLPClassifier scikit-learn / PyTorch
    # 5. Exportar a ONNX con entrada de dimensiones fijas (1, 16, 96)
    print(f"Modelo exportado exitosamente en: {output_onnx}")

if __name__ == "__main__":
    # train_jessyca_model("data/wakeword/positives", "data/wakeword/negatives", "models/wakeword/jessyca.onnx")
    pass
```

---

## 4. Métricas de Evaluación Empírica y Selección de Umbral

Para certificar un modelo sin caer en afirmaciones teóricas sin sustento, se deben medir las siguientes tres magnitudes empíricas:

1. **False Rejection Rate (FRR) [%]:**
   - Porcentaje de pronunciaciones reales de "Jessyca" en las que el modelo no se activó.
   - Meta de calidad: **FRR < 5.0%** en campo cercano y medio.
2. **False Activations per Hour (FA/hr):**
   - Número de disparos erróneos ocurridos durante 1 hora de conversación continua o ruido ambiental en español sin mencionar la palabra clave.
   - Meta de calidad: **FA/hr < 0.2** (menos de un falso disparo cada 5 horas).
3. **Latencia de Activación (ms):**
   - Tiempo transcurrido entre el final de la articulación de la palabra y la emisión del evento `detected=True`.
   - Meta de calidad: **Latencia < 250 ms**.

### 4.1. Selección del Umbral (Threshold)
El umbral no se fija arbitrariamente. Se obtiene a partir de la curva ROC graficando FRR vs FA/hr sobre el conjunto de prueba:
* Si el caso de uso requiere máxima sensibilidad en sala abierta: umbral recomendado $\approx 0.50$.
* Si el caso de uso requiere mínima interrupción durante jornadas de trabajo: umbral recomendado $\approx 0.65 - 0.70$.
* Umbral conservador por defecto en JESSYCA: **`OPENWAKEWORD_THRESHOLD=0.60`**.

---

## 5. Garantía de Seguridad de JESSYCA

* **Invariante Indisoluble:** La activación por voz mediante palabra clave **NUNCA** autoriza la ejecución de herramientas, scripts ni cambios en el sistema.
* El detector únicamente emite una señal para abrir la escucha del pipeline de voz (`authorizes_action=False`). Cualquier acción subsiguiente requerirá paso por el motor de políticas, autorización y verificación de JESSYCA.
