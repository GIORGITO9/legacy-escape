# Uso de inteligencia artificial

## Uso 1
- Herramienta: Claude Code (Claude Opus)
- Para qué se usó: leer el kit completo (RETO, RUBRICA, validador y datos) y resumir qué exige cada prueba G01–G15 y cada entregable GE01–GE11
- Prompt principal (resumido): "revisa la carpeta del hackathon de la FESC y dime qué hay que construir para sacar el máximo puntaje"
- Qué produjo: un resumen del contrato, de las reglas del adapter y de las penalizaciones, y la deducción de que fullName se arma como nombres más apellidos
- Qué modificó o corrigió el equipo: no confiamos en la deducción del formato de fullName y la comprobamos calculando la huella PBKDF2 de .validator.json para los dos afiliados públicos; ambas coincidieron antes de escribir código

## Uso 2
- Herramienta: Claude Code (Claude Opus)
- Para qué se usó: diseñar el gateway, el modelo canónico y el adapter que resiste el cambio de esquema PERSON_MASTER
- Prompt principal (resumido): "gateway en Python con adapter que funcione antes y después de schema-change.sh sin reiniciar"
- Qué produjo: un adapter con dos variantes del maestro de afiliados que prueba la otra variante si la tabla o columna no existe
- Qué modificó o corrigió el equipo: revisamos con grep que ningún archivo fuera de src/adapter nombre tablas ni columnas legacy (GE01), incluso en comentarios, y dejamos los códigos A/R/S y C/H/P/M solo dentro del adapter

## Uso 3
- Herramienta: Claude Code (Claude Opus)
- Para qué se usó: resolver la idempotencia de retiros y la tolerancia a la caída de la base
- Prompt principal (resumido): "el mismo requestId no puede duplicar LOGMOV y un retiro aceptado con la base caída debe aplicarse una sola vez"
- Qué produjo: una primera propuesta que guardaba los requestId solo en una SQLite del gateway
- Qué modificó o corrigió el equipo: la SQLite sola podía duplicar si se perdía el volumen, así que agregamos una tabla de requestId en la base legacy escrita en la misma transacción que el procedimiento y dejamos la SQLite como cola de pendientes

## Uso 4
- Herramienta: Claude Code (Claude Opus)
- Para qué se usó: escribir la suite de pruebas pytest con reporte JUnit para el servicio tests
- Prompt principal (resumido): "al menos 10 pruebas de contrato contra la API corriendo, incluido un retiro real"
- Qué produjo: la idea inicial de probar el retiro con un afiliado de los datos sintéticos
- Qué modificó o corrigió el equipo: retirar afiliados reales cambiaba los datos y los conteos de activeMembers que revisa el calificador, por eso las pruebas crean su propia empresa y afiliados de prueba y los borran al terminar
