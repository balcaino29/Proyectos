# CLAUDE.md — Sistema de Gestión Documental OT6021

> Reglas y contexto para Claude Code. Actualizar aquí cada vez que se corrija un error
> para que no se repita. Formato de regla: **qué no hacer → qué hacer en cambio**.

---

## Contexto del Proyecto

Sistema web de **control documental de ingeniería** para el proyecto **OT6021**.

| Actor | Rol |
|---|---|
| **SEH** | Empresa de ingeniería que emite los documentos |
| **INN** | Cliente que revisa y aprueba |
| **Codelco** | Dueño del proyecto (propietario final) |

Cada documento pasa por múltiples **emisiones** (revisiones): se envía al cliente con un *transmittal* (acta de envío), el cliente responde con comentarios o aprobación, y se registra el tiempo de respuesta.

---

## Stack Técnico

| Capa | Tecnología |
|---|---|
| Backend | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.x + SQLite (`proyecto.db`) |
| Validación | Pydantic v2 |
| Excel import | openpyxl |
| Frontend | HTML/CSS/JS vanilla en `static/index.html` (SPA sin frameworks) |
| Email | smtplib estándar (SMTP con TLS) |

**Python 3.14** (los `.pyc` son `cpython-314`).

---

## Cómo Ejecutar

```bat
run.bat           # instala deps y lanza en 8080 → 5000 → 3000 (fallback)
```

O manual:
```powershell
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

Abrir: `http://127.0.0.1:8080`

---

## Estructura del Proyecto

```
Gestor Documental/
├── main.py                    # Punto de entrada FastAPI, monta routers y static
├── requirements.txt
├── run.bat
├── proyecto.db                # SQLite — NO versionar
├── smtp_config.json           # Credenciales SMTP — NO versionar
├── uploads/                   # Adjuntos físicos por doc_id/ — NO versionar
├── static/
│   └── index.html             # SPA completa (HTML + CSS + JS inline)
└── app/
    ├── database.py            # Engine SQLite, SessionLocal, Base, get_db()
    ├── models.py              # ORM: Documento, Emision, Adjunto
    ├── schemas.py             # Pydantic schemas (Create/Update/Read)
    └── routes/
        ├── documentos.py      # CRUD documentos + emisiones
        ├── dashboard.py       # Estadísticas agregadas
        ├── importar.py        # Importación desde Excel .xlsx
        ├── adjuntos.py        # Upload/download/preview/delete de archivos
        └── email_route.py     # SMTP config + envío de email con adjuntos
```

---

## Modelo de Datos

### `Documento` — entidad principal

```
id, item, tipo_ing, sala_tag,
codigo_segura,      ← código interno SEH
codigo_inn,         ← código del cliente INN
codigo_codelco,     ← código del dueño Codelco
descripcion, compromiso_entrega, criticidad,
deadline_cliente, comentario_interno, disciplina,
revision_actual,    ← letra de la última revisión (B, 0, 1…)
acta_trl,           ← número del último transmittal SEH
fecha_ultimo_envio, fecha_respuesta_cliente, estatus
```

### `Emision` — cada envío/revisión de un documento

```
id, documento_id, numero,
revision,           ← letra de esta emisión
transmittal_seh,    ← acta de envío de SEH
fecha_envio,
transmittal_cliente, ← número de transmittal de respuesta del cliente
fecha_respuesta,
tiempo_respuesta,   ← días calendario
observaciones       ← estatus/comentario de esta emisión
```

### `Adjunto` — archivos físicos

```
id, documento_id, nombre_original, nombre_guardado (UUID), content_type, tamanio, creado_en
```
Físicamente en `uploads/{documento_id}/{uuid}.ext`.

---

## Importación desde Excel

Hoja: **"MASTER INGENIERÍA CLIENTE"** (se detecta buscando "MASTER" + "ING" + "CLIENTE" en el nombre).
Datos desde **fila 4** (fila 1-3 son encabezados).

| Índice columna (0-based) | Campo |
|---|---|
| 1 | item |
| 2 | tipo_ing |
| 3 | sala_tag |
| 4 | codigo_segura |
| 5 | codigo_inn |
| 6 | codigo_codelco |
| 7 | descripcion |
| 8 | compromiso_entrega |
| 9 | criticidad |
| 10 | deadline_cliente |
| 11 | comentario_interno |
| 12 | disciplina |
| 13 | revision_actual |
| 14 | acta_trl |
| 15 | fecha_ultimo_envio |
| 16 | fecha_respuesta_cliente |
| 17 | estatus |
| 21+ | emisiones (grupos de 8 columnas por emisión) |

Cada grupo de emisión (desde col 21, grupos de 8):
`rev, trl_seh, [col+2 sin uso], fecha_envio, trl_cliente, fecha_resp, tiempo_resp, obs`

---

## Rutas API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/dashboard` | Estadísticas generales |
| GET | `/api/documentos` | Lista paginada con filtros |
| GET | `/api/documentos/filtros` | Valores únicos para dropdowns |
| GET | `/api/documentos/{id}` | Detalle con emisiones y adjuntos |
| POST | `/api/documentos` | Crear documento |
| PUT | `/api/documentos/{id}` | Actualizar documento |
| DELETE | `/api/documentos/{id}` | Eliminar documento (cascade) |
| POST | `/api/documentos/{id}/emisiones` | Agregar emisión |
| PUT | `/api/emisiones/{id}` | Actualizar emisión |
| POST | `/api/importar` | Importar Excel |
| POST | `/api/documentos/{id}/adjuntos` | Subir adjunto |
| GET | `/api/adjuntos/{id}/download` | Descargar adjunto |
| GET | `/api/adjuntos/{id}/preview` | Preview inline (PDF, imágenes) |
| DELETE | `/api/adjuntos/{id}` | Eliminar adjunto |
| GET | `/api/smtp-config` | Leer config SMTP (sin password) |
| POST | `/api/smtp-config` | Guardar config SMTP |
| POST | `/api/documentos/{id}/enviar-email` | Enviar email con adjuntos |

---

## Patrones y Convenciones del Código

- **Pydantic v2**: usar `.model_dump()` (no `.dict()`), `from_attributes = True` (no `orm_mode`).
- **SQLAlchemy 2.x**: `db.query(Model)...` (patrón legacy compatible, no Session.execute con select()).
- **Fechas**: el modelo usa `Column(Date)` — siempre pasar objetos `date`, no strings.
- **Archivos**: los adjuntos se guardan con nombre UUID; el nombre original se guarda en BD.
- **Estatus**: texto libre (no enum). Los filtros de dashboard usan `ilike("%palabra%")`.
- **Paginación**: `page` + `limit` en query params; respuesta incluye `total`, `pages`.
- **Frontend SPA**: todo en `static/index.html`. Las vistas se muestran/ocultan con clase `.active`. Sin bundler, sin npm.

---

## Archivos que NO se Versionan

- `proyecto.db` — base de datos SQLite
- `smtp_config.json` — credenciales de email
- `uploads/` — archivos adjuntos físicos
- `__pycache__/` — bytecode Python

---

## Errores Conocidos y Reglas para No Repetirlos

### E-01: No confundir índices de columnas Excel (0-based vs 1-based)
- `openpyxl` con `values_only=True` devuelve tuplas **0-based**.
- La columna B del Excel es `row[1]`, la E es `row[4]`, etc.
- NO asumir que columna "V" = índice 21 sin verificar el mapeo real del Excel del cliente.

### E-02: No sobreescribir estatus con observaciones automáticamente
- En `actualizar_emision` (`documentos.py:197`), se copia `observaciones → estatus` del documento padre.
- Esto es intencional para el flujo de trabajo, pero puede sobrescribir el estatus manualmente puesto.
- Cualquier cambio a esta lógica debe consultarse con el usuario primero.

### E-03: No eliminar la columna `acta_trl` del modelo `Documento`
- `acta_trl` es el número del **último transmittal SEH** y se actualiza automáticamente al agregar una emisión.
- Es un campo desnormalizado intencional para acceso rápido en la lista de documentos.

### E-04: No asumir que Python 3.14 tiene las mismas APIs que 3.11/3.12
- El entorno corre **Python 3.14** (cpython-314).
- Evitar usar APIs marcadas como deprecated que puedan haberse removido.
- `declarative_base` de `sqlalchemy.ext.declarative` sigue funcionando (legacy pero presente).

### E-05: No crear archivos nuevos cuando la lógica cabe en uno existente
- El frontend es un solo `static/index.html`. No crear archivos `.js` o `.css` separados
  a menos que el usuario lo pida explícitamente.
- Los routers van en `app/routes/`. No crear helpers en otras rutas.

### E-06: No usar `text/html` ni markdown en respuestas de API
- Todas las respuestas de la API son JSON.
- Los errores van en `HTTPException` con `detail` string, nunca HTML.

### E-07: No modificar `proyecto.db` directamente con scripts de migración sin respaldo
- La BD es SQLite local. Cambios de schema se hacen modificando `models.py` y
  recreando tablas (`drop_all` + `create_all`) SOLO en desarrollo, previo aviso al usuario.
- En producción, usar ALTER TABLE o migraciones Alembic.

### E-08: No confundir `transmittal_seh` con `acta_trl`
- `transmittal_seh` (en `Emision`): número del acta de envío de esa emisión específica.
- `acta_trl` (en `Documento`): número del último acta, campo resumen desnormalizado.
- Son el mismo número pero en contextos distintos del modelo.

### E-09: Agregar `--bare` al usar `claude -p` (modo no interactivo)
- Para invocaciones no interactivas del SDK usar `claude -p --bare` para inicio ~10x más rápido.
- Sin `--bare`, Claude carga configs locales, MCPs y settings innecesariamente.

---

## Vocabulario del Dominio

| Término | Significado |
|---|---|
| Transmittal | Documento formal de envío (acta de envío / carta de transmisión) |
| Acta TRL / acta de envío | Número correlativo del transmittal emitido por SEH |
| Emisión | Una revisión específica de un documento (A, B, 0, 1…) |
| Sala/TAG | Identificador de sala o sistema de la planta |
| Criticidad | Prioridad del documento (Alta/Media/Baja o numérica) |
| Estatus | Estado actual: En revisión INN, Aprobado, Comentado, Aprobado con comentarios, etc. |
| Disciplina | Especialidad de ingeniería: ME (Mecánica), EL (Eléctrica), CI (Civil), etc. |
| Master documental | Archivo Excel fuente con todos los documentos del proyecto |

---

## Cómo Agregar una Corrección

Cuando Claude comete un error, agrega una entrada al final de la sección
**"Errores Conocidos"** con formato:

```markdown
### E-NN: [Título descriptivo del error]
- Descripción del error cometido.
- Regla correcta a seguir en adelante.
```

Luego actualiza este archivo en el repositorio.
