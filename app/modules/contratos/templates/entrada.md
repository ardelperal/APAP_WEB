<!-- CONTRATO-PLANTILLA: TEXTO PENDIENTE DE PORTAR DEL LEGACY (issue #1109) -->

Contrato de entrada

Fecha: {{solicitud.fecha}}
Animal: {{animal.nombre}} ({{animal.chip}})
Persona entregadora: {{persona.nombre}} {{persona.apellidos}}

{% if animal.edad_meses >= 6 %}
Clausula pendiente de portar del legacy.
{% endif %}
