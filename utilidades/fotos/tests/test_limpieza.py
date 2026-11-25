"""Limpiar repetidas: grupos, mejor copia, papelera, reimportación y servidor."""

import http.client
import json
import sqlite3
import threading
import unittest
from contextlib import closing
from pathlib import Path

from PIL import Image

from exportador import galeria
from exportador import servidor
from exportador.catalogo import ruta_catalogo
from exportador.fotos import OpcionesFotos, procesar_fotos
from exportador.limpieza import ErrorLimpieza, Limpieza, RutaNoValida, elegir_mejor
from tests.ayudas import CasoConCarpeta
from tests.test_similares import escena


def huella(carpeta: Path) -> dict:
    return {p.relative_to(carpeta).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in carpeta.rglob("*") if p.is_file()}


class MejorCopia(unittest.TestCase):
    def foto(self, src, ancho=1000, alto=750, bytes_=100, **extra):
        return {"src": src, "ancho": ancho, "alto": alto, "bytes": bytes_, **extra}

    def test_mas_resolucion_gana(self):
        mejor, motivo = elegir_mejor([self.foto("a.jpg", 800, 600, 900),
                                      self.foto("b.jpg", 4000, 3000, 100)])
        self.assertEqual((mejor, motivo), ("b.jpg", "más resolución"))

    def test_misma_resolucion_exif_y_no_whatsapp(self):
        fotos = [self.foto("WhatsApp/x.jpg", bytes_=500, ambito="whatsapp"),
                 self.foto("2024/x.jpg", bytes_=400, camara="Pixel 8")]
        self.assertEqual(elegir_mejor(fotos), ("2024/x.jpg", "tiene EXIF de cámara"))
        fotos = [self.foto("WhatsApp/a.jpg", ambito="whatsapp"), self.foto("2024/a.jpg")]
        self.assertEqual(elegir_mejor(fotos), ("2024/a.jpg", "no viene de WhatsApp"))

    def test_sent_pierde_y_luego_el_peso(self):
        fotos = [self.foto("WhatsApp/1.jpg", origen=r"C:\m\WhatsApp Images\Sent\1.jpg", ambito="whatsapp"),
                 self.foto("WhatsApp/2.jpg", origen=r"C:\m\WhatsApp Images\2.jpg", ambito="whatsapp")]
        self.assertEqual(elegir_mejor(fotos)[0], "WhatsApp/2.jpg")
        fotos = [self.foto("a.jpg", bytes_=10, bytes_origen=900), self.foto("b.jpg", bytes_=20)]
        self.assertEqual(elegir_mejor(fotos), ("a.jpg", "más peso (menos comprimida)"))


class Biblioteca(CasoConCarpeta):
    """Origen con una foto de cámara y dos copias de WhatsApp (una en Sent/)."""

    def setUp(self):
        super().setUp()
        self.origen, self.bib = self.dir / "movil", self.dir / "bib"
        camara = escena(self.origen / "DCIM" / "IMG_0001.jpg", 3, fecha="2024:05:12 10:00:00")
        with Image.open(camara) as im:
            pequena = im.resize((800, 600))
        (self.origen / "WhatsApp Images" / "Sent").mkdir(parents=True)
        pequena.save(self.origen / "WhatsApp Images" / "IMG-20240512-WA0001.jpg", quality=70)
        pequena.save(self.origen / "WhatsApp Images" / "Sent" / "IMG-20240512-WA0002.jpg", quality=60)
        escena(self.origen / "DCIM" / "otra.jpg", 4, fecha="2024:05:13 10:00:00")
        self.importar()
        galeria.generar_galeria(self.bib)
        self.huella_origen = huella(self.origen)
        self.limpieza = Limpieza(self.bib)

    def tearDown(self):
        # La carpeta de origen nunca se toca, pase lo que pase en el test
        self.assertEqual(huella(self.origen), self.huella_origen)
        super().tearDown()

    def importar(self):
        return procesar_fotos(self.origen, self.bib, False, OpcionesFotos(hilos=2))

    def srcs_galeria(self) -> set:
        datos = json.loads((self.bib / "galeria.json").read_text(encoding="utf-8"))
        return {e["src"] for e in datos["elementos"]}

    def grupo(self) -> dict:
        grupos = self.limpieza.grupos()["grupos"]
        self.assertEqual(len(grupos), 1)
        return grupos[0]

    def decidir_propuesta(self):
        g = self.grupo()
        srcs = [f["src"] for f in g["fotos"]]
        quitar = [s for s in srcs if s != g["mejor"]]
        return g, srcs, quitar, self.limpieza.decidir(srcs, quitar)


class Grupos(Biblioteca):
    def test_agrupa_y_propone_la_de_camara(self):
        g = self.grupo()
        self.assertEqual(len(g["fotos"]), 3)
        self.assertTrue(g["mejor"].startswith("2024/"), g["mejor"])   # no la de WhatsApp/
        self.assertEqual(g["motivo"], "más resolución")
        por = {f["src"]: f for f in g["fotos"]}
        self.assertEqual(por[g["mejor"]]["nombre_original"], "IMG_0001.jpg")
        self.assertTrue(por[g["mejor"]]["carpeta_origen"].endswith("DCIM"))
        self.assertEqual(sum(f["rasgos"]["sent"] for f in g["fotos"]), 1)
        self.assertGreater(g["liberable"], 0)

    def test_umbral_cero_es_mas_estricto(self):
        self.assertLessEqual(len(self.limpieza.grupos(umbral=0)["grupos"]), 1)
        self.assertEqual(self.limpieza.grupos(umbral=999)["umbral"], 24)


class Papelera(Biblioteca):
    def test_quitar_mueve_a_la_papelera_y_saca_de_la_galeria(self):
        _, srcs, quitar, r = self.decidir_propuesta()
        self.assertEqual(r["quitadas"], 2)
        for s in quitar:
            self.assertFalse((self.bib / s).exists())
            self.assertTrue((self.bib / ".exportador" / "papelera" / s).is_file())
        self.assertFalse(set(quitar) & self.srcs_galeria())
        self.assertEqual(self.limpieza.grupos()["grupos"], [])
        self.assertEqual(self.limpieza.grupos()["papelera"]["fotos"], 2)
        # Las decisiones quedan guardadas en disco (para seguir otro día)
        datos = json.loads((self.bib / ".exportador" / "limpieza.json").read_text(encoding="utf-8"))
        self.assertEqual(datos["historial"][-1]["quitar"], sorted(quitar))

    def test_reimportar_no_trae_lo_descartado(self):
        _, _, quitar, _ = self.decidir_propuesta()
        stats = self.importar()
        self.assertEqual((stats["procesados"], stats.get("descartadas")), (0, 2))
        for s in quitar:
            self.assertFalse((self.bib / s).exists())
        # Ni aunque se vacíe la papelera
        self.limpieza.vaciar("VACIAR")
        stats = self.importar()
        self.assertEqual((stats["procesados"], stats.get("descartadas")), (0, 2))

    def test_copia_identica_en_otra_ruta_tampoco_vuelve(self):
        _, _, quitar, _ = self.decidir_propuesta()
        sent = self.origen / "WhatsApp Images" / "Sent" / "IMG-20240512-WA0002.jpg"
        otra = self.dir / "otro_movil"
        otra.mkdir()
        (otra / "copia.jpg").write_bytes(sent.read_bytes())
        stats = procesar_fotos(otra, self.bib, False, OpcionesFotos(hilos=1))
        self.assertEqual((stats["procesados"], stats.get("descartadas")), (0, 1))

    def test_restaurar_devuelve_a_su_sitio(self):
        _, _, quitar, _ = self.decidir_propuesta()
        r = self.limpieza.restaurar()
        self.assertEqual(sorted(r["restauradas"]), sorted(quitar))
        for s in quitar:
            self.assertTrue((self.bib / s).is_file())
        self.assertTrue(set(quitar) <= self.srcs_galeria())
        self.assertFalse((self.bib / ".exportador" / "papelera").exists()
                         and any((self.bib / ".exportador" / "papelera").rglob("*.jpg")))
        self.assertEqual(len(self.limpieza.grupos()["grupos"]), 1)   # vuelve a salir
        stats = self.importar()
        self.assertEqual((stats["procesados"], stats["ya_importados"]), (0, 4))
        with closing(sqlite3.connect(ruta_catalogo(self.bib))) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM descartadas").fetchone()[0], 0)

    def test_restaurar_una_si_su_sitio_esta_ocupado(self):
        _, _, quitar, _ = self.decidir_propuesta()
        (self.bib / quitar[0]).write_bytes(b"otra cosa")
        r = self.limpieza.restaurar([quitar[0]])
        self.assertNotEqual(r["restauradas"], [quitar[0]])
        self.assertTrue((self.bib / r["restauradas"][0]).is_file())
        self.assertEqual((self.bib / quitar[0]).read_bytes(), b"otra cosa")

    def test_vaciar_exige_confirmacion(self):
        _, _, quitar, _ = self.decidir_propuesta()
        with self.assertRaises(ErrorLimpieza):
            self.limpieza.vaciar("si")
        self.assertTrue((self.bib / ".exportador" / "papelera" / quitar[0]).is_file())
        r = self.limpieza.vaciar("VACIAR")
        self.assertEqual(r["borradas"], 2)
        self.assertFalse(any((self.bib / ".exportador" / "papelera").rglob("*.jpg"))
                         if (self.bib / ".exportador" / "papelera").exists() else False)
        self.assertEqual(self.limpieza.contenido_papelera()["fotos"], [])

    def test_deshacer_la_ultima_decision(self):
        g, _, quitar, _ = self.decidir_propuesta()
        r = self.limpieza.deshacer()
        self.assertEqual(sorted(r["restauradas"]), sorted(quitar))
        self.assertEqual(self.grupo()["id"], g["id"])
        with self.assertRaises(ErrorLimpieza):
            self.limpieza.deshacer()

    def test_no_son_repetidas_no_vuelve_a_salir_salvo_deshacer(self):
        g = self.grupo()
        antes = huella(self.bib / "2024") | huella(self.bib / "WhatsApp")
        self.limpieza.no_repetidas([f["src"] for f in g["fotos"]])
        self.assertEqual(self.limpieza.grupos()["grupos"], [])
        self.assertEqual(huella(self.bib / "2024") | huella(self.bib / "WhatsApp"), antes)
        self.limpieza.deshacer()
        self.assertEqual(self.grupo()["id"], g["id"])

    def test_conservar_parte_del_grupo_lo_da_por_revisado(self):
        g = self.grupo()
        srcs = [f["src"] for f in g["fotos"]]
        sent = next(f["src"] for f in g["fotos"] if f["rasgos"]["sent"])
        self.limpieza.decidir(srcs, [sent])
        self.assertEqual(self.limpieza.grupos()["grupos"], [])


class SinCatalogo(CasoConCarpeta):
    def test_consultar_no_crea_nada(self):
        escena(self.dir / "2024" / "a.jpg", 5)
        galeria.generar_galeria(self.dir)
        limpieza = Limpieza(self.dir)
        self.assertEqual(limpieza.grupos()["grupos"], [])
        self.assertEqual(limpieza.contenido_papelera()["fotos"], [])
        self.assertFalse((self.dir / ".exportador").exists())


class Seguridad(Biblioteca):
    def test_rutas_fuera_de_la_biblioteca_se_rechazan(self):
        fuera = self.dir / "fuera.jpg"
        escena(fuera, 1)
        malas = ["../fuera.jpg", str(fuera), fuera.as_posix(), "/etc/passwd", "C:/Windows/x.jpg",
                 "2024\\..\\..\\fuera.jpg", ".exportador/catalogo.sqlite",
                 "_galeria/thumbs/x.jpg", "originales/x.jpg", "2024/./x.jpg", "", None,
                 "galeria.json", "2024//x.jpg"]
        for mala in malas:
            with self.subTest(mala=mala), self.assertRaises(RutaNoValida):
                self.limpieza.validar(mala)
        g = self.grupo()
        with self.assertRaises(RutaNoValida):
            self.limpieza.decidir([g["mejor"], "../fuera.jpg"], ["../fuera.jpg"])
        self.assertTrue(fuera.is_file())

    def test_no_se_puede_quitar_todo_ni_lo_ajeno_al_grupo(self):
        g = self.grupo()
        srcs = [f["src"] for f in g["fotos"]]
        with self.assertRaises(ErrorLimpieza):
            self.limpieza.decidir(srcs, srcs)
        otra = next(s for s in self.srcs_galeria() if s not in srcs)
        with self.assertRaises(ErrorLimpieza):
            self.limpieza.decidir(srcs[:2], [otra])
        for s in srcs + [otra]:
            self.assertTrue((self.bib / s).is_file())

    def test_un_archivo_de_origen_dentro_de_la_biblioteca_no_se_toca(self):
        dentro = self.bib / "importar" / "x.jpg"
        escena(dentro, 7)
        procesar_fotos(self.bib / "importar", self.bib, False, OpcionesFotos(hilos=1))
        with self.assertRaises(RutaNoValida), self.limpieza._db() as db:
            self.limpieza._no_es_origen(db, [dentro.resolve()])
        self.assertTrue(dentro.is_file())


class Servidor(Biblioteca):
    def setUp(self):
        super().setUp()
        self.servidor = servidor.crear_servidor(self.bib, puerto=0, intentos=1)
        self.puerto = self.servidor.server_address[1]
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        super().tearDown()

    def pedir(self, metodo, ruta, cuerpo=None, **cabeceras):
        con = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
            base = {"Host": f"127.0.0.1:{self.puerto}"}
            if datos is not None:
                base["Content-Type"] = "application/json"
            con.request(metodo, ruta, body=datos, headers={**base, **cabeceras})
            r = con.getresponse()
            texto = r.read()
            try:
                return r.status, json.loads(texto)
            except ValueError:
                return r.status, texto
        finally:
            con.close()

    def propias(self):
        return {"Origin": f"http://127.0.0.1:{self.puerto}", "Sec-Fetch-Site": "same-origin",
                "X-Exportador-Token": servidor.TOKEN_LIMPIEZA}

    def test_pagina_y_grupos(self):
        estado, html = self.pedir("GET", "/limpiar.html")
        self.assertEqual(estado, 200)
        self.assertIn(b"Limpiar repetidas", html)
        estado, datos = self.pedir("GET", "/api/limpieza/grupos?umbral=10")
        self.assertEqual((estado, datos["umbral"], len(datos["grupos"])), (200, 10, 1))
        self.assertEqual(datos["token"], servidor.TOKEN_LIMPIEZA)

    def test_csrf_y_rutas(self):
        _, datos = self.pedir("GET", "/api/limpieza/grupos")
        g = datos["grupos"][0]
        srcs = [f["src"] for f in g["fotos"]]
        quitar = [s for s in srcs if s != g["mejor"]]
        cuerpo = {"grupo": srcs, "quitar": quitar}
        sin_token = {**self.propias(), "X-Exportador-Token": "otro"}
        ajena = {**self.propias(), "Origin": "http://evil.example"}
        otro_puerto = {**self.propias(), "Origin": "http://127.0.0.1:1"}
        cruzada = {**self.propias(), "Sec-Fetch-Site": "cross-site"}
        for cabeceras in (sin_token, ajena, otro_puerto, cruzada, {"X-Exportador-Token": "x"}):
            with self.subTest(cabeceras=cabeceras):
                estado, _ = self.pedir("POST", "/api/limpieza/decidir", cuerpo, **cabeceras)
                self.assertEqual(estado, 403)
        estado, _ = self.pedir("POST", "/api/limpieza/decidir", cuerpo,
                               **{**self.propias(), "Host": "evil.example"})
        self.assertEqual(estado, 403)
        for s in srcs:
            self.assertTrue((self.bib / s).is_file())

        estado, r = self.pedir("POST", "/api/limpieza/decidir",
                               {"grupo": [srcs[0], "../movil/DCIM/otra.jpg"],
                                "quitar": ["../movil/DCIM/otra.jpg"]}, **self.propias())
        self.assertEqual(estado, 400, r)
        estado, r = self.pedir("POST", "/api/limpieza/vaciar", {"confirmar": "no"}, **self.propias())
        self.assertEqual(estado, 409)

        estado, r = self.pedir("POST", "/api/limpieza/decidir", cuerpo, **self.propias())
        self.assertEqual((estado, r["quitadas"]), (200, 2))
        estado, r = self.pedir("GET", "/api/limpieza/papelera")
        self.assertEqual(len(r["fotos"]), 2)
        estado, r = self.pedir("POST", "/api/limpieza/deshacer", {}, **self.propias())
        self.assertEqual((estado, len(r["restauradas"])), (200, 2))


if __name__ == "__main__":
    unittest.main()


class ParecidasIncrementales(unittest.TestCase):
    """`actualizar_parecidas` agrupa igual que recalcularlo todo con `marcar_parecidas`."""

    @staticmethod
    def _particion(elementos):
        grupos = {}
        for e in elementos:
            if e.get("parecidas"):
                grupos.setdefault(e["parecidas"], set()).add(e["src"])
        return sorted(sorted(g) for g in grupos.values())

    def test_quitar_y_restaurar(self):
        import copy
        import random
        from exportador.galeria import actualizar_parecidas, marcar_parecidas
        azar = random.Random(7)
        bases = [azar.getrandbits(128) for _ in range(40)]
        elementos = []
        for i in range(400):   # familias de hashes parecidos entre sí
            h = azar.choice(bases)
            for _ in range(azar.randint(0, 8)):
                h ^= 1 << azar.randrange(128)
            elementos.append({"src": f"f{i}.jpg", "dhash": f"{h:032x}", "ancho": 4, "alto": 3})
        marcar_parecidas(elementos)
        quitados = azar.sample(elementos, 60)
        restantes = [e for e in elementos if e not in quitados]
        actualizar_parecidas(restantes, {e.get("parecidas") for e in quitados})
        referencia = copy.deepcopy(restantes)
        marcar_parecidas(referencia)
        self.assertEqual(self._particion(restantes), self._particion(referencia))
        vuelven = [dict(e, parecidas=None) for e in quitados[:30]]
        restantes += vuelven
        actualizar_parecidas(restantes, nuevos=[e["src"] for e in vuelven])
        referencia = copy.deepcopy(restantes)
        marcar_parecidas(referencia)
        self.assertEqual(self._particion(restantes), self._particion(referencia))
