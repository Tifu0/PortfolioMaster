1. Riesgo de corrupción al restaurar backups JSON.

La función de restauración no respeta correctamente una ruta de base de datos alternativa y puede dejar el estado vacío o parcialmente restaurado si falla una conversión después de borrar los datos anteriores.


2. Posible asignación incorrecta de precios históricos.

Si no se encuentra el cierre de la fecha solicitada, existen rutas de fallback que pueden utilizar una cotización reciente como si correspondiera a una fecha antigua. Es especialmente importante corregirlo porque afecta a las métricas desde análisis.


3. Los errores de Yahoo pueden eliminar el último precio válido.

El refresco persiste cotizaciones fallidas incluso cuando no contienen un precio. La migración debería separar el último valor válido del resultado del último intento de actualización.


4. La exportación invierte los argumentos del cálculo del precio objetivo.

El resultado exportado puede diferir del mostrado por la API, aunque ambos utilicen la misma función matemática.


5. La importación desde la interfaz pierde datos YTD.

El frontend no envía start_of_year_date ni start_of_year_price al confirmar la importación, aunque los otros componentes del sistema sí contemplan esos campos.