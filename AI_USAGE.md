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

## Uso 5
- Herramienta: Claude Code (Claude Opus)
- Para qué se usó: hacer que el gateway responda 503 en menos de 3 segundos cuando se detiene legacy-db (prueba G10)
- Prompt principal (resumido): "con docker compose stop legacy-db la consulta tarda casi 4 segundos, el límite es 3"
- Qué produjo: la primera versión del adapter conectaba por nombre de host con connect_timeout de 2 segundos
- Qué modificó o corrigió el equipo: medimos con curl y vimos que el DNS de Docker tarda unos 4 segundos en fallar con el contenedor detenido; agregamos un monitor que guarda la IP de la base y una sonda TCP de 0,5 s, y el peor caso bajó a 0,5 s

## Uso 6
- Herramienta: Claude Code (Claude Opus)
- Para qué se usó: revisar la auditoría en logs/audit.log contra la regla de una línea JSON por petición de consumidor
- Prompt principal (resumido): "revisa todo de nuevo contra la rúbrica antes de entregar"
- Qué produjo: la auditoría registraba todas las peticiones, incluidas las del healthcheck de Docker a /health
- Qué modificó o corrigió el equipo: el healthcheck escribía una línea anónima cada 5 segundos y llenaba el log de ruido, así que dejamos fuera la sonda /health y mantenemos registrados los intentos sin token
