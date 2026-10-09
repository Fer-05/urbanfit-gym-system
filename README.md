# \# UrbanFit | Sistema de gestión de gimnasio

# 

# UrbanFit es una aplicación web para gestionar las operaciones de un gimnasio.

# 

# \## Funcionalidades

# 

# \- Gestión de socios y membresías.

# \- Registro de pagos y control de vencimientos.

# \- Registro de asistencia.

# \- Gestión de clases y coaches.

# \- Inventario de suplementos y productos.

# \- Registro de ventas y actualización de existencias.

# \- Cierres diarios y por período.

# \- Reportes de ingresos e inventario.

# \- Usuarios con roles y permisos.

# 

# \## Tecnologías

# 

# \- Python

# \- Flask

# \- PostgreSQL

# \- Psycopg

# \- Gunicorn

# \- HTML, CSS y JavaScript

# 

# \## Configuración local

# 

# 1\. Instala Python.

# 2\. Crea un entorno virtual:

# 

# &#x20;  `py -m venv venv`

# 

# 3\. Actívalo:

# 

# &#x20;  `venv\\Scripts\\activate`

# 

# 4\. Instala las dependencias:

# 

# &#x20;  `pip install -r requirements.txt`

# 

# 5\. Configura las variables de entorno necesarias:

# &#x20;  - `DATABASE\_URL`

# &#x20;  - `SECRET\_KEY`

# &#x20;  - `JEFE\_PASSWORD`

# &#x20;  - `ADMIN\_PASSWORD`

# 

# 6\. Ejecuta la aplicación:

# 

# &#x20;  `py app.py`

# 

# 7\. Abre `http://127.0.0.1:5000` en el navegador.

# 

# \## Despliegue

# 

# La aplicación está preparada para utilizar PostgreSQL como base de datos y Gunicorn como servidor de aplicaciones.

# 

# Las variables de entorno deben configurarse en la plataforma de alojamiento. No se deben incluir contraseñas ni cadenas de conexión en el repositorio.

# 

# \## Proyecto académico

# 

# Desarrollado como proyecto universitario. Los datos de socios, pagos y ventas deben tratarse como información sensible. Para un uso real, se recomienda revisar los controles de acceso, las copias de seguridad y la seguridad de la aplicación antes de utilizarla con datos reales.

# 

