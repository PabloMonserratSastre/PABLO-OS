# PABLO OS en iPhone: preparación gratuita

Esta copia es una preparación de despliegue, no una instalación online ya publicada.
La instalación Windows original no ha sido reemplazada.

Validación local del 24/09/2026: 239 pruebas de backend aprobadas; compilación y TypeScript correctos; lint sin errores (dos avisos existentes sobre imágenes). Pruebas de navegador aprobadas para chat, tareas, aprobaciones, calendario local, Workspace, apertura de webs, dos sesiones independientes compartiendo tareas, formato móvil 390×844 y modo sin conexión sin caché de datos privados. PostgreSQL real, Render, Safari/iPhone físico y Google online quedan pendientes. Docker no estaba iniciado y no se ha afirmado una prueba de contenedor.

## Cuentas y despliegue

1. Crea una cuenta gratuita de GitHub si no tienes una, Render y Supabase. No actives planes de pago.
2. En Supabase crea un proyecto Free y guarda su contraseña. En Connect elige Session pooler, puerto 5432 (compatible con IPv4). Conserva la URL de conexión de forma privada.
3. Sube SOLO el código de esta copia a un repositorio privado de GitHub conectado a Render. El paquete de scripts/cloud/package.ps1 excluye bases de datos, claves, archivos generados y capturas personales.
4. En Render crea un Blueprint del repositorio. render.yaml solicita un único Web Service con plan free. No añade base de datos Render, disco de pago ni segundo worker.
5. Introduce DATABASE_URL (Session pooler), PABLO_OWNER_PASSWORD (12 caracteres mínimo) y AI_API_KEY (tu clave de Groq). PABLO_CLOUD_MASTER_KEY se genera al desplegar: guarda una copia privada y no la cambies, protege las integraciones.
6. Espera a que /ready responda. RENDER_EXTERNAL_URL configura el origen HTTPS automáticamente. Inicia sesión con la contraseña que has elegido.

La base usa el esquema privado pablo: no lo añadas a los esquemas expuestos por la API de Supabase. Los datos nunca se guardan en SQLite temporal en Render.

## Tus datos actuales

El script scripts/cloud/migrate.py prepara una copia de los datos e integraciones desde Windows a una nube vacía y vuelve a cifrar los secretos. Mantiene los identificadores y el historial. No elimina la copia local.

Hay que parar el servidor local y terminar o cancelar ejecuciones pendientes antes de migrar. Guarda las cuatro variables de conexión descritas en el script en un archivo privado fuera del repositorio. Ejecuta primero sin --apply para validar y después con --apply para transferir. No pegues claves en el chat.

Después ambos dispositivos deben abrir LA MISMA URL HTTPS. El localhost anterior conserva una copia antigua y no sincroniza automáticamente con la nube. El acceso directo del PC debe cambiarse después de verificar la migración.

La migración conserva tu contraseña local anterior: después de transferir los datos, esa es la contraseña de acceso. La contraseña inicial de Render solo sirve antes de la migración.

Tras comprobar la nube, scripts/cloud/connect-desktop.ps1 -Url https://TU-SERVICIO.onrender.com/ -LocalProject RUTA-DE-LA-INSTALACION-LOCAL adapta el acceso del escritorio y el de inicio automático, conservando copias recuperables. No ejecutes este paso antes de migrar y verificar los datos.

En Google Cloud añade https://TU-SERVICIO.onrender.com/api/v1/integrations/google/callback como URI autorizada del mismo cliente OAuth. Autoriza Google desde la aplicación online. No elimines aún la URI local.

## Instalar en el iPhone

En Safari abre la URL HTTPS, inicia sesión y usa Compartir > Añadir a pantalla de inicio. Abre PABLO OS desde su icono. La app requiere Internet; sin conexión muestra una página explicativa y no conserva documentos ni conversaciones en caché.

## Límites que siguen existiendo

- Render Free duerme tras inactividad. Abrir puede tardar aproximadamente un minuto.
- La IA gratuita conserva las cuotas de Groq. No se activa ningún proveedor de pago.
- Supabase Free puede pausar proyectos inactivos y tiene sus propias cuotas.
- El worker recupera programaciones vencidas al despertar. No se garantizan avisos a una hora exacta durante la suspensión, ni notificaciones push: esta versión no las implementa.
- Workspace guarda en PostgreSQL los archivos visibles: hasta 500 archivos, 50 MB en total y 5 MB por archivo. Carpetas de dependencias, repositorios .git y archivos protegidos no se migran ni persisten. Es almacenamiento dentro de la cuota de base de datos, no el bucket de 1 GB de Supabase Storage.
- Acciones sobre tu Windows, archivos que no hayas subido y Ollama local requieren el ordenador.
- Un único servicio/worker soportado. La conexión Session pooler es necesaria para el bloqueo que evita ejecuciones duplicadas durante despliegues.
- No hay una garantía de coste cero ilimitado: usa Free y no añadas servicios de pago ni un método de pago en Render. Si una cuota impide continuar, se debe parar y revisar.

## Validación pendiente antes de darlo por terminado

Despliegue real, prueba PostgreSQL/Supabase, migración de datos, autorización Google, prueba en iPhone 16e físico, apertura con el PC apagado y comprobación de cambios desde ambos dispositivos. Las pruebas locales no sustituyen estas comprobaciones.
