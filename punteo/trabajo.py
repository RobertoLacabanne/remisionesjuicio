"""
Procesamiento en segundo plano, con progreso real.

Leer un legajo lleva minutos y a veces horas: no puede colgar el navegador ni obligar a
nadie a abrir una terminal. Un hilo trabajador por caso, y un estado que la interfaz
consulta cada dos segundos.

Un solo hilo a propósito: Tesseract ya usa varios núcleos por página, SQLite escribe
mejor de a uno, y un trabajador único hace que el progreso sea comprensible en lugar de
ser una suma de barras que avanzan a saltos.
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import busqueda, config, db, foliatura, ocr
from .evidencia import deteccion, duplicados

ETAPAS = ("leyendo las páginas", "buscando la foliatura", "proponiendo evidencia",
          "buscando duplicados", "indexando para la búsqueda")


@dataclass
class Estado:
    estado: str = "inactivo"      # inactivo | corriendo | terminado | detenido | error
    etapa: str = ""
    hecho: int = 0
    total: int = 0
    mensaje: str = ""
    errores: list = field(default_factory=list)
    inicio: float | None = None
    fin: float | None = None
    resumen: dict = field(default_factory=dict)

    def como_dict(self) -> dict:
        d = asdict(self)
        d["segundos"] = round((self.fin or time.time()) - self.inicio, 1) if self.inicio else 0
        if self.hecho and self.total and self.estado == "corriendo":
            paso = (time.time() - self.inicio) / self.hecho
            d["faltan_segundos"] = round(paso * (self.total - self.hecho))
        else:
            d["faltan_segundos"] = None
        return d


class Procesador:
    """Un trabajador. `arrancar` no hace nada si ya hay algo corriendo."""

    def __init__(self, caso: str | None = None, ruta_base: Path | None = None):
        # De qué caso es este trabajador. Hace falta guardarlo porque el caso activo
        # vive por hilo: el hilo que arranca el procesamiento no es el que lo corre, así
        # que el trabajador tiene que volver a declararlo cuando empieza. Sin esto, las
        # imágenes de un caso terminan escritas en la carpeta de otro.
        self.caso = caso
        self.ruta_base = ruta_base
        self.estado = Estado()
        self._lock = threading.Lock()
        self._hilo: threading.Thread | None = None
        # Se levanta para pedir que pare. Se consulta entre página y página: cortar en
        # medio de una es lo que deja basura, cortar entre dos no cuesta nada.
        self._parar = threading.Event()

    def ocupado(self) -> bool:
        return bool(self._hilo and self._hilo.is_alive())

    def detener(self) -> dict:
        if not self.ocupado():
            return {"ok": False, "motivo": "no hay nada corriendo"}
        self._parar.set()
        with self._lock:
            self.estado.mensaje = "parando… se termina la página que está en curso"
        return {"ok": True}

    def arrancar(self) -> dict:
        with self._lock:
            if self.ocupado():
                return {"ok": False, "motivo": "ya hay un procesamiento en curso"}
            self._parar.clear()
            self.estado = Estado(estado="corriendo", etapa="preparando", inicio=time.time())
            self._hilo = threading.Thread(target=self._correr, daemon=True)
            self._hilo.start()
        return {"ok": True}

    # ── el trabajo ──
    def _correr(self) -> None:
        # LO PRIMERO. Este hilo recién nace y no tiene caso activo; sin esta línea,
        # `config.BASE` levanta SinCasoAbierto o, peor en una instalación vieja,
        # resuelve a otra carpeta.
        config.activar_caso(self.caso)
        cx = db.abrir(self.ruta_base)
        try:
            self._fase(ETAPAS[0], cx.execute(
                "SELECT COUNT(*) FROM pagina WHERE texto IS NULL").fetchone()[0])

            def avance(hechas, total):
                with self._lock:
                    self.estado.hecho, self.estado.total = hechas, total

            lectura = ocr.leer_caso(cx, avance=avance,
                                    seguir=lambda: not self._parar.is_set())
            if lectura.get("cortado"):
                return self._cortado(lectura["hechas"], lectura["paginas"])

            self._fase(ETAPAS[1], 1)
            fojas = foliatura.detectar(cx)
            self._avance()

            self._fase(ETAPAS[2], 1)
            evidencia = deteccion.detectar(cx)
            self._avance()

            self._fase(ETAPAS[3], 1)
            dups = duplicados.detectar(cx)
            self._avance()

            self._fase(ETAPAS[4], 1)
            indexadas = busqueda.reindexar(cx)
            self._avance()

            with self._lock:
                self.estado.estado = "terminado"
                self.estado.etapa = "listo"
                self.estado.fin = time.time()
                self.estado.resumen = {**lectura, **fojas, **evidencia, **dups,
                                       "paginas_indexadas": indexadas}
                partes = [f"{lectura['hechas']} páginas leídas"]
                if evidencia["creadas"]:
                    partes.append(f"{evidencia['creadas']} piezas propuestas")
                elif evidencia.get("motivo"):
                    partes.append(evidencia["motivo"])
                partes.append(f"{fojas['paginas_con_foja']} con foja detectada")
                if dups["propuestos"]:
                    partes.append(f"{dups['propuestos']} posibles duplicados")
                if lectura["fallidas"]:
                    partes.append(f"{lectura['fallidas']} páginas fallaron")
                self.estado.mensaje = " · ".join(partes)
        except Exception as e:
            traceback.print_exc()
            with self._lock:
                self.estado.estado = "error"
                self.estado.fin = time.time()
                self.estado.mensaje = f"{type(e).__name__}: {e}"
        finally:
            cx.close()

    def _cortado(self, hechas: int, total: int) -> None:
        """Lo paró una persona. No es un error y no se muestra como uno."""
        with self._lock:
            self.estado.estado = "detenido"
            self.estado.etapa = "parado"
            self.estado.fin = time.time()
            self.estado.mensaje = (
                f"Lo paraste en {hechas} de {total} páginas. Lo leído quedó guardado: "
                f"al procesar de nuevo retoma donde iba y no repite nada.")

    def _fase(self, etapa: str, total: int) -> None:
        with self._lock:
            self.estado.etapa = etapa
            self.estado.hecho = 0
            self.estado.total = total
            self.estado.inicio = self.estado.inicio or time.time()

    def _avance(self) -> None:
        with self._lock:
            self.estado.hecho += 1
