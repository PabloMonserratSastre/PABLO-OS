# Seguridad

## Comunicar una vulnerabilidad

No publiques vulnerabilidades, credenciales ni datos personales en una incidencia pública. Utiliza **Security → Advisories → New draft security advisory** en GitHub para comunicar el problema de forma privada.

Incluye una descripción, los pasos mínimos para reproducirlo, el impacto observado y la versión afectada. No adjuntes bases de datos, tokens OAuth ni documentos personales.

## Versiones compatibles

El proyecto está en beta. Las correcciones de seguridad se aplican sobre la rama `main`; no se mantienen versiones anteriores.

## Secretos

El repositorio ignora archivos `.env`, bases de datos, claves y certificados. Las credenciales de producción deben guardarse únicamente en el gestor de secretos del servicio de alojamiento. Si una credencial se expone, revócala y sustitúyela antes de informar del incidente.
