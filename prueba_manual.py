from skills.apps import AbrirAplicacion

abrir = AbrirAplicacion()

# Caso de éxito
res_exito = abrir.ejecutar({"nombre": "bloc de notas"})
print("Caso Éxito:", res_exito)

# Caso de error (aplicación no registrada)
res_error = abrir.ejecutar({"nombre": "programa_inventado"})
print("Caso Error:", res_error)
