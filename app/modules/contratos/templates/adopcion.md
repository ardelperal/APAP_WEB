<!-- CONTRATO-PLANTILLA: TEXTO PENDIENTE DE PORTAR DEL LEGACY (issue #1109) -->

Contrato de adopcion

Fecha: {{solicitud.fecha}}
Adoptante: {{persona.nombre}} {{persona.apellidos}}
Animal: {{animal.nombre}} ({{animal.chip}})

{% if animal.edad_meses >= 6 %}
Clausula pendiente de portar del legacy.
{% endif %}
