"""Pruebas rigurosas de inmutabilidad profunda, snapshots defensivos y serialización de SecurityPolicy (Prompt 03).

Verifica:
1. Reasignación de atributos en SecurityPolicy bloqueada.
2. Modificación de atributos de reglas (PolicyRule) congeladas bloqueada.
3. Operaciones clear/append/pop/item assignment sobre la secuencia de reglas bloqueadas.
4. Edición de condiciones y parámetros anidados (MappingProxyType y tuplas recursivas) bloqueada.
5. Mutación de colecciones/diccionarios de entrada originales posterior a la construcción no afecta al snapshot.
6. Round-trip completo de serialización (dict y JSON) preservando inmutabilidad y tipos.
7. Orden determinista y protección DENY override irrompible.
8. Flujo administrativo con builders mutables y actualización controlada en DefaultPolicyProvider.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType
import pytest

from core.risk_engine import RiskEngine
from core.security_architecture import (
    SecurityContext,
    SecurityDecisionType,
    SecurityLevel,
    ToolSecurityMetadata,
)
from core.security_policy import (
    DefaultPolicyProvider,
    InvalidPolicyError,
    PolicyRule,
    PolicyRuleBuilder,
    PolicyRuleCondition,
    PolicySource,
    SecurityPolicy,
    SecurityPolicyBuilder,
    SecurityPolicyEvaluator,
    create_default_security_policy,
)


def _make_sample_ctx_and_meta(tool_name: str = "powershell", operation: str = "execute"):
    ctx = SecurityContext(user="operator", tool_name=tool_name, parameters={"operation": operation})
    meta = ToolSecurityMetadata(tool_name=tool_name, risk_level=SecurityLevel.SAFE)
    return ctx, meta


# 1. Reasignación
def test_security_policy_reassignment_blocked() -> None:
    policy = create_default_security_policy()

    with pytest.raises((InvalidPolicyError, FrozenInstanceError, TypeError, AttributeError)):
        policy.policy_id = "hacked-policy"

    with pytest.raises((InvalidPolicyError, FrozenInstanceError, TypeError, AttributeError)):
        policy.rules = ()

    with pytest.raises((InvalidPolicyError, FrozenInstanceError, TypeError, AttributeError)):
        policy.max_allowed_risk = SecurityLevel.SAFE

    with pytest.raises((InvalidPolicyError, FrozenInstanceError, TypeError, AttributeError)):
        policy.is_immutable = False

    with pytest.raises((InvalidPolicyError, FrozenInstanceError, TypeError, AttributeError)):
        del policy.rules


# 2. Modificación de regla
def test_policy_rule_modification_blocked() -> None:
    policy = create_default_security_policy()
    rule = policy.rules[0]

    with pytest.raises(FrozenInstanceError):
        rule.decision = SecurityDecisionType.ALLOW

    with pytest.raises(FrozenInstanceError):
        rule.priority = 9999

    with pytest.raises(FrozenInstanceError):
        rule.name = "Renamed Rule"

    with pytest.raises(FrozenInstanceError):
        rule.tool_name = "any"

    with pytest.raises(FrozenInstanceError):
        rule.conditions = PolicyRuleCondition()


# 3. clear / append / item assignment
def test_policy_rules_clear_and_append_blocked() -> None:
    policy = create_default_security_policy()

    assert isinstance(policy.rules, tuple)

    with pytest.raises(AttributeError):
        policy.rules.clear()  # type: ignore[attr-defined]

    with pytest.raises(AttributeError):
        new_rule = PolicyRule(name="Injected", decision=SecurityDecisionType.ALLOW)
        policy.rules.append(new_rule)  # type: ignore[attr-defined]

    with pytest.raises(AttributeError):
        policy.rules.pop()  # type: ignore[attr-defined]

    with pytest.raises(TypeError):
        new_rule = PolicyRule(name="Injected", decision=SecurityDecisionType.ALLOW)
        policy.rules[0] = new_rule  # type: ignore[index]

    with pytest.raises(TypeError):
        del policy.rules[0]  # type: ignore[index]


# 4. Edición de condición y parámetros anidados
def test_condition_and_nested_parameters_modification_blocked() -> None:
    nested_params = {
        "level_1": {
            "level_2": ["val_a", "val_b"],
            "threshold": 10,
        },
        "allowed_roots": ["c:\\system", "c:\\apps"],
    }
    cond = PolicyRuleCondition(
        path_patterns=["c:\\windows\\*"],
        users=["admin", "operator"],
        environments=["prod"],
        parameters=nested_params,
    )
    rule = PolicyRule(
        name="Nested Rule",
        decision=SecurityDecisionType.DENY,
        conditions=cond,
    )
    policy = SecurityPolicy(rules=[rule])
    active_cond = policy.rules[0].conditions

    # Tuplas inmutables en colecciones
    assert isinstance(active_cond.path_patterns, tuple)
    assert isinstance(active_cond.users, tuple)
    assert isinstance(active_cond.environments, tuple)

    with pytest.raises(AttributeError):
        active_cond.path_patterns.append("c:\\evil\\*")  # type: ignore[attr-defined]

    with pytest.raises(AttributeError):
        active_cond.users.append("attacker")  # type: ignore[attr-defined]

    with pytest.raises(AttributeError):
        active_cond.environments.append("dev")  # type: ignore[attr-defined]

    # MappingProxyType inmutable en parámetros de primer nivel
    assert isinstance(active_cond.parameters, MappingProxyType)
    with pytest.raises(TypeError):
        active_cond.parameters["injected_root"] = "evil"  # type: ignore[index]

    # MappingProxyType inmutable en parámetros anidados
    lvl1 = active_cond.parameters["level_1"]
    assert isinstance(lvl1, MappingProxyType)
    with pytest.raises(TypeError):
        lvl1["threshold"] = 999  # type: ignore[index]

    # Tuplas inmutables en listas anidadas
    lvl2 = lvl1["level_2"]
    assert isinstance(lvl2, tuple)
    with pytest.raises(AttributeError):
        lvl2.append("val_evil")  # type: ignore[attr-defined]

    roots = active_cond.parameters["allowed_roots"]
    assert isinstance(roots, tuple)
    with pytest.raises(AttributeError):
        roots.append("c:\\unrestricted")  # type: ignore[attr-defined]


# 5. Mutación de la lista/dict original después de construir
def test_mutation_of_original_inputs_after_construction_has_no_effect() -> None:
    rule_a = PolicyRule(name="Rule A", decision=SecurityDecisionType.ALLOW, priority=10)
    rule_b = PolicyRule(name="Rule B", decision=SecurityDecisionType.DENY, priority=20)
    input_rules_list = [rule_a, rule_b]

    input_patterns = ["c:\\safe\\*"]
    input_users = ["alice"]
    input_params = {"config": {"retries": [1, 2, 3]}}

    cond = PolicyRuleCondition(
        path_patterns=input_patterns,
        users=input_users,
        parameters=input_params,
    )
    rule_c = PolicyRule(name="Rule C", decision=SecurityDecisionType.ALLOW, conditions=cond)
    input_rules_list.append(rule_c)

    policy = SecurityPolicy(policy_id="p-test-defensive", rules=input_rules_list)

    # Mutar listas y dicts originales de entrada
    input_rules_list.clear()
    input_patterns.append("c:\\evil\\*")
    input_users.append("attacker")
    input_params["config"]["retries"].append(999)
    input_params["config"]["new_evil"] = True

    # Comprobar que el snapshot en policy no sufrió ningún cambio
    assert len(policy.rules) == 3
    found_c = [r for r in policy.rules if r.name == "Rule C"][0]
    assert found_c.conditions.path_patterns == ("c:\\safe\\*",)
    assert found_c.conditions.users == ("alice",)
    assert found_c.conditions.parameters["config"]["retries"] == (1, 2, 3)
    assert "new_evil" not in found_c.conditions.parameters["config"]


# 6. Round-trip de serialización
def test_serialization_round_trip() -> None:
    policy = create_default_security_policy()

    # Round trip dict
    data = policy.to_dict()
    assert isinstance(data, dict)
    assert isinstance(data["rules"], list)
    assert len(data["rules"]) == len(policy.rules)

    restored = SecurityPolicy.from_dict(data)
    assert restored.policy_id == policy.policy_id
    assert restored.version == policy.version
    assert len(restored.rules) == len(policy.rules)
    assert isinstance(restored.rules, tuple)
    assert restored == policy

    # Round trip JSON
    json_str = policy.to_json()
    assert isinstance(json_str, str)
    restored_json = SecurityPolicy.from_json(json_str)
    assert restored_json == policy
    assert isinstance(restored_json.rules, tuple)
    assert isinstance(restored_json.rules[0].conditions.path_patterns, tuple)
    assert isinstance(restored_json.rules[0].conditions.parameters, MappingProxyType)


# 7. Evaluación y prioridad de DENY override determinista
def test_deny_overriding_and_deterministic_order() -> None:
    evaluator = SecurityPolicyEvaluator()

    # Reglas en orden inverso de prioridad
    rule_allow_low = PolicyRule(name="Low Allow", tool_name="powershell", decision=SecurityDecisionType.ALLOW, priority=10)
    rule_allow_high = PolicyRule(name="High Allow", tool_name="powershell", decision=SecurityDecisionType.ALLOW, priority=1000)
    rule_deny = PolicyRule(name="Specific Deny", tool_name="powershell", decision=SecurityDecisionType.DENY, priority=50)

    # SecurityPolicy ordena deterministamente por prioridad descendente en __post_init__
    policy = SecurityPolicy(rules=[rule_allow_low, rule_deny, rule_allow_high])

    # Verificar orden interno
    priorities = [r.priority for r in policy.rules]
    assert priorities == [1000, 50, 10]

    # Evaluar: DENY override debe prevalecer a pesar de que High Allow tiene prioridad 1000
    ctx, meta = _make_sample_ctx_and_meta(tool_name="powershell")
    risk_eng = RiskEngine()
    assessment = risk_eng.evaluate_risk(ctx, {})

    decision = evaluator.evaluate_policy(ctx, meta, assessment, policy)
    assert decision.is_allowed is False
    assert decision.decision_type == SecurityDecisionType.DENY
    assert decision.matched_rule_name == "Specific Deny"


# 8. Builders administrativos y reemplazo completo en Provider
def test_administrative_builders_and_provider_replacement() -> None:
    base_policy = create_default_security_policy()
    provider = DefaultPolicyProvider(base_policy)

    # Crear builder mutable a partir de la política base
    builder = SecurityPolicyBuilder.from_policy(base_policy)
    builder.version = "2.0.0"
    builder.policy_id = "sys-updated-v2"

    # Añadir nueva regla mediante PolicyRuleBuilder
    rule_b = PolicyRuleBuilder(
        name="Custom Admin Rule",
        decision=SecurityDecisionType.ALLOW,
        priority=600,
        tool_name="admin_tool",
    )
    rule_b.path_patterns.append("c:\\admin\\*")
    builder.add_rule(rule_b)

    # Construir nuevo snapshot inmutable
    new_policy = builder.build()
    assert new_policy.version == "2.0.0"
    assert new_policy.policy_id == "sys-updated-v2"
    assert len(new_policy.rules) == len(base_policy.rules) + 1
    assert isinstance(new_policy.rules, tuple)

    # Actualizar proveedor por ruta administrativa
    provider.update_policy(new_policy)
    active_policy = provider.get_policy()
    assert active_policy.version == "2.0.0"
    assert active_policy == new_policy

    # Intentar mutar la política activa falla
    with pytest.raises((InvalidPolicyError, FrozenInstanceError, TypeError, AttributeError)):
        active_policy.version = "3.0.0"
