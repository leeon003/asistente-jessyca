# AnyDoc Fase 3 — Auditoría de Verificación Física y Protección Anti Falso Éxito

## 1. Principio Fundamental de Verificación

En JESSYCA PC, el éxito de una operación jamás se asume por la mera ausencia de excepciones o el retorno de una biblioteca. Toda operación debe superar una auditoría física de tres estados:

1. `CLAIMED_SUCCESS`: Estado preliminar donde se alega éxito pero aún falta comprobación física independiente o gate formal.
2. `VERIFIED_SUCCESS`: Estado definitivo que exige:
   - Preservación íntegra del archivo original (`SHA256(input BEFORE) == SHA256(input AFTER)`).
   - Existencia física del archivo de salida dentro del sandbox autorizado.
   - Tamaño del archivo de salida mayor a cero bytes (`size > 0`).
   - Hash del archivo de salida registrado fehacientemente en el recibo JDE.
3. `VERIFICATION_FAILED`: Estado seguro al que se conmuta si cualquiera de los criterios anteriores falla (archivo faltante, vacío, corrupto o hash inconsistente).

---

## 2. Cobertura de Pruebas de False-Success

- **Salida inexistente**: Si la ruta de salida no se crea, el resultado conmuta a `VERIFICATION_FAILED`.
- **Salida vacía**: Un archivo de cero bytes no se certifica como éxito.
- **Entrada alterada**: Si la conversión intentase modificar el archivo de origen, la discrepancia en el hash SHA-256 dispara fallo inmediato.
- **Resultado simulado / alteración externa**: Si el archivo es borrado o corrompido antes de la verificación final, la operación concluye en `VERIFICATION_FAILED`.
