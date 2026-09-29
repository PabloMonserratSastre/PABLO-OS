# Despliegue de PABLO OS

PABLO OS se distribuye como un único contenedor: compila la interfaz y la sirve desde FastAPI junto con la API. `render.yaml` describe un servicio web compatible con el plan gratuito de Render.

## Servicios necesarios

- Un repositorio de GitHub.
- PostgreSQL duradero. Supabase Session Pooler es compatible con conexiones IPv4.
- Un servicio web Docker en Render u otro proveedor equivalente.
- Un proveedor de IA compatible con la API de OpenAI.

## Variables de producción

| Variable | Uso |
| --- | --- |
| `DATABASE_URL` | Conexión PostgreSQL. No se admite SQLite efímero en la nube. |
| `APP_ORIGIN` | URL HTTPS pública. Render proporciona `RENDER_EXTERNAL_URL` automáticamente. |
| `PABLO_CLOUD_MASTER_KEY` | Secreto de 32 caracteres o más para derivar la clave de cifrado. |
| `PABLO_OWNER_PASSWORD` | Contraseña inicial de 12 caracteres o más. |
| `PABLO_OWNER_NAME` | Nombre mostrado al propietario. |
| `AI_BASE_URL` | Endpoint compatible con OpenAI. |
| `AI_MODEL` | Identificador exacto del modelo. |
| `AI_API_KEY` | Clave privada del proveedor. |

Guarda estas variables en el gestor de secretos del alojamiento. No las escribas en archivos versionados.

## Despliegue con Render

1. Crea un Web Service a partir del repositorio o utiliza **New → Blueprint**.
2. Confirma que Render detecta `render.yaml` y el `Dockerfile` de la raíz.
3. Añade las variables marcadas como privadas.
4. Espera a que `/ready` devuelva HTTP 200.
5. Abre la URL HTTPS e inicia sesión.

## Google OAuth

Para Gmail, Calendar y Drive, añade esta URI al cliente OAuth de tipo aplicación web:

```text
https://TU-DOMINIO/api/v1/integrations/google/callback
```

Mantén las credenciales OAuth fuera del repositorio y autoriza únicamente los ámbitos que necesites.

## iPhone

Abre la URL HTTPS en Safari, pulsa **Compartir → Añadir a pantalla de inicio** y abre PABLO OS desde su icono. La PWA necesita conexión; su caché no conserva documentos ni conversaciones privadas.

## Límites operativos

Los planes gratuitos pueden suspender servicios inactivos y aplicar cuotas. Las automatizaciones se recuperan cuando el servicio vuelve a estar activo, pero una instancia suspendida no puede garantizar ejecuciones o avisos en un minuto exacto.
