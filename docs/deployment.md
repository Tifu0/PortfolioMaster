# 🚀 Guía de Despliegue en Producción — PortfolioMaster (100% Plan Gratuito)

Esta guía paso a paso está diseñada para desplegar **PortfolioMaster** desde cero utilizando únicamente los **planes gratuitos** (*Free Tiers*) de las plataformas, sin necesidad de introducir tarjetas de crédito.

---

## 🏗️ Arquitectura del Despliegue

```
┌────────────────────────────────┐         ┌────────────────────────────────┐
│      VERCEL (Plan Hobby)       │         │       RENDER (Plan Free)       │
│    Frontend: Next.js 16        │ ──────> │      Backend: FastAPI          │
│   (https://tu-app.vercel.app)  │  HTTPS  │ (https://tu-app.onrender.com)  │
└────────────────────────────────┘         └────────────────────────────────┘
                 │                                         │
                 │              ┌──────────────────────────┘
                 ▼              ▼
     ┌───────────────────────────────────────┐
     │         SUPABASE (Plan Free)          │
     │  - Base de Datos PostgreSQL           │
     │  - Autenticación de Usuarios (JWT)   │
     │  - Row Level Security (RLS)           │
     └───────────────────────────────────────┘
```

El despliegue debe realizarse en un orden estricto porque cada servicio depende del anterior:
1. **Supabase**: Proporciona la base de datos y la autenticación (necesario tanto para el backend como para el frontend).
2. **Render**: Aloja el backend FastAPI y genera su URL pública (necesaria para el frontend).
3. **Vercel**: Aloja el frontend Next.js y genera su dominio público.
4. **CORS en Render**: Conecta el dominio final de Vercel con el backend de Render.

---

## 📋 Fase 0: Creación de Cuentas Gratuitas

Si aún no tienes cuentas, créalas usando tu cuenta de **GitHub** (esto facilita la vinculación automática de repositorios):

1. **GitHub**: Asegúrate de tener tu repositorio con el código subido en la rama `main` (por ejemplo: `https://github.com/TuUsuario/PortfolioMaster`).
2. **Supabase**: Regístrate gratis en [supabase.com](https://supabase.com) haciendo clic en **"Start your project"** y autenticándote con GitHub.
3. **Render**: Regístrate gratis en [render.com](https://render.com) seleccionando **"Sign up with GitHub"**.
4. **Vercel**: Regístrate gratis en [vercel.com](https://vercel.com) seleccionando **"Sign Up"** -> **"Hobby (Free)"** y continuando con GitHub.

---

## 🗄️ Fase 1: Configurar la Base de Datos y Auth en Supabase

Supabase nos ofrece una base de datos PostgreSQL completa y servicio de autenticación gratis.

### 1.1 Crear el Proyecto
1. En el panel de Supabase ([database.new](https://database.new)), haz clic en **"New Project"**.
2. Rellena los datos:
   - **Name**: `portfoliomaster-db`
   - **Database Password**: Genera una contraseña segura y **guárdala bien** (la necesitarás para la URL de conexión).
   - **Region**: Elige una región cercana (por ejemplo: `Central EU (Frankfurt)` o `West EU (London)`).
   - **Pricing Plan**: `Free` ($0/month).
3. Haz clic en **"Create new project"** y espera ~2 minutos a que se aprovisione.

### 1.2 Ejecutar el Script de la Base de Datos
PortfolioMaster ya incluye todo el esquema listo en el archivo `SQL_supabase.txt` (tablas, índices, funciones, triggers anti-spam y políticas de seguridad RLS).

1. En el menú lateral izquierdo de Supabase, entra en **SQL Editor**.
2. Haz clic en **"New query"**.
3. Abre el archivo [`SQL_supabase.txt`](../SQL_supabase.txt) de este repositorio, copia **todo su contenido** y pégalo en el editor de Supabase.
4. Haz clic en el botón verde **"Run"** (o presiona `Ctrl + Enter`).
5. Debe mostrar el mensaje: `Success. No rows returned`. Con esto, las tablas `market_quotes`, `user_instruments`, `refresh_runs`, vistas y permisos quedan creados.

### 1.3 Obtener las Credenciales de Supabase
Ve al icono de engranaje ⚙️ **Project Settings** (abajo a la izquierda):

1. **URL del Proyecto y Llave Anónima:**
   - Ve a **API** en el menú de ajustes.
   - Copia **Project URL** (ej: `https://abcdefghij.supabase.co`).
   - Copia **Project API keys -> `anon` / `public`** (ej: `eyJh...`).
2. **JWT Secret (para verificar tokens en FastAPI):**
   - En la misma página de **API**, baja hasta la sección **JWT Settings**.
   - Haz clic en el botón para ver o copiar el **JWT Secret**.
3. **URL de Conexión a la Base de Datos (Pooler Supavisor - Puerto 6543):**
   - Ve a **Database** en el menú de ajustes de Supabase.
   - En la sección **Connection string**, selecciona la pestaña **URI**.
   - Marca la casilla **"Display connection pooler"** y selecciona el modo **"Transaction"** (puerto `6543`).
   - La cadena tendrá este aspecto:
     ```
     postgresql://postgres.[TU-REF]:[TU-CONTRASEÑA]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
     ```
   - Reemplaza `[TU-CONTRASEÑA]` con la contraseña que elegiste al crear el proyecto.
   - Para SQLAlchemy/FastAPI, usa el driver `postgresql+psycopg://`:
     ```
     postgresql+psycopg://postgres.[TU-REF]:[TU-CONTRASEÑA]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
     ```
   - *Nota de compatibilidad:* El backend de PortfolioMaster configura automáticamente `prepare_threshold = None` para psycopg 3, lo cual evita colisiones con el pooler en modo transacción de Supavisor.

> 📝 **Anota estos 4 datos en un bloc de notas temporal:**
> - `SUPABASE_URL`
> - `SUPABASE_ANON_KEY`
> - `SUPABASE_JWT_SECRET`
> - `DATABASE_URL`

---

## 🐍 Fase 2: Desplegar el Backend en Render (Plan Free)

El backend es una API de FastAPI que se ejecutará como un Web Service en Render.

### 2.1 Crear el Web Service
1. Entra a tu [Dashboard de Render](https://dashboard.render.com).
2. Haz clic en el botón azul **"New +"** (arriba a la derecha) y selecciona **"Web Service"**.
3. Selecciona la opción **"Build and deploy from a Git repository"** y haz clic en **Next**.
4. Conecta tu cuenta de GitHub si te lo solicita y busca tu repositorio **`PortfolioMaster`**. Haz clic en **"Connect"**.

### 2.2 Configuración del Servicio
Configura el formulario exactamente con estos parámetros:

| Campo | Valor a introducir | Notas |
| :--- | :--- | :--- |
| **Name** | `portfoliomaster-backend` | O el nombre que prefieras |
| **Region** | `Frankfurt (EU Central)` | Elige la misma región que elegiste en Supabase |
| **Branch** | `main` | Rama principal de tu repositorio |
| **Root Directory** | `.` | Déjalo vacío o pon un punto `.` |
| **Runtime** | `Python 3` | |
| **Build Command** | `pip install -r requirements.txt && pip install .` | En los servidores Linux de Render el operador `&&` funciona perfectamente |
| **Start Command** | `uvicorn backend.api.main:app --host 0.0.0.0 --port $PORT` | Inicia FastAPI con Uvicorn |
| **Instance Type** | **Free** ($0/month) | Asegúrate de seleccionar el plan gratuito |

### 2.3 Variables de Entorno en Render
Baja hasta la sección **"Environment Variables"** y haz clic en **"Add Environment Variable"** para añadir cada una de las siguientes:

| Clave (Key) | Valor (Value) | ¿De dónde sale? |
| :--- | :--- | :--- |
| `PYTHON_VERSION` | `3.12.6` | Fija la versión de Python recomendada |
| `ENVIRONMENT` | `production` | Activa el modo de producción seguro |
| `DATABASE_URL` | `postgresql+psycopg://...:6543/postgres?sslmode=require` | La URI de conexión con Pooler Supavisor (Fase 1.3) |
| `SUPABASE_URL` | `https://xxxx.supabase.co` | La URL de tu proyecto Supabase (Fase 1.3) |
| `SUPABASE_JWT_SECRET` | *(tu secreto JWT)* | El JWT Secret de Supabase (Fase 1.3) |
| `REFRESH_INTERVAL_SECONDS` | `300` | Refresco cada 5 minutos (pausado automáticamente tras 15m idle) |
| `REFRESH_COOLDOWN_SECONDS` | `120` | Cooldown de llamadas a Yahoo Finance |
| `BATCH_SIZE` | `50` | Tamaño de lote de acciones (reduce roundtrips a la BD) |
| `REFRESH_BATCH_SIZE` | `50` | Tamaño de lote para el background worker |
| `IDLE_TIMEOUT_SECONDS` | `900` | Pausa el worker tras 15 min de inactividad de clientes (ahorro de Egress) |
| `CORS_ORIGINS` | `http://localhost:3000` | Temporal; lo actualizaremos con la URL de Vercel en la Fase 4 |

### 2.4 Desplegar
1. Haz clic en **"Create Web Service"** (o **"Deploy Web Service"**).
2. Render comenzará a compilar e instalar dependencias.
3. Al cabo de 2-4 minutos, verás en los logs: `Application startup complete` y el estado cambiará a **"Live"**.
4. Copia la URL pública que Render le asignó a tu servicio (arriba a la izquierda, debajo del nombre):
   - Ejemplo: `https://portfoliomaster-backend-xxxx.onrender.com`
5. Puedes verificar que funciona abriendo en tu navegador:
   `https://portfoliomaster-backend-xxxx.onrender.com/health`
   Debe responder: `{"status":"ok","database":"connected"}`.

> ℹ️ **Comportamiento del Plan Gratuito de Render:**
> Los servicios gratuitos de Render entran en suspensión (*spindown*) tras 15 minutos sin recibir visitas. Cuando alguien entra a la web tras un tiempo de inactividad, la primera petición tardará entre **30 y 50 segundos** mientras la máquina virtual despierta. Las siguientes peticiones serán instantáneas.

---

## ⚡ Fase 3: Desplegar el Frontend en Vercel (Plan Hobby Free)

El frontend está desarrollado con Next.js 16 y Tailwind CSS.

### 3.1 Importar el Proyecto en Vercel
1. Entra a tu [Dashboard de Vercel](https://vercel.com/dashboard).
2. Haz clic en **"Add New..."** -> **"Project"**.
3. En la lista de repositorios de GitHub, busca **`PortfolioMaster`** y haz clic en **"Import"**.

### 3.2 Configurar el Directorio Raíz (¡PASO CRUCIAL!)
En la pantalla de configuración:
1. Localiza la opción **"Root Directory"**.
2. Haz clic en el botón **"Edit"**.
3. Selecciona la carpeta **`frontend`** y haz clic en **"Continue"**.
   > ⚠️ **Importante:** Si no seleccionas `frontend`, Vercel buscará Next.js en la raíz del repositorio y el despliegue fallará.
4. **Framework Preset**: Vercel detectará automáticamente **Next.js**.

### 3.3 Variables de Entorno en Vercel
Despliega la sección **"Environment Variables"** y añade estas tres variables:

| Clave (Key) | Valor (Value) |
| :--- | :--- |
| `NEXT_PUBLIC_API_URL` | La URL de Render de la Fase 2 (ej: `https://portfoliomaster-backend-xxxx.onrender.com`) |
| `NEXT_PUBLIC_SUPABASE_URL` | La URL de Supabase de la Fase 1.3 (ej: `https://xxxx.supabase.co`) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | La Anon Key de Supabase de la Fase 1.3 |

### 3.4 Desplegar
1. Haz clic en el botón azul **"Deploy"**.
2. Vercel construirá la aplicación (tardará aproximadamente 1 minuto).
3. Cuando termine, verás la pantalla de felicitaciones con confeti y una vista previa.
4. Haz clic en la captura o en el botón **"Continue to Dashboard"** para ver tu dominio público de Vercel:
   - Ejemplo: `https://portfoliomaster-frontend-xxxx.vercel.app`

---

## 🔗 Fase 4: Vincular CORS (Paso Final Obligatorio)

Para que tu frontend en Vercel tenga permiso de comunicarse con tu backend en Render sin bloqueos de seguridad del navegador (*CORS*), debemos registrar el dominio de Vercel en Render:

1. Vuelve a tu [Dashboard de Render](https://dashboard.render.com).
2. Entra en tu servicio **`portfoliomaster-backend`**.
3. En el menú de la izquierda, haz clic en **"Environment"**.
4. Busca la variable `CORS_ORIGINS`.
5. Edítala para incluir tu URL de Vercel (separada por comas, sin barra diagonal `/` al final):
   ```
   https://tu-proyecto.vercel.app,http://localhost:3000
   ```
   *(Sustituye `https://tu-proyecto.vercel.app` por tu dominio real de Vercel)*.
6. Haz clic en **"Save Changes"**. Render aplicará el cambio y reiniciará el servicio automáticamente.

---

## ✅ Fase 5: Verificación del Despliegue

1. Abre tu dominio de Vercel (`https://tu-proyecto.vercel.app`) en tu navegador o en tu móvil.
2. Haz clic en el botón de **Iniciar Sesión / Registro** (icono de usuario arriba a la derecha).
3. Regístrate con tu correo y contraseña (se guardará en Supabase Auth).
4. Añade tu primera acción a la Watchlist:
   - Haz clic en **"Add Instrument"** (o en el botón `+`).
   - Introduce un ticker (por ejemplo `AAPL`, `MSFT` o `SAN.MC`).
5. Haz clic en **"Update Quotes"** (Actualizar Cotizaciones):
   - Observa cómo la barra de estado conecta con el backend de Render y descarga los precios reales de Yahoo Finance.
   - Los datos se guardan en tiempo real en tu base de datos PostgreSQL de Supabase.

¡Tu aplicación PortfolioMaster ya está en producción, 100% operativa y sin coste alguno! 🎉

---

## 🛠️ Preguntas Frecuentes y Solución de Problemas

### 1. ¿Por qué me daba error `El token '&&' no es un separador válido` en mi PC?
El operador `&&` es propio de terminales tipo Bash (Linux/Mac) o CMD. En **PowerShell de Windows**, debes ejecutar los comandos por separado:
```powershell
pip install -r .\requirements.txt
pip install .
```
*(En cambio, dentro del servidor de Render, que corre sobre Linux Debian, el comando `pip install -r requirements.txt && pip install .` funciona sin problemas).*

### 2. ¿Qué pasa con las migraciones de base de datos (`alembic.ini`) en el plan gratuito?
En planes de pago de Render existe un comando llamado `preDeployCommand: alembic upgrade head`. Sin embargo, el **Plan Free de Render no permite `preDeployCommand`**. 

Por esa razón, la solución más limpia y recomendada para el plan gratuito es la que hemos seguido en la **Fase 1.2**: ejecutar directamente el script [`SQL_supabase.txt`](../SQL_supabase.txt) desde el editor SQL de Supabase. Este script contiene el 100% de las tablas, funciones y políticas de seguridad necesarias.

Si en el futuro deseas aplicar migraciones con Alembic manualmente desde tu PC sobre la base de datos de producción:
```powershell
# En PowerShell (temporalmente en tu terminal local):
$env:DATABASE_URL="postgresql+psycopg://postgres:[PASSWORD]@[HOST]:[PORT]/postgres"
alembic upgrade head
```

### 3. La primera vez que abro la página web los datos tardan unos 45 segundos en cargar
Esto es completamente normal en el plan gratuito de Render. Tras 15 minutos sin uso, el contenedor entra en modo "hibernación" para ahorrar recursos. En cuanto recibe la primera petición, se despierta automáticamente y las siguientes operaciones funcionarán a máxima velocidad.
