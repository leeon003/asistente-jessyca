from skills.apps import _normalizar, _buscar_en_mapeo

mapeo = {"bloc de notas": "notepad.exe", "calculadora": "calc.exe"}

casos = ["Bloc de Notas", "bloc de notas", "BLOC DE NOTAS", "bloc_de_notas", "Bloc De Notas"]
print("=== Prueba de normalizacion ===")
for c in casos:
    resultado = _buscar_en_mapeo(c, mapeo)
    icono = "OK" if resultado == "notepad.exe" else "FALLO"
    print(f"  [{icono}]  '{c}' -> {resultado}")
