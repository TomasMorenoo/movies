# Configuración de seguridad

Antes de desplegar, configurar SECRET_KEY con al menos 32 caracteres aleatorios
(por ejemplo, generar con `python -c "import secrets; print(secrets.token_hex(32))"`).
Cambiarla invalida las sesiones existentes. No subir .env a Git ni a imágenes.

COOKIE_SECURE=true es el valor predeterminado y requiere HTTPS. Para desarrollo
local por HTTP usar COOKIE_SECURE=false. Las contraseñas nuevas requieren 12
caracteres; las existentes siguen funcionando.

Gunicorn usa un proceso y cuatro hilos. Los límites en memoria se reinician con
el proceso. Antes de escalar procesos configurar RATELIMIT_STORAGE_URI con un
almacenamiento compartido y sus dependencias.

No se confía en X-Forwarded-For. Revisar la red y el proxy del VPS antes de
habilitar IPs reenviadas: actualmente usuarios detrás del mismo proxy comparten
los límites por IP. Configurar límites también en el proxy.

PostgreSQL ya no publica su puerto. Se mantiene 5001 para compatibilidad con el
proxy actual; revisar y restringir ese acceso al analizar el servidor.

El service worker elimina sus cachés anteriores al activarse. Las páginas
privadas dejan de estar disponibles sin conexión. Abrir la web conectada para
recibir esa actualización en dispositivos que ya tenían instalada la PWA.

Queda pendiente verificar HTTPS, firewall, permisos de PostgreSQL, copias de
seguridad y rotación de credenciales en el VPS. No se modificaron datos reales.
