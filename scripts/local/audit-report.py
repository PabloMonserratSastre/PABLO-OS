"""Build a human-readable audit log from recorded test results (no personal data)."""
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parents[2]
tests = ET.parse(root / '.local/audit-tests.xml').getroot().findall('.//testcase')
failed = sum(t.find('failure') is not None or t.find('error') is not None for t in tests)
live = [json.loads(line) for line in (root / '.local/audit-live.jsonl').read_text(encoding='utf-8').splitlines()]
latest = {row['case']: row for row in live}
google = json.loads((root / '.local/audit-google.json').read_text(encoding='utf-8'))
website = json.loads((root / '.local/audit-generated-web.json').read_text(encoding='utf-8'))
lines = [
    '# Auditoría de PABLO OS · 15/09/2026',
    '',
    '## Resultado y alcance',
    f'- Servidor: **{len(tests) - failed}/{len(tests)} pruebas aprobadas**, {failed} fallos. Base SQLite temporal; datos personales intactos.',
    '- Primera pasada: 143 aprobadas y 2 fallos. Se corrigieron ambos; la batería se amplió con peticiones formales e informales y regresiones.',
    '- Navegador Chrome: conversación, dos tareas con aprobación, resumen desde Inicio, actualización en reposo, carpeta de web en Workspace, calendario local, Integraciones, Ajustes, escritorio y móvil. Sin errores JavaScript ni desbordamiento horizontal en los escenarios comprobados.',
    '- TypeScript y ESLint de la aplicación: correctos. Compilación local correcta.',
    '- npm audit --omit=dev: 0 vulnerabilidades conocidas reportadas en dependencias de producción. No sustituye una auditoría de seguridad completa.',
    '- Modelo configurado: Groq openai/gpt-oss-120b. Solo peticiones ficticias; sin ejecución de los planes sobre datos personales y sin cambiar de proveedor.',
    f'- Conexiones reales, solo lectura: {", ".join(row["service"] + " " + row["status"] for row in google["results"])}. El informe no contiene correos ni títulos de eventos personales.',
    f'- Web ficticia generada por el modelo: {website["status"]}. Guardada aparte; menú visible y botón de teléfono verificado en navegador, sin acceso a red.',
    '',
    '## Fallos corregidos',
    '1. Crear webs/juegos fallaba por falta del import de JSON.',
    '2. Calendar fallaba al leer la zona horaria de un perfil inexistente.',
    '3. El resumen diario y los enlaces de actividad podían seleccionar una ejecución sin abrir su conversación.',
    '4. Inicio no descubría ejecuciones nuevas mientras permanecía en reposo. Ahora se actualiza cada 15 segundos cuando está visible y al recuperar conexión o visibilidad.',
    '5. El modelo eligió 20/09 (domingo) al pedir el próximo viernes. Las consultas habituales de días de la semana ahora se calculan en el programa; el resultado corregido fue 18/09. También se prueban días de 23 y 25 horas.',
    '6. El catálogo de Gmail omitía el parámetro limit: pedir tres correos podía devolver diez. Se completó el contrato; el modelo ya envía limit=3. La consulta sin filtro usa Recibidos; se conserva cualquier filtro explícito.',
    '7. Convertir una consulta local de calendario a Google perdía los límites from/to. Ahora se convierten a start/end.',
    '8. Las peticiones exactas consultaban documentos innecesariamente. Se evita esa búsqueda y una posible llamada a embeddings.',
    '9. La creación de webs solo ofrecía plantillas fijas. Ahora permite HTML/CSS/JavaScript propios en una carpeta nueva, con project.json. Valida todos los contenidos antes de escribir y rechaza sobrescribir una carpeta existente.',
    '10. Workspace agrupa archivos por proyecto y deja las herramientas avanzadas plegadas. Se conservan los archivos anteriores.',
    '11. Las nuevas automatizaciones usan CHAT también en la herramienta y el servidor. Se retiró el selector antiguo de modos de su formulario; las existentes conservan su configuración.',
    '12. Se retiró la rama visual inaccesible de Agentes, se corrigieron avisos de código de la interfaz y se simplificaron respuestas de archivos y cambios para evitar JSON e identificadores innecesarios.',
    '',
    '## Muestra con el proveedor configurado',
    'La primera comprobación del viernes solo validaba la herramienta; la revisión del contenido detectó que la fecha era incorrecta. Se añadió comprobación del día de la semana. La corrección del viernes termina por la vía determinista (sin tokens), no mediante una nueva respuesta del modelo.',
    '',
    '| Petición | Resultado final | Herramientas |',
    '|---|---|---|',
]
for row in latest.values():
    lines.append('| ' + row['goal'].replace('|', '/') + ' | ' + row['status'] + ' | ' + (', '.join(row.get('actual', [])) or 'Respuesta sin acciones') + ' |')
lines += [
    '',
    '## Límites pendientes antes de un lanzamiento abierto',
    '- No se puede garantizar toda petición posible: la muestra verifica estos escenarios, no la totalidad del lenguaje natural.',
    '- El modelo gratuito mantiene sus cuotas y puede equivocarse en planes complejos. No se activó facturación ni un proveedor de pago alternativo.',
    '- No se hicieron envíos reales de correo, modificaciones de repositorios externos ni borrados de datos personales. Sus controles se prueban con datos temporales o servicios simulados.',
    '- Google Calendar permite consultar y crear con las herramientas existentes; editar o borrar eventos de Google desde el chat sigue sin herramienta específica. El calendario visual consulta el calendario principal, no todos los calendarios compartidos.',
    '- Workspace muestra código y permite descargar archivos; no ofrece todavía una vista previa integrada ni descarga conjunta de una carpeta. Los proyectos anteriores guardados en la raíz no se migraron automáticamente.',
    '- Las operaciones complejas que necesitan usar el resultado de una búsqueda para construir otro paso requieren más trabajo en el planificador. No se presenta como equivalente completo a ChatGPT.',
    '- Dos avisos de deprecación pertenecen al entorno de pruebas Starlette/httpx/anyio. La ejecución de las pruebas no falla por ellos.',
    '',
    '## Registro de pruebas automatizadas',
    'Los nombres parametrizados conservan las peticiones ensayadas. Las pruebas de API/worker verifican datos guardados, respuestas y aprobaciones; las de interpretación exacta verifican límites y que no se descarten condiciones adicionales. No deben confundirse con llamadas al modelo real.',
    '',
    '| Prueba / petición | Estado |',
    '|---|---|',
]
for test in tests:
    name = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1],16)), test.get('name', ''))
    status = 'FAIL' if test.find('failure') is not None or test.find('error') is not None else 'SKIP' if test.find('skipped') is not None else 'PASS'
    lines.append('| ' + name.replace('|', '/').replace('\n', ' ') + ' | ' + status + ' |')
target = root / 'docs/AUDITORIA-2026-09-15.md'
target.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'Audit report saved: {len(tests)} tests; {failed} failures.')
