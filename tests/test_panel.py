import http.client
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import panel
from main import construir_parser
from media_utils import MARCA_PROGRESO, VARIABLE_PROGRESO
from tests.ayudas import CasoConCarpeta, crear_foto


def esperar(condicion, segundos=60):
    limite = time.time() + segundos
    while time.time() < limite:
        if condicion():
            return True
        time.sleep(0.05)
    return False


class Esquema(unittest.TestCase):
    def test_comandos_y_opciones_salen_de_argparse(self):
        e = panel.ESQUEMA
        self.assertEqual(set(e), set(panel.COMANDOS_PANEL))
        todo = {o["dest"]: o for o in e["todo"]["opciones"]}
        self.assertEqual(todo["calidad"]["defecto"], 88)
        self.assertEqual((todo["calidad"]["min"], todo["calidad"]["max"]), (1, 100))
        self.assertEqual(todo["codec"]["opciones"], ["h264", "h265", "vp9"])
        self.assertTrue(todo["origen"]["posicional"])
        self.assertEqual(todo["destino"]["tipo"], "ruta")
        self.assertEqual(todo["caras"]["tipo"], "si_no")
        self.assertTrue(e["todo"]["simular"])
        self.assertFalse(e["galeria"]["simular"])

    def test_sin_opciones_del_servidor_ni_ocultas(self):
        for comando in panel.ESQUEMA.values():
            dests = {o["dest"] for o in comando["opciones"]}
            self.assertFalse(dests & {"servir", "puerto", "sin_navegador", "help", "sin_originales"})
        self.assertNotIn("panel", panel.ESQUEMA)

    def test_argv_sin_valores_por_defecto(self):
        argv = panel.construir_argv("todo", {
            "origen": r"C:\Mis fotos", "calidad": "88", "formato": "webp", "caras": True,
            "descargar_lugares": False, "descargar_modelos_caras": False,
            "crf": "", "sin_audio": False, "regenerar": True}, simular=True)
        # regenerar no es de "todo": se ignora
        self.assertEqual(argv, ["todo", r"C:\Mis fotos", "--simular", "--formato", "webp",
                                "--caras"])
        args = construir_parser().parse_args(argv)
        self.assertEqual((args.formato, args.calidad, args.simular), ("webp", 88, True))

    def test_galeria_completa_por_defecto_solo_en_el_panel(self):
        opciones = {o["dest"]: o for o in panel.ESQUEMA["galeria"]["opciones"]}
        for dest in ("caras", "descargar_lugares", "descargar_modelos_caras"):
            self.assertIs(opciones[dest]["defecto"], True)
        self.assertIs(opciones["regenerar"]["defecto"], False)
        self.assertEqual(panel.construir_argv("galeria", {"carpeta": "bib"}),
                         ["galeria", "bib", "--caras", "--descargar-lugares",
                          "--descargar-modelos-caras"])
        self.assertEqual(panel.construir_argv("galeria", {"carpeta": "bib", "caras": False}),
                         ["galeria", "bib", "--descargar-lugares", "--descargar-modelos-caras"])
        # La línea de comandos no cambia: hay que pedirlas
        args = construir_parser().parse_args(["todo", "x"])
        self.assertFalse(args.caras or args.descargar_lugares or args.descargar_modelos_caras)

    def test_posicional_obligatorio(self):
        with self.assertRaisesRegex(panel.ErrorPanel, "origen"):
            panel.construir_argv("fotos", {})
        with self.assertRaisesRegex(panel.ErrorPanel, "biblioteca"):
            panel.construir_argv("galeria", {"origen": "x"})
        with self.assertRaises(panel.ErrorPanel):
            panel.construir_argv("borrar_todo", {})

    def test_linea_de_comandos_entrecomilla(self):
        linea = panel.linea_de_comandos(["fotos", r"C:\Mis fotos"])
        self.assertIn('"C:\\Mis fotos"' if os.name == "nt" else "'C:\\Mis fotos'", linea)


class Validacion(CasoConCarpeta):
    def test_valores_fuera_de_rango(self):
        (self.dir / "o").mkdir()
        with self.assertRaisesRegex(panel.ErrorPanel, "entre 1 y 100"):
            panel.comprobar("fotos", {"origen": str(self.dir / "o"), "calidad": "150"})

    def test_carpetas(self):
        with self.assertRaisesRegex(panel.ErrorPanel, "no existe"):
            panel.comprobar("fotos", {"origen": str(self.dir / "nada")})
        (self.dir / "o").mkdir()
        with self.assertRaisesRegex(panel.ErrorPanel, "dentro del origen"):
            panel.comprobar("fotos", {"origen": str(self.dir / "o"),
                                      "destino": str(self.dir / "o" / "bib")})
        with self.assertRaisesRegex(panel.ErrorPanel, "Indica qué"):
            panel.comprobar("reorganizar", {"biblioteca": str(self.dir / "o")})

    def test_destino_por_defecto_y_fases(self):
        (self.dir / "movil").mkdir()
        r = panel.comprobar("todo", {"origen": str(self.dir / "movil")})
        self.assertEqual(Path(r["carpeta"]), (self.dir / "movil_organizados").resolve())
        self.assertFalse(r["biblioteca_existe"])
        self.assertEqual(r["fases"], ["fotos", "videos", "audio", "galeria"])
        r = panel.comprobar("todo", {"origen": str(self.dir / "movil"), "sin_audio": True,
                                     "renombrar_aproximadas": True}, simular=True)
        self.assertEqual(r["fases"], ["fotos", "videos", "reorganizar"])
        r = panel.comprobar("galeria", {"carpeta": str(self.dir / "movil")})
        self.assertEqual(r["fases"], ["galeria"])


class EventosDeProgreso(CasoConCarpeta):
    def test_solo_si_lo_lanza_el_panel(self):
        from fotos import procesar_fotos
        for i in range(3):
            crear_foto(self.dir / "o" / f"f{i}.jpg", color=(40 * i, 90, 160))
        procesar_fotos(self.dir / "o", self.dir / "a", True)
        self.assertNotIn(MARCA_PROGRESO, self.consola.getvalue())

        with mock.patch.dict(os.environ, {VARIABLE_PROGRESO: "1"}):
            procesar_fotos(self.dir / "o", self.dir / "b", False)
        eventos = [json.loads(l[len(MARCA_PROGRESO):]) for l in self.consola.getvalue().splitlines()
                   if l.startswith(MARCA_PROGRESO)]
        pasos = [(e["paso"], e["hecho"], e["total"]) for e in eventos if e["evento"] == "avance"]
        self.assertIn(("Analizando", 3, 3), pasos)
        self.assertIn(("Guardando", 0, 3), pasos)
        self.assertIn(("Guardando", 3, 3), pasos)


class EstadoDelTrabajo(unittest.TestCase):
    def trabajo(self, fases):
        previa = {"argv": ["todo", "x"], "linea": "python main.py todo x", "carpeta": "x",
                  "fases": fases}
        return panel.Trabajo(1, "todo", {}, False, previa)

    def evento(self, t, **e):
        t.procesar_linea(MARCA_PROGRESO + json.dumps(e))

    def test_fases_avance_y_resumen(self):
        t = self.trabajo(["fotos", "videos", "audio", "galeria"])
        self.evento(t, evento="inicio", fase="fotos")
        self.evento(t, evento="avance", fase="fotos", paso="Analizando", hecho=5, total=10,
                    archivo="a/b.jpg")
        t.procesar_linea("  [1/4] OK  b.jpg  ->  2024/05-Mayo/x.jpg")
        t.procesar_linea("  [2/4] ERROR c.jpg: roto")
        t.procesar_linea("AVISO: algo")
        estado = t.estado_json()
        fotos = estado["fases"][0]
        self.assertEqual((fotos["estado"], fotos["paso"], fotos["hecho"], fotos["total"]),
                         ("en_curso", "Analizando", 5, 10))
        self.assertEqual((estado["errores"], estado["avisos"]), (1, 1))
        self.assertEqual([n for n, _ in estado["registro"]["lineas"]], ["ok", "error", "aviso"])

        self.evento(t, evento="fin", fase="fotos", resumen={"procesados": 4})
        self.evento(t, evento="video", fase="videos", archivo="v.mp4", porcentaje=40)
        self.assertEqual(t.estado_json()["videos"], [{"archivo": "v.mp4", "porcentaje": 40}])
        self.evento(t, evento="video_fin", fase="videos", archivo="v.mp4")
        self.assertEqual(t.estado_json()["videos"], [])
        # Los vídeos no llegan a empezar (sin FFmpeg): al empezar el audio quedan omitidos
        self.evento(t, evento="inicio", fase="audio")
        estados = [f["estado"] for f in t.estado_json()["fases"]]
        self.assertEqual(estados, ["hecha", "omitida", "en_curso", "pendiente"])
        t.terminar(0)
        estado = t.estado_json()
        self.assertEqual(estado["estado"], "terminado")
        self.assertEqual([f["estado"] for f in estado["fases"]],
                         ["hecha", "omitida", "hecha", "omitida"])
        self.assertEqual(estado["fases"][0]["resumen"], {"procesados": 4})

    def test_error_y_registro_incremental(self):
        t = self.trabajo(["fotos"])
        for i in range(5):
            t.procesar_linea(f"línea {i}")
        t.procesar_linea("La carpeta de origen no existe: x")
        t.terminar(1)
        estado = t.estado_json(desde=3)
        self.assertEqual(estado["estado"], "error")
        self.assertEqual(estado["mensaje"], "La carpeta de origen no existe: x")
        self.assertEqual(estado["registro"]["desde"], 3)
        self.assertEqual(len(estado["registro"]["lineas"]), 3)
        self.assertEqual(estado["fases"][0]["estado"], "pendiente")

    def test_evento_mal_formado_va_al_registro(self):
        t = self.trabajo(["fotos"])
        t.procesar_linea(MARCA_PROGRESO + "{no es json")
        self.assertEqual(len(t.estado_json()["registro"]["lineas"]), 1)


class Ejecucion(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.panel = panel.Panel(self.dir / "prefs" / "panel.json")

    def test_importacion_real_con_progreso(self):
        for i in range(2):
            crear_foto(self.dir / "movil" / f"IMG_{i}.jpg", color=(60 * i, 100, 150))
        valores = {"origen": str(self.dir / "movil"), "destino": str(self.dir / "bib")}
        trabajo = self.panel.ejecutar("fotos", valores, simular=False)
        with self.assertRaisesRegex(panel.ErrorPanel, "en marcha"):
            self.panel.ejecutar("fotos", valores, simular=False)
        self.assertTrue(esperar(lambda: trabajo.estado not in ("en_marcha", "deteniendo")))

        estado = trabajo.estado_json()
        self.assertEqual(estado["estado"], "terminado", estado["registro"])
        fotos = estado["fases"][0]
        self.assertEqual((fotos["fase"], fotos["estado"]), ("fotos", "hecha"))
        self.assertEqual(fotos["resumen"]["procesados"], 2)
        self.assertEqual(fotos["total"], 2)
        self.assertTrue(any("RESUMEN" in texto for _, texto in estado["registro"]["lineas"]))
        self.assertNotIn(MARCA_PROGRESO, trabajo.registro_texto())
        self.assertEqual(len(list((self.dir / "bib").rglob("*.jpg"))), 2)

        # Preferencias e historial guardados (el archivo se escribe justo al terminar)
        def guardadas():
            try:
                datos = json.loads((self.dir / "prefs" / "panel.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):   # aún escribiéndose (os.replace en Windows)
                return None
            return datos if datos.get("historial") else None
        self.assertTrue(esperar(guardadas, 20))
        prefs = guardadas()
        self.assertEqual(prefs["comando"], "fotos")
        self.assertEqual(prefs["valores"]["origen"], str(self.dir / "movil"))
        self.assertIn(str((self.dir / "bib").resolve()), prefs["recientes"])
        self.assertEqual(prefs["historial"][0]["resumen"]["fotos"]["procesados"], 2)
        # Un panel nuevo continúa la numeración
        self.assertEqual(panel.Panel(self.dir / "prefs" / "panel.json").siguiente,
                         trabajo.numero + 1)

    def test_detener(self):
        previa = {"argv": [], "linea": "", "carpeta": str(self.dir), "fases": ["fotos"]}
        t = panel.Trabajo(1, "fotos", {}, False, previa)
        t.lanzar([sys.executable, "-u", "-c",
                  "import time\nwhile True:\n    print('trabajando', flush=True)\n    time.sleep(0.05)"])
        self.assertTrue(esperar(lambda: t.estado_json()["registro"]["total"] > 2, 20))
        with mock.patch.object(panel, "ESPERA_DETENER", 3):
            self.assertTrue(t.detener())
            self.assertFalse(t.detener())     # ya se está deteniendo
            self.assertTrue(esperar(lambda: t.estado == "detenido", 30))
        self.assertIsNotNone(t.proceso.poll())


class Http(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.servidor, self.panel = panel.crear_panel(
            puerto=0, intentos=1, panel=panel.Panel(self.dir / "panel.json"))
        self.puerto = self.servidor.server_address[1]
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        super().tearDown()

    def pedir(self, metodo, ruta, cuerpo=None, cabeceras=None):
        con = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        cabeceras = {"Content-Type": "application/json", **(cabeceras or {})}
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        con.request(metodo, ruta, body=datos, headers=cabeceras)
        r = con.getresponse()
        contenido = r.read()
        con.close()
        return r.status, contenido

    def test_pagina_y_esquema(self):
        estado, html = self.pedir("GET", "/")
        self.assertEqual(estado, 200)
        self.assertIn(b"/api/esquema", html)
        estado, cuerpo = self.pedir("GET", "/api/esquema")
        self.assertEqual(estado, 200)
        self.assertIn("todo", json.loads(cuerpo))
        estado, cuerpo = self.pedir("GET", "/api/estado")
        self.assertEqual(json.loads(cuerpo), {"trabajo": None})

    def test_comprobar(self):
        (self.dir / "movil").mkdir()
        estado, cuerpo = self.pedir("POST", "/api/comprobar", {
            "comando": "todo", "valores": {"origen": str(self.dir / "movil")}})
        r = json.loads(cuerpo)
        self.assertEqual(estado, 200)
        self.assertNotIn("error", r)
        self.assertIn("main.py todo", r["linea"])
        estado, cuerpo = self.pedir("POST", "/api/comprobar", {
            "comando": "todo", "valores": {"origen": str(self.dir / "nada")}})
        r = json.loads(cuerpo)
        self.assertIn("no existe", r["error"])
        self.assertIn("main.py todo", r["linea"])

    def test_errores_al_ejecutar(self):
        estado, cuerpo = self.pedir("POST", "/api/ejecutar", {"comando": "fotos", "valores": {}})
        self.assertEqual(estado, 400)
        self.assertIn("origen", json.loads(cuerpo)["error"])

    def test_solo_local(self):
        estado, _ = self.pedir("GET", "/api/esquema", cabeceras={"Host": "evil.example"})
        self.assertEqual(estado, 403)
        estado, _ = self.pedir("POST", "/api/detener", {}, {"Origin": "http://evil.example"})
        self.assertEqual(estado, 403)
        estado, _ = self.pedir("POST", "/api/detener", {}, {"Content-Type": "text/plain"})
        self.assertEqual(estado, 415)
        estado, _ = self.pedir("POST", "/api/no-existe", {})
        self.assertEqual(estado, 404)

    def test_galeria_inexistente(self):
        estado, cuerpo = self.pedir("POST", "/api/galeria", {"carpeta": str(self.dir)})
        self.assertEqual(estado, 400)
        self.assertIn("galería", json.loads(cuerpo)["error"])


if __name__ == "__main__":
    unittest.main()
