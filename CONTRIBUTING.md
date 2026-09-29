# Contribuir a PABLO OS

Gracias por querer mejorar el proyecto.

## Antes de proponer un cambio

1. Abre una incidencia breve que describa el problema, el comportamiento esperado y cómo reproducirlo.
2. Mantén cada cambio centrado en un único objetivo.
3. No incluyas datos reales, capturas privadas, documentos personales ni credenciales.

## Validación local

```bash
python -m pytest backend/tests
python -m ruff check backend
npm run typecheck
npm run lint:app
npm run build:local
```

Añade pruebas cuando corrijas un fallo de comportamiento o incorpores una capacidad. Las modificaciones visuales deben comprobarse en escritorio y en un viewport móvil.

## Pull requests

Explica el problema, el comportamiento resultante y las comprobaciones realizadas. Si el cambio altera datos, autenticación, integraciones o despliegue, documenta también la migración y el procedimiento de recuperación.
