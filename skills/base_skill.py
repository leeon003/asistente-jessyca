from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseSkill(ABC):
    """
    Clase base abstracta para todas las habilidades (skills) de Jessyca.
    """

    def __init__(self, nombre: str, nivel_riesgo: int = 1):
        """
        :param nombre: Nombre identificador de la skill.
        :param nivel_riesgo: 1 = bajo (auto-ejecuta), 2 = medio (confirma una vez), 3 = alto (siempre confirma explícito).
        """
        self.nombre = nombre
        self.nivel_riesgo = nivel_riesgo

    @abstractmethod
    def ejecutar(self, parametros: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ejecuta la acción correspondiente a la skill.

        :param parametros: Diccionario con los parámetros requeridos para la ejecución.
        :return: Diccionario con el formato {"exito": bool, "mensaje": str}
        """
        pass

    def descripcion(self) -> str:
        """
        Retorna la descripción de lo que realiza la skill.
        Por defecto utiliza el docstring de la clase si está definido.
        """
        if self.__doc__:
            return self.__doc__.strip()
        return f"Skill {self.nombre}"
