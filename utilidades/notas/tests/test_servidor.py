import http.client
import io
import json
import threading
import time
import unittest
import unittest.mock
import zipfile
from urllib.parse import quote

from notas import servidor as srv
from notas.cuaderno import Cuaderno
from tests.ayudas import HTML, CasoConCuaderno, png, wav


class CasoConServidor(CasoConCuaderno):
    def setUp(self):
        super().setUp()
        self.servidor = srv.crear_servidor(self.c, 0)
        self.puerto = self.servidor.server_address[1]
        self.hilo = threading.Thread(target=self.servidor.serve_forever, args=(0.02,), daemon=True)
        self.hilo.start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join()
        super().tearDown()

    def pedir(self, metodo, ruta, cuerpo=None, cabeceras=None, quitar=()):
        """(estado, cabeceras, cuerpo) como lo pediría la propia página."""
        todas = {"Host": f"127.0.0.1:{self.puerto}", "Sec-Fetch-Site": "same-origin"}
        if metodo != "GET":
            todas.update({"Origin": f"http://127.0.0.1:{self.puerto}",
                          srv.CABECERA_TOKEN: srv.TOKEN, "Content-Type": "application/json"})
        todas.update(cabeceras or {})
        for nombre in quitar:
            todas.pop(nombre, None)
        if cuerpo is not None and not isinstance(cuerpo, bytes):
            cuerpo = json.dumps(cuerpo).encode()
        con = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            con.request(metodo, ruta, cuerpo, todas)
            r = con.getresponse()
            return r.status, r.headers, r.read()
        finally:
            con.close()

    def json(self, *args, **kwargs):
        estado, _, cuerpo = self.pedir(*args, **kwargs)
        return estado, json.loads(cuerpo)

    def subir(self, id_nota, datos, nombre="x", mime="application/octet-stream", **otras):
        return self.json("POST", f"/api/notas/{id_nota}/adjuntos", datos,
                         {"Content-Type": mime, "X-Nombre": quote(nombre), **otras})


class Pagina(CasoConServidor):
    def test_pagina_y_estaticos(self):
        estado, cabeceras, cuerpo = self.pedir("GET", "/")
        self.assertEqual(estado, 200)
        self.assertIn("text/html", cabeceras["Content-Type"])
        self.assertIn("script-src 'self'", cabeceras["Content-Security-Policy"])
        self.assertIn(b"/estaticos/notas.js", cuerpo)
        for nombre in srv.ESTATICOS:
            self.assertEqual(self.pedir("GET", f"/estaticos/{nombre}")[0], 200)

    def test_nada_mas(self):
        for ruta in ("/estaticos/cuaderno.py", "/estaticos/../cuaderno.py", "/estaticos/%2e%2e/cli.py",
                     "/notas.sqlite", "/adjuntos/1", "/adjuntos/../notas.sqlite", "/api/nada"):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.pedir("GET", ruta)[0], 404)
        self.assertEqual(self.pedir("DELETE", "/api/notas/1")[0], 404)


class Seguridad(CasoConServidor):
    def test_host_ajeno(self):
        for host in ("evil.example", "127.0.0.1.evil.example", "192.168.1.5:8790", ""):
            with self.subTest(host=host):
                self.assertEqual(self.pedir("GET", "/", cabeceras={"Host": host})[0], 403)
        self.assertEqual(self.pedir("GET", "/", cabeceras={"Host": "localhost:1"})[0], 200)

    def test_otra_web_no_puede_leer(self):
        n = self.c.crear("A")
        a = self.adjuntar(n, png())
        for sitio in ("cross-site", "same-site"):
            for ruta in ("/api/estado", "/api/notas", "/api/copia", f"/adjuntos/{a['id']}"):
                with self.subTest(sitio=sitio, ruta=ruta):
                    estado, cabeceras, cuerpo = self.pedir("GET", ruta, cabeceras={"Sec-Fetch-Site": sitio})
                    self.assertEqual(estado, 403)
                    self.assertNotIn(srv.TOKEN.encode(), cuerpo)
                    self.assertNotIn("Access-Control-Allow-Origin", cabeceras)

    def test_otra_web_no_puede_cambiar_nada(self):
        n = self.c.crear("A")
        origen = f"http://127.0.0.1:{self.puerto}"
        ataques = [({"Origin": "http://evil.example"}, ()), ({"Origin": "http://127.0.0.1:1"}, ()),
                   ({}, ("Origin",)), ({"Sec-Fetch-Site": "cross-site"}, ()),
                   ({srv.CABECERA_TOKEN: "otro"}, ()), ({srv.CABECERA_TOKEN: "ñ"}, ()),
                   ({"Origin": origen}, (srv.CABECERA_TOKEN,))]
        for cabeceras, quitar in ataques:
            with self.subTest(cabeceras=cabeceras, quitar=quitar):
                for metodo, ruta, cuerpo in (
                        ("POST", "/api/notas", {"titulo": "x"}),
                        ("PATCH", f"/api/notas/{n['id']}", {"titulo": "x"}),
                        ("POST", "/api/lote", {"ids": [n["id"]], "accion": "papelera"}),
                        ("DELETE", "/api/categorias/1", None)):
                    self.assertEqual(self.pedir(metodo, ruta, cuerpo, cabeceras, quitar)[0], 403)
        self.assertEqual(self.titulos(), ["A"])

    def test_token_caducado_se_distingue(self):
        _, datos = self.json("POST", "/api/notas", {"titulo": "x"}, {srv.CABECERA_TOKEN: "viejo"})
        self.assertEqual(datos["codigo"], "token")
        self.assertEqual(self.json("GET", "/api/estado")[1]["token"], srv.TOKEN)

    def test_solo_escucha_en_este_equipo(self):
        self.assertEqual(self.servidor.server_address[0], "127.0.0.1")


class Api(CasoConServidor):
    def test_crear_listar_y_editar(self):
        estado, n = self.json("POST", "/api/notas", {"titulo": "Ñu", "texto": "x", "categorias": ["Casa"]})
        self.assertEqual(estado, 201)
        estado, r = self.json("GET", f"/api/notas?vista=activas&buscar={quote('ñu casa')}&orden=titulo")
        self.assertEqual([x["id"] for x in r["notas"]], [n["id"]])
        estado, n2 = self.json("PATCH", f"/api/notas/{n['id']}", {"texto": "y", "version": n["version"]})
        self.assertEqual((estado, n2["texto"]), (200, "y"))
        self.assertEqual(self.json("GET", f"/api/notas/{n['id']}")[1], n2)
        categoria = n["categorias"][0]["id"]
        self.assertEqual(len(self.json("GET", f"/api/notas?categoria={categoria}")[1]["notas"]), 1)
        self.assertEqual(self.json("GET", "/api/notas?categoria=0")[1]["notas"], [])

    def test_conflicto(self):
        n = self.c.crear("A", "x")
        self.c.editar(n["id"], texto="otra ventana")
        estado, r = self.json("PATCH", f"/api/notas/{n['id']}", {"texto": "mío", "version": n["version"]})
        self.assertEqual((estado, r["nota"]["texto"]), (409, "otra ventana"))

    def test_errores_claros_y_rapidos(self):
        n = self.c.crear("A")
        casos = [("POST", "/api/notas", {"color": "fucsia"}, 400), ("POST", "/api/notas", [1], 400),
                 ("POST", "/api/notas", b"{", 400), ("PATCH", "/api/notas/99", {"texto": "x"}, 404),
                 ("POST", "/api/lote", {"ids": "x", "accion": "fijar"}, 400),
                 ("POST", "/api/lote", {}, 400), ("POST", "/api/notas", None, 411),
                 ("POST", "/api/papelera/vaciar", {"confirmar": "si"}, 400),
                 ("PATCH", f"/api/notas/{n['id']}", {"id_nota": 3, "self": 1}, 200)]
        for metodo, ruta, cuerpo, esperado in casos:
            with self.subTest(ruta=ruta, cuerpo=cuerpo):
                antes = time.perf_counter()
                estado, datos = self.json(metodo, ruta, cuerpo)
                self.assertEqual(estado, esperado)
                self.assertTrue(estado == 200 or datos["error"])
                self.assertLess(time.perf_counter() - antes, 1.5)
        for ruta in ("/api/notas?categoria=x", "/api/notas?categoria=%C2%B2", "/api/notas?vista=x",
                     "/api/notas?tipo=x", "/api/notas?orden=x"):
            self.assertEqual(self.pedir("GET", ruta)[0], 400)
        self.assertEqual(self.pedir("POST", "/api/notas", {"titulo": "x"}, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.pedir("POST", "/api/notas", b"{}", {"Content-Type": "application/json"})[0], 201)

    def test_lote_y_papelera(self):
        ids = [self.c.crear(t)["id"] for t in "ABC"]
        self.assertEqual(self.json("POST", "/api/lote", {"ids": ids, "accion": "papelera"})[1], {"cambiadas": 3})
        self.assertEqual(self.json("POST", "/api/lote", {"ids": ids[:1], "accion": "eliminar"})[1], {"cambiadas": 1})
        self.json("POST", "/api/lote", {"ids": ids[1:2], "accion": "restaurar"})
        self.assertEqual(self.json("POST", "/api/papelera/vaciar", {"confirmar": "VACIAR"})[1], {"borradas": 1})
        self.assertEqual(self.titulos(vista="todas"), ["B"])

    def test_categorias(self):
        estado, c = self.json("POST", "/api/categorias", {"nombre": "Casa"})
        self.assertEqual(estado, 201)
        self.assertEqual(self.json("POST", "/api/categorias", {"nombre": "casa"})[0], 400)
        self.assertEqual(self.json("POST", "/api/categorias", {})[0], 400)
        self.assertEqual(self.json("PATCH", f"/api/categorias/{c['id']}", {"nombre": "Hogar"})[0], 200)
        self.assertEqual(self.json("GET", "/api/estado")[1]["categorias"],
                         [{"id": c["id"], "nombre": "Hogar", "total": 0}])
        self.assertEqual(self.json("DELETE", f"/api/categorias/{c['id']}")[0], 200)
        self.assertEqual(self.json("DELETE", f"/api/categorias/{c['id']}")[0], 404)

    def test_copia(self):
        n = self.c.crear("A")
        a = self.adjuntar(n, png())
        estado, cabeceras, cuerpo = self.pedir("GET", "/api/copia")
        self.assertEqual((estado, cabeceras["Content-Type"]), (200, "application/zip"))
        with zipfile.ZipFile(io.BytesIO(cuerpo)) as z:
            self.assertIn(a["archivo"], z.namelist())


class Adjuntos(CasoConServidor):
    def test_subir_y_descargar(self):
        n = self.c.crear("A")
        datos = wav(2)
        estado, a = self.subir(n["id"], datos, "Nota ñ.wav", "audio/wav", **{"X-Duracion": "2.04"})
        self.assertEqual((estado, a["nombre"], a["duracion"]), (201, "Nota ñ.wav", 2.04))
        estado, cabeceras, cuerpo = self.pedir("GET", a["url"])
        self.assertEqual((estado, cuerpo), (200, datos))
        self.assertEqual((cabeceras["Content-Type"], cabeceras["X-Content-Type-Options"]), ("audio/wav", "nosniff"))
        self.assertIn("inline", cabeceras["Content-Disposition"])
        self.assertIn("attachment", self.pedir("GET", a["url"] + "&descargar=1")[1]["Content-Disposition"])

    def test_rangos(self):
        a = self.adjuntar(self.c.crear("A"), wav(1))
        datos = wav(1)
        for rango, esperado in (("bytes=0-9", datos[:10]), ("bytes=100-", datos[100:]), ("bytes=-5", datos[-5:]),
                                ("bytes=10-99999999", datos[10:])):
            estado, cabeceras, cuerpo = self.pedir("GET", a["url"], cabeceras={"Range": rango})
            self.assertEqual((estado, cuerpo), (206, esperado))
            self.assertIn(f"/{len(datos)}", cabeceras["Content-Range"])
        for rango in (f"bytes={len(datos)}-", "bytes=9-3", "bytes=-0"):
            self.assertEqual(self.pedir("GET", a["url"], cabeceras={"Range": rango})[0], 416)
        for rango in ("bytes=-", "otra cosa", "bytes=1-2,5-6"):
            self.assertEqual(self.pedir("GET", a["url"], cabeceras={"Range": rango})[0], 200)

    def test_no_se_admite_cualquier_archivo(self):
        n = self.c.crear("A")
        estado, r = self.subir(n["id"], HTML * 3000, "foto.png", "image/png")
        self.assertEqual(estado, 415)
        self.assertIn("foto.png", r["error"])
        self.assertEqual(self.subir(n["id"], b"", "x.png")[0], 411)
        self.assertEqual(self.subir(99, png(), "x.png")[0], 404)
        with unittest.mock.patch.object(srv.adj, "MAX_BYTES", 1000):
            self.assertEqual(self.subir(n["id"], wav(), "x.wav")[0], 413)
        self.assertEqual(self.en_disco(), [])

    def test_quitar_recuperar_y_archivo_perdido(self):
        n = self.c.crear("A")
        a = self.adjuntar(n, png())
        self.assertEqual(self.json("POST", f"/api/adjuntos/{a['id']}/quitar")[1]["adjuntos"], [])
        self.assertEqual(len(self.json("POST", f"/api/adjuntos/{a['id']}/recuperar")[1]["adjuntos"]), 1)
        self.assertEqual(self.pedir("GET", a["miniatura"])[0], 200)
        (self.carpeta / a["archivo"]).unlink()
        self.assertEqual(self.pedir("GET", a["url"])[0], 404)
        self.assertEqual(self.pedir("GET", a["miniatura"])[0], 404)
        voz = self.adjuntar(n, wav())
        self.assertEqual(self.pedir("GET", f"/adjuntos/{voz['id']}/miniatura")[0], 404)


class Puertos(CasoConServidor):
    def test_puerto_ocupado_usa_el_siguiente(self):
        otro = srv.crear_servidor(self.c, self.puerto)
        self.addCleanup(otro.server_close)
        self.assertGreater(otro.server_address[1], self.puerto)

    def test_reconoce_el_mismo_cuaderno_ya_abierto(self):
        self.assertTrue(srv.ya_abierto(self.c, self.puerto))
        self.assertFalse(srv.ya_abierto(Cuaderno(self.dir / "otro"), self.puerto))
        with unittest.mock.patch("webbrowser.open") as abrir:
            srv.servir(self.c, self.puerto)
        abrir.assert_called_once_with(f"http://127.0.0.1:{self.puerto}/")
        self.assertIn("ya están abiertas", self.consola.getvalue())


if __name__ == "__main__":
    unittest.main()
