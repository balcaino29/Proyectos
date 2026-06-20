# Despliegue del Reporte WMS en Azure Container Apps Jobs

Guía paso a paso para que el reporte de stock crítico se ejecute **una vez al día**
en Azure, sin mantener ninguna máquina encendida. Pensada para hacerse desde el
**Portal de Azure** + **Azure Cloud Shell** (la terminal que se abre dentro del
propio Portal, en el navegador). No necesitas instalar Docker ni Azure CLI en tu PC.

---

## Arquitectura

- **Azure Container Registry (ACR):** guarda la imagen del contenedor.
- **Azure Container Apps Job (tipo Schedule):** dispara el contenedor con un cron
  diario. El contenedor corre `python wms_reporte_seguro.py --run-now`, envía el
  correo y se apaga. Pagas solo por los ~1–2 minutos que dura cada ejecución
  (costo prácticamente nulo).

El contenedor **no necesita** `schedule` ni el bucle `while True`: la programación
la hace Azure.

---

## Archivos del paquete

Sube estos 4 archivos juntos a Cloud Shell (todos en la misma carpeta):

- `wms_reporte_seguro.py` — el script (ya ajustado para contenedor).
- `Dockerfile` — define la imagen.
- `requirements.txt` — dependencias de Python.
- `.dockerignore` — evita meter secretos/basura en la imagen.

> **No subas el `.env` con credenciales.** En Azure las credenciales van como
> *secrets* del Job (ver Paso 4), no dentro de la imagen.

---

## Paso 1 — Abrir Cloud Shell y subir los archivos

1. En el Portal de Azure, arriba a la derecha, haz clic en el ícono de terminal
   (**Cloud Shell**). Elige **Bash** si te lo pregunta.
2. En la barra de Cloud Shell usa **Upload/Download files → Upload** y sube los 4
   archivos. Quedan en tu carpeta home (`~`).
3. Crea una carpeta y muévelos ahí para tenerlos ordenados:

   ```bash
   mkdir -p wms && mv wms_reporte_seguro.py Dockerfile requirements.txt .dockerignore wms/
   cd wms
   ls -la
   ```

---

## Paso 2 — Crear el Container Registry y construir la imagen (en la nube)

`az acr build` construye la imagen **dentro de Azure**, no en tu PC. Por eso no
necesitas Docker local.

```bash
# Variables (ajusta región y nombres). El nombre del ACR debe ser único global,
# solo minúsculas y números.
RG="rg-wms-seh"
LOC="eastus"
ACR="acrwmsseh$RANDOM"
echo "ACR = $ACR"   # anota este nombre, lo usarás después

# Grupo de recursos (si ya tienes uno, omite este comando y usa el tuyo)
az group create --name $RG --location $LOC

# Container Registry
az acr create --resource-group $RG --name $ACR --sku Basic

# Construir y subir la imagen (ejecútalo dentro de la carpeta 'wms', donde está el Dockerfile)
az acr build --registry $ACR --image wms-reporte:v1 .
```

La primera build tarda unos minutos (descarga la imagen base de Playwright, que es
grande). Al terminar verás `Run ID ... was successful`.

> Si vuelves a cambiar el código más adelante, repite solo `az acr build ... v2`
> (sube la versión del tag) y luego actualiza la imagen del Job.

---

## Paso 3 — Crear el Container Apps Job (Portal)

Primero habilita el usuario admin del ACR para que el Job pueda leer la imagen
(lo más simple desde el Portal):

```bash
az acr update --name $ACR --admin-enabled true
az acr credential show --name $ACR   # muestra username y password del ACR; anótalos
```

Ahora en el Portal:

1. Busca **Container App Jobs** → **Create**.
2. **Basics:**
   - *Resource group:* `rg-wms-seh` (el mismo de arriba).
   - *Job name:* `job-wms-reporte`.
   - *Region:* la misma que usaste.
   - *Trigger type:* **Schedule**.
   - *Cron expression:* `0 12 * * *` (ver Paso 5 sobre la hora).
3. **Container:**
   - *Image source:* Azure Container Registry.
   - *Registry:* selecciona tu ACR.
   - *Image:* `wms-reporte` — *Tag:* `v1`.
   - *CPU/Memory:* **1 vCPU / 2 Gi** (Chromium necesita memoria; con menos puede
     fallar).
4. (Las variables y secretos se configuran en el Paso 4, en la misma pantalla,
   sección *Environment variables*.)
5. **Review + create**.

> Si en *Image source* te pide credenciales del registro, usa el username/password
> que mostró `az acr credential show`.

---

## Paso 4 — Credenciales: usar *secrets* del Job (recomendado)

**Recomendación:** para este caso usa los **secrets nativos del Container Apps Job**,
no Azure Key Vault.

- Las contraseñas (WMS y la *app password* de Gmail) quedan **cifradas en reposo**
  y se exponen al contenedor como variables de entorno que referencian al secret.
- Es directo desde el Portal, sin *managed identity* ni permisos extra.
- Key Vault tiene sentido cuando vas a **centralizar muchos secretos** o compartirlos
  entre varias apps; para un único job interno añade complejidad sin beneficio
  proporcional. Puedes migrar a Key Vault más adelante sin tocar el código.

En el Job, sección **Secrets**, crea:

| Nombre del secret | Valor |
|---|---|
| `wms-pass`  | la contraseña del WMS |
| `smtp-pass` | la *app password* de Gmail |

En la sección **Environment variables** del contenedor, define (las dos contraseñas
como *Reference a secret*, el resto como *Manual entry*):

| Variable | Tipo | Valor |
|---|---|---|
| `WMS_USUARIO` | Manual | `balcaino@seguraehijos.cl` |
| `WMS_CONTRASENA` | Secret ref | `wms-pass` |
| `SMTP_SERVIDOR` | Manual | `smtp.gmail.com` |
| `SMTP_PUERTO` | Manual | `587` |
| `SMTP_REMITENTE` | Manual | `notificacionesseh@seguraehijos.cl` |
| `SMTP_CONTRASENA` | Secret ref | `smtp-pass` |
| `CORREO_DESTINATARIO` | Manual | `fmedina@...,mcampos@...,balcaino@...` |

El script ya lee todas estas variables con `os.getenv`, así que no hay que tocar
código.

> **Importante:** rota la *app password* de Gmail actual (quedó expuesta en texto)
> y usa la nueva aquí.

### Alternativa: crear el Job por CLI (todo en Cloud Shell)

Si prefieres no usar el Portal para el Job, este comando lo crea completo. Primero
necesitas un *environment*:

```bash
az containerapp env create --name "env-wms-seh" --resource-group $RG --location $LOC

ACR_PASS=$(az acr credential show --name $ACR --query "passwords[0].value" -o tsv)

az containerapp job create \
  --name "job-wms-reporte" \
  --resource-group $RG \
  --environment "env-wms-seh" \
  --trigger-type "Schedule" \
  --cron-expression "0 12 * * *" \
  --replica-timeout 600 \
  --replica-retry-limit 1 \
  --cpu 1 --memory 2Gi \
  --image "$ACR.azurecr.io/wms-reporte:v1" \
  --registry-server "$ACR.azurecr.io" \
  --registry-username "$ACR" \
  --registry-password "$ACR_PASS" \
  --secrets wms-pass="LA_CLAVE_WMS" smtp-pass="LA_APP_PASSWORD_GMAIL" \
  --env-vars \
    WMS_USUARIO="balcaino@seguraehijos.cl" \
    WMS_CONTRASENA=secretref:wms-pass \
    SMTP_SERVIDOR="smtp.gmail.com" \
    SMTP_PUERTO="587" \
    SMTP_REMITENTE="notificacionesseh@seguraehijos.cl" \
    SMTP_CONTRASENA=secretref:smtp-pass \
    CORREO_DESTINATARIO="fmedina@seguraehijos.cl,mcampos@seguraehijos.cl,balcaino@seguraehijos.cl"
```

---

## Paso 5 — La hora: cron en UTC y el horario de Chile

El cron de Container Apps Jobs **se evalúa siempre en UTC**; no soporta zonas
horarias. Como Chile cambia de huso dos veces al año, "las 8 AM" se traduce a una
hora UTC distinta según la estación:

| Estación en Chile | Huso | Cron para las 08:00 local |
|---|---|---|
| **Invierno** (abril–septiembre) | UTC−4 | `0 12 * * *` |
| **Verano** (septiembre–abril) | UTC−3 | `0 11 * * *` |

Hoy (junio) estás en invierno, así que usa `0 12 * * *`. Cuando Chile entre en
horario de verano, edita el cron del Job a `0 11 * * *` (un cambio de un campo en
el Portal). Es el método más simple y transparente.

> Si quieres que se ajuste solo, sin tocar nada dos veces al año, se puede disparar
> el Job desde una **Logic App** con trigger *Recurrence* (que sí entiende zonas
> horarias) llamando a la ejecución del Job. Añade un componente más; dímelo y te
> armo esa variante.

---

## Paso 6 — Probar antes de confiar en el cron

No esperes al día siguiente: lanza una ejecución manual.

- **Portal:** entra al Job → **Run now**.
- **CLI:** `az containerapp job start --name job-wms-reporte --resource-group $RG`

Para ver qué pasó (los `log.info`/`log.error` del script salen por consola y Azure
los captura):

```bash
az containerapp job execution list --name job-wms-reporte --resource-group $RG -o table
```

O en el Portal: Job → **Execution history** → la ejecución → **Console logs**
(puede tardar un par de minutos en aparecer en Log Analytics).

Resultado esperado: un log que diga "Tabla cargada con N filas" y "Correo enviado",
o bien "No se encontraron resultados" si los filtros no devuelven nada ese día.

---

## Notas y pendientes

- **El diagnóstico (screenshots/HTML) no persiste.** El contenedor es efímero, así
  que la carpeta `diagnostico/` se borra al terminar. Para depurar fallos en
  producción te basan los *Console logs*. Si en algún momento quieres conservar las
  capturas, habría que subirlas a un Azure Blob Storage (te ayudo si lo necesitas).
- **Filtro pendiente:** quedó por decidir si el reporte usa "Solo stock crítico" o
  la combinación con "Solo seguimiento". Define eso en el script **antes** de
  construir la imagen, o el job correrá pero el correo podría salir siempre vacío.
- **Costo:** un job de ~2 min/día con 1 vCPU/2 Gi cuesta centavos al mes (pago por
  segundo de ejecución).