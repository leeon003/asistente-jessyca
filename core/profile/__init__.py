"""Sub-sistema de Perfil de Usuario y Personalización (Fase 22).

Exporta las clases, modelos y utilidades para gestionar preferencias persistentes,
estilos de comunicación, aplicaciones habituales, hábitos de interacción y protocolo
de consentimiento explícito.

INVARIANTE DE SEGURIDAD:
PROFILE != AUTHORIZATION
"""

from core.profile.preference_detector import PreferenceDetector
from core.profile.profile_models import (
    ConsentStatus,
    InformationScopeType,
    ProfileCategory,
    ProfilePreferenceItem,
)
from core.profile.profile_store import UserProfileStore
from core.profile.user_profile_manager import (
    UserProfileManager,
    get_user_profile_manager,
)

__all__ = [
    "ConsentStatus",
    "InformationScopeType",
    "PreferenceDetector",
    "ProfileCategory",
    "ProfilePreferenceItem",
    "UserProfileManager",
    "UserProfileStore",
    "get_user_profile_manager",
]
