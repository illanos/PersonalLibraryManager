import http.client
import json
import threading
import unittest
from unittest import mock

import galeria
from fotos import OpcionesFotos, procesar_fotos
from servidor import crear_servidor
from tests.ayudas import CasoConCarpeta, crear_foto


class Indice(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        crear_foto(self.dir / "movil" / "IMG_0001.jpg", completa=True)
        crear_foto(self.dir / "movil" / "Screenshot_20240305-101112.jpg", tam=(300, 650),
                   fecha=None)
        self.bib = self.dir / "bib"
        procesar_fotos(self.dir / "movil", self.bib, False,
                       OpcionesFotos(hilos=1, conservar_originales=True))

    def test_genera_indice_con_metadatos_y_miniaturas(self):
        self.assertTrue(galeria.generar_galeria(self.bib))
        datos = json.loads((self.bib / "galeria.json").read_text(encoding="utf-8"))
        por_nombre = {e["nombre_original"]: e for e in datos["elementos"]}
        foto = por_nombre["IMG_0001.jpg"]
        self.assertEqual(foto["etiquetas"][:2], ["playa", "vacaciones"])
        self.assertEqual(foto["personas"], ["Ana"])
        self.assertEqual(foto["original"], "originales/2023/08-Agosto/IMG_0001.jpg")
        self.assertIn("Selfies", foto["auto"])
        self.assertIn("Con ubicación", foto["auto"])
        captura = por_nombre["Screenshot_20240305-101112.jpg"]
        self.assertEqual(set(captura["auto"]), {"Capturas", "Verticales"})
        for e in datos["elementos"]:
            self.assertTrue((self.bib / e["thumb"]).exists())
        self.assertTrue((self.bib / "galeria.html").exists())

    def test_regeneracion_incremental_y_limpieza(self):
        galeria.generar_galeria(self.bib)
        huerfana = self.bib / "_galeria" / "thumbs" / "huerfana.jpg"
        huerfana.write_bytes(b"x")
        with mock.patch("metadatos.leer_metadatos") as leer:
            _, stats = galeria.construir_indice(self.bib)
        leer.assert_not_called()
        self.assertEqual(stats["reutilizados"], 2)
        self.assertFalse(huerfana.exists())

    def test_foto_y_video_con_el_mismo_nombre_no_comparten_miniatura(self):
        self.assertNotEqual(galeria._clave("2024/05/a.jpg"), galeria._clave("2024/05/a.mp4"))

    def test_etiquetas_automaticas(self):
        auto = galeria.etiquetas_automaticas
        self.assertEqual(auto({"nombre_original": "IMG-20250402-WA0007.jpg"}), ["WhatsApp"])
        self.assertEqual(auto({"ancho": 8000, "alto": 2000}), ["Panorámicas"])
        self.assertEqual(auto({"ancho": 1080, "alto": 2400}), ["Verticales"])
        self.assertEqual(auto({"fuente_fecha": "archivo", "valoracion": 3}),
                         ["Con estrellas", "Fecha dudosa"])


class Servidor(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        (self.dir / "video.mp4").write_bytes(bytes(range(256)) * 4)
        self.servidor = crear_servidor(self.dir, puerto=0, intentos=1)
        self.puerto = self.servidor.server_address[1]
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        super().tearDown()

    def pedir(self, metodo, ruta, cuerpo=None, cabeceras=None):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=5)
        conexion.request(metodo, ruta, body=cuerpo, headers=cabeceras or {})
        respuesta = conexion.getresponse()
        datos = respuesta.read()
        conexion.close()
        return respuesta, datos

    def test_peticiones_parciales(self):
        r, datos = self.pedir("GET", "/video.mp4", cabeceras={"Range": "bytes=10-19"})
        self.assertEqual(r.status, 206)
        self.assertEqual(r.getheader("Content-Range"), "bytes 10-19/1024")
        self.assertEqual(datos, bytes(range(10, 20)))
        r, datos = self.pedir("GET", "/video.mp4", cabeceras={"Range": "bytes=-4"})
        self.assertEqual(datos, bytes(range(252, 256)))
        r, _ = self.pedir("GET", "/video.mp4", cabeceras={"Range": "bytes=5000-"})
        self.assertEqual(r.status, 416)
        r, datos = self.pedir("GET", "/video.mp4")
        self.assertEqual((r.status, len(datos), r.getheader("Accept-Ranges")), (200, 1024, "bytes"))

    def test_rechaza_host_ajeno(self):
        r, _ = self.pedir("GET", "/video.mp4", cabeceras={"Host": "evil.example"})
        self.assertEqual(r.status, 403)

    def test_favoritos(self):
        json_ = {"Content-Type": "application/json"}
        r, _ = self.pedir("POST", "/api/favoritos", b'["b.jpg", "a.jpg", "a.jpg"]', json_)
        self.assertEqual(r.status, 200)
        _, datos = self.pedir("GET", "/api/favoritos")
        self.assertEqual(json.loads(datos), ["a.jpg", "b.jpg"])
        r, _ = self.pedir("POST", "/api/favoritos", b"[]", {"Content-Type": "text/plain"})
        self.assertEqual(r.status, 415)
        r, _ = self.pedir("POST", "/api/favoritos", b"[]",
                          {**json_, "Origin": "https://evil.example"})
        self.assertEqual(r.status, 403)
        r, _ = self.pedir("POST", "/api/favoritos", b'{"no": "lista"}', json_)
        self.assertEqual(r.status, 400)


if __name__ == "__main__":
    unittest.main()
