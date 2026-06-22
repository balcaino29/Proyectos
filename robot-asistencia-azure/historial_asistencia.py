"""
historial_asistencia.py
=======================
Módulo de gestión del historial mensual de asistencia.
Persiste los datos en un archivo JSON local y evalúa las reglas de alerta.

Reglas de alerta (solo aplican a inasistencias SIN justificación):
  - ALERTA_LUNES:       2 o más lunes de inasistencia en el mes
  - ALERTA_MES:         3 o más inasistencias en el mes
  - ALERTA_CONSECUTIVA: 2 días hábiles seguidos de inasistencia
                        (viernes + lunes cuenta como consecutivo;
                         los feriados legales chilenos se excluyen)

Corrección retroactiva:
  Si un día se registra una inasistencia y luego se detecta un permiso
  para esa misma fecha, corregir_a_justificado() mueve la fecha de
  'inasistencias' → 'con_permiso' automáticamente.
"""

import json
import os
import logging
from datetime import datetime, date, timedelta

try:
    import holidays as holiday_lib
    _HOLIDAYS_DISPONIBLE = True
except ImportError:
    _HOLIDAYS_DISPONIBLE = False
    logging.warning(
        "Librería 'holidays' no instalada. Los feriados NO serán excluidos. "
        "Ejecuta: pip install holidays"
    )

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  CONSTANTES
# --------------------------------------------------------------------------- #
LIMITE_LUNES      = 2   # lunes sin justificación → alerta
LIMITE_MES        = 3   # inasistencias en el mes → alerta
LIMITE_CONSECUTIV = 2   # días hábiles seguidos   → alerta

FMT = "%d/%m/%Y"


# --------------------------------------------------------------------------- #
#  HELPERS DE CALENDARIO
# --------------------------------------------------------------------------- #
def _feriados_chile(año: int) -> set:
    """Retorna un set de objetos date con los feriados legales de Chile para el año dado."""
    if not _HOLIDAYS_DISPONIBLE:
        return set()
    return set(holiday_lib.Chile(years=año).keys())


def es_dia_habil(d: datetime | date) -> bool:
    """
    Devuelve True si 'd' es un día hábil:
    lunes a viernes y que NO sea feriado legal chileno.
    """
    if isinstance(d, datetime):
        d = d.date()
    if d.weekday() >= 5:          # sábado o domingo
        return False
    feriados = _feriados_chile(d.year)
    return d not in feriados


def siguiente_habil(d: datetime) -> datetime:
    """
    Retorna el siguiente día hábil (lun-vie, sin feriados) después de 'd'.
    Así viernes→lunes se considera consecutivo, pero si el lunes es feriado
    se avanza hasta el próximo día hábil real.
    """
    # Calculamos feriados para el año actual y el siguiente por si cruzamos año
    feriados = _feriados_chile(d.year) | _feriados_chile(d.year + 1)
    sig = d + timedelta(days=1)
    while sig.weekday() >= 5 or sig.date() in feriados:
        sig += timedelta(days=1)
    return sig


# --------------------------------------------------------------------------- #
#  CLASE PRINCIPAL
# --------------------------------------------------------------------------- #
class HistorialAsistencia:
    """
    Mantiene un archivo JSON con la siguiente estructura:

    {
      "<RUT_CLEAN>": {
        "<YYYY-MM>": {
          "nombre":         "Juan Pérez",
          "area":           "Administración",
          "atrasos":        ["10/06/2025", "12/06/2025"],
          "inasistencias":  ["09/06/2025", "16/06/2025"],   # sin permiso
          "con_permiso":    ["23/06/2025"]                   # justificadas
        }
      }
    }
    """

    def __init__(self, ruta_archivo: str):
        self.ruta = ruta_archivo
        self._datos: dict = self._cargar()

    # ---------------------------------------------------------------------- #
    #  I/O
    # ---------------------------------------------------------------------- #
    def _cargar(self) -> dict:
        if os.path.exists(self.ruta):
            try:
                with open(self.ruta, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error leyendo historial: {e}. Se creará uno nuevo.")
        return {}

    def guardar(self):
        try:
            with open(self.ruta, 'w', encoding='utf-8') as f:
                json.dump(self._datos, f, ensure_ascii=False, indent=4)
            logger.info(f"Historial guardado en {self.ruta}")
        except Exception as e:
            logger.error(f"Error guardando historial: {e}")

    # ---------------------------------------------------------------------- #
    #  ACCESO / ESCRITURA
    # ---------------------------------------------------------------------- #
    def _periodo(self, fecha_str: str) -> str:
        """Convierte 'DD/MM/YYYY' → 'YYYY-MM'."""
        return datetime.strptime(fecha_str, FMT).strftime("%Y-%m")

    def _registro(self, rut: str, periodo: str) -> dict:
        self._datos.setdefault(rut, {})
        self._datos[rut].setdefault(periodo, {
            "nombre":        "",
            "area":          "",
            "atrasos":       [],
            "inasistencias": [],
            "con_permiso":   []
        })
        return self._datos[rut][periodo]

    # ---------------------------------------------------------------------- #
    #  REGISTRO DE EVENTOS
    # ---------------------------------------------------------------------- #
    def registrar_atraso(self, rut: str, fecha_str: str, nombre: str = "", area: str = ""):
        p = self._periodo(fecha_str)
        r = self._registro(rut, p)
        r["nombre"] = nombre or r["nombre"]
        r["area"]   = area   or r["area"]
        if fecha_str not in r["atrasos"]:
            r["atrasos"].append(fecha_str)
            logger.debug(f"[ATRASO]       {rut} | {fecha_str}")

    def registrar_inasistencia(self, rut: str, fecha_str: str,
                                nombre: str = "", area: str = "",
                                con_permiso: bool = False):
        p = self._periodo(fecha_str)
        r = self._registro(rut, p)
        r["nombre"] = nombre or r["nombre"]
        r["area"]   = area   or r["area"]

        if con_permiso:
            # Si esta fecha ya estaba como injustificada, se corrige
            self.corregir_a_justificado(rut, fecha_str)
        else:
            # Solo registrar como injustificada si NO está ya justificada
            if fecha_str not in r["con_permiso"] and fecha_str not in r["inasistencias"]:
                r["inasistencias"].append(fecha_str)
                logger.debug(f"[INASISTENCIA] {rut} | {fecha_str}")

    def corregir_a_justificado(self, rut: str, fecha_str: str):
        """
        Mueve la fecha de 'inasistencias' → 'con_permiso' si existe.
        Se invoca cuando se detecta un permiso para una fecha ya registrada
        como falta injustificada (ej: permiso cargado retroactivamente).
        """
        p = self._periodo(fecha_str)
        r = self._registro(rut, p)

        if fecha_str in r["inasistencias"]:
            r["inasistencias"].remove(fecha_str)
            logger.info(f"[CORRECCIÓN]   {rut} | {fecha_str} — falta reemplazada por permiso")

        if fecha_str not in r["con_permiso"]:
            r["con_permiso"].append(fecha_str)
            logger.debug(f"[JUSTIFICADO]  {rut} | {fecha_str}")

    # ---------------------------------------------------------------------- #
    #  CONSULTAS SIMPLES
    # ---------------------------------------------------------------------- #
    def get_atrasos_mes(self, rut: str, periodo: str) -> list:
        return sorted(
            self._datos.get(rut, {}).get(periodo, {}).get("atrasos", []),
            key=lambda d: datetime.strptime(d, FMT)
        )

    def get_inasistencias_mes(self, rut: str, periodo: str) -> list:
        return sorted(
            self._datos.get(rut, {}).get(periodo, {}).get("inasistencias", []),
            key=lambda d: datetime.strptime(d, FMT)
        )

    # ---------------------------------------------------------------------- #
    #  EVALUACIÓN DE ALERTAS
    # ---------------------------------------------------------------------- #
    def evaluar_alertas(self, rut: str, periodo: str) -> list:
        """
        Devuelve lista de alertas activas para el RUT en el período dado.
        Cada alerta: {"codigo": str, "mensaje": str, "fechas": list}
        Solo considera inasistencias injustificadas y excluye feriados.
        """
        inasistencias = self.get_inasistencias_mes(rut, periodo)
        alertas = []

        # ── ALERTA 1: Lunes reincidente ────────────────────────────────── #
        lunes_ausentes = [
            f for f in inasistencias
            if datetime.strptime(f, FMT).weekday() == 0
        ]
        if len(lunes_ausentes) >= LIMITE_LUNES:
            alertas.append({
                "codigo":  "ALERTA_LUNES",
                "mensaje": f"⚠️ {len(lunes_ausentes)} lunes de inasistencia en el mes",
                "fechas":  lunes_ausentes
            })

        # ── ALERTA 2: Inasistencias acumuladas ────────────────────────── #
        if len(inasistencias) >= LIMITE_MES:
            alertas.append({
                "codigo":  "ALERTA_MES",
                "mensaje": f"⚠️ {len(inasistencias)} inasistencias acumuladas en el mes",
                "fechas":  inasistencias
            })

        # ── ALERTA 3: Días hábiles consecutivos ───────────────────────── #
        # Usa siguiente_habil() que ya excluye feriados.
        # Viernes + lunes siguiente = consecutivo (fin de semana no rompe),
        # pero si el lunes es feriado se espera al siguiente día hábil real.
        if len(inasistencias) >= LIMITE_CONSECUTIV:
            fechas_dt = sorted(datetime.strptime(f, FMT) for f in inasistencias)
            for i in range(len(fechas_dt) - 1):
                if fechas_dt[i + 1] == siguiente_habil(fechas_dt[i]):
                    par = [fechas_dt[i].strftime(FMT), fechas_dt[i + 1].strftime(FMT)]
                    ya_existe = any(
                        a["codigo"] == "ALERTA_CONSECUTIVA" and set(par) <= set(a["fechas"])
                        for a in alertas
                    )
                    if not ya_existe:
                        alertas.append({
                            "codigo":  "ALERTA_CONSECUTIVA",
                            "mensaje": "⚠️ 2 días hábiles consecutivos de inasistencia",
                            "fechas":  par
                        })

        return alertas

    # ---------------------------------------------------------------------- #
    #  RESUMEN PARA EMAIL
    # ---------------------------------------------------------------------- #
    def resumen_persona(self, rut: str, periodo: str) -> dict:
        """Resumen completo de un colaborador para incluir en el correo."""
        return {
            "atrasos":       self.get_atrasos_mes(rut, periodo),
            "inasistencias": self.get_inasistencias_mes(rut, periodo),
            "alertas":       self.evaluar_alertas(rut, periodo)
        }