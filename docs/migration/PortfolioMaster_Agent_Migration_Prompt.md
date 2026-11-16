# Prompt maestro para el agente que migrará PortfolioMaster

Actúa como arquitecto de software y agente senior de migración. Tu fuente de verdad es el repositorio actual `Tifu0/PortfolioMaster` y el documento `PortfolioMaster_Migration_Dossier.md`. **No asumas que el README siempre describe lo que el código realmente hace**: abre y lee el código/test antes de concluir. No hagas una reescritura masiva ni elimines el original hasta que haya pruebas de paridad y un plan de rollback.

## Objetivo
Migrar PortfolioMaster preservando el comportamiento de usuario, datos, fórmulas, referencias temporales, contratos HTTP y operaciones de backup/restore. Mejorar los bugs identificados en el dossier en vez de replicarlos. Mantén la migración agnóstica al destino hasta confirmar la plataforma objetivo, el modelo de hosting (local-first o remoto/multiusuario), base de datos y necesidades de autenticación. Si esos aspectos aún no están definidos, trabaja primero en análisis y especificación, presenta las opciones recomendadas y explicita supuestos; no bloquees el análisis detallado del origen.

## Paso 1 — Inspección real, archivo por archivo
1. Confirma rama, commit/hash y estado del repo.
2. Recorre todos los archivos de código, tests y configuración, abriendo sus contenidos. No trates el filename o el README como prueba suficiente.
3. Excluye de migración `__pycache__`, `.pytest_cache`, `.next`, `node_modules`, builds, secretos, ficheros temporales, base de datos real y backups locales.
4. Lee `README.md`, `frontend/AGENTS.md`, `pyproject.toml`, `requirements.txt`, `pytest.ini`, `.env.example`, `frontend/package.json`, `frontend/next.config.ts` y `frontend/lib/types.ts`.
5. Produce un inventario que incluya, para cada archivo relevante: propósito, símbolos/clases/funciones principales, consumidores, entradas/salidas, efectos laterales, dependencias, riesgos, tests actuales y tests faltantes.
6. Construye un mapa de llamadas para: alta/edición/borrado; refresco individual/masivo/scheduler; SSE; preview/confirm import; CSV/XLSX/JSON export; backup SQLite; restore de JSON/DB; completar precios históricos y YTD.
7. Verifica la API con OpenAPI/runtime si es posible y compara cada endpoint/respuesta con el cliente `frontend/lib/api.ts` y los tipos TypeScript. Documenta discrepancias exactas.

## Paso 2 — Caracterizar reglas de negocio
Documenta y prueba en forma reproducible:
- fórmulas de variación diaria, desde análisis, YTD y variación al precio objetivo;
- política de redondeo (`Decimal`, precisión y modo);
- condiciones que hacen válidas/invalidan métricas y política ante None/0/negativos/NaN/Infinity;
- diferencia semántica entre `user_ticker` y `provider_symbol`;
- fecha de análisis vs fecha efectiva del cierre usado; fecha YTD vs primera sesión disponible;
- estados `FRESH`, `DELAYED`, `STALE`, `UNAVAILABLE`, `ERROR` y reglas por exchange;
- campos opcionales: diferencia entre “omitido”, “null para limpiar” y valor válido;
- política de activos/inactivos;
- comportamiento duplicado de símbolos de proveedor;
- qué se considera export de trabajo y qué se considera backup completo.

Genera golden fixtures de valores sintéticos y utiliza el sistema original como referencia para todo comportamiento intencionado. Registra por separado cualquier bug antiguo, su síntoma y el comportamiento nuevo elegido; no cambies fórmulas silenciosamente.

## Paso 3 — Tratar explícitamente los problemas del dossier
Como mínimo, investigar, reproducir y corregir estos puntos:
1. `src/portfoliomaster/backup/exporters.py`: `decline_to_target` recibe argumentos invertidos comparado con `core/calculations.py` y `/api/positions`.
2. `frontend/components/ImportView.tsx`: el payload final omite `start_of_year_date` y `start_of_year_price`.
3. `restore_from_json`: el `target_db_path` no se propaga a `wipe_database`/`upsert_instrument`; la restauración puede escribir en otra BD.
4. Restore JSON no atómico: validar por completo e importar a DB temporal; si falla cualquier fila/quote, mantener intacta la DB original.
5. `upsert_quote` y refresco: evitar que una respuesta `ERROR` o `UNAVAILABLE` destruya el último precio válido.
6. Histórico: no etiquetar `fast_info` o precio de los últimos días como precio de una fecha antigua; aceptar solo observación con fecha real válida, y comunicar fallos/fechas de trading aproximadas.
7. Edición de campos: definir semántica de null/omitido para limpiar target, precio/fecha de análisis, campos YTD y notas.
8. Diferencia entre activos/inactivos de `/api/positions`, `/api/instruments`, métricas, refresco y export.
9. `get_export_records(db_path)`: consulta por el destino especificado, sin funciones globales que abran otra BD.
10. `repository._parse_date`: separar parser de `date` y `datetime` para preservar timestamps de cotización.
11. Varios instrumentos con mismo `provider_symbol`: todos deben recibir el resultado correcto.
12. Refresh individual frente a masivo: evitar carreras y estados finales de SSE que nunca terminan.
13. API URL: `.env.example` usa `API_BASE_URL`; cliente mira `NEXT_PUBLIC_API_URL`; el cliente hace peticiones absolutas y el rewrite puede quedar sin uso.
14. Validaciones de importación: ticker case-insensitive, datos numéricos/fechas, duplicados, previews caducadas o manipuladas, límite de tamaño y errores no silenciosos.
15. Protección de rutas destructivas y uploads, especialmente si el destino deja de ser estrictamente local.

No borres tests que fallen para que la suite quede verde. Decide si el comportamiento fallido era bug o contrato e incluye la razón en el informe.

## Paso 4 — Propuesta de arquitectura objetivo
Antes de implementar, escribe una propuesta con límites claros:
- dominio sin dependencia del framework;
- un solo servicio de cálculo financiero;
- repositorio/DAO con transacciones explícitas e inyección de dependencia;
- migraciones de base de datos versionadas;
- capa proveedor con contrato y pruebas mock deterministas;
- pipeline de refresh con run-id, progreso, resultados por símbolo, idempotencia y estado terminal;
- import preview firmado/referenciado y commit atómico;
- export de hoja de trabajo separado del backup restaurable;
- API schemas estrictos y documentación;
- frontend separado en componentes/hooks mantenibles y un único cliente API;
- logging, salud, configuración, autorización y límites acordes con el despliegue.

Incluye diagrama de componentes, decisiones ADR cortas, esquema de datos destino, tabla endpoint viejo → endpoint nuevo, tratamiento de SSE, estrategia de símbolos/mercados y manejo de timestamps/time zones. Explica las alternativas que descartas.

## Paso 5 — Migración de datos sin pérdidas
1. Crear backup inmutable del origen; nunca utilizar el archivo real del usuario para pruebas destructivas.
2. Especificar mapping campo a campo de SQLite actual a destino, incluidas quotes/estados/fechas/notas/active y todos los símbolos.
3. Crear herramienta de migración idempotente con dry-run y reporte por fila.
4. No normalizar/reformatear tickers del usuario silenciosamente; conservar la representación original.
5. Validar claves únicas, número de instrumentos y quotes, valores no finitos, consistencia precio/fecha y export/restore.
6. Probar restauración del backup, fallo parcial, restart y rollback.
7. No cortar el origen hasta que el usuario autorice el cutover y el nuevo sistema pase la suite.

## Paso 6 — Tests y definición de terminado
Crea pruebas unitarias de dominio, tests de repo/DB, contract tests de API, test de proveedor mock, tests React reales y E2E de rutas críticas. Como mínimo cubrir:
- cálculo idéntico entre dominio/API/CSV/XLSX/JSON;
- CSV/XLSX preview-confirm conserva YTD, notas, target y fechas;
- export/import JSON roundtrip completo;
- restore a ruta DB alternativa y no alterar la DB no destino;
- restauración fallida mantiene DB original;
- quote válida + fallo siguiente conserva precio bueno y anota fallo;
- histórico ausente no se hace pasar por dato antiguo;
- null/omitido en edición;
- activo/inactivo definido y consistente;
- tickers duplicados case-insensitive y provider symbol compartido;
- timestamp parseable;
- refresh concurrente produce estado correcto y SSE termina;
- upload masivo/rechazo seguro;
- preferencias de columnas/sort/altura y deep links;
- manejo de API offline y proveedor no disponible.

Ejecuta las suites originales y nuevas en entorno limpio con versiones fijadas. No afirmes tests frontend pasados si solo se han inspeccionado scripts fuente-basados; ejecuta build/lint y pruebas runtime cuando dependencias estén instaladas.

## Entregables obligatorios
1. Informe final de auditoría archivo-por-archivo y findings con severidad, prueba y localización.
2. Especificación de comportamiento y contratos/API.
3. Esquema destino y mapping de datos.
4. Plan de migración por fases, plan de rollback y decisiones ADR.
5. Código de migración y tests si se autoriza implementar.
6. Lista exacta de comandos ejecutados y resultado real de cada uno, incluyendo bloqueos por dependencias/red.
7. Lista de diferencias deliberadas respecto al origen y bugs corregidos.
8. Check de datos: conteos/checksums antes y después y resultado de restore en entorno de prueba.

## Reglas de trabajo
- No inventar funciones, resultados, pruebas ni contenido de archivos que no se hayan abierto.
- Referenciar `ruta:línea` siempre que sea útil.
- Separar evidencia, hipótesis y recomendación.
- Mantener la privacidad: no subir `.env`, secretos, cartera real ni backups privados a servicios externos.
- Preferir cambios acotados, reversibles y con tests en lugar de una reescritura monolítica.
- Si destino todavía no está definido, terminar análisis/propuesta y dejar la implementación desacoplada de esa decisión, no asumir un stack sin aprobación.

**Primer paso operativo:** compara el repo actual con `PortfolioMaster_Migration_Dossier.md`, reproduce los findings P0/P1 y devuelve un inventario real de código con el plan de trabajo propuesto antes de empezar una migración destructiva.
