# PortfolioMaster — Dossier técnico de origen y guía de migración

**Fecha de inspección:** 22 de octubre de 2026  
**Fuente revisada:** ZIP `PortfolioMaster-main.zip`, rama `main` (el README / proyecto incluye referencias Next.js 16.4.1, React 19.3.0).  
**Objetivo:** permitir que un agente de programación migre el comportamiento de PortfolioMaster sin perder datos, contratos, reglas financieras ni funcionalidades implícitas.

> **Alcance y honestidad de la auditoría.** Se inspeccionó el contenido fuente incluido en el ZIP, la configuración, los tests, las rutas de API, las importaciones/exportaciones y el recorrido de datos entre frontend y backend. Las observaciones de código citan rutas y números de línea orientativos del ZIP tal como se recibió. La suite no se pudo ejecutar íntegramente porque el entorno de auditoría no tenía instalado `yfinance`; las pruebas de núcleo ejecutables pasaron. No se ha hecho una prueba de integración real contra Yahoo Finance ni una prueba de navegador del frontend.

## 1. Resumen ejecutivo

PortfolioMaster es una aplicación de seguimiento de watchlists de inversión **local-first**. No es una plataforma de trading ni un libro contable de operaciones: no modela compras, cantidades, costes medios, dividendos cobrados o valor de cartera por posiciones en el sentido de cartera transaccional. Su unidad principal es un **instrumento vigilado** con ticker personal, símbolo para proveedor, mercado/divisa, fecha y precio de análisis, referencia de inicio de año, precio objetivo, notas y última cotización recibida.

La aplicación consta de:

- **Frontend:** Next.js App Router, React, TypeScript, Tailwind CSS v4 y TanStack Table; vistas de watchlist, importación y copias/exportaciones.
- **Backend:** una API FastAPI central en `backend/api/main.py`; actualmente concentra endpoints, tareas programadas, llamadas Yahoo, lógica de importación y operaciones de mantenimiento.
- **Núcleo Python:** modelos, cálculos financieros, configuración, normalización, repositorio SQLite, proveedor Yahoo/mock, lotes y copias de seguridad/exportadores bajo `src/portfoliomaster/`.
- **Persistencia:** SQLite, tablas `instruments` y `quotes`; no se observa un sistema formal/versionado de migraciones de esquema.
- **Proveedor:** `yfinance` / Yahoo Finance; el precio y los metadatos dependen de disponibilidad y semántica del proveedor.
- **Actualización:** refresco de lotes con persistencia por lote, tarea en segundo plano durante la vida de FastAPI y eventos SSE para reportar avance.

### Evaluación general

Hay una separación de dominio razonable en `src/portfoliomaster`, pero la API de 1.875 líneas vuelve a implementar parte de la lógica y concentra demasiadas responsabilidades. El frontend tiene componentes grandes (`WatchlistTable.tsx`, `ManualEntryModal.tsx`, `BackupExportModal.tsx`) y algunas verificaciones de frontend son pruebas basadas en el texto del código, no tests de comportamiento. Para una migración fiable conviene separar las reglas del negocio de sus adaptadores tecnológicos y escribir pruebas de caracterización **antes** de reimplementar.

### Hallazgos que deben considerarse bloqueantes para migrar datos con seguridad

1. **Exportación calcula mal la variación hasta precio objetivo:** `src/portfoliomaster/backup/exporters.py:77` llama `decline_to_target(quote.price, inst.target_price)`, aunque la firma es `(target_price, latest_price)`. En `/api/positions` se usa el orden correcto (`backend/api/main.py:390`). La exportación puede no coincidir con la tabla.
2. **La importación de la UI omite las referencias YTD:** `frontend/components/ImportView.tsx:108-119` no incluye `start_of_year_date` ni `start_of_year_price`, aunque el backend, el modelo y el exportador sí los soportan. Importar desde la interfaz pierde esos datos.
3. **Restauración JSON no respeta `target_db_path`:** `restore_from_json` calcula el destino y hace el backup de ese fichero, pero vacía y repuebla la base por las funciones del repositorio que usan la ruta global/default (`src/portfoliomaster/backup/exporters.py:319-368`). Con destino personalizado, puede modificar otra BD.
4. **Restauración JSON no es atómica:** vacía la BD antes de convertir/restaurar todos los campos (`exporters.py:325-394 en adelante`). Un registro malformado puede dejar el estado vacío o parcialmente restaurado.
5. **Una cotización fallida puede borrar el último precio válido:** `upsert_quote` sustituye siempre precio/status por los recibidos (`src/portfoliomaster/db/repository.py:131-163`), y el callback de refresco guarda también `ERROR`/`UNAVAILABLE` (`backend/api/main.py:1418-1431`). El error temporal se convierte en pérdida de dato previo.
6. **Riesgo de precio histórico incorrectamente fechado:** `backend/api/main.py:985-1017` y `src/portfoliomaster/providers/yahoo_adapter.py:346-378` recurren a `fast_info` o al historial reciente si falta la cotización de la fecha solicitada; el primer camino mantiene `actual_dt = target_date` incluso si se usa un precio actual. Esto puede guardar un precio actual como referencia histórica antigua.
7. **Las operaciones de edición no siempre permiten limpiar un campo:** el backend ignora `None` en muchos campos opcionales (`backend/api/main.py:861` en adelante), mientras que el frontend envía `null` al dejar algunas entradas vacías. El usuario ve el campo vacío, pero el valor anterior puede mantenerse.
8. **No hay garantía suficiente de integridad ante importación:** el endpoint de confirmación confía en la lista suministrada por el cliente; la validación de ticker es muy limitada, el backup previo se intenta pero los errores se ignoran y las escrituras son por instrumento (`backend/api/main.py:1656-1718`).

Estos problemas deben abordarse antes de usar datos migrados como fuente fiable de decisiones de inversión.

## 2. Arquitectura y responsabilidades reales

```text
Usuario / navegador
   │
   ├─ Next.js App Router: /, /import, /backup
   ├─ PortfolioContext: estado compartido, polling de config, suscripción SSE
   ├─ lib/api.ts: cliente HTTP y contratos TypeScript
   │
   ▼
FastAPI — backend/api/main.py
   ├─ /api/positions + cálculos devueltos al frontend
   ├─ CRUD de instrumentos
   ├─ histórico/YTD y resoluciones de referencias faltantes
   ├─ refresco manual/individual/programado + SSE
   ├─ previsualización/confirmación de importaciones
   └─ exportaciones, reset y restauración
   │
   ├───────────────┬────────────────┬─────────────────┐
   ▼               ▼                ▼                 ▼
SQLite repo     core/calculations  ingest/import    backup/export
   │                                │                 │
   └────────────────────────────────┴─────────────────┘
                                    │
                          YahooAdapter / yfinance
                                    │
                              Yahoo Finance
```

### Principios que deben preservar los agentes de migración

- El frontend muestra métricas calculadas por el backend; las funciones de `core/calculations.py` y los valores/flags de la respuesta de `/api/positions` son referencia de negocio. No trasladar cálculos a TypeScript sin pruebas numéricas de equivalencia.
- `user_ticker` y `provider_symbol` no son intercambiables. El primero representa el símbolo introducido/mostrado por el usuario; el segundo es el símbolo normalizado que consume Yahoo (p. ej. suffix como `.MC`, `.PA`). Ambos deben conservarse.
- Una ausencia de dato no equivale a cero. Las métricas incluyen flags `*_valid`; un dato inválido debe ser `null`/inválido, no un número artificial.
- Fecha de referencia y precio de referencia forman un par semántico. No recalcular una fecha a partir de la fecha de descarga; almacenar la fecha de mercado real usada.
- Una recuperación, importación o reset es una operación destructiva: debe validarse completamente y poder revertirse.
- Las copias deben incluir datos de instrumentos y cotizaciones, con valores y estados; exportar solo instrumentos activos puede estar bien para un CSV de trabajo, pero un backup debe ser íntegro.

## 3. Modelo de dominio

### 3.1 Instrumento (`src/portfoliomaster/core/models.py`)

Campos principales observados:

| Campo | Significado / consideración de migración |
|---|---|
| `id` | ID entero interno de SQLite. No es una identidad externa estable si se reconstruye la BD. |
| `user_ticker` | Símbolo mostrado al usuario; único en SQLite. Mantener literalmente, salvo que el usuario solicite renombrarlo. |
| `provider_symbol` | Símbolo enviado al proveedor (`yfinance`), puede contener sufijo de mercado. |
| `exchange` | Enum `Exchange`; hay soporte para mercados de muchos países y `UNKNOWN`. |
| `currency` | Código de divisa usado para normalización. En algunos caminos la omisión hereda `EUR` por el default del modelo de petición de API. |
| `company_name` | Nombre legible; puede resolverse mediante Yahoo o ser fallback al ticker. |
| `analysis_date` | Fecha de referencia elegida por el usuario. |
| `analysis_reference_price` | Precio de cierre/valor usado como referencia de variación desde análisis; debe mantenerse sincronizado con su fecha. |
| `start_of_year_date` | Fecha real del precio de arranque anual. Puede ser el primer día de negociación disponible, no siempre el 1 de enero. |
| `start_of_year_price` | Precio de referencia para YTD. |
| `target_price` | Precio objetivo introducido por el usuario. |
| `comment` | Notas de investigación, texto libre. |
| `active` | Activa/desactiva; actualmente los endpoints no son consistentes con este flag. |
| `created_at`, `updated_at` | Timestamps SQLite. El repositorio actualiza `updated_at` en upsert/update. |

### 3.2 Cotización (`Quote`)

- `instrument_id`, `price`, `previous_close`, `quote_timestamp`, `fetched_at`, `provider`, `status`, `error_message`.
- Estados: `FRESH`, `DELAYED`, `STALE`, `UNAVAILABLE`, `ERROR`.
- `quote_timestamp` debe reflejar cuándo corresponde el dato de mercado; `fetched_at` cuándo se descargó.
- `FreshnessConfig` define límites por antigüedad. Por defecto una cotización retrasada o antigua no debe disparar alertas salvo configuración específica.
- El estado `UNAVAILABLE` o `ERROR` no debería borrar el último precio válido: conviene modelar último dato válido y último intento por separado, o actualizar status/error sin sustituir el precio histórico válido.

### 3.3 Persistencia (`src/portfoliomaster/db/connection.py`, `repository.py`)

El esquema inicial tiene dos tablas:

- `instruments`: ticker único; metadatos y referencias financieras.
- `quotes`: una fila por `instrument_id`, con precio más reciente; `instrument_id` es `UNIQUE` y tiene una FK declarada.

`init_db()` hace `CREATE TABLE IF NOT EXISTS` y una migración manual de `start_of_year_date` y `start_of_year_price`. No se encontró un registro de versiones de esquema. `get_connection()` no habilita explícitamente `PRAGMA foreign_keys=ON`; en SQLite la declaración de FK por sí sola no garantiza que se comprueben en cada conexión.

Problemas de persistencia confirmados:

- `repository._parse_date()` usa `date.fromisoformat()` también para columnas timestamp (`quote_timestamp` y `fetched_at`); un string normal con hora, p. ej. `2026-10-21 15:30:00`, no se parsea como `date` y se convierte en `None` (`repository.py:251-265`, `get_quote_by_instrument_id` líneas 219-229).
- `upsert_instrument` reemplaza con `NULL`/vacío los valores existentes para análisis, target y comentario cuando el input viene vacío; YTD es la excepción porque usa `COALESCE` (`repository.py:54-66`). Esto puede borrar datos por importación parcial.
- `_safe_decimal()` puede lanzar `InvalidOperation` si la BD contiene texto no numérico, y no filtra explícitamente `NaN`/infinito (`repository.py:268-279`).
- No hay transacciones de dominio multi-operación centralizadas. Cada función abre/concluye una conexión y hace `commit()` individual.

**Recomendación de migración:** definir un esquema con versión; una unidad de trabajo/transacción por operación; constraints e índices explícitos; preservar `Decimal` en el dominio y convertir a decimal/numérico solo en límites definidos; parsers de `date` y `datetime` separados; y restauraciones usando una BD temporal validada más swap atómico.

## 4. Reglas de cálculo financiero

Implementaciones puras en `src/portfoliomaster/core/calculations.py`; respuesta principal en `backend/api/main.py:386-449`.

- **Variación diaria (%):** `((precio_actual - cierre_anterior) / cierre_anterior) × 100`.
- **Variación desde análisis (%):** `((precio_actual - precio_referencia_análisis) / precio_referencia_análisis) × 100`.
- **Variación YTD (%):** `((precio_actual - precio_inicio_año) / precio_inicio_año) × 100`.
- **Variación vs objetivo / decline-to-target (%):** `((precio_objetivo - precio_actual) / precio_actual) × 100`. Un resultado positivo significa que el precio objetivo está por encima del actual; un resultado negativo que está por debajo. Es más parecido a “upside hasta objetivo” que a la caída porcentual del precio hacia el objetivo; al migrar hay que preservar la semántica que la UI usa o renombrarla de forma deliberada.

Detalles a preservar:

- Las conversiones usan `Decimal` y el redondeo se hace a dos decimales con `ROUND_HALF_UP`.
- `None`, cero en denominador, números no finitos y precios de referencia ausentes pueden hacer que un resultado sea inválido; el backend acompaña valores con flags `*_valid`.
- Las validaciones no son totalmente homogéneas: `ytd_variation` y `is_target_reached` validan positividad de precio de referencia/objetivo más estrictamente que las funciones diaria, desde análisis y `decline_to_target`. Hay que unificar criterios con pruebas de caracterización, sin cambiar silenciosamente valores históricos.
- `is_target_reached(...)` existe en el núcleo, pero no se ve en el contrato de `/api/positions`; la tabla comunica `decline_to_target` en lugar de un booleano de objetivo alcanzado.
- Exportación contradice el cálculo autoritativo: `exporters.py:77` invierte los argumentos del objetivo. Un test específico debe comparar el mismo instrumento entre `/api/positions`, CSV, XLSX y JSON.

## 5. Proveedor de mercado y refresco

### 5.1 YahooAdapter (`src/portfoliomaster/providers/yahoo_adapter.py`)

- Normaliza símbolos para el formato Yahoo y descarga varios tickers con `yf.download` cuando hay más de uno (`period="5d"`, multi-ticker y threading); si no obtiene datos por símbolo, usa `yf.Ticker(...).fast_info`/`history` de forma individual.
- Extrae `Close` y calcula `previous_close` usando el penúltimo cierre cuando hay historial suficiente; de lo contrario usa fallback `Open` en un caso de batch.
- La fecha del índice del historial se usa como timestamp de cotización. En datos diarios suele ser la fecha de sesión a medianoche; no representa una hora real de cotización intradía y puede resultar retrasada según las reglas de freshness.
- En fallos se devuelve `QuoteStatus.UNAVAILABLE` o `ERROR` con `price=None`.
- `fetch_historical_quote` primero busca cierres en una ventana anterior hasta la fecha solicitada; cuando no encuentra datos, el fallback puede usar `fast_info` o el último dato de los últimos cinco días y devolverlo como resultado histórico. No debe asumirse que el precio pertenece a la fecha solicitada.
- Lectura de `fast_info`: se debe probar el tratamiento de `NaN`, valores no finitos y excepciones. El valor `NaN` no es necesariamente equivalente a `None`.

### 5.2 BatchRunner (`src/portfoliomaster/refresh/batch_runner.py`)

- Divide los símbolos en lotes según el tamaño de batch y llama al proveedor.
- Hace callback después de cada lote, también si el lote falla, para permitir actualizar el progreso.
- El comportamiento de retries/sleep está codificado dentro del runner (reintentos dos veces y espera fija de 1 s) aunque `core/config.py` declara `MAX_RETRIES`, `BASE_BACKOFF_SECONDS` y `MAX_BACKOFF_SECONDS`. En migración debe existir una sola fuente de configuración y backoff testeable.
- La configuración declara `MAX_BATCH_SIZE`, pero `get_batch_size()` no impone ese límite, así que el valor de entorno puede superar la constante.

### 5.3 Ciclo de refresco en API (`backend/api/main.py`)

- El `lifespan` inicializa SQLite y arranca una tarea que programa refrescos; el valor base del intervalo es 300 segundos, y `0` permite desactivar.
- `/api/refresh` dispara un refresco masivo; `/api/instruments/{ticker}/refresh` refresca un elemento.
- El refresco masivo adquiere un lock no bloqueante; el refresco individual no usa el mismo lock, por lo que ambos caminos podrían solaparse y escribir para un mismo instrumento.
- Se traduce `provider_symbol → instrument_id` mediante un dict (`instrument_map`). Si dos instrumentos comparten el mismo `provider_symbol`, el dict solo retiene uno y la actualización no se aplica a ambos.
- El callback por lote persiste todas las respuestas, incluso las fallidas, pudiendo borrar la última cotización útil.
- El estado global de progreso y subscribers SSE viven en memoria del proceso; desaparecen al reiniciar y no son adecuados para escalar a varios workers/procesos sin un canal compartido.
- SSE publica `start`, `batch`, `complete`/`error` y el frontend mantiene una suscripción listen. El parámetro `trigger` se declara en el endpoint pero no parece leerse efectivamente; hay una posible carrera cuando un refresh concurrente hace que el worker responda `in_progress` y el stream no reciba un evento terminal.

**Recomendación:** modelar las actualizaciones como tarea explícita con `run_id`, estado persistente, resultados por símbolo, último precio bueno, `requested_at`, `started_at`, `completed_at`; cancelar/reintentar por política y no por efecto colateral del frontend; y usar SSE/WebSocket/cola según el despliegue objetivo.

## 6. API HTTP actual (contrato de comportamiento)

`backend/api/main.py` es el punto de entrada y contiene 27 rutas en total si se cuenta `GET /`, incluyendo 26 bajo `/api`. Preservar métodos, parámetros, status codes, esquemas de datos y semántica es parte de la migración aunque internamente se cambien nombres o framework.

| Método | Ruta | Responsabilidad | Consideraciones |
|---|---|---|---|
| `GET` | `/` | health/app/version | verificar qué metadatos son consumidos por tooling. |
| `GET` | `/api/positions` | instrumentos+cotizaciones+métricas y flags | actualmente consulta todas las filas, incluso `active=0`. Cálculo de métricas en servidor. |
| `GET` | `/api/metrics` | KPIs: total, mejor/peor y media de variación diaria | deriva desde `/api/positions`, por lo que hereda inconsistencia de activos/inactivos. |
| `GET` | `/api/instruments` | instrumentos raw | usa repositorio, que devuelve solo `active=1`. |
| `GET` | `/api/instruments/check-yahoo?ticker&currency` | comprobar si Yahoo resuelve un ticker | depende del proveedor y hace llamadas potencialmente lentas. |
| `GET` | `/api/instruments/{ticker}` | detalle instrumento + quote | parsing de timestamp afectado por `_parse_date`. |
| `POST` | `/api/instruments` | crear instrumento; normalizar, resolver metadatos, precios | default de currency del request `EUR`; aclarar AUTO vs default. |
| `PUT` | `/api/instruments/{ticker}` | editar datos y a veces renombrar símbolo | `None` no limpia en la mayoría de campos opcionales. |
| `POST` | `/api/instruments/{ticker}/fetch-analysis-price?target_date=...` | recuperar precio de análisis | fallback histórico puede fechar mal un precio actual. |
| `POST` | `/api/instruments/{ticker}/fetch-ytd-price?target_year=...` | recuperar precio de inicio de año | debe persistir la sesión real usada. |
| `POST` | `/api/instruments/resolve-missing-analysis-prices` | completar referencias análisis ausentes | solo activos; reglas de elegibilidad exactas deben conservarse. |
| `POST` | `/api/instruments/resolve-missing-ytd-prices` | completar referencias YTD ausentes | solo activos; depende de mercado/año. |
| `DELETE` | `/api/instruments/{ticker}` | borrar instrumento y cotización | operación destructiva. |
| `POST` | `/api/instruments/{ticker}/refresh` | refresco individual y completar referencias | no sincronizado con lock global. |
| `POST` | `/api/refresh` | refresco masivo por lotes | bloqueo por refresco activo, progreso global. |
| `GET` | `/api/refresh/stream?mode=listen` | SSE para progreso | `trigger` documentado, aparentemente no usado. |
| `GET` | `/api/config` | config y progreso actual | exponer solo lo necesario en despliegue compartido. |
| `POST` | `/api/import/preview` | sube/analiza CSV/XLSX y valida preview | lee todo el archivo; no hay cap de tamaño observado. |
| `POST` | `/api/import/confirm` | persiste instrumentos recibidos | no liga la confirmación a una preview ni repite toda la validación. |
| `DELETE` | `/api/database` | reset completo | backup previo se intenta pero no bloquea el borrado si falla. |
| `GET` | `/api/export/csv` | descarga CSV | el cálculo de objetivo exportado está invertido. |
| `GET` | `/api/export/excel` | descarga XLSX formateado | misma ruta de records que CSV; comprobar fórmulas/datos. |
| `GET` | `/api/export/json` | dump JSON versionado | es el formato de backup estructurado; version `1.0`. |
| `GET` | `/api/backup/download` | snapshot SQLite descargable | no confundir con CSV de instrumentos activos. |
| `POST` | `/api/backup/restore` | restaurar subida JSON o SQLite | requiere prevalidación completa y transacción/swap atómico. |
| `GET` | `/api/backup/list` | listar snapshots locales | solo tiene sentido con almacenamiento local accesible al proceso. |
| `POST` | `/api/backup/restore/{filename}` | restaurar snapshot local | proteger resolución de rutas y autorización si hay acceso remoto. |

### Esquemas/contratos principales del frontend

`frontend/lib/types.ts` define `QuoteStatus`, `Exchange`, `Instrument`, `Quote`, `Position`, respuestas de lista/detalle y requests de crear/actualizar/importar. Es el contrato de tipos de facto. No reemplaza validación en el servidor; por ejemplo, la confirmación de importación utiliza `list[dict]` de Python y el frontend construye un objeto parcial.

Respuesta conceptual de `/api/positions`:

```json
{
  "positions": [
    {
      "id": 1,
      "user_ticker": "MSFT",
      "provider_symbol": "MSFT",
      "exchange": "US",
      "currency": "USD",
      "analysis_date": "2026-01-15",
      "analysis_reference_price": 400.0,
      "start_of_year_date": "2026-01-02",
      "start_of_year_price": 405.0,
      "target_price": 500.0,
      "latest_price": 450.0,
      "previous_close": 445.0,
      "daily_variation": 1.12,
      "daily_variation_valid": true,
      "variation_since_analysis": 12.5,
      "variation_since_analysis_valid": true,
      "ytd_variation": 11.11,
      "ytd_variation_valid": true,
      "decline_to_target": 11.11,
      "decline_to_target_valid": true
    }
  ],
  "count": 1
}
```

El ejemplo anterior es **esquemático** para mostrar campos, no datos devueltos durante esta auditoría.

## 7. Importación, normalización y exportación

### 7.1 Mapeo de columnas (`ingest/columns.py`)

Acepta múltiples cabeceras/sinónimos para ticker, nombre, fecha y precio de análisis, campos YTD, objetivo, divisa, notas y activo. Normaliza acentos y puntuación. `ACTIVO` se mapea intencionadamente a `company_name` en el código: hay que revisar los alias para asegurar que no se confunda cabecera de empresa con flag activo en los archivos habituales.

### 7.2 Parser (`ingest/parser.py`)

- CSV: intenta detección de delimitador coma/punto y coma; admite BOM UTF-8, UTF-8, cp1252 y latin-1; interpreta celdas como texto para evitar inferencias tempranas.
- Excel: lee la primera hoja usando `openpyxl` con `read_only=True`, `data_only=True`.
- El parser menciona extensión `.xls`, pero `openpyxl` no procesa el formato binario antiguo XLS; API limita oficialmente a `.csv` y `.xlsx`.
- La API lee el upload entero a memoria y luego a un tempfile, sin límites explícitos de tamaño.

### 7.3 Normalización (`ingest/normalizer.py`, `core/config.py`)

- Reconoce prefijos tipo `BME:VIS`; detecta sufijos de exchange; utiliza divisa como fallback y para símbolos no cualificados asume mercado US en muchos casos.
- Existe un mapeo amplio de exchanges/sufijos/divisas. Deben preservarse símbolos internacionales (p. ej. `.MC`, `.PA`) y no eliminar sufijos de mercados no estadounidenses.
- Normalizar un ticker no debe reescribir lo que introdujo el usuario: separar siempre `user_ticker` del `provider_symbol` calculado.

### 7.4 Validación e import session (`ingest/validator.py`, `ingest/import_session.py`)

- La validación es mínima: requerir ticker y detectar duplicado con comparación de string sensible a mayúsculas/minúsculas.
- Celdas numéricas/fechas inválidas pueden convertirse en `None` sin generar un error visible suficientemente claro.
- Filas duplicadas pueden mantenerse con warning; si se confirman ambas, la última puede sobrescribir a la primera.
- El confirm endpoint no verifica un identificador de sesión/preview y acepta datos directos del frontend.
- `upsert_instrument` usa `COALESCE` para los campos YTD, pero sustituye con nulos otras referencias. Importar una hoja parcial puede cambiar/corromper datos existentes.
- **Bug UI verificado:** el mapa `instrumentsToCommit` en `frontend/components/ImportView.tsx:108-119` no incluye `start_of_year_date` ni `start_of_year_price`; esos campos se pierden al confirmar una importación desde la interfaz.

### 7.5 Exportadores (`backup/exporters.py`)

Formatos:
- CSV con cabeceras en español y compatibilidad destinada al importador.
- XLSX con formato, anchos y paneles congelados.
- JSON versión `1.0` con instrumentos, datos de quote y timestamps.

Hallazgos:
- `get_export_records(db_path)` abre una conexión al `db_path` indicado, pero los instrumentos/cotizaciones se obtienen con funciones globales que usan la ruta por defecto; el parámetro personalizado no controla realmente la lectura (`exporters.py:55-68`).
- La exportación usa `get_all_instruments()` y por tanto omite `active=0`. Es correcto para “exportar watchlist activa” (README) pero no es un backup completo de todos los instrumentos; mantener separadas las nociones de export de trabajo vs backup restaurable.
- `decline_to_target` se invoca con argumentos invertidos (`exporters.py:77`).
- `quote_timestamp` de salida tabular pasa por `_serialize_date`, lo que acorta el timestamp a fecha; el bloque raw JSON conserva `.isoformat()`.
- `restore_from_json` valida solo que exista la lista `instruments` y ticker no vacío antes del borrado; el resto de tipos/valores puede fallar más tarde.
- `active=bool(item.get("active", True))` interpreta un string no vacío como `True` (incluso el texto `"false"`).
- `target_db_path` solo se usa para crear backup; funciones `wipe_database` y `upsert_instrument` siguen usando conexión global/default. La API puede ocultar este fallo al usar siempre la ruta configurada de entorno.
- Si el JSON es válido a nivel superficial pero contiene un decimal inválido o cotización malformada, el proceso podría fallar después del wipe y dejar datos parciales.

### 7.6 Backup SQLite (`backup/sqlite_backup.py`)

- Usa SQLite backup API para construir snapshot consistente y gestiona carpeta mediante `PORTFOLIOMASTER_BACKUP_DIR` o `backups/` local.
- Rotación de snapshots automáticos: conserva los 10 más recientes.
- Valida `integrity_check` y comprobaciones básicas de la tabla `instruments`/columna `user_ticker`.
- `restore_automatic_backup` constriñe el nombre usando `basename` y extensión `.db`, reduciendo path traversal.
- Validador debería comprobar también tabla `quotes`, columnas críticas, versión de schema y capacidad de apertura con migraciones compatibles.
- Nombre temporal/fecha con granularidad de un segundo puede colisionar si se crean varias copias con misma razón en el mismo segundo; usar UUID/milisegundos para unicidad.
- Algunas rutas de operación continúan aunque el backup previo falle; para un reset/restore destructivo esto debe convertirse en fallo cerrado o confirmación explícita de riesgo.

## 8. Frontend: páginas, estado y componentes

### 8.1 App Router y navegación

- `frontend/app/layout.tsx`: layout raíz, fuentes Geist, metadata y `PortfolioProvider`; el atributo `lang` aparece en inglés aunque la UI es principalmente en español.
- `frontend/app/page.tsx`: dashboard/watchlist; hace carga inicial servidor de posiciones/métricas/config usando `Promise.allSettled` y muestra aviso si backend falla.
- `frontend/app/import/page.tsx` y `app/backup/page.tsx`: rutas para importación y operaciones de backup/export.
- `app/loading.tsx`, páginas loading de import/backup, `app/error.tsx`, `app/not-found.tsx`: estados de carga/error/404 del router.
- `app/globals.css`: estilos globales y utilidades; Tailwind v4.
- `app/sitemap.ts`, `public/sitemap.xml`, `public/robots.txt`, `public/llms.txt`: metadatos de indexación/discovery; si la app sigue privada/local-first, confirmar que no se exponga públicamente información de usuario (actualmente archivos son estáticos y no contienen datos de cartera).

### 8.2 Estado global (`frontend/context/PortfolioContext.tsx`)

- Centraliza `positions`, `metrics`, `config`, `isRefreshing` y progreso de batch.
- Coordina fetching/revalidación, EventSource SSE y polling adaptativo para estado/config.
- Tras eventos por lote vuelve a leer posiciones y métricas; esto mantiene la UI cerca del backend, pero con muchas posiciones/lotes puede multiplicar solicitudes.
- Hay una actualización/fallback por intervalo que refresca estado de UI; no significa por sí misma que solicite un refresco de cotizaciones al proveedor.
- Al migrar hay que preservar identidad de estado entre rutas, evitar refrescos dobles y distinguir “consultar datos” de “provocar refresh a Yahoo”.

### 8.3 Cliente HTTP (`frontend/lib/api.ts`)

- Envoltorio tipado para CRUD, métricas, refresh, SSE, import/export, restore y config.
- Usa `process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'` en `frontend/lib/api.ts:25-26`.
- `.env.example` documenta en cambio `API_BASE_URL`; variable no usada por ese cliente.
- `frontend/next.config.ts` define proxy rewrite `/api/:path*` a `localhost:8000`, pero como el cliente construye URLs absolutas hacia el backend, ese rewrite no es el camino habitual de llamadas de `lib/api.ts`.
- Esto funciona en setup local separado si navegador accede al backend por localhost; no es una configuración adecuada de despliegue en la que navegador/servidor remotos deben hablar por URL propia/proxy seguro.
- Corregir antes de migrar: unificar variable base y preferir rutas relativas `/api/...` detrás de un reverse proxy/BFF si el destino es web desplegada.

### 8.4 Dashboard (`WatchlistContent.tsx`, `WatchlistTable.tsx`, `MetricCards.tsx`)

- `WatchlistContent.tsx`: compone indicadores + tabla + modal de alta/edición; gestiona feedback/estado de operaciones y query params para add/edit.
- `WatchlistTable.tsx` (~2.5k líneas): tabla TanStack, filtros, orden, resize de columnas, notas/fechas inline, refresh individual/global, resolve missing refs, delete/reset, modales y preferencias persistidas en localStorage.
- Preferencias de browser incluyen `portfoliomaster_row_height`, `portfoliomaster_table_sorting`, `portfoliomaster_column_sizing`, `portfoliomaster_toolbar_config`. Son preferencias locales, no datos de negocio; si se migra a otro frontend, decidir si mantener claves/importarlas.
- Altura fila min/default/max reportada en código: 32/48/88 px.
- Hay una lógica grande concentrada en un componente; dividir en tabla presentacional, hooks de persistencia de preferencias, hooks de operaciones y celdas editables disminuye riesgo.
- `MetricCards.tsx`: cuatro KPI básicos (total, mayor ganador, mayor perdedor, variación promedio); puede tener fallback de cálculo en cliente. La fuente autoritativa debería ser backend y las métricas de cliente solo tener propósito visual claramente separado.

### 8.5 Formulario de instrumento (`ManualEntryModal.tsx`)

- Un modal maneja creación y edición, comprobación de Yahoo, precio manual, datos de análisis/YTD, objetivo/notas y renombrado de ticker.
- En edición, cambios de ticker pueden disparar sincronización/resolución de nombre, divisa, mercado, cotización y referencias: tratarlo como workflow de varias operaciones, no un mero rename en DB.
- El flujo “guardar + actualizar fecha” puede asignar la cotización más reciente como referencia de análisis; al migrar debe preservar exactamente la intención y la referencia temporal resultante.
- Revisar campos vacíos/null con el backend: un UI que envía null no garantiza que la API los borre.

### 8.6 Importación (`ImportView.tsx`)

- Solo permite `.csv` y `.xlsx`, presenta previsualización, errores, unresolved/warnings y confirmación.
- Invoca preview y confirm del backend y luego recarga context/router.
- Omite los dos campos YTD en el payload final; hallazgo de prioridad alta.
- La importación debe tener límites de archivo, validación por campo, preview ligado a hash/token/session, política explícita de duplicados y transacción atómica.

### 8.7 Backup/export (`BackupExportView.tsx`, `BackupExportModal.tsx`)

- Dos interfaces distintas exponen exportación CSV/XLSX/JSON, descarga de DB, lista de snapshots locales y restore de JSON/SQLite.
- Modal y página contienen lógica repetida: riesgo de que arreglos de validación, estados y UX se apliquen en un lugar y no en el otro.
- Especificar por separado: **export de watchlist activa** para trabajar en Excel y **backup completo** para restaurar exactamente el estado; no confundir semántica.

### 8.8 Navegación (`HeaderNav.tsx`)

- Enlaces a watchlist/añadir/import/export; emite el evento cliente `portfoliomaster:open-add` y navega con `/?add=1` para activar modal de alta.
- Al migrar rutas y modales, mantener enlaces profundos (`?add=1`, `?edit=TICKER`) o sustituirlos con equivalencia documentada.

## 9. Configuración, ejecución y dependencias

### Python (`requirements.txt`, `pyproject.toml`, `pytest.ini`, `run.bat`, `.env.example`)

- Dependencias: `pandas`, `openpyxl`, `yfinance`, `python-dateutil`, `fastapi`, `uvicorn[standard]`, `python-multipart`, `python-dotenv`; testing: `pytest`, `pytest-cov`, `pytest-timeout`, `httpx`.
- `pyproject.toml` describe empaquetado/dependencias y extras de desarrollo; mantener sincronizados los requisitos si se cambia la instalación.
- `pytest.ini` pone `--timeout=10` en opciones por defecto; requiere `pytest-timeout` instalado. Si el entorno omite extras de test, pytest no arranca con esa configuración.
- `.env.example` trae `PORTFOLIOMASTER_DB_PATH`, `REFRESH_INTERVAL_SECONDS`, `REFRESH_BATCH_SIZE` y `API_BASE_URL`; la variable `API_BASE_URL` no coincide con la leída por frontend.
- `REFRESH_BATCH_SIZE` de ejemplo es 25, aunque el comentario dice default 10; el default de runtime de configuración es 10.
- `run.bat`: lanzador de Windows que crea entorno virtual/instala dependencias y `node_modules` cuando faltan, y ejecuta backend/frontend en puertos locales. No hay lanzador equivalente multiplataforma en los ficheros fuente enumerados.
- `.gitignore` y `frontend/.gitignore`: revisar exclusión de DB/backups/.env/node_modules/build; no migrar secretos, ficheros locales o caches.

### Frontend (`frontend/package.json`, lockfile y config)

- Next `16.4.1`, React/React DOM `19.3.0`, TanStack Table, Lucide React, Tailwind CSS `4`, TypeScript 5, ESLint 9, `tsx` para los scripts de verificación.
- `npm run test` encadena 15 scripts `frontend/scripts/verify_*.mts`. Son verificaciones fuente-basadas con búsqueda de texto/regex y algunas simulaciones de funciones; no sustituyen pruebas de componentes React, navegador ni contratos contra FastAPI.
- `next.config.ts` usa rewrites del prefijo `/api`; el cliente actual usa URL absoluta, por lo que hay inconsistencia de configuración.
- `tsconfig.json`, `eslint.config.mjs` son configuración, no reglas de negocio. `package-lock.json` fija árbol de dependencias; debe regenerarse mediante npm de forma determinista si cambia `package.json`.

## 10. Seguridad, privacidad y modelo de amenaza

El proyecto afirma ser local-first y no enviar cartera a un backend cloud. Eso es un modelo de despliegue, no una garantía de seguridad automática.

- No hay autenticación/autorización en las rutas observadas. Es aceptable solo en un proceso estrictamente local y restringido a loopback; no exponer FastAPI tal cual a una red o dominio público.
- `GET /api/backup/list`, descargas, restore y `DELETE /api/database` son accesibles al mismo perímetro sin sesión.
- Los archivos subidos se leen completos y no hay límite explícito de bytes/filas/tiempo de parseo.
- Las operaciones destructivas intentan backups, pero algunos flujos registran warning y continúan si el backup falla; esto no alcanza para garantizar recuperabilidad.
- CORS autoriza `http://localhost:3000`, con credentials. Ajustarlo cuidadosamente para el origen real; no confundir CORS con autenticación.
- Un despliegue remoto requiere auth, TLS, protección de CSRF si aplica, rate limit, límite de archivo, logs auditables, autorización para export/restore/reset, secretos de proveedor fuera del frontend y un almacenamiento privado con backups probados.
- Validar ZIP/JSON/CSV/XLSX como datos no confiables: evitar archivos comprimidos anómalos, celdas masivas, fórmulas/CSV injection al exportar si se abre en hojas de cálculo, y fallos parciales de restauración.

## 11. Pruebas y límites de validación ejecutada

### Resultados de esta auditoría

- **25 tests de núcleo pasaron** al ejecutar: `pytest -o addopts='' -q tests/test_calculations.py tests/test_db.py tests/test_ingest.py tests/test_backup.py tests/test_batch_runner.py tests/test_providers.py` (0.71 s en este entorno).
- Suite Python completa: **no recopiló** tres módulos por falta de `yfinance` en el entorno (`tests/test_refresh_functionality.py`, `backend/tests/test_api.py`, `backend/tests/test_backup_api.py`). Esto es fallo de dependencia de ejecución, no evidencia de tests funcionales fallidos.
- `pytest.ini` contiene `--timeout=10`; fue necesario vaciar `addopts` porque `pytest-timeout` tampoco estaba instalado en este entorno.
- Entorno Node mostró Node `v22.16.0` y npm `10.9.2`, pero `frontend/node_modules` no está presente. No se ejecutaron `npm test`, `npm run lint` ni `npm run build` para no instalar paquetes sin hacer una validación de red/dependencias controlada.
- No se ejecutaron llamadas de red reales a Yahoo Finance, prueba del scheduler a lo largo del tiempo, prueba de múltiples clientes SSE, navegador, carga grande, ni roundtrip real de export/import para XLSX/JSON.

### Calidad actual de pruebas

- Los tests Python de núcleo cubren cálculos, SQLite, importación y backup, lotes y mock provider; deben ampliarse con los fallos detectados.
- `backend/tests/test_api.py` y `test_backup_api.py` proporcionan tests de API cuando se instalan dependencias.
- Los scripts `frontend/scripts/verify_*.mts` tienden a verificar fragmentos fuente y presencia de contratos; no montan realmente React ni sustituyen E2E. Pueden pasar aunque haya un bug de lógica que no esté codificado en la aserción.

### Tests de regresión que deben añadirse sí o sí

1. Los mismos inputs producen la misma `decline_to_target` en cálculo puro, `/api/positions`, CSV, XLSX y JSON.
2. CSV/XLSX con `start_of_year_price/date` realiza preview → confirm → consulta y preserva los dos campos.
3. Import JSON con `target_db_path` personalizado solo modifica ese fichero, no el DB default.
4. Restore con datos inválidos deja DB original intacta; restore válido es atómico.
5. Fallo Yahoo tras una cotización válida conserva precio/timestamp previo y registra error aparte.
6. Pedir precio histórico para una fecha sin datos no acepta `fast_info` actual con fecha antigua; se valida `actual_dt`.
7. `None` explícito borra un campo nullable cuando el contrato indica “clear”; campo omitido no cambia el valor. Cubrir target, analysis price/date, YTD price/date y comentario.
8. Activos/inactivos: `/api/positions`, `/api/instruments`, metrics, refresh y export concuerdan con una política documentada.
9. Dos user tickers con mismo provider symbol refrescan correctamente ambos instrumentos.
10. Timestamps SQLite se leen como `datetime` válidos, con política timezone clara.
11. Dos solicitudes concurrentes de refresco individual/masivo no se pisan; SSE siempre acaba o se reconecta con estado identificable.
12. Duplicados de ticker son case-insensitive; validación numérica y de fecha devuelve errores claros antes de persistir.
13. CSV con fórmulas/valores que empiezan por `=`, `+`, `-`, `@` se exporta sin riesgo de ejecución en Excel cuando aplique.
14. Límite de tamaño/filas para uploads, error HTTP comprensible y ausencia de escritura parcial.

## 12. Riesgos y acciones priorizadas

| Prioridad | Hallazgo | Evidencia | Tratamiento recomendado |
|---|---|---|---|
| P0 | Precio histórico puede ser actual con fecha antigua | `backend/api/main.py:985-1017`; `yahoo_adapter.py:346-378` | Eliminar fallback a cotización actual para fechas pasadas o devolver fecha real y obligar a confirmar diferencia. |
| P0 | Restauración JSON no atómica | `exporters.py:325-394+` | Validar todo, restaurar en BD temporal y hacer swap atómico; mantener backup previo verificable. |
| P0 | `target_db_path` ignorado al restaurar JSON | `exporters.py:319-368` | Inyectar repositorio/conexión destino en todas las operaciones. |
| P0 | Se puede borrar último precio bueno al fallar proveedor | `repository.py:131-163`; `main.py:1422-1431` | Preservar precio bueno, almacenar status/error por intento. |
| P1 | Export de objetivo invierte argumentos | `exporters.py:77` | Corregir y test de paridad con API. |
| P1 | UI import omite las dos referencias YTD | `ImportView.tsx:108-119` | Incluir campos, test de roundtrip. |
| P1 | Campos null no se limpian en edición | `backend/api/main.py:861+`; cliente de edición | Definir semántica PATCH/tristate y tests de campo omitido vs `null`. |
| P1 | `/api/positions` lista inactivos, otras rutas solo activos | `main.py:356-452`; `repository.py:166-174` | Una sola regla activa/inactiva por caso de uso; contar y exportar de forma explícita. |
| P1 | Exportador ignora `db_path` real | `exporters.py:55-68` | Usar la conexión destino en todas las consultas o retirar el argumento. |
| P1 | Confirmación/importación no atómica ni validación completa | `main.py:1656-1718` | Esquemas request fuertes, token preview, validación server-side y transacción única. |
| P1 | Sin auth / límites de upload si se despliega remotamente | `backend/api/main.py` global; upload lines 1623-1645 | Limitar al loopback o añadir controles antes de cualquier exposición pública. |
| P2 | Parse de quote timestamps con `_parse_date` | `repository.py:219-229, 251-265` | `parse_datetime` distinto de `parse_date`. |
| P2 | Refresh de proveedor símbolo duplicado solo actualiza una fila | `main.py` construcción de `instrument_map` + batch callback | Agrupar IDs por provider symbol y aplicar resultado a todos. |
| P2 | Refresco individual no usa lock global | `main.py` ruta refresh individual y `_execute_refresh_all` | Mutex/lock por instrumento o cola única de jobs. |
| P2 | Config frontend nombrada distinto | `.env.example:13-15`; `frontend/lib/api.ts:25-26`; `next.config.ts` | Definir una única base URL y elegir proxy/BFF. |
| P2 | Validaciones de cálculo inconsistentes | `core/calculations.py` | Contratos de inputs, rangos plausibles y tests para cero/negativo/NaN. |
| P2 | Sin versionado formal schema DB | `db/connection.py:24-70` | Migraciones numeradas, copia antes de upgrade y downgrade/rollback plan. |
| P2 | Pruebas frontend source-based y componentes grandes | `frontend/scripts/verify_*.mts`, `WatchlistTable.tsx` | Unit tests de funciones, React Testing Library y E2E de workflows críticos. |
| P3 | constantes batch/retry sin aplicar uniformemente | `core/config.py`, `refresh/batch_runner.py` | Una sola configuración aplicada y documentada. |
| P3 | `RefreshRun` definido pero sin persistencia útil | `core/models.py` | Decidir si eliminarlo o convertirlo en auditoría/job record. |

## 13. Plan de migración recomendado

No iniciar con una reescritura de pantalla ni con traducción archivo-a-archivo. La unidad de migración debe ser **comportamiento y contrato**, con golden tests obtenidos del sistema original.

### Fase 0 — Congelar y caracterizar el origen

1. Guardar commit/hash y ZIP auditado, versión de Python/Node, configuración no secreta y un backup de prueba anonimizado.
2. Obtener fixtures para: ticker US, ticker español `.MC`, francés `.PA`, ticker no resuelto, instrumento sin quote, cotización retrasada, referencias vacías, campos target/YTD y comentario largo.
3. Guardar respuestas actuales de API y archivos exportados con valores sintéticos conocidos; corregir primero los tests de caracterización para capturar comportamiento intencional y etiquetar los bugs conocidos.
4. Diferenciar “compatibilidad necesaria” de “bug que no se debe copiar”. Documentar explícitamente cada desviación.

### Fase 1 — Modelo neutral del dominio

Definir modelos/contratos independientes del framework para `Instrument`, `QuoteSnapshot/QuoteAttempt`, `RefreshRun`, `ImportPreview`, `BackupManifest`. Fijar política de nullability, redondeo, timezone, estados de cotización y regla de símbolo. Centralizar fórmulas en un solo servicio.

### Fase 2 — Datos y migración de SQLite

1. Especificar esquema destino incluyendo campos y restricciones.
2. Exportar e importar por filas, preservando `user_ticker`, `provider_symbol`, exchange/currency, fechas, precios Decimal, notas, active, quote/status/timestamps y claves de relación.
3. Validar conteo, claves únicas, pares fecha/precio, nullability y checksums/estadísticas antes de cambiar de base.
4. Hacer dry-run y no destructivo; mantener backup de origen inmutable; ejecutar swap solo al pasar validación.
5. Mantener por separado datos de trabajo exportados y backup completo restaurable.

### Fase 3 — Proveedor y actualización

1. Crear interfaz de proveedor: `fetch_latest(symbols)`, `fetch_historical(symbol, target_date)`, `resolve_metadata(symbol)` con contrato explícito de timestamp y moneda.
2. Dejar los fallos como eventos de intento, no sustituir precio bueno por `None`.
3. Evitar presentar datos diarios como cotización en tiempo real; el texto UI debe indicar granularidad, fuente y retraso real.
4. Garantizar deduplicación por provider symbol, idempotencia, mutex/queue de refresh y estado por `run_id`.

### Fase 4 — API/BFF

Preservar rutas o proporcionar adaptador y contrato de compatibilidad. Versionar APIs si cambia semántica. Tipar todos los requests; validar la confirmación de importación también en servidor. Inyectar repositorios con target explícito y ejecutar transacciones en el servicio de aplicación, no mediante funciones globales que reabren conexiones.

### Fase 5 — Frontend

Recrear las tres rutas principales, el estado compartido, tabla y preferencias, gestión de modal, import preview/confirm, export/restore, feedback de error y progreso refresh. No es necesario copiar la estructura de componentes gigantes, pero sí su funcionalidad documentada. Usar pruebas que validen interacción real y accesibilidad.

### Fase 6 — Pruebas de paridad y cutover

- Ejecutar tests Python, tests UI, API contract tests y E2E.
- Hacer roundtrip con datasets sintéticos y copia de una DB real anonimizada.
- Comparar output legacy vs nuevo (con excepciones documentadas por bugs corregidos).
- Ensayar restore, fallo de proveedor, red desconectada, actualización concurrente y reinicio a mitad de refresh.
- Solo después de paridad y restore probado, cambiar el punto de entrada y conservar procedimiento de rollback.

## 14. Inventario archivo por archivo

El ZIP contiene **121 entradas en el listado, incluidas carpetas; 99 son archivos no-directorio**. El inventario complementario `PortfolioMaster_File_Inventory.md` enumera los 99 archivos con número de líneas/bytes y símbolos top-level cuando se pueden extraer. El número de líneas corresponde a la versión auditada y puede variar si se aplican cambios.

### Raíz y ejecución

| Archivo | Función / qué conservar |
|---|---|
| `.env.example` | Variables runtime; corregir la variable URL inconsistente, aclarar default batch 10 vs ejemplo 25. |
| `.gitignore` | Exclusiones de entorno/artefactos locales. Verificar que DB, backups y `.env` queden fuera del control de versiones. |
| `LICENSE` | Licencia del proyecto; conservar sus términos y atribución al migrar/redistribuir. |
| `README.md` | Documenta features, setup, arquitectura, rutas API, pruebas y disclaimer local-first. Comparar promesas con comportamiento real. |
| `pyproject.toml` | Metadata/config del paquete Python, deps y extras. |
| `pytest.ini` | Config de pytest; `--timeout=10` requiere `pytest-timeout`. |
| `requirements.txt` | Dependencias Python runtime/test. Mantener sincronizado con `pyproject.toml`. |
| `run.bat` | Arranque local Windows de backend y frontend; instalación condicional del entorno. |

### Backend de API

| Archivo | Función / qué conservar |
|---|---|
| `backend/__init__.py` | Marca paquete Python. |
| `backend/api/__init__.py` | Inicialización del subpaquete API. |
| `backend/api/main.py` | Aplicación FastAPI, 27 rutas incl. `/`, startup/scheduler, CRUD, Yahoo/histórico, SSE, import/export y backups. Alto riesgo por concentración de responsabilidades. |
| `backend/tests/test_api.py` | Tests de rutas y workflows; no pudo recopilarse en este entorno por falta de `yfinance`. Ejecutar en entorno completo. |
| `backend/tests/test_backup_api.py` | Tests API de backup/restore; mismo blocker de dependencia. |

### Frontend app router

| Archivo | Función / qué conservar |
|---|---|
| `frontend/AGENTS.md` | Instrucciones de trabajo para agentes sobre frontend; leer antes de generar cambios automatizados. |
| `frontend/README.md` | Instrucciones específicas frontend y scripts. |
| `frontend/app/layout.tsx` | Layout raíz, metadata, fuentes y provider global. Revisar `lang="en"` frente a la UI española. |
| `frontend/app/page.tsx` | Dashboard de watchlist y carga inicial. |
| `frontend/app/globals.css` | Base visual / estilos globales, Tailwind. |
| `frontend/app/loading.tsx` | Skeleton/carga global App Router. |
| `frontend/app/error.tsx` | Límite de error de página. |
| `frontend/app/not-found.tsx` | Página 404. |
| `frontend/app/favicon.ico` | Icono de app; recurso binario. |
| `frontend/app/import/page.tsx` | Ruta/vista de importación. |
| `frontend/app/import/loading.tsx` | Estado de carga de import. |
| `frontend/app/backup/page.tsx` | Ruta de backup/export. |
| `frontend/app/backup/loading.tsx` | Estado de carga de backup. |
| `frontend/app/sitemap.ts` | Generación de sitemap desde Next. Comparar con `public/sitemap.xml`. |

### Componentes frontend

| Archivo | Función / qué conservar |
|---|---|
| `frontend/components/HeaderNav.tsx` | Navegación, deep links add/edit y evento cliente para abrir alta. |
| `frontend/components/WatchlistContent.tsx` | Composición del dashboard, KPIs, tabla, modal y mensajes. |
| `frontend/components/WatchlistTable.tsx` | Tabla principal TanStack (~2.5k líneas): filtros/sort/resize, inline editing, preferencias, refresh, borrado y toolbar. Ideal dividir en migración. |
| `frontend/components/MetricCards.tsx` | KPIs total/top winner/top loser/average change; evitar divergencia con métricas del backend. |
| `frontend/components/ManualEntryModal.tsx` | Modal de alta/edición, comprobación Yahoo, manual quote, sincronización al renombrar y acción de actualizar referencia. |
| `frontend/components/ImportView.tsx` | Selección de archivo, preview/confirm, errores, refresh del estado. Omite dos campos YTD al confirmar. |
| `frontend/components/BackupExportView.tsx` | Vista completa para descargar/exportar/restore/listar backups. |
| `frontend/components/BackupExportModal.tsx` | Variante modal de backup/export con lógica duplicada de la vista completa. |
| `frontend/components/README.md` | Documentación específica de componentes. |

### Estado y contrato frontend

| Archivo | Función / qué conservar |
|---|---|
| `frontend/context/PortfolioContext.tsx` | Fuente de estado global; carga, polling, SSE, progreso y refrescos. |
| `frontend/lib/api.ts` | Cliente HTTP; es la lista práctica de operaciones que frontend consume. Corrige API base URL antes de desplegar. |
| `frontend/lib/types.ts` | Contratos TypeScript que corresponden a modelos Python y respuesta FastAPI. Mantener paridad. |
| `frontend/next.config.ts` | Proxy rewrites `/api/*` al backend local; actualmente inconsistente con URL absoluta de cliente. |
| `frontend/tsconfig.json` | Opciones TypeScript/paths. |
| `frontend/eslint.config.mjs` | Configuración lint. |
| `frontend/package.json` | Dependencias y scripts `dev/build/start/lint/test`. |
| `frontend/package-lock.json` | Lockfile npm; generado, no lógica. Mantener reproducible/regenerarlo si cambia manifiesto. |

### Scripts de verificación del frontend

Todos son tests/verificaciones fuente-basados en TypeScript/MTS (se ejecutan por el script `npm test`). No equivalen a E2E de navegador; leer sus assertions, no dar por probado lo que no asertan.

| Archivo | Enfoque inferido por nombre y contenido |
|---|---|
| `frontend/scripts/verify_analysis_date_column.mts` | Columna/fecha de análisis. |
| `frontend/scripts/verify_api_cache.mts` | Cache del cliente API. |
| `frontend/scripts/verify_api_client.mts` | Funciones/contratos del cliente API. |
| `frontend/scripts/verify_backup_export.mts` | Controles de backup/export. |
| `frontend/scripts/verify_batch_auto_sync.mts` | Sincronización tras batches de refresh. |
| `frontend/scripts/verify_phase3.mts` | Verificaciones históricas de fase 3. |
| `frontend/scripts/verify_phase4.mts` | Verificaciones históricas de fase 4. |
| `frontend/scripts/verify_phase5.mts` | Verificaciones históricas de fase 5. |
| `frontend/scripts/verify_phase6.mts` | Verificaciones históricas de fase 6. |
| `frontend/scripts/verify_phase7.mts` | Verificaciones históricas de fase 7. |
| `frontend/scripts/verify_portfolio_context.mts` | Estado global y contexto. |
| `frontend/scripts/verify_responsive_headers_and_row_height.mts` | Headers responsive y altura de fila. |
| `frontend/scripts/verify_save_and_update_analysis_date.mts` | Guardado + actualización de fecha de análisis. |
| `frontend/scripts/verify_toolbar_and_backup_tab.mts` | Configuración de toolbar y pestaña backup. |
| `frontend/scripts/verify_watchlist_fixes.mts` | Regresiones generales de tabla/watchlist. |

### Recursos públicos

| Archivo | Función / qué conservar |
|---|---|
| `frontend/public/file.svg` | Asset SVG genérico, probablemente boilerplate/no core. |
| `frontend/public/globe.svg` | Asset SVG genérico, probablemente boilerplate/no core. |
| `frontend/public/next.svg` | Asset de Next.js; comprobar si está referenciado. |
| `frontend/public/vercel.svg` | Asset Vercel; comprobar si está referenciado. |
| `frontend/public/window.svg` | Asset genérico; comprobar si está referenciado. |
| `frontend/public/robots.txt` | Directivas de robots estáticas. |
| `frontend/public/sitemap.xml` | Sitemap estático; revisar duplicación con `app/sitemap.ts`. |
| `frontend/public/llms.txt` | Texto de descubrimiento para LLMs; no debe incluir datos personales. |

### Núcleo Python: paquete y modelos

| Archivo | Función / qué conservar |
|---|---|
| `src/portfoliomaster/__init__.py` | Inicialización/metadata del paquete. |
| `src/portfoliomaster/core/__init__.py` | Paquete de dominio. |
| `src/portfoliomaster/core/models.py` | `Instrument`, `Quote`, estados, exchanges, freshness config y resultados. Base de contrato de dominio. |
| `src/portfoliomaster/core/calculations.py` | Fórmulas puras Decimal/validity flags; golden tests imprescindibles. |
| `src/portfoliomaster/core/config.py` | Variables de entorno, exchanges, divisas, suffixes, lotes, intervalos y freshness por mercado. Centralizar tras migración. |

### Persistencia

| Archivo | Función / qué conservar |
|---|---|
| `src/portfoliomaster/db/__init__.py` | Paquete de persistencia. |
| `src/portfoliomaster/db/connection.py` | Ruta SQLite, adapters Decimal/date/datetime, creación de tablas y migración manual YTD. |
| `src/portfoliomaster/db/repository.py` | CRUD/upserts, mapping de rows a modelos, conversión de valores. Contiene bug de parse de timestamp y riesgo de borrar datos por null. |

### Ingesta

| Archivo | Función / qué conservar |
|---|---|
| `src/portfoliomaster/ingest/__init__.py` | Paquete importador. |
| `src/portfoliomaster/ingest/columns.py` | Alias de cabeceras y mapping de columnas. |
| `src/portfoliomaster/ingest/parser.py` | Decodificación CSV/XLSX y carga a DataFrame. |
| `src/portfoliomaster/ingest/normalizer.py` | Normalización de prefijos/sufijos de ticker y exchange. |
| `src/portfoliomaster/ingest/validator.py` | Reglas ligeras de validación. Mejorar antes de fiarse en migración. |
| `src/portfoliomaster/ingest/import_session.py` | Coordina parser, mapping, normalización, warnings y construcción de instrumentos. |

### Proveedores y refresco

| Archivo | Función / qué conservar |
|---|---|
| `src/portfoliomaster/providers/__init__.py` | Paquete de proveedores. |
| `src/portfoliomaster/providers/base.py` | Interfaz base de proveedor. |
| `src/portfoliomaster/providers/mock_provider.py` | Proveedor determinista para tests; clave para no usar red en tests. |
| `src/portfoliomaster/providers/yahoo_adapter.py` | Adaptador real yfinance, fallback de cotización/histórico, status freshness. Históricos y timestamp necesitan corrección. |
| `src/portfoliomaster/refresh/__init__.py` | Paquete de refresco. |
| `src/portfoliomaster/refresh/batch_runner.py` | Partición de batch, retry, callback/progreso. |

### Backup/exportación

| Archivo | Función / qué conservar |
|---|---|
| `src/portfoliomaster/backup/__init__.py` | Paquete de backups. |
| `src/portfoliomaster/backup/sqlite_backup.py` | Snapshot SQLite, validación de archivo, restore, rotación y ruta de snapshots. |
| `src/portfoliomaster/backup/exporters.py` | Export CSV/XLSX/JSON y restore JSON; bugs de orden de parámetros, DB target y atomicidad. |

### Tests Python

| Archivo | Función / qué conservar |
|---|---|
| `tests/conftest.py` | Fixtures y ajuste del entorno para tests. Revisar cómo fija ruta de SQLite/limpieza. |
| `tests/test_calculations.py` | Pruebas de fórmulas y validez. Ampliar con negativos/no finitos/paridad export. |
| `tests/test_db.py` | Pruebas de repositorio/esquema. Añadir parse datetime, FK y no-borrado por null. |
| `tests/test_ingest.py` | Parser/mapping/validación/normalización. Añadir duplicados case-insensitive, celdas inválidas, YTD UI roundtrip. |
| `tests/test_backup.py` | Tests de backup/export JSON y restauración. Añadir `target_db_path`, atomicidad y valores malformados. |
| `tests/test_batch_runner.py` | Batch/callback/reintentos. |
| `tests/test_providers.py` | Tests básicos a proveedor mock/abstracción, separados del proveedor Yahoo. |
| `tests/test_refresh_functionality.py` | Tests de YahooAdapter y refresco; no pudo recopilarse por `yfinance` ausente. |
| `backend/tests/test_api.py` | Contratos de API y flujos principales; no pudo recopilarse por `yfinance` ausente. |
| `backend/tests/test_backup_api.py` | Rutas API de backup/restore; blocker de `yfinance` en import de app. |

El inventario archivo-por-archivo incluye también configuración, lockfile, tests, SVG/robots/sitemap y los archivos `__init__.py`; úsalo junto con esta sección para verificar que el agente no omita una parte del origen.

### Artefactos que no se deben migrar como código funcional

- Directorios `__pycache__`, `.pytest_cache`, `frontend/node_modules`, `.next`, `dist`, logs, archivos temporales, DB local, backups y cualquier `.env` real son artefactos/estado de máquina, no fuentes de negocio. Algunos caches de Python aparecieron en el directorio descomprimido durante la propia ejecución de tests; no forman parte de las fuentes que hay que portar.
- `frontend/package-lock.json` sí se conserva como lockfile de dependencias, aunque no se reimplementa.
- `LICENSE` y la atribución no son funcionalidad, pero sí requisitos de distribución.

## 15. Instrucción final para el agente de migración

Antes de tocar código, el agente debe leer este dossier, `README.md`, `frontend/AGENTS.md`, los modelos/cálculos y los tests. Después debe producir su propio inventario de archivos verificados (no solo por nombre), mapa de llamadas, esquema actual, OpenAPI/contratos reales y un registro de desviaciones. No debe empezar una reescritura masiva sin una decisión explícita sobre destino (hosting, si seguirá local-first, si habrá multiusuario y qué base de datos se usará). Si el usuario aún no lo decidió, presentar recomendación y supuestos antes de convertirlos en arquitectura.

**Criterio de aceptación clave:** el producto migrado conserva datos, referencias de fecha/precio, símbolos internacionales, estados de freshness, notas y todas las operaciones de usuario; no replica los bugs P0/P1 indicados, y las correcciones quedan documentadas y cubiertas por tests.
