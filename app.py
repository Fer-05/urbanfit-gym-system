from flask import Flask, render_template, request, redirect, url_for, session, flash

import os, calendar, re
import psycopg
from psycopg.rows import dict_row

from datetime import datetime, date

from functools import wraps

from werkzeug.security import generate_password_hash, check_password_hash



app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
SECRET_KEY = os.environ.get("SECRET_KEY")

if DATABASE_URL and not SECRET_KEY:
    raise RuntimeError("Falta configurar la variable de entorno SECRET_KEY.")

if not DATABASE_URL and not SECRET_KEY:
    SECRET_KEY = os.urandom(32).hex()

app.secret_key = SECRET_KEY

BASE_DIR = os.path.dirname(os.path.abspath(__file__))



PERMS = {

    'jefe': {'socios', 'pagos', 'asistencia', 'clases', 'reportes', 'usuarios', 'suplementos', 'cierres', 'coaches', 'ventas'},

    'administrativo': {'socios', 'pagos', 'asistencia', 'clases', 'reportes', 'suplementos', 'cierres', 'ventas'}

}



MEMBRESIAS = [

    'Mensualidad CrossFit',

    'Combo Amigos',

    'Day Pass',

    'Pago Anual',

    'Promoción / Otro',

]







PRODUCTOS_INICIALES = [

    ('Proteína ISO en Polvo', 'Proteínas', 535.00, 'Precio oficial Blast'),

    ('Proteína Whey en Polvo, 30 serv.', 'Proteínas', 415.00, 'Q415–Q435 según sabor en la tienda oficial'),

    ('Vegan Protein', 'Proteínas', 295.00, 'Precio oficial Blast'),

    ('Colágeno Hidrolizado', 'Recuperación', 235.00, 'Precio oficial Blast'),

    ('Pre-workout', 'Pre-entreno', 200.00, 'Precio oficial Blast'),

    ('Creatina Monohidratada', 'Creatina', 235.00, 'Precio oficial Blast'),

    ('Hi-dration', 'Hidratación', 80.00, 'Bolsa de 14 sticks; precio oficial Blast'),

    ('FitBurn (Quemador de Grasa)', 'Vitaminas y Minerales', 235.00, 'Precio oficial Blast'),

    ('Omega-3', 'Vitaminas y Minerales', 225.00, 'Precio oficial Blast'),

    ('Magnesio 3 en 1', 'Vitaminas y Minerales', 190.00, 'Precio oficial Blast'),

    ('Multivitamínico', 'Vitaminas y Minerales', 225.00, 'Precio oficial Blast'),

    ('Vitaminas D3+K2', 'Vitaminas y Minerales', 190.00, 'Precio oficial Blast'),

    ('Agua pura', 'Bebidas', 4.00, 'Precio UrbanFit'),

    ('Batido de proteína', 'Bebidas preparadas', 25.00, 'Precio UrbanFit por vaso'),

    ('Vaso de Gatorade', 'Bebidas preparadas', 10.00, 'Precio UrbanFit por vaso'),

    ('Vaso de electrolito', 'Bebidas preparadas', 10.00, 'Precio UrbanFit por vaso'),

]



def sumar_meses(fecha_texto, meses):

    """Suma meses calendario conservando el día cuando sea posible."""

    fecha = datetime.strptime(fecha_texto, '%Y-%m-%d').date()

    total = (fecha.year * 12 + (fecha.month - 1)) + meses

    anio = total // 12

    mes = total % 12 + 1

    ultimo_dia = calendar.monthrange(anio, mes)[1]

    dia = min(fecha.day, ultimo_dia)

    return date(anio, mes, dia).strftime('%Y-%m-%d')



def sumar_un_mes(fecha_texto):

    return sumar_meses(fecha_texto, 1)



class DBConnection:
    """Adaptador pequeño para conservar las consultas existentes y usar PostgreSQL."""

    def __init__(self, raw_connection):
        self.raw = raw_connection

    def execute(self, sql, params=None):
        # psycopg usa %s en lugar de los signos ? de SQLite.
        sql = sql.replace("?", "%s")
        # PostgreSQL usa GREATEST para obtener el mayor valor escalar.
        sql = re.sub(
            r"MAX\s*\(\s*0\s*,\s*stock\s*\+\s*%s\s*\)",
            "GREATEST(0, stock + %s)",
            sql,
            flags=re.IGNORECASE,
        )
        return self.raw.execute(sql, params or ())

    def commit(self):
        return self.raw.commit()

    def rollback(self):
        return self.raw.rollback()

    def close(self):
        return self.raw.close()


def db():
    """Abre una conexión a PostgreSQL usando DATABASE_URL."""
    if not DATABASE_URL:
        raise RuntimeError(
            "No se configuró DATABASE_URL. Configura la conexión PostgreSQL "
            "en las variables de entorno antes de usar la aplicación."
        )
    raw = psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=15,
    )
    return DBConnection(raw)


def actualizar_estados_pago(conn):
    """Actualiza automáticamente el estado de pago según la fecha de vencimiento."""
    hoy = date.today().isoformat()
    conn.execute(
        "UPDATE socios SET estado='Pendiente de pago' "
        "WHERE vencimiento IS NULL OR TRIM(vencimiento)=''"
    )
    conn.execute(
        "UPDATE socios SET estado='Activo' "
        "WHERE vencimiento IS NOT NULL AND TRIM(vencimiento)<>'' AND vencimiento>=?",
        (hoy,),
    )
    conn.execute(
        "UPDATE socios SET estado='Vencido' "
        "WHERE vencimiento IS NOT NULL AND TRIM(vencimiento)<>'' AND vencimiento<?",
        (hoy,),
    )
    conn.commit()


def column_exists(conn, table, column):
    """Comprueba una columna en el esquema público de PostgreSQL."""
    result = conn.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = %s
          AND column_name = %s
        """,
        (table, column),
    ).fetchone()
    return result is not None


def init_db():
    """Crea las tablas iniciales en PostgreSQL e inserta datos de catálogo."""
    c = db()
    try:
        schema = [
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                nombre TEXT NOT NULL,
                rol TEXT NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS socios (
                id SERIAL PRIMARY KEY,
                nombre TEXT,
                telefono TEXT,
                email TEXT,
                fecha_inscripcion TEXT,
                membresia TEXT,
                vencimiento TEXT,
                estado TEXT DEFAULT 'Pendiente de pago',
                monto_membresia REAL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS pagos (
                id SERIAL PRIMARY KEY,
                socio_id INTEGER,
                fecha TEXT,
                monto REAL,
                metodo TEXT,
                concepto TEXT,
                usuario_id INTEGER
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS asistencia (
                id SERIAL PRIMARY KEY,
                socio_id INTEGER,
                fecha TEXT,
                hora TEXT,
                coach TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS clases (
                id SERIAL PRIMARY KEY,
                nombre TEXT,
                coach TEXT,
                horario TEXT,
                capacidad INTEGER,
                estado TEXT DEFAULT 'Activa'
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS coaches (
                id SERIAL PRIMARY KEY,
                nombre TEXT UNIQUE NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1,
                creado TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS suplementos (
                id SERIAL PRIMARY KEY,
                nombre TEXT UNIQUE NOT NULL,
                categoria TEXT NOT NULL,
                precio REAL NOT NULL DEFAULT 0,
                stock INTEGER NOT NULL DEFAULT 0,
                nota TEXT,
                actualizado TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ventas (
                id SERIAL PRIMARY KEY,
                producto_id INTEGER NOT NULL REFERENCES suplementos(id),
                fecha TEXT NOT NULL,
                cantidad INTEGER NOT NULL DEFAULT 1,
                precio_unitario REAL NOT NULL DEFAULT 0,
                total REAL NOT NULL DEFAULT 0,
                metodo TEXT NOT NULL,
                usuario_id INTEGER REFERENCES usuarios(id),
                fecha_registro TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS cierres_diarios (
                id SERIAL PRIMARY KEY,
                fecha TEXT UNIQUE NOT NULL,
                total REAL NOT NULL DEFAULT 0,
                efectivo REAL NOT NULL DEFAULT 0,
                transferencia REAL NOT NULL DEFAULT 0,
                tarjeta REAL NOT NULL DEFAULT 0,
                operaciones INTEGER NOT NULL DEFAULT 0,
                realizado_por INTEGER,
                fecha_cierre TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS cierres_periodo (
                id SERIAL PRIMARY KEY,
                tipo TEXT NOT NULL,
                fecha_inicio TEXT NOT NULL,
                fecha_fin TEXT NOT NULL,
                total REAL NOT NULL DEFAULT 0,
                efectivo REAL NOT NULL DEFAULT 0,
                transferencia REAL NOT NULL DEFAULT 0,
                tarjeta REAL NOT NULL DEFAULT 0,
                operaciones INTEGER NOT NULL DEFAULT 0,
                realizado_por INTEGER,
                fecha_cierre TEXT NOT NULL,
                UNIQUE(tipo, fecha_inicio, fecha_fin)
            )
            """,
        ]
        for statement in schema:
            c.execute(statement)

        if not column_exists(c, "socios", "monto_membresia"):
            c.execute("ALTER TABLE socios ADD COLUMN monto_membresia REAL DEFAULT 0")

        # No se crean contraseñas conocidas por defecto. Configura estas variables
        # en Render: JEFE_PASSWORD y ADMIN_PASSWORD.
        usuarios_iniciales = [
            (
                os.environ.get("JEFE_USERNAME", "jefe"),
                os.environ.get("JEFE_PASSWORD"),
                "Jefe UrbanFit",
                "jefe",
            ),
            (
                os.environ.get("ADMIN_USERNAME", "administrativo"),
                os.environ.get("ADMIN_PASSWORD"),
                "Administrativo UrbanFit",
                "administrativo",
            ),
        ]
        for username, password, nombre, rol in usuarios_iniciales:
            if not password:
                continue
            exists = c.execute(
                "SELECT 1 FROM usuarios WHERE username=?",
                (username,),
            ).fetchone()
            if not exists:
                c.execute(
                    "INSERT INTO usuarios(username,password_hash,nombre,rol) VALUES(?,?,?,?)",
                    (username, generate_password_hash(password), nombre, rol),
                )

        c.execute("DELETE FROM usuarios WHERE rol='coach' OR username='coach'")

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for nombre in ["Josue", "Keren", "Marissa"]:
            exists = c.execute(
                "SELECT 1 FROM coaches WHERE nombre=?",
                (nombre,),
            ).fetchone()
            if not exists:
                c.execute(
                    "INSERT INTO coaches(nombre,activo,creado) VALUES(?,?,?)",
                    (nombre, 1, now),
                )

        for nombre, categoria, precio, nota in PRODUCTOS_INICIALES:
            exists = c.execute(
                "SELECT 1 FROM suplementos WHERE nombre=?",
                (nombre,),
            ).fetchone()
            if not exists:
                c.execute(
                    """
                    INSERT INTO suplementos(nombre,categoria,precio,stock,nota,actualizado)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (nombre, categoria, precio, 0, nota, now),
                )

        actualizar_estados_pago(c)
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def logged(f):

    @wraps(f)

    def w(*a, **k):

        if 'uid' not in session:

            return redirect(url_for('login'))

        return f(*a, **k)

    return w



def can(p):

    return p in PERMS.get(session.get('rol'), set())



def need(p):

    def d(f):

        @wraps(f)

        def w(*a, **k):

            if 'uid' not in session:

                return redirect(url_for('login'))

            if not can(p):

                flash('Tu rol no tiene permiso para esta sección.', 'danger')

                return redirect(url_for('dashboard'))

            return f(*a, **k)

        return w

    return d



@app.context_processor

def ctx():

    return {'can': can}



@app.route('/')

def splash():

    return render_template('splash.html')



@app.route('/login', methods=['GET', 'POST'])

def login():

    if request.method == 'POST':

        c = db()

        u = c.execute(

            'SELECT * FROM usuarios WHERE username=? AND activo=1',

            (request.form['username'].strip(),)

        ).fetchone()

        c.close()

        if u and check_password_hash(u['password_hash'], request.form['password']):

            session.clear()

            session.update(uid=u['id'], nombre=u['nombre'], rol=u['rol'])

            return redirect(url_for('dashboard'))

        flash('Usuario o contraseña incorrectos.', 'danger')

    return render_template('login.html')



@app.route('/logout')

def logout():

    session.clear()

    return redirect(url_for('splash'))



@app.route('/dashboard')

@logged

def dashboard():

    c = db()

    actualizar_estados_pago(c)

    data = {

        'socios': c.execute('SELECT COUNT(*) n FROM socios').fetchone()['n'],

        'activos': c.execute("SELECT COUNT(*) n FROM socios WHERE estado='Activo'").fetchone()['n'],

        'ingresos': c.execute("SELECT (SELECT COALESCE(SUM(monto),0) FROM pagos) + (SELECT COALESCE(SUM(total),0) FROM ventas) n").fetchone()['n'],

        'ingresos_hoy': c.execute("SELECT (SELECT COALESCE(SUM(monto),0) FROM pagos WHERE fecha=?) + (SELECT COALESCE(SUM(total),0) FROM ventas WHERE fecha=?) n", (datetime.now().strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d'))).fetchone()['n'],

        'hoy': c.execute('SELECT COUNT(*) n FROM asistencia WHERE fecha=?', (datetime.now().strftime('%Y-%m-%d'),)).fetchone()['n'],

        'stock_total': c.execute('SELECT COALESCE(SUM(stock),0) n FROM suplementos').fetchone()['n'],

    }

    c.close()

    return render_template('dashboard.html', **data)



@app.route('/socios', methods=['GET', 'POST'])

@logged

def socios():

    if not can('socios'):

        return redirect(url_for('dashboard'))

    c = db()

    if request.method == 'POST':

        membresia = request.form['membresia']

        # Pago anual: Q150 x 12 = Q1,800; descuento 15% = Q1,530.

        if membresia == 'Pago Anual':

            monto = 150.00 * 12 * 0.85

        else:

            try:

                monto = max(0, float(request.form.get('monto_membresia', 0)))

            except (ValueError, TypeError):

                monto = 0

        c.execute(

            '''INSERT INTO socios(nombre,telefono,email,fecha_inscripcion,membresia,monto_membresia,vencimiento,estado)

               VALUES(?,?,?,?,?,?,?,?)''',

            (request.form['nombre'], request.form['telefono'], request.form['email'],

             request.form['fecha_inscripcion'], membresia, monto,

             '', 'Pendiente de pago')

        )

        c.commit(); flash('Socio registrado. Estado de pago: Pendiente de pago.', 'success')

    actualizar_estados_pago(c)

    rows = c.execute('SELECT * FROM socios ORDER BY id DESC').fetchall()

    c.close()

    return render_template('socios.html', rows=rows, membresias=MEMBRESIAS)



@app.route('/pagos', methods=['GET', 'POST'])

@need('pagos')

def pagos():

    c = db()

    actualizar_estados_pago(c)

    socios = c.execute('SELECT id,nombre,membresia,monto_membresia,vencimiento,estado FROM socios ORDER BY nombre').fetchall()

    if request.method == 'POST':

        try:

            m = float(request.form['monto'])

        except (ValueError, TypeError):

            m = 0

        if m <= 0:

            flash('El monto debe ser mayor que cero.', 'danger')

        else:

            socio_id = request.form['socio_id']

            fecha_pago = request.form['fecha']

            c.execute(

                'INSERT INTO pagos(socio_id,fecha,monto,metodo,concepto,usuario_id) VALUES(?,?,?,?,?,?)',

                (socio_id, fecha_pago, m, request.form['metodo'],

                 request.form['concepto'], session['uid'])

            )

            socio = c.execute('SELECT membresia,vencimiento FROM socios WHERE id=?', (socio_id,)).fetchone()

            nuevo_vencimiento = None

            if socio:

                try:

                    if socio['membresia'] in ('Mensualidad CrossFit', 'Combo Amigos', 'Pago Anual'):

                        # Si ya tiene una membresía vigente, el nuevo pago extiende desde el

                        # vencimiento actual. Si ya venció, se calcula desde la fecha de pago.

                        base_vencimiento = fecha_pago

                        vencimiento_actual = (socio['vencimiento'] or '').strip()

                        if vencimiento_actual and vencimiento_actual >= fecha_pago:

                            base_vencimiento = vencimiento_actual

                        meses = 12 if socio['membresia'] == 'Pago Anual' else 1

                        nuevo_vencimiento = sumar_meses(base_vencimiento, meses)

                    elif socio['membresia'] == 'Day Pass':

                        nuevo_vencimiento = fecha_pago

                    if nuevo_vencimiento:

                        c.execute(

                            "UPDATE socios SET vencimiento=? WHERE id=?",

                            (nuevo_vencimiento, socio_id)

                        )

                except ValueError:

                    nuevo_vencimiento = None

            c.commit()

            actualizar_estados_pago(c)

            if nuevo_vencimiento:

                flash(f'Pago registrado. Nueva fecha de vencimiento: {nuevo_vencimiento}. El estado se actualiza automáticamente según la fecha.', 'success')

            else:

                flash('Pago registrado. El estado de pago se administra automáticamente cuando existe una fecha de vencimiento.', 'success')

    socios = c.execute('SELECT id,nombre,membresia,monto_membresia,vencimiento,estado FROM socios ORDER BY nombre').fetchall()

    rows = c.execute(

        'SELECT p.*,s.nombre socio FROM pagos p JOIN socios s ON s.id=p.socio_id ORDER BY p.id DESC'

    ).fetchall()

    c.close()

    return render_template('pagos.html', rows=rows, socios=socios, hoy=datetime.now().strftime('%Y-%m-%d'))



@app.route('/asistencia', methods=['GET', 'POST'])

@need('asistencia')

def asistencia():

    c = db()

    actualizar_estados_pago(c)

    socios = c.execute("SELECT id,nombre FROM socios WHERE estado='Activo' ORDER BY nombre").fetchall()

    now = datetime.now()

    if request.method == 'POST':

        c.execute(

            'INSERT INTO asistencia(socio_id,fecha,hora,coach) VALUES(?,?,?,?)',

            (request.form['socio_id'], request.form['fecha'], request.form['hora'], session['nombre'])

        )

        c.commit(); flash('Asistencia registrada.', 'success')

    rows = c.execute(

        'SELECT a.*,s.nombre socio FROM asistencia a JOIN socios s ON s.id=a.socio_id ORDER BY a.id DESC'

    ).fetchall()

    c.close()

    return render_template('asistencia.html', rows=rows, socios=socios,

                           hoy=now.strftime('%Y-%m-%d'), hora=now.strftime('%H:%M'))



@app.route('/clases', methods=['GET', 'POST'])

@need('clases')

def clases():

    c = db()

    if request.method == 'POST':

        c.execute(

            'INSERT INTO clases(nombre,coach,horario,capacidad,estado) VALUES(?,?,?,?,?)',

            (request.form['nombre'], request.form['coach'], request.form['horario'],

             request.form['capacidad'], request.form['estado'])

        )

        c.commit(); flash('Clase registrada.', 'success')

    rows = c.execute('SELECT * FROM clases ORDER BY id DESC').fetchall()

    coaches = c.execute('SELECT nombre FROM coaches WHERE activo=1 ORDER BY nombre').fetchall()

    c.close()

    return render_template('clases.html', rows=rows, coaches=coaches)



@app.route('/coaches', methods=['GET', 'POST'])

@need('coaches')

def coaches():

    c = db()

    if request.method == 'POST':

        accion = request.form.get('accion')

        if accion == 'agregar':

            nombre = request.form.get('nombre', '').strip()

            if not nombre:

                flash('Ingresa el nombre del coach.', 'danger')

            else:

                try:

                    c.execute(

                        'INSERT INTO coaches(nombre,activo,creado) VALUES(?,?,?)',

                        (nombre, 1, datetime.now().strftime('%Y-%m-%d %H:%M'))

                    )

                    c.commit(); flash(f'Coach {nombre} agregado.', 'success')

                except psycopg.IntegrityError:

                    flash('Ese coach ya está registrado.', 'danger')

        elif accion == 'cambiar_estado':

            coach_id = request.form.get('coach_id', type=int)

            coach = c.execute('SELECT nombre,activo FROM coaches WHERE id=?', (coach_id,)).fetchone()

            if coach:

                nuevo_estado = 0 if coach['activo'] else 1

                c.execute('UPDATE coaches SET activo=? WHERE id=?', (nuevo_estado, coach_id))

                c.commit()

                estado_txt = 'Activo' if nuevo_estado else 'Inactivo'

                flash(f'Coach {coach["nombre"]} actualizado a {estado_txt}.', 'success')

        elif accion == 'eliminar':

            coach_id = request.form.get('coach_id', type=int)

            coach = c.execute('SELECT nombre FROM coaches WHERE id=?', (coach_id,)).fetchone()

            if coach:

                c.execute('DELETE FROM coaches WHERE id=?', (coach_id,))

                c.commit(); flash(f'Coach {coach["nombre"]} eliminado de la lista.', 'success')

    rows = c.execute('SELECT * FROM coaches ORDER BY nombre').fetchall()

    c.close()

    return render_template('coaches.html', rows=rows)



@app.route('/suplementos', methods=['GET', 'POST'])

@need('suplementos')

def suplementos():

    c = db()

    if request.method == 'POST':

        accion = request.form.get('accion')

        producto_id = request.form.get('producto_id', type=int)



        if accion == 'agregar':

            # Tanto Jefe como Administrativo pueden ingresar nuevos productos.

            if session.get('rol') not in ('jefe', 'administrativo'):

                flash('No tienes permiso para agregar productos.', 'danger')

            else:

                nombre = request.form.get('nombre', '').strip()

                categoria = request.form.get('categoria', '').strip() or 'Otros'

                nota = request.form.get('nota', '').strip()

                try:

                    precio = max(0, float(request.form.get('precio_nuevo', 0)))

                    stock = max(0, int(request.form.get('stock_nuevo', 0)))

                    if not nombre:

                        raise ValueError

                    c.execute(

                        'INSERT INTO suplementos(nombre,categoria,precio,stock,nota,actualizado) VALUES(?,?,?,?,?,?)',

                        (nombre, categoria, precio, stock, nota, datetime.now().strftime('%Y-%m-%d %H:%M'))

                    )

                    c.commit()

                    flash(f'Producto {nombre} agregado al inventario.', 'success')

                except psycopg.IntegrityError:

                    flash('Ya existe un producto con ese nombre.', 'danger')

                except (ValueError, TypeError):

                    flash('Verifica el nombre, precio y stock del producto.', 'danger')



        elif accion == 'guardar_todos':

            # Un solo botón actualiza precio y stock de todos los productos visibles.

            try:

                productos = c.execute('SELECT id FROM suplementos').fetchall()

                ahora = datetime.now().strftime('%Y-%m-%d %H:%M')

                actualizados = 0

                for p in productos:

                    pid = p['id']

                    stock_key = f'stock_{pid}'

                    precio_key = f'precio_{pid}'

                    if stock_key in request.form and precio_key in request.form:

                        stock = max(0, int(request.form.get(stock_key, 0)))

                        precio = max(0, float(request.form.get(precio_key, 0)))

                        c.execute(

                            'UPDATE suplementos SET stock=?, precio=?, actualizado=? WHERE id=?',

                            (stock, precio, ahora, pid)

                        )

                        actualizados += 1

                c.commit()

                flash(f'Inventario actualizado: {actualizados} producto(s).', 'success')

            except (ValueError, TypeError):

                c.rollback()

                flash('Verifica los precios y cantidades ingresadas.', 'danger')



        elif accion in ('sumar', 'restar'):

            delta = 1 if accion == 'sumar' else -1

            c.execute(

                'UPDATE suplementos SET stock=GREATEST(0, stock + ?), actualizado=? WHERE id=?',

                (delta, datetime.now().strftime('%Y-%m-%d %H:%M'), producto_id)

            )

            c.commit()



        elif accion == 'eliminar':

            if session.get('rol') != 'jefe':

                flash('Solo el Jefe puede eliminar productos.', 'danger')

            else:

                producto = c.execute('SELECT nombre FROM suplementos WHERE id=?', (producto_id,)).fetchone()

                if producto:

                    c.execute('DELETE FROM suplementos WHERE id=?', (producto_id,))

                    c.commit()

                    flash(f'Producto {producto["nombre"]} eliminado.', 'success')



    rows = c.execute('SELECT * FROM suplementos ORDER BY categoria,nombre').fetchall()

    total_unidades = c.execute('SELECT COALESCE(SUM(stock),0) n FROM suplementos').fetchone()['n']

    valor_inventario = c.execute('SELECT COALESCE(SUM(stock*precio),0) n FROM suplementos').fetchone()['n']

    c.close()

    return render_template('suplementos.html', rows=rows, total_unidades=total_unidades,

                           valor_inventario=valor_inventario)







@app.route('/ventas', methods=['GET', 'POST'])

@need('ventas')

def ventas():

    c = db()

    hoy = datetime.now().strftime('%Y-%m-%d')

    if request.method == 'POST':

        producto_id = request.form.get('producto_id', type=int)

        fecha = request.form.get('fecha') or hoy

        metodo = request.form.get('metodo', 'Efectivo')

        try:

            cantidad = int(request.form.get('cantidad', 1))

            if cantidad <= 0:

                raise ValueError

        except (ValueError, TypeError):

            c.close()

            flash('La cantidad debe ser mayor que cero.', 'danger')

            return redirect(url_for('ventas'))



        try:

            c.execute('BEGIN')

            producto = c.execute('SELECT * FROM suplementos WHERE id=?', (producto_id,)).fetchone()

            if not producto:

                c.rollback(); c.close()

                flash('Producto no encontrado.', 'danger')

                return redirect(url_for('ventas'))

            if producto['stock'] < cantidad:

                disponible = producto['stock']

                c.rollback(); c.close()

                flash(f'Stock insuficiente. Disponible: {disponible}.', 'danger')

                return redirect(url_for('ventas'))



            precio = float(producto['precio'])

            total = precio * cantidad

            c.execute(

                'UPDATE suplementos SET stock=stock-?, actualizado=? WHERE id=?',

                (cantidad, datetime.now().strftime('%Y-%m-%d %H:%M'), producto_id)

            )

            c.execute(

                'INSERT INTO ventas(producto_id,fecha,cantidad,precio_unitario,total,metodo,usuario_id,fecha_registro) VALUES(?,?,?,?,?,?,?,?)',

                (producto_id, fecha, cantidad, precio, total, metodo, session['uid'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

            )

            c.commit()

            flash(f'Venta registrada: {cantidad} x {producto["nombre"]} = Q{total:.2f}. Stock actualizado automáticamente.', 'success')

        except psycopg.Error:

            c.rollback(); c.close()

            raise



    productos = c.execute('SELECT * FROM suplementos ORDER BY categoria,nombre').fetchall()

    rows = c.execute('''SELECT v.*, s.nombre producto, u.nombre usuario

                        FROM ventas v

                        JOIN suplementos s ON s.id=v.producto_id

                        LEFT JOIN usuarios u ON u.id=v.usuario_id

                        ORDER BY v.id DESC LIMIT 100''').fetchall()

    total_hoy = c.execute('SELECT COALESCE(SUM(total),0) n FROM ventas WHERE fecha=?', (hoy,)).fetchone()['n']

    unidades_hoy = c.execute('SELECT COALESCE(SUM(cantidad),0) n FROM ventas WHERE fecha=?', (hoy,)).fetchone()['n']

    c.close()

    return render_template('ventas.html', productos=productos, rows=rows, hoy=hoy, total_hoy=total_hoy, unidades_hoy=unidades_hoy)



def resumen_pagos(c, fecha_inicio, fecha_fin=None):

    """Resume todos los ingresos: membresías/pagos + ventas de inventario."""

    fecha_fin = fecha_fin or fecha_inicio

    row = c.execute(

        """SELECT COALESCE(SUM(monto),0) total,

                  COALESCE(SUM(CASE WHEN metodo='Efectivo' THEN monto ELSE 0 END),0) efectivo,

                  COALESCE(SUM(CASE WHEN metodo='Transferencia' THEN monto ELSE 0 END),0) transferencia,

                  COALESCE(SUM(CASE WHEN metodo='Tarjeta' THEN monto ELSE 0 END),0) tarjeta,

                  COUNT(*) operaciones

           FROM (

                SELECT monto, metodo FROM pagos WHERE fecha BETWEEN ? AND ?

                UNION ALL

                SELECT total AS monto, metodo FROM ventas WHERE fecha BETWEEN ? AND ?

           ) ingresos""",

        (fecha_inicio, fecha_fin, fecha_inicio, fecha_fin)

    ).fetchone()

    return row



@app.route('/cierres', methods=['GET', 'POST'])

@need('cierres')

def cierres():

    c = db()

    hoy = datetime.now().strftime('%Y-%m-%d')

    mes_actual = datetime.now().strftime('%Y-%m')



    if request.method == 'POST':

        accion = request.form.get('accion')

        if accion == 'cierre_diario':

            fecha = request.form.get('fecha') or hoy

            r = resumen_pagos(c, fecha)

            c.execute(

                """INSERT INTO cierres_diarios(fecha,total,efectivo,transferencia,tarjeta,operaciones,realizado_por,fecha_cierre)

                   VALUES(?,?,?,?,?,?,?,?)

                   ON CONFLICT(fecha) DO UPDATE SET total=excluded.total, efectivo=excluded.efectivo,

                   transferencia=excluded.transferencia, tarjeta=excluded.tarjeta, operaciones=excluded.operaciones,

                   realizado_por=excluded.realizado_por, fecha_cierre=excluded.fecha_cierre""",

                (fecha, r['total'], r['efectivo'], r['transferencia'], r['tarjeta'], r['operaciones'],

                 session['uid'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

            )

            c.commit(); flash(f'Cierre diario de {fecha} realizado correctamente.', 'success')



        elif accion in ('cierre_15', 'cierre_fin_mes'):

            mes = request.form.get('mes') or mes_actual

            try:

                anio, numero_mes = [int(x) for x in mes.split('-')]

                ultimo_dia = calendar.monthrange(anio, numero_mes)[1]

            except Exception:

                c.close(); flash('Mes inválido.', 'danger'); return redirect(url_for('cierres'))



            if accion == 'cierre_15':

                tipo = 'Cierre del 15'

                fecha_inicio = f'{anio:04d}-{numero_mes:02d}-01'

                fecha_fin = f'{anio:04d}-{numero_mes:02d}-15'

            else:

                tipo = 'Cierre de fin de mes'

                fecha_inicio = f'{anio:04d}-{numero_mes:02d}-16'

                fecha_fin = f'{anio:04d}-{numero_mes:02d}-{ultimo_dia:02d}'



            r = resumen_pagos(c, fecha_inicio, fecha_fin)

            c.execute(

                """INSERT INTO cierres_periodo(tipo,fecha_inicio,fecha_fin,total,efectivo,transferencia,tarjeta,operaciones,realizado_por,fecha_cierre)

                   VALUES(?,?,?,?,?,?,?,?,?,?)

                   ON CONFLICT(tipo,fecha_inicio,fecha_fin) DO UPDATE SET total=excluded.total,

                   efectivo=excluded.efectivo, transferencia=excluded.transferencia, tarjeta=excluded.tarjeta,

                   operaciones=excluded.operaciones, realizado_por=excluded.realizado_por, fecha_cierre=excluded.fecha_cierre""",

                (tipo, fecha_inicio, fecha_fin, r['total'], r['efectivo'], r['transferencia'], r['tarjeta'],

                 r['operaciones'], session['uid'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

            )

            c.commit(); flash(f'{tipo} realizado correctamente.', 'success')



    resumen_hoy = resumen_pagos(c, hoy)

    diarios = c.execute("""SELECT cd.*, u.nombre usuario FROM cierres_diarios cd

                           LEFT JOIN usuarios u ON u.id=cd.realizado_por ORDER BY cd.fecha DESC LIMIT 31""").fetchall()

    periodos = c.execute("""SELECT cp.*, u.nombre usuario FROM cierres_periodo cp

                            LEFT JOIN usuarios u ON u.id=cp.realizado_por ORDER BY cp.fecha_fin DESC, cp.id DESC LIMIT 24""").fetchall()

    c.close()

    return render_template('cierres.html', hoy=hoy, mes_actual=mes_actual,

                           resumen_hoy=resumen_hoy, diarios=diarios, periodos=periodos)



@app.route('/reportes')

@need('reportes')

def reportes():

    c = db()

    actualizar_estados_pago(c)

    meses = c.execute(

        """SELECT mes, SUM(total) total, SUM(cantidad) cantidad FROM (

               SELECT substr(fecha,1,7) mes, SUM(monto) total, COUNT(*) cantidad FROM pagos GROUP BY substr(fecha,1,7)

               UNION ALL

               SELECT substr(fecha,1,7) mes, SUM(total) total, COUNT(*) cantidad FROM ventas GROUP BY substr(fecha,1,7)

           ) GROUP BY mes ORDER BY mes DESC"""

    ).fetchall()

    ventas_productos = c.execute("""SELECT s.nombre producto, COALESCE(SUM(v.cantidad),0) unidades, COALESCE(SUM(v.total),0) total

                                      FROM ventas v JOIN suplementos s ON s.id=v.producto_id

                                      GROUP BY s.id,s.nombre ORDER BY unidades DESC, s.nombre""").fetchall()

    estados = c.execute('SELECT estado,COUNT(*) cantidad FROM socios GROUP BY estado').fetchall()

    inventario = c.execute(

        'SELECT categoria,SUM(stock) unidades,SUM(stock*precio) valor FROM suplementos GROUP BY categoria ORDER BY categoria'

    ).fetchall()

    c.close()

    return render_template('reportes.html', meses=meses, estados=estados, inventario=inventario, ventas_productos=ventas_productos)



@app.route('/usuarios')

@need('usuarios')

def usuarios():

    c = db()

    rows = c.execute("SELECT username,nombre,rol,activo FROM usuarios WHERE rol!='coach' ORDER BY id").fetchall()

    c.close()

    return render_template('usuarios.html', rows=rows)



init_db()

if __name__ == '__main__':

    app.run(debug=True)
