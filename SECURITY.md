# Política de seguridad

**Proceso de disclosure de vulnerabilidades, versiones soportadas y reconocimiento a reporters de APAP_WEB.**

APAP_WEB maneja datos sensibles: PII de voluntarios y personal del refugio, registros sanitarios y clínicos, autorizaciones por email.

Esta política describe cómo reportar una vulnerabilidad y qué esperar del proceso.

---

## Versiones soportadas

APAP_WEB se encuentra en fase pre-MVP. Solo la rama `main` recibe parches de seguridad.

| Rama | Soporte |
|---|---|
| `main` | Soportada. Recibe parches de seguridad mientras esté abierta. |
| Ramas de feature archivadas | Sin soporte. Migrar a `main` antes de reportar. |
| Tags publicados | Sin soporte retroactivo. La política de disclosure aplica al HEAD de `main`. |

Cuando el proyecto alcance MVP, esta sección se actualizará con la matriz de soporte por minor (`0.1.x`, `0.2.x`, …) siguiendo SemVer.

---

## Cómo reportar una vulnerabilidad

Envíe el reporte por email a `security@apap.example.org`. No abra una issue pública ni comente el problema en un PR existente.

Incluya en el reporte:

1. **Resumen** de la vulnerabilidad en una o dos frases.
2. **Pasos de reproducción** completos, con curl, comandos o capturas. Si la vulnerabilidad es visible solo en runtime, indique el flujo de pantallas o endpoints.
3. **Impacto observado**: qué datos o sistemas quedan expuestos, bajo qué condiciones de autenticación.
4. **Versión y commit SHA** donde reprodujo. Si afecta a varias versiones, indíquelo.
5. **Configuración relevante**: variables de entorno o flags activos (modo, debug, csrf_enabled).
6. **Mitigación temporal** conocida, si la tiene.

### Ventana de respuesta

- **Acknowledgement**: dentro de cinco días hábiles desde la recepción.
- **Triage y severidad**: dentro de quince días hábiles.
- **Parche y disclosure coordinada**: hasta noventa días desde el acknowledgement, según severidad y complejidad.

Las vulnerabilidades críticas (RCE, bypass de authorization, exposición masiva de PII) se atienden con prioridad.

Si la corrección requiere más tiempo, el maintainer notifica una extensión con fecha objetivo.

---

## Política de disclosure

Seguimos coordinated disclosure: el reporte se mantiene privado hasta que el parche esté disponible, momento en que publicamos un advisory junto al fix.

1. El reporter y el maintainer acuerdan una fecha de disclosure (default: noventa días desde el acknowledgement).
2. El maintainer prepara el fix en una rama privada o con acceso limitado; el reporter recibe una build de prueba si la solicita.
3. El día de la disclosure, publicamos un advisory en GitHub Security Advisories con descripción, severidad, créditos al reporter y la lista de commits que cierran el vector.
4. Las CVEs se asignan si la severidad y el alcance lo justifican; no todas las vulnerabilidades reciben CVE.

No publique detalles técnicos antes de la fecha acordada.

Si la vulnerabilidad se filtra o se explota, el maintainer puede acortar la ventana y publicar sin coordinación adicional.

---

## Reconocimiento

Agradecemos a quien reporta vulnerabilidades de forma responsable. Cada advisory publicado incluye el nombre o alias que el reporter indique.

Si el reporter prefiere permanecer anónimo, el advisory lo refleja sin nombre y solo con el identificador del reporte.

---

## Alcance fuera de esta política

Esta política cubre el código y los despliegues oficiales de APAP_WEB. Quedan fuera de alcance:

- El legacy Access/VBA que esta reescritura reemplaza. Para vulnerabilidades del código legacy, consulte el equipo responsable del sistema legacy.
- Dependencias de terceros en versiones ya parcheadas upstream. Reporte directamente al maintainer upstream y mencione el issue en una discussion si quiere trazabilidad cruzada.
- Ataques de ingeniería social, phishing o cualquier vector que requiera acción del usuario fuera del software.

[← Back to README](README.md) · [Next: DOCS →](DOCS.md)